//! Local supervision of execution workers with ash-flare (Module 24).
//!
//! ash-flare 3.0.0 (ashforge-rs/ash-flare, Apache-2.0) is an Erlang/OTP-style
//! supervision-tree library. START uses it as a dependency for one thing
//! only: **process liveness of local execution workers** — start a worker,
//! restart it if it crashes, and give up loudly if it keeps crashing.
//!
//! What the supervisor does (audited from the 3.0.0 source, tag `v3.0.0`,
//! commit `11beb3d3018b260eaaae983688e0d90d95210e62` — `src/supervisor.rs`,
//! `src/supervisor/spec.rs`, `src/supervisor/runtime.rs`,
//! `src/supervisor_common.rs`, `src/restart.rs`, `src/worker.rs`):
//!
//! * A supervisor owns a tree of children (workers or nested supervisors)
//!   and applies one restart strategy to the whole tree: `OneForOne`
//!   (restart only the failed child — the default, and the only strategy
//!   START uses), `OneForAll` (restart every child if any fails) or
//!   `RestForOne` (restart the failed child and all children started after
//!   it).
//! * Each worker carries a restart policy: `Permanent` (restart on ANY
//!   termination, including a normal clean exit), `Temporary` (never
//!   restart — the child is dropped from supervision), or `Transient`
//!   (restart only on an abnormal exit). START uses `Transient` for
//!   execution workers: a worker that finished its job must not be
//!   restarted, and a worker that crashed must be. `Permanent` is a
//!   trap for run-once work — it restarts a worker that already
//!   completed successfully — and is never used here (pinned by a test).
//! * Restart policy, intensity accounting and backoff live in one shared
//!   decision function, `decide_restart` (`supervisor_common.rs`), used
//!   by both the stateless and stateful supervisor runtimes, so the two
//!   cannot drift apart.
//! * Restart intensity (default 3 restarts within 5 seconds) is a sliding
//!   window. Exceeding it does NOT silently keep trying: the runtime
//!   escalates — it shuts down all children and stops the supervisor
//!   itself, reporting an abnormal exit to a parent supervisor (`Escalate`
//!   in `runtime.rs`). A permanently failing worker therefore ends in a
//!   stopped supervisor, which `which_children()` reports as an error,
//!   never in a fake success.
//! * Backoff (default exponential 100 ms doubling, capped at 30 s) is
//!   tracked per child and resets once a child has stayed up for at
//!   least the cap, so an occasional failure does not inherit an old
//!   crash loop's delay.
//! * On shutdown a worker is asked to stop cooperatively via a
//!   `ShutdownSignal` and gets its `shutdown` hook run; a worker that
//!   ignores the signal is aborted after the shutdown timeout (default
//!   5 s) and does NOT get the hook.
//!
//! Governance — supervision is about liveness, NOT verification:
//!
//! * A restart re-creates the worker from its factory as a fresh
//!   instance. It re-runs the worker's `run()` from scratch. That is
//!   fine for execution work and is exactly what must NEVER happen to a
//!   verification or planning step: a restarted worker must never
//!   re-emit, carry over, or inherit a verified verdict. Verification
//!   results live in the separate verify step and are re-derived there,
//!   never inherited across a restart.
//! * The ledger below records attempts, failures and completion — and
//!   `verified` is a field that this module NEVER sets to `true`. A
//!   supervised worker's output is unverified until the separate verify
//!   step passes AND a human approves (`needs_human_decision=true`).
//! * A crashed worker is reported as failed, never silently as success:
//!   the ledger counts the failure, and if the restart budget is
//!   exhausted the supervisor stops, which is observable via
//!   [`supervisor_is_stopped`].
//!
//! Known gaps found in the audit (recorded, not worked around silently):
//!
//! * The public `ChildInfo` returned by `which_children()` carries only
//!   id, child type and restart policy — no restart count, no last exit
//!   reason, no running/failed state. Restart history is therefore NOT
//!   queryable from ash-flare; START tracks it itself in the
//!   [`WorkerLedger`], and treats a stopped supervisor as the
//!   permanent-failure signal.
//! * A panic inside a worker's `run()` is NOT delivered to the
//!   supervisor as an abnormal exit: `run_worker` has no `catch_unwind`,
//!   so a panicking task unwinds without sending `WorkerTermination`
//!   (only the linked-init path detects a panic, via the closed init
//!   channel). The `ChildExitReason::Abnormal` doc says "error or
//!   panic", but the run path only delivers errors. START workers must
//!   therefore return `Err` on failure, never panic — the workers here
//!   do, and a panic would leave a dead child listed as supervised.
//! * `distributed` is not a feature flag: `pub mod distributed` is
//!   always compiled (rkyv is a non-optional dependency) and its
//!   protocol has no authentication, authorization or encryption
//!   (stated in `src/distributed.rs`). "Distributed mode OFF" is
//!   enforced by non-use: this module never imports it, and no START
//!   code listens for supervision commands.
//! * Single author, very low adoption (2 stars at audit time). The
//!   supervisor core was audited first, as the sweep required, and the
//!   dependency is small and replaceable: only this module and its
//!   tests touch ash-flare.

use ash_flare::{
    RestartBackoff, RestartIntensity, RestartPolicy, RestartStrategy, SupervisorHandle,
    SupervisorSpec, Worker,
};
use async_trait::async_trait;
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;

