//! Fault-injection test tooling (Module 24) — original Rust, stdlib +
//! serde_json only, no Tumult code, no Tumult dependency.
//!
//! Design inspiration: Tumult (mwigge/tumult, Apache-2.0, 151,498 lines
//! — verified in the sweep from its own LICENSE file). The sweep's
//! verdict for it was INSPIRATION-REBUILD: rebuild the experiment
//! pattern (hypothesis → baseline → fault → recovery measurement →
//! evidence journal) as original small Rust/Python test tooling. The
//! full Tumult platform (daemon, web UI, MCP server, ClickHouse/K8s
//! integrations, optional paid-LLM tutor) is deferred as heavyweight
//! and is NOT adopted. **No Tumult code was copied** — this module
//! was written from the pattern description only.
//!
//! What an experiment is here (original, defined in this file):
//! * A [`FaultExperiment`] states a hypothesis ("the supervised run
//!   recovers from a worker crash within the restart budget"),
//!   a baseline (the expected candidate: delivered 600 t /
//!   shortage 50 t — the spine's known LP optimum), one [`Fault`],
//!   and a restart/timeout budget.
//! * A [`Fault`] is one of three kinds, the same taxonomy as the
//!   Python half (`adapters/fault_injection.py`):
//!   `WorkerCrash` (the worker fails before returning), `DelayedResponse`
//!   (the response arrives after the timeout), `CorruptedValue` (a
//!   candidate value is altered in transit, so it no longer matches
//!   the baseline).
//! * Running a fault produces a [`FaultReport`]: whether the fault
//!   was injected, whether it was detected, a [`RunOutcome`], and a
//!   recovery measurement (restarts observed, timed out or not).
//!   [`RunOutcome`] has exactly two variants, `Fail` and `Unknown` —
//!   there is NO `Pass` variant, so a fault-injection run can never
//!   report a pass, by construction, not by convention.
//! * An [`EvidenceJournal`] is an append-only list of phase entries
//!   (hypothesis → baseline → fault → recovery → verdict), serialised
//!   to JSON. There is no delete or edit method.
//!
//! Governance — this is TEST-ONLY tooling:
//! * It never runs outside tests, never touches real plans, and never
//!   calls the verify step. A fault-injection run's output is a
//!   report about the supervision behaviour, never a plan verdict.
//! * `verified` on a [`FaultReport`] is always `false`: the field is
//!   set to `false` by every constructor and there is no setter and
//!   no code path that writes `true` (pinned by a test that reads
//!   this source file). A corrupted value is caught by comparing the
//!   received candidate against the baseline and is reported FAIL,
//!   never PASS. A crash is reported as a restart (or FAIL when the
//!   restart budget is exhausted), a delay as UNKNOWN (timed out).
//! * Recovery never promotes anything: even a worker that recovers
//!   after a restart reports UNKNOWN, not PASS — its output still
//!   needs the separate verify step and human approval, exactly as
//!   the supervision module requires of a restarted worker.
//!
//! Wire format stays JSON: reports and journal entries are plain
//! JSON-able values (schema_version "1.0.0"). All data here is
//! synthetic; no real plans, no network, no Tumult daemon.

use serde::Serialize;

/// Schema version for every report and journal entry this module emits.
pub const SCHEMA_VERSION: &str = "1.0.0";
/// Licence of the inspiration source (Tumult, Apache-2.0).
pub const LICENCE: &str = "Apache-2.0";
/// Provenance note carried on every report.
pub const PROVENANCE: &str = "START original — Tumult experiment pattern \
    (hypothesis -> baseline -> fault -> recovery measurement -> evidence \
    journal) as inspiration only, no code copied";

/// The three fault kinds. The string form is the shared taxonomy with
/// the Python half (`adapters/fault_injection.py`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FaultKind {
    WorkerCrash,
    DelayedResponse,
    CorruptedValue,
}

impl FaultKind {
    /// The shared taxonomy string: "worker_crash", "delayed_response",
    /// "corrupted_value".
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            FaultKind::WorkerCrash => "worker_crash",
            FaultKind::DelayedResponse => "delayed_response",
            FaultKind::CorruptedValue => "corrupted_value",
        }
    }
}

/// The outcome of a fault-injection run. Deliberately two variants
/// only: there is no `Pass`, so no fault run can ever report a pass.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RunOutcome {
    Fail,
    Unknown,
}

impl RunOutcome {
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            RunOutcome::Fail => "FAIL",
            RunOutcome::Unknown => "UNKNOWN",
        }
    }
}

