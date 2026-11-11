//! Behavior-tree orchestration tests (Module 4, BehaviorTree.rs rebuild).
//!
//! Original Rust in `src/behavior_tree.rs` — no BehaviorTree.rs code
//! copied. The governance property under test throughout: trees
//! orchestrate plan → verify → report, they never verify, and the
//! report step refuses unless verify ran and passed in the same run.

use start_core_spine::behavior_tree::{
    parse_tree, run_json_tree, Blackboard, BlackboardError, Status, TreeRunner,
};

const PLAN_VERIFY_REPORT: &str = r#"{"type": "sequence", "children": [
    {"type": "action", "step": "plan"},
    {"type": "action", "step": "verify"},
    {"type": "action", "step": "report"}
]}"#;

#[test]
fn plan_verify_report_tree_runs_end_to_end_in_order() {
    let mut runner = TreeRunner::new();
    let status = run_json_tree(PLAN_VERIFY_REPORT, &mut runner).expect("valid tree JSON");
    assert_eq!(status, Status::Success);
    assert_eq!(runner.trace, vec!["plan", "verify", "report"]);
    assert_eq!(runner.blackboard.get_bool("plan_produced"), Ok(true));
    assert_eq!(runner.blackboard.get_bool("verify_ran"), Ok(true));
    assert_eq!(runner.blackboard.get_bool("verify_passed"), Ok(true));
    assert_eq!(runner.blackboard.get_bool("report_emitted"), Ok(true));
    assert_eq!(
        runner.blackboard.get_text("report_status"),
        Ok("PASS".to_string())
    );
    assert_eq!(
        runner.blackboard.get_bool("needs_human_decision"),
        Ok(true),
        "every report needs a human decision"
    );
    // The tree never marks anything verified: there is no such key.
    assert_eq!(
        runner.blackboard.get_bool("verified"),
        Err(BlackboardError::Missing("verified".to_string()))
    );
}

#[test]
fn fallback_takes_second_branch_when_first_fails() {
    let tree = parse_tree(
        r#"{"type": "fallback", "children": [
            {"type": "action", "step": "fail"},
            {"type": "action", "step": "succeed"}
        ]}"#,
    )
    .expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Success);
    assert_eq!(runner.trace, vec!["fail", "succeed"]);
}

#[test]
fn fallback_with_all_children_failing_returns_failure() {
    let tree = parse_tree(
        r#"{"type": "fallback", "children": [
            {"type": "action", "step": "fail"},
            {"type": "action", "step": "fail"}
        ]}"#,
    )
    .expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Failure);
    assert_eq!(runner.trace, vec!["fail", "fail"]);
}

#[test]
fn report_refuses_when_verify_node_is_removed() {
    // The verify node removed from the JSON tree: plan -> report.
    let tree = parse_tree(
        r#"{"type": "sequence", "children": [
            {"type": "action", "step": "plan"},
            {"type": "action", "step": "report"}
        ]}"#,
    )
    .expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Failure);
    assert_eq!(runner.trace, vec!["plan", "report_refused"]);
    // Assert the report was NOT emitted: no report entry on the blackboard.
    assert_eq!(
        runner.blackboard.get_bool("report_emitted"),
        Err(BlackboardError::Missing("report_emitted".to_string())),
        "report must not be emitted without verification"
    );
    assert_eq!(
        runner.blackboard.get_bool("verify_ran"),
        Err(BlackboardError::Missing("verify_ran".to_string()))
    );

    // Report alone, with no plan and no verify at all, also refuses.
    let tree = parse_tree(r#"{"type": "action", "step": "report"}"#).expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Failure);
    assert_eq!(runner.trace, vec!["report_refused"]);
    assert!(!runner.blackboard.has("report_emitted"));
}

#[test]
fn verify_failure_blocks_report() {
    // A plan whose numbers do not add up: verify fails, report refuses.
    let mut runner = TreeRunner::new();
    runner.blackboard.set_bool("plan_produced", true);
    runner.blackboard.set_float("plan_delivered_t", 500.0);
    runner.blackboard.set_float("plan_shortage_t", 50.0);
    runner.blackboard.set_float("plan_demand_t", 650.0);
    let tree = parse_tree(
        r#"{"type": "sequence", "children": [
            {"type": "action", "step": "verify"},
            {"type": "action", "step": "report"}
        ]}"#,
    )
    .expect("valid tree JSON");
    assert_eq!(runner.tick(&tree), Status::Failure);
    assert_eq!(runner.blackboard.get_bool("verify_passed"), Ok(false));
    assert!(!runner.blackboard.has("report_emitted"));
}

