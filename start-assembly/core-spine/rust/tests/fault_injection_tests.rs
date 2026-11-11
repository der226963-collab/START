//! Fault-injection experiment tests (Tumult experiment-pattern rebuild,
//! Module 24).
//!
//! The crash tests run against the REAL ash-flare supervisor
//! (`supervision::start_supervised_execution`): a crashing worker is
//! restarted under the documented Transient policy, and the report
//! is built from the observed ledger. Delay and corruption are
//! exercised with real sleeps/timeouts and exact comparisons.
//! Run with `cargo test` (rustc 1.99.1 at ~/.cargo/bin).

use start_core_spine::fault_injection::{
    delay_exceeds_timeout, value_is_corrupted, EvidenceJournal, Fault, FaultKind,
    FaultReport, JournalPhase, RunOutcome,
};
use start_core_spine::supervision::{start_supervised_execution, supervisor_is_stopped, WorkerBehaviour};
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
async fn crash_fault_real_supervisor_restarts_once_then_recovers_unverified() {
    // Fault: worker crashes once. Real supervisor (Transient, budget
    // 5 restarts): 2 attempts, completes after 1 restart.
    let (handle, ledger) =
        start_supervised_execution("fault-crash-1", WorkerBehaviour::FailNTimes(1), 5, 60);
    let done = wait_until(|| ledger.snapshot().completed, Duration::from_secs(15)).await;
    assert!(done, "worker never completed: {:?}", ledger.snapshot());
    let outcome = ledger.snapshot();
    assert_eq!(outcome.attempts, 2, "1 crash + 1 success = 2 attempts");
    assert_eq!(outcome.failures, 1);
    let restarts = outcome.attempts - 1;
    let report = FaultReport::for_crash(
        "exp-rs-crash-1",
        "the supervised run recovers from one worker crash",
        restarts,
        outcome.completed,
    );
    assert!(report.injected);
    assert!(report.detected);
    assert_eq!(report.recovery.restarts, 1);
    assert!(report.recovery.restarted);
    // Recovered — but UNKNOWN, never PASS: the restarted worker's
    // output still needs the verify step.
    assert_eq!(report.outcome, RunOutcome::Unknown);
    assert!(!report.verified, "a fault run must NEVER be verified");
    assert!(report.needs_human_decision);
    handle.shutdown().await.unwrap();
}

