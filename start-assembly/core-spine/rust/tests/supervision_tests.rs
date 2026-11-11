//! ash-flare local supervision tests (Module 24).
//!
//! Every test asserts the behaviour the supervisor-core audit found in
//! the ash-flare 3.0.0 source, against the real library — not a stub:
//! a crashing worker is restarted under the documented policy, a
//! worker that keeps crashing exhausts its restart budget and the
//! supervisor STOPS (permanent failure is visible, never silent
//! success), and a supervised worker's output is never recorded as
//! verified. Run with `cargo test` (rustc 1.99.1 at ~/.cargo/bin).

use ash_flare::{
    RestartBackoff, RestartIntensity, RestartPolicy, SupervisorHandle, SupervisorSpec,
};
use start_core_spine::supervision::{
    execution_supervisor_spec, start_supervised_execution, supervisor_is_stopped,
    ExecutionWorker, WorkerBehaviour, WorkerLedger,
};
use std::sync::Arc;
use std::time::Duration;

async fn wait_until<F>(mut cond: F, timeout: Duration) -> bool
where
    F: FnMut() -> bool,
{
    let start = std::time::Instant::now();
    loop {
        if cond() {
            return true;
        }
        if start.elapsed() > timeout {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

#[tokio::test]
async fn transient_worker_restarts_then_completes_but_stays_unverified() {
    // Fail twice, then succeed: Transient restarts only on abnormal exit,
    // so the supervisor must restart the worker twice and then leave the
    // completed worker alone (no restart on normal completion).
    let (handle, ledger) =
        start_supervised_execution("flaky", WorkerBehaviour::FailNTimes(2), 5, 60);
    let done = wait_until(
        || ledger.snapshot().completed,
        Duration::from_secs(15),
    )
    .await;
    assert!(done, "worker never completed: {:?}", ledger.snapshot());
    let outcome = ledger.snapshot();
    assert_eq!(outcome.attempts, 3, "2 crashes + 1 success = 3 attempts");
    assert_eq!(outcome.failures, 2, "both crashes must be counted as failures");
    assert!(outcome.completed, "third attempt must complete");
    // The governance assertion: supervision is liveness, not verification.
    assert!(
        !outcome.verified,
        "a supervised worker's output must NEVER be recorded as verified"
    );
    // A completed Transient worker leaves supervision: a Normal exit
    // under Transient is a Drop decision, and Drop removes the child
    // from the list (verified in runtime.rs: Drop => children.remove).
    // It must NOT be restarted again: attempts stay at 3.
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(
        ledger.snapshot().attempts,
        3,
        "a completed Transient worker must not be restarted again"
    );
    let children = handle.which_children().await.unwrap();
    assert!(
        children.is_empty(),
        "completed Transient worker leaves supervision (Drop removes it): got {children:?}"
    );
    handle.shutdown().await.unwrap();
}

#[tokio::test]
async fn always_failing_worker_hits_intensity_limit_and_supervisor_stops() {
    // Budget: 3 restarts within 60 s. Expect 1 initial attempt + 3
    // restarts = 4 attempts, then Escalate: the supervisor shuts down
    // instead of retrying forever, and that stop is observable.
    let (handle, ledger) =
        start_supervised_execution("crash-loop", WorkerBehaviour::AlwaysFail, 3, 60);
    let stopped = wait_until(
        || ledger.snapshot().attempts >= 4,
        Duration::from_secs(15),
    )
    .await;
    assert!(stopped, "worker did not reach 4 attempts: {:?}", ledger.snapshot());
    // Give the escalate path a moment to stop the runtime after the
    // 4th failure's decision.
    let mut supervisor_down = false;
    for _ in 0..150 {
        if supervisor_is_stopped(&handle).await {
            supervisor_down = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(
        supervisor_down,
        "supervisor must stop once the intensity limit is exceeded"
    );
    let outcome = ledger.snapshot();
    assert_eq!(outcome.attempts, 4, "1 initial + 3 restarts, then stop");
    assert_eq!(outcome.failures, 4, "every attempt failed and was counted");
    assert!(!outcome.completed, "a worker that always fails must never complete");
    assert!(
        !outcome.verified,
        "a crashed worker must NEVER be reported as verified/success"
    );
    assert!(
        supervisor_is_stopped(&handle).await,
        "after the intensity limit the supervisor must have stopped; \
         a stopped supervisor is the permanent-failure signal, not silence"
    );
    // which_children() on a stopped supervisor errors (ShuttingDown) —
    // the failure is visible to any caller that asks.
    assert!(handle.which_children().await.is_err());
}

#[tokio::test]
async fn temporary_worker_is_never_restarted() {
    // Temporary policy: never restart. One failure, one attempt, and the
    // child is dropped from supervision (children list becomes empty).
    let ledger = Arc::new(WorkerLedger::default());
    let ledger_for_factory = Arc::clone(&ledger);
    let spec = SupervisorSpec::new("temp-only")
        .with_worker(
            "one-shot",
            move || ExecutionWorker::new(Arc::clone(&ledger_for_factory), WorkerBehaviour::AlwaysFail),
            RestartPolicy::Temporary,
        );
    let handle = SupervisorHandle::start(spec);
    let dropped = wait_until(|| ledger.snapshot().attempts >= 1, Duration::from_secs(15)).await;
    assert!(dropped, "temporary worker never ran");
    // Wait until the Drop decision has removed the child.
    let mut empty = false;
    for _ in 0..150 {
        if let Ok(children) = handle.which_children().await {
            if children.is_empty() {
                empty = true;
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(empty, "a Temporary child must be dropped after failing");
    let outcome = ledger.snapshot();
    assert_eq!(outcome.attempts, 1, "Temporary must never restart");
    assert_eq!(outcome.failures, 1);
    assert!(!outcome.completed);
    assert!(!outcome.verified);
    handle.shutdown().await.unwrap();
}

#[test]
fn documented_backoff_and_intensity_defaults_match() {
    // Pin the documented policy values from restart.rs so a future
    // ash-flare upgrade that changes them fails loudly here instead of
    // silently changing START's restart behaviour.
    let backoff = RestartBackoff::default();
    assert_eq!(backoff.delay_for_attempt(0), Duration::from_millis(100));
    assert_eq!(backoff.delay_for_attempt(1), Duration::from_millis(200));
    assert_eq!(backoff.delay_for_attempt(2), Duration::from_millis(400));
    assert_eq!(backoff.delay_for_attempt(100), Duration::from_secs(30));
    let explicit = RestartBackoff::exponential(Duration::from_millis(100), Duration::from_secs(30));
    assert_eq!(explicit, backoff);
    assert_eq!(RestartBackoff::none().delay_for_attempt(3), Duration::ZERO);

    let intensity = RestartIntensity::default();
    assert_eq!(intensity.max_restarts, 3);
    assert_eq!(intensity.within_seconds, 5);
    assert_eq!(RestartIntensity::new(3, 5).max_restarts, 3);
}

#[tokio::test]
async fn permanent_policy_restarts_even_on_normal_completion() {
    // Audit finding, pinned as a test: Permanent restarts on ANY
    // termination, including a clean Ok. A run-once execution worker
    // under Permanent would therefore be re-run forever. This is why
    // START's `execution_supervisor_spec` uses Transient, never
    // Permanent — this test proves the trap is real.
    let ledger = Arc::new(WorkerLedger::default());
    let ledger_for_factory = Arc::clone(&ledger);
    let spec = SupervisorSpec::new("permanent-trap")
        .with_restart_backoff(start_core_spine::supervision::TEST_BACKOFF)
        .with_restart_intensity(RestartIntensity::new(100, 60))
        .with_worker(
            "always-ok",
            move || {
                ExecutionWorker::new(
                    Arc::clone(&ledger_for_factory),
                    WorkerBehaviour::FailNTimes(0),
                )
            },
            RestartPolicy::Permanent,
        );
    let handle = SupervisorHandle::start(spec);
    let repeated = wait_until(|| ledger.snapshot().attempts >= 3, Duration::from_secs(15)).await;
    assert!(
        repeated,
        "a Permanent worker that returns Ok must be restarted, not left alone: {:?}",
        ledger.snapshot()
    );
    assert!(
        ledger.snapshot().completed,
        "the worker did complete — and was STILL restarted"
    );
    handle.shutdown().await.unwrap();
}

#[tokio::test]
async fn spec_builder_uses_transient_one_for_one() {
    // The START spec builder must not silently drift: Transient policy,
    // OneForOne strategy, and the worker must be listed as a child.
    let ledger = Arc::new(WorkerLedger::default());
    let spec = execution_supervisor_spec(
        "builder-check",
        Arc::clone(&ledger),
        WorkerBehaviour::FailNTimes(0),
        5,
        60,
    );
    let handle = SupervisorHandle::start(spec);
    let children = handle.which_children().await.unwrap();
    assert_eq!(children.len(), 1);
    // Policy is Transient (restart only on abnormal exit).
    assert_eq!(children[0].restart_policy, Some(RestartPolicy::Transient));
    let strategy = handle.restart_strategy().await.unwrap();
    assert_eq!(strategy, ash_flare::RestartStrategy::OneForOne);
    handle.shutdown().await.unwrap();
}