/// One fault to inject, with the parameters that define it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Fault {
    /// The worker fails (returns `Err`) on this attempt; the
    /// supervisor is expected to restart it.
    WorkerCrash,
    /// The response is delayed by `delay_ms`; the run's timeout is
    /// `timeout_ms`. Detected (timed out) iff delay > timeout.
    DelayedResponse { delay_ms: u64, timeout_ms: u64 },
    /// The candidate's delivered tonnes are altered in transit from
    /// `expected_t` to `received_t`; detected iff they differ.
    CorruptedValue { expected_t: i64, received_t: i64 },
}

impl Fault {
    #[must_use]
    pub fn kind(&self) -> FaultKind {
        match self {
            Fault::WorkerCrash => FaultKind::WorkerCrash,
            Fault::DelayedResponse { .. } => FaultKind::DelayedResponse,
            Fault::CorruptedValue { .. } => FaultKind::CorruptedValue,
        }
    }
}

/// Whether a delayed response exceeds its timeout. Pure and exact:
/// a delay strictly greater than the timeout is a timeout.
#[must_use]
pub fn delay_exceeds_timeout(delay_ms: u64, timeout_ms: u64) -> bool {
    delay_ms > timeout_ms
}

/// Whether a received candidate value is corrupted relative to the
/// baseline expectation. Pure and exact: any difference is corruption.
#[must_use]
pub fn value_is_corrupted(expected_t: i64, received_t: i64) -> bool {
    expected_t != received_t
}

/// The baseline a fault run is measured against: the spine's known
/// LP optimum, delivered 600 t / shortage 50 t.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Baseline {
    pub delivered_t: i64,
    pub shortage_t: i64,
}

impl Default for Baseline {
    fn default() -> Self {
        Self {
            delivered_t: 600,
            shortage_t: 50,
        }
    }
}

/// The recovery measurement for one fault run.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Recovery {
    /// Whether the supervisor restarted the worker at least once.
    pub restarted: bool,
    /// How many restarts were observed.
    pub restarts: usize,
    /// Whether the run timed out (delay faults only).
    pub timed_out: bool,
    /// The timeout applied, in ms (delay faults only).
    pub timeout_ms: Option<u64>,
}

/// The report for one fault-injection run. `verified` is always
/// `false`: every constructor sets it to `false`, there is no
/// setter, and no code path writes `true`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FaultReport {
    pub schema_version: &'static str,
    pub experiment_id: String,
    pub hypothesis: String,
    pub baseline: Baseline,
    pub fault_kind: FaultKind,
    pub injected: bool,
    pub detected: bool,
    pub outcome: RunOutcome,
    /// Always `false`. A fault run never produces a verified verdict.
    pub verified: bool,
    pub needs_human_decision: bool,
    pub recovery: Recovery,
    pub licence: &'static str,
    pub provenance: &'static str,
    pub synthetic: bool,
}