#[test]
fn typed_blackboard_right_type_wrong_type_and_missing_key() {
    let mut board = Blackboard::new();
    board.set_float("delivered_t", 600.0);
    board.set_bool("passed", true);
    board.set_int("count", 3);
    board.set_text("status", "PASS");
    assert_eq!(board.get_float("delivered_t"), Ok(600.0));
    assert_eq!(board.get_bool("passed"), Ok(true));
    assert_eq!(board.get_int("count"), Ok(3));
    assert_eq!(board.get_text("status"), Ok("PASS".to_string()));
    // Wrong type is an error, never a silent coercion.
    assert_eq!(
        board.get_bool("delivered_t"),
        Err(BlackboardError::WrongType {
            key: "delivered_t".to_string(),
            expected: "bool",
            found: "float",
        })
    );
    assert_eq!(
        board.get_float("passed"),
        Err(BlackboardError::WrongType {
            key: "passed".to_string(),
            expected: "float",
            found: "bool",
        })
    );
    // Missing key is an error, never a default.
    assert_eq!(
        board.get_bool("no_such_key"),
        Err(BlackboardError::Missing("no_such_key".to_string()))
    );
    assert_eq!(
        board.get_text("no_such_key"),
        Err(BlackboardError::Missing("no_such_key".to_string()))
    );
}

#[test]
fn inverter_decorator_inverts_success_and_failure() {
    let mut runner = TreeRunner::new();
    let invert_fail = parse_tree(
        r#"{"type": "inverter", "child": {"type": "action", "step": "fail"}}"#,
    )
    .expect("valid tree JSON");
    assert_eq!(runner.tick(&invert_fail), Status::Success);
    let invert_succeed = parse_tree(
        r#"{"type": "inverter", "child": {"type": "action", "step": "succeed"}}"#,
    )
    .expect("valid tree JSON");
    assert_eq!(runner.tick(&invert_succeed), Status::Failure);
    // Inverter over a condition: verify_passed is unset, so the
    // condition fails and the inverter turns it into Success.
    let invert_condition = parse_tree(
        r#"{"type": "inverter", "child": {"type": "condition", "step": "verify_passed"}}"#,
    )
    .expect("valid tree JSON");
    assert_eq!(runner.tick(&invert_condition), Status::Success);
}

#[test]
fn succeeder_decorator_turns_failure_into_success() {
    let tree = parse_tree(
        r#"{"type": "succeeder", "child": {"type": "action", "step": "fail"}}"#,
    )
    .expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Success);
    // Succeeder passes Success through unchanged.
    let tree = parse_tree(
        r#"{"type": "succeeder", "child": {"type": "action", "step": "succeed"}}"#,
    )
    .expect("valid tree JSON");
    assert_eq!(runner.tick(&tree), Status::Success);
}

#[test]
fn running_is_genuinely_exercised_by_defer_once() {
    // Running is not just a defined variant: defer_once returns
    // Running on its first tick and Success on the next.
    let tree = parse_tree(r#"{"type": "action", "step": "defer_once"}"#).expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&tree), Status::Running);
    assert_eq!(runner.tick(&tree), Status::Success);
    // A Sequence containing it returns Running on the first tick and
    // does not run the following child until the next tick.
    let seq = parse_tree(
        r#"{"type": "sequence", "children": [
            {"type": "action", "step": "defer_once"},
            {"type": "action", "step": "succeed"}
        ]}"#,
    )
    .expect("valid tree JSON");
    let mut runner = TreeRunner::new();
    assert_eq!(runner.tick(&seq), Status::Running);
    assert_eq!(runner.trace, vec!["defer_once"]);
    assert_eq!(runner.tick(&seq), Status::Success);
    assert_eq!(runner.trace, vec!["defer_once", "defer_once", "succeed"]);
}

#[test]
fn invalid_tree_json_and_unknown_node_type_are_errors() {
    assert!(parse_tree("{not json").is_err());
    assert!(parse_tree(r#"{"type": "parallel", "children": []}"#).is_err());
    assert!(parse_tree(r#"{"type": "action"}"#).is_err());
    assert!(run_json_tree(r#"{"type": "action", "step": "nope"}"#, &mut TreeRunner::new())
        .map(|s| s)
        .expect("unknown step parses; it fails at run time")
        == Status::Failure);
}
