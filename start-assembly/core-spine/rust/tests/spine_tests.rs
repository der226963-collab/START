//! Rust spine tests: Cedar governance + egg rewrites + Tonic stub.
//! Run with `cargo test` (rustc 1.99.1 at ~/.cargo/bin).

use start_core_spine::cedar_eval;
use start_core_spine::egg_demo;
use start_core_spine::tonic_stub::{ConstraintEvaluationService, LocalEvaluator};

#[test]
fn cedar_planner_may_plan_synthetic() {
    assert_eq!(cedar_eval::planner_may_plan_synthetic().unwrap(), true);
}

#[test]
fn cedar_planner_may_not_plan_real() {
    assert_eq!(cedar_eval::planner_may_not_plan_real().unwrap(), false);
}

#[test]
fn cedar_publish_denied_when_unverified() {
    assert_eq!(cedar_eval::publish_denied_unverified().unwrap(), false);
}

#[test]
fn cedar_publish_allowed_when_verified_and_approved() {
    assert_eq!(
        cedar_eval::publish_allowed_verified_and_approved().unwrap(),
        true
    );
}

#[test]
fn egg_simplifies_add_zero() {
    assert_eq!(egg_demo::simplify_add_zero("(+ x 0)").unwrap(), "x");
}

#[test]
fn egg_simplifies_mul_one() {
    assert_eq!(egg_demo::simplify_add_zero("(* y 1)").unwrap(), "y");
}

#[test]
fn tonic_stub_evaluates_le_pass() {
    let ev = LocalEvaluator;
    assert_eq!(
        ev.evaluate("mass", "<=", 8.0, "t", 10.0, "t", 0.0),
        ("PASS".to_string(), "OK".to_string())
    );
}

#[test]
fn tonic_stub_unknown_on_incompatible_units() {
    let ev = LocalEvaluator;
    assert_eq!(
        ev.evaluate("vol", "<=", 5.0, "L", 10.0, "kg", 0.0),
        ("UNKNOWN".to_string(), "INCOMPATIBLE_UNIT".to_string())
    );
}

#[test]
fn tonic_stub_never_passes_unknown() {
    // Empty constraint_id must not pass.
    let ev = LocalEvaluator;
    let (status, _) = ev.evaluate("", "<=", 1.0, "kg", 10.0, "kg", 0.0);
    assert_ne!(status, "PASS");
}