impl FaultReport {
    fn new(
        experiment_id: &str,
        hypothesis: &str,
        fault_kind: FaultKind,
        detected: bool,
        outcome: RunOutcome,
        recovery: Recovery,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            experiment_id: experiment_id.to_string(),
            hypothesis: hypothesis.to_string(),
            baseline: Baseline::default(),
            fault_kind,
            injected: true,
            detected,
            outcome,
            verified: false,
            needs_human_decision: true,
            recovery,
            licence: LICENCE,
            provenance: PROVENANCE,
            synthetic: true,
        }
    }

    /// Report for a worker-crash fault, from the observed supervision
    /// behaviour. `restarts` restarts were observed; `recovered`
    /// says whether the worker eventually completed after a restart.
    /// A recovered worker is UNKNOWN (recovered but unverified —
    /// its output still needs the verify step); a worker that never
    /// recovered within the budget is FAIL.
    #[must_use]
    pub fn for_crash(experiment_id: &str, hypothesis: &str, restarts: usize, recovered: bool) -> Self {
        let outcome = if recovered {
            RunOutcome::Unknown
        } else {
            RunOutcome::Fail
        };
        Self::new(
            experiment_id,
            hypothesis,
            FaultKind::WorkerCrash,
            true,
            outcome,
            Recovery {
                restarted: restarts > 0,
                restarts,
                timed_out: false,
                timeout_ms: None,
            },
        )
    }

    /// Report for a delayed-response fault. A delay past the timeout
    /// is detected and UNKNOWN (no result is accepted); a delay
    /// inside the timeout is not detected — but the run is still
    /// UNKNOWN, never PASS, because a fault run never verifies.
    #[must_use]
    pub fn for_delay(experiment_id: &str, hypothesis: &str, delay_ms: u64, timeout_ms: u64) -> Self {
        let detected = delay_exceeds_timeout(delay_ms, timeout_ms);
        Self::new(
            experiment_id,
            hypothesis,
            FaultKind::DelayedResponse,
            detected,
            RunOutcome::Unknown,
            Recovery {
                restarted: false,
                restarts: 0,
                timed_out: detected,
                timeout_ms: Some(timeout_ms),
            },
        )
    }

    /// Report for a corrupted-value fault. A value that differs from
    /// the baseline is detected, rejected, and FAIL. An uncorrupted
    /// value is not detected — but the run is still UNKNOWN, never
    /// PASS, because a fault run never verifies.
    #[must_use]
    pub fn for_corruption(experiment_id: &str, hypothesis: &str, expected_t: i64, received_t: i64) -> Self {
        let detected = value_is_corrupted(expected_t, received_t);
        let outcome = if detected {
            RunOutcome::Fail
        } else {
            RunOutcome::Unknown
        };
        Self::new(
            experiment_id,
            hypothesis,
            FaultKind::CorruptedValue,
            detected,
            outcome,
            Recovery {
                restarted: false,
                restarts: 0,
                timed_out: false,
                timeout_ms: None,
            },
        )
    }

    /// Canonical JSON for the report (sorted keys are not guaranteed
    /// by serde_json struct order, but the value is deterministic for
    /// a given report: field order is the declaration order).
    #[must_use]
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("FaultReport is JSON-serialisable")
    }
}

/// One phase of an experiment, in Tumult's order: hypothesis →
/// baseline → fault → recovery measurement → verdict.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum JournalPhase {
    Hypothesis,
    Baseline,
    FaultInjected,
    RecoveryMeasured,
    Verdict,
}

impl JournalPhase {
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            JournalPhase::Hypothesis => "hypothesis",
            JournalPhase::Baseline => "baseline",
            JournalPhase::FaultInjected => "fault_injected",
            JournalPhase::RecoveryMeasured => "recovery_measured",
            JournalPhase::Verdict => "verdict",
        }
    }
}

/// One append-only evidence-journal entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct JournalEntry {
    pub schema_version: &'static str,
    pub experiment_id: String,
    pub phase: JournalPhase,
    pub detail: String,
    /// Always `false`: journal entries never record a verified verdict.
    pub verified: bool,
}

/// Append-only evidence journal. Entries can only be added, never
/// edited or deleted — there is deliberately no remove method.
#[derive(Debug, Default)]
pub struct EvidenceJournal {
    entries: Vec<JournalEntry>,
}

impl EvidenceJournal {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Append one entry. No edit or delete exists.
    pub fn record(&mut self, experiment_id: &str, phase: JournalPhase, detail: &str) {
        self.entries.push(JournalEntry {
            schema_version: SCHEMA_VERSION,
            experiment_id: experiment_id.to_string(),
            phase,
            detail: detail.to_string(),
            verified: false,
        });
    }

    /// Record the five phases of one experiment, in order, from its
    /// report. The verdict entry carries the outcome, never a pass.
    pub fn record_experiment(&mut self, report: &FaultReport) {
        self.record(
            &report.experiment_id,
            JournalPhase::Hypothesis,
            &report.hypothesis,
        );
        self.record(
            &report.experiment_id,
            JournalPhase::Baseline,
            &format!(
                "delivered_t={} shortage_t={}",
                report.baseline.delivered_t, report.baseline.shortage_t
            ),
        );
        self.record(
            &report.experiment_id,
            JournalPhase::FaultInjected,
            &format!("fault_kind={} injected=true", report.fault_kind.as_str()),
        );
        self.record(
            &report.experiment_id,
            JournalPhase::RecoveryMeasured,
            &format!(
                "restarted={} restarts={} timed_out={}",
                report.recovery.restarted, report.recovery.restarts, report.recovery.timed_out
            ),
        );
        self.record(
            &report.experiment_id,
            JournalPhase::Verdict,
            &format!(
                "outcome={} detected={} verified=false",
                report.outcome.as_str(),
                report.detected
            ),
        );
    }

    #[must_use]
    pub fn entries(&self) -> &[JournalEntry] {
        &self.entries
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    #[must_use]
    pub fn to_json(&self) -> String {
        serde_json::to_string(&self.entries).expect("journal is JSON-serialisable")
    }
}