#[tokio::test]
async fn crash_fault_real_supervisor_exhausted_budget_is_fail() {
    // Fault: worker always crashes. Budget 3 restarts: 4 attempts,
    // then the supervisor STOPS (permanent failure, visible).
    let (handle, ledger) =
        start_supervised_execution("fault-crash-2", WorkerBehaviour::AlwaysFail, 3, 60);
    let reached = wait_until(|| ledger.snapshot().attempts >= 4, Duration::from_secs(15)).await;
    assert!(reached, "worker did not reach 4 attempts: {:?}", ledger.snapshot());
    let mut stopped = false;
    for _ in 0..150 {
        if supervisor_is_stopped(&handle).await {
            stopped = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(stopped, "supervisor must stop once the budget is exhausted");
    let outcome = ledger.snapshot();
    let report = FaultReport::for_crash(
        "exp-rs-crash-2",
        "a worker that keeps crashing exhausts its restart budget",
        outcome.attempts - 1,
        outcome.completed,
    );
    assert_eq!(report.outcome, RunOutcome::Fail);
    assert!(!report.verified);
    assert_eq!(report.recovery.restarts, 3);
}

#[tokio::test]
async fn delay_fault_past_timeout_is_detected_unknown_and_result_rejected() {
    // Real timeout: the "worker" sleeps 150 ms, the timeout is
    // 100 ms — tokio::time::timeout must fire, and no result is
    // accepted.
    let delay_ms = 150u64;
    let timeout_ms = 100u64;
    let result = tokio::time::timeout(
        Duration::from_millis(timeout_ms),
        tokio::time::sleep(Duration::from_millis(delay_ms)),
    )
    .await;
    assert!(result.is_err(), "a 150 ms response must time out at 100 ms");
    assert!(delay_exceeds_timeout(delay_ms, timeout_ms));
    let report = FaultReport::for_delay(
        "exp-rs-delay-1",
        "a response slower than the timeout is not accepted",
        delay_ms,
        timeout_ms,
    );
    assert!(report.detected);
    assert!(report.recovery.timed_out);
    assert_eq!(report.recovery.timeout_ms, Some(100));
    assert_eq!(report.outcome, RunOutcome::Unknown);
    assert!(!report.verified);
}

#[tokio::test]
async fn delay_fault_inside_timeout_is_not_detected_but_still_unverified() {
    let result = tokio::time::timeout(
        Duration::from_millis(100),
        tokio::time::sleep(Duration::from_millis(50)),
    )
    .await;
    assert!(result.is_ok(), "a 50 ms response must arrive inside 100 ms");
    let report = FaultReport::for_delay(
        "exp-rs-delay-2",
        "a response inside the timeout is not a timeout",
        50,
        100,
    );
    assert!(!report.detected);
    assert!(!report.recovery.timed_out);
    // Still UNKNOWN, never PASS: a fault run never verifies.
    assert_eq!(report.outcome, RunOutcome::Unknown);
    assert!(!report.verified);
    // Strict boundary: delay == timeout is not a timeout.
    assert!(!delay_exceeds_timeout(100, 100));
    assert!(delay_exceeds_timeout(101, 100));
}

#[test]
fn corruption_fault_is_detected_fail_and_value_rejected() {
    // The detector compares the received candidate against the
    // baseline (delivered 600 t); 650 t is corruption.
    assert!(value_is_corrupted(600, 650));
    assert!(value_is_corrupted(50, 51));
    assert!(!value_is_corrupted(600, 600));
    let report = FaultReport::for_corruption(
        "exp-rs-corrupt-1",
        "a candidate altered in transit must be rejected",
        600,
        650,
    );
    assert!(report.detected);
    assert_eq!(report.outcome, RunOutcome::Fail);
    assert!(!report.verified);
    // An unaltered value is not detected — but still UNKNOWN.
    let clean = FaultReport::for_corruption(
        "exp-rs-corrupt-2",
        "an unaltered candidate is not corruption",
        600,
        600,
    );
    assert!(!clean.detected);
    assert_eq!(clean.outcome, RunOutcome::Unknown);
    assert!(!clean.verified);
}

#[test]
fn fault_taxonomy_matches_python_half_and_has_no_pass_outcome() {
    // Shared taxonomy strings, identical to adapters/fault_injection.py.
    assert_eq!(FaultKind::WorkerCrash.as_str(), "worker_crash");
    assert_eq!(FaultKind::DelayedResponse.as_str(), "delayed_response");
    assert_eq!(FaultKind::CorruptedValue.as_str(), "corrupted_value");
    assert_eq!(Fault::WorkerCrash.kind(), FaultKind::WorkerCrash);
    assert_eq!(
        Fault::DelayedResponse { delay_ms: 150, timeout_ms: 100 }.kind(),
        FaultKind::DelayedResponse
    );
    assert_eq!(
        Fault::CorruptedValue { expected_t: 600, received_t: 650 }.kind(),
        FaultKind::CorruptedValue
    );
    // RunOutcome has exactly two variants — there is no Pass to
    // construct. The enum itself enforces it; assert the two that
    // exist serialise as the Python half's strings.
    assert_eq!(RunOutcome::Fail.as_str(), "FAIL");
    assert_eq!(RunOutcome::Unknown.as_str(), "UNKNOWN");
}

#[test]
fn evidence_journal_records_five_phases_in_order_and_never_verifies() {
    let report = FaultReport::for_crash(
        "exp-rs-journal-1",
        "one crash, then recovery",
        1,
        true,
    );
    let mut journal = EvidenceJournal::new();
    journal.record_experiment(&report);
    assert_eq!(journal.len(), 5);
    let phases: Vec<JournalPhase> =
        journal.entries().iter().map(|e| e.phase).collect();
    assert_eq!(
        phases,
        vec![
            JournalPhase::Hypothesis,
            JournalPhase::Baseline,
            JournalPhase::FaultInjected,
            JournalPhase::RecoveryMeasured,
            JournalPhase::Verdict,
        ]
    );
    assert!(journal.entries().iter().all(|e| !e.verified));
    assert!(journal.entries()[4].detail.contains("outcome=UNKNOWN"));
    assert!(journal.entries()[4].detail.contains("verified=false"));
    // JSON round-trip keeps verified false everywhere.
    let parsed: serde_json::Value =
        serde_json::from_str(&journal.to_json()).unwrap();
    assert_eq!(parsed.as_array().unwrap().len(), 5);
    assert!(parsed
        .as_array()
        .unwrap()
        .iter()
        .all(|e| e["verified"] == serde_json::Value::Bool(false)));
    // Append-only: no remove method exists on EvidenceJournal, and
    // entries() returns a slice, not a mutable view.
    let _entries: &[start_core_spine::fault_injection::JournalEntry] = journal.entries();
}

#[test]
fn report_json_shape_matches_python_half() {
    let report = FaultReport::for_corruption(
        "exp-rs-shape-1",
        "a candidate altered in transit must be rejected",
        600,
        650,
    );
    let parsed: serde_json::Value =
        serde_json::from_str(&report.to_json()).unwrap();
    // Same keys as the Python half's report (minus "result", which
    // is a Python-runner field: the Rust report is built from an
    // observed supervision outcome, not a returned candidate).
    for key in [
        "schema_version",
        "experiment_id",
        "hypothesis",
        "baseline",
        "fault_kind",
        "injected",
        "detected",
        "outcome",
        "verified",
        "needs_human_decision",
        "recovery",
        "licence",
        "provenance",
        "synthetic",
    ] {
        assert!(parsed.get(key).is_some(), "missing report key {key}");
    }
    assert_eq!(parsed["verified"], serde_json::Value::Bool(false));
    assert_eq!(parsed["outcome"], serde_json::Value::String("FAIL".to_string()));
    assert_eq!(parsed["fault_kind"], serde_json::Value::String("corrupted_value".to_string()));
    assert_eq!(parsed["baseline"]["delivered_t"], serde_json::Value::from(600));
    assert_eq!(parsed["baseline"]["shortage_t"], serde_json::Value::from(50));
}

#[test]
fn fault_injector_source_never_sets_verified_true() {
    // The module's own source is compiled into the test: no code
    // path may write verified=true. Every constructor sets false.
    let source = include_str!("../src/fault_injection.rs");
    assert!(!source.contains("verified: true"), "source must never set verified: true");
    assert!(!source.contains("verified = true"), "source must never set verified = true");
    assert!(source.contains("verified: false"), "reports must set verified: false");
    // Journal entries likewise never verify.
    assert!(!source.contains("verified: true"));
}

#[test]
fn journal_phase_order_matches_tumult_pattern() {
    assert_eq!(JournalPhase::Hypothesis.as_str(), "hypothesis");
    assert_eq!(JournalPhase::Baseline.as_str(), "baseline");
    assert_eq!(JournalPhase::FaultInjected.as_str(), "fault_injected");
    assert_eq!(JournalPhase::RecoveryMeasured.as_str(), "recovery_measured");
    assert_eq!(JournalPhase::Verdict.as_str(), "verdict");
}