/// Test-scale backoff for supervised execution workers: 10 ms doubling to
/// a 1 s cap. The library default (100 ms doubling to 30 s) is the right
/// shape for production; the small values here keep the restart tests
/// fast while still exercising exponential growth (10, 20, 40 ms, ...).
/// Any production use must consciously pick its backoff, not inherit
/// this test value by accident.
pub const TEST_BACKOFF: RestartBackoff =
    RestartBackoff::exponential(Duration::from_millis(10), Duration::from_secs(1));

/// Liveness ledger for one supervised execution worker, shared between
/// the worker instances the supervisor creates on each (re)start.
///
/// `verified` is deliberately present and deliberately always `false`:
/// supervision records that a worker ran, crashed, or completed — it
/// never records that its output is verified. Only the separate verify
/// step may produce a verified verdict.
#[derive(Debug, Default)]
pub struct WorkerLedger {
    /// How many times a worker instance started (`run` entered).
    pub attempts: AtomicUsize,
    /// How many attempts ended in `Err`.
    pub failures: AtomicUsize,
    /// Whether any attempt ever returned `Ok`.
    pub completed: AtomicBool,
    /// Always `false` from this module. See the module docs.
    pub verified: AtomicBool,
}

impl WorkerLedger {
    /// A snapshot of the ledger. `verified` is always `false` here.
    #[must_use]
    pub fn snapshot(&self) -> WorkerOutcome {
        WorkerOutcome {
            attempts: self.attempts.load(Ordering::SeqCst),
            failures: self.failures.load(Ordering::SeqCst),
            completed: self.completed.load(Ordering::SeqCst),
            verified: self.verified.load(Ordering::SeqCst),
        }
    }
}

/// Plain-data snapshot of a [`WorkerLedger`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkerOutcome {
    pub attempts: usize,
    pub failures: usize,
    pub completed: bool,
    /// Always `false` for supervised execution: a restart, a completion,
    /// or a crash is liveness information, never a verified verdict.
    pub verified: bool,
}

/// Behaviour of an execution worker, for tests and demos. Real workers
/// replace this with their own `Worker` impl; the rule is the same:
/// return `Err` on failure, never panic, never claim verification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerBehaviour {
    /// Fail the first `n` attempts, then succeed.
    FailNTimes(usize),
    /// Fail every attempt.
    AlwaysFail,
}

/// An execution worker driven by a shared [`WorkerLedger`].
///
/// Each restart creates a fresh instance from the factory, so per-attempt
/// state must live in the ledger, not in the worker struct.
pub struct ExecutionWorker {
    ledger: Arc<WorkerLedger>,
    behaviour: WorkerBehaviour,
}

impl ExecutionWorker {
    #[must_use]
    pub fn new(ledger: Arc<WorkerLedger>, behaviour: WorkerBehaviour) -> Self {
        Self { ledger, behaviour }
    }
}

#[async_trait]
impl Worker for ExecutionWorker {
    type Error = std::io::Error;

    async fn run(&mut self) -> Result<(), Self::Error> {
        let attempt = self.ledger.attempts.fetch_add(1, Ordering::SeqCst) + 1;
        let should_fail = match self.behaviour {
            WorkerBehaviour::FailNTimes(n) => attempt <= n,
            WorkerBehaviour::AlwaysFail => true,
        };
        if should_fail {
            self.ledger.failures.fetch_add(1, Ordering::SeqCst);
            Err(std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("execution worker failed on attempt {attempt}"),
            ))
        } else {
            self.ledger.completed.store(true, Ordering::SeqCst);
            Ok(())
        }
    }
}

/// Build a local-only supervisor spec for one execution worker.
///
/// Fixed START policy, not caller-configurable per call: strategy
/// `OneForOne` (only the failed child restarts), policy `Transient`
/// (restart only on abnormal exit — a worker that finished is done),
/// the given restart-intensity budget, and [`TEST_BACKOFF`].
/// No distributed anything is configured; the spec has no way to
/// enable it.
#[must_use]
pub fn execution_supervisor_spec(
    name: &str,
    ledger: Arc<WorkerLedger>,
    behaviour: WorkerBehaviour,
    max_restarts: usize,
    within_seconds: u64,
) -> SupervisorSpec<ExecutionWorker> {
    SupervisorSpec::new(name)
        .with_restart_strategy(RestartStrategy::OneForOne)
        .with_restart_intensity(RestartIntensity::new(max_restarts, within_seconds))
        .with_restart_backoff(TEST_BACKOFF)
        .with_worker("execution-worker", move || {
            ExecutionWorker::new(Arc::clone(&ledger), behaviour)
        }, RestartPolicy::Transient)
}

/// Start a local-only supervisor for one execution worker and return
/// its handle plus the shared ledger.
#[must_use]
pub fn start_supervised_execution(
    name: &str,
    behaviour: WorkerBehaviour,
    max_restarts: usize,
    within_seconds: u64,
) -> (SupervisorHandle<ExecutionWorker>, Arc<WorkerLedger>) {
    let ledger = Arc::new(WorkerLedger::default());
    let spec = execution_supervisor_spec(
        name,
        Arc::clone(&ledger),
        behaviour,
        max_restarts,
        within_seconds,
    );
    (SupervisorHandle::start(spec), ledger)
}

/// Whether the supervisor behind `handle` has stopped.
///
/// The observable permanent-failure signal: when the restart budget is
/// exhausted the runtime escalates, shuts the children down and stops,
/// and `which_children()` then fails because the command channel is
/// closed. A stopped supervisor is a FAILED worker, never a success.
pub async fn supervisor_is_stopped<W: Worker>(handle: &SupervisorHandle<W>) -> bool {
    handle.which_children().await.is_err()
}
