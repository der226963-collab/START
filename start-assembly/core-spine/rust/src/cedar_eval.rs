//! Cedar governance evaluation (cedar-policy/cedar, Apache-2.0).
//!
//! Evaluates `../policies.cedar` with the real Cedar engine.
//! The plan entity carries synthetic / verified / human_approved
//! attributes; the forbid policy denies Publish/Execute unless
//! verified AND human-approved. A denied action stays denied —
//! there is no override path here.

use cedar_policy::{Authorizer, Context, Decision, Entities, EntityUid, PolicySet, Request};
use std::str::FromStr;

pub const POLICIES: &str = include_str!("../../policies.cedar");

fn plan_entities(synthetic: bool, verified: bool, human_approved: bool) -> Entities {
    let json = serde_json::json!([{
        "uid": {"type": "Plan", "id": "plan1"},
        "attrs": {
            "synthetic": synthetic,
            "verified": verified,
            "human_approved": human_approved,
        },
        "parents": [],
    }]);
    Entities::from_json_value(json, None).expect("plan entities must parse")
}

fn decide(principal: &str, action: &str, synthetic: bool, verified: bool,
          human_approved: bool) -> Result<bool, String> {
    let policies = PolicySet::from_str(POLICIES).map_err(|e| format!("policy parse: {e}"))?;
    let entities = plan_entities(synthetic, verified, human_approved);
    let request = Request::new(
        EntityUid::from_str(principal).map_err(|e| format!("principal: {e}"))?,
        EntityUid::from_str(action).map_err(|e| format!("action: {e}"))?,
        EntityUid::from_str("Plan::\"plan1\"").map_err(|e| format!("resource: {e}"))?,
        Context::empty(),
        None,
    )
    .map_err(|e| format!("request: {e}"))?;
    let authorizer = Authorizer::new();
    let response = authorizer.is_authorized(&request, &policies, &entities);
    Ok(response.decision() == Decision::Allow)
}

/// Planner may PlanAction on a synthetic plan.
pub fn planner_may_plan_synthetic() -> Result<bool, String> {
    decide("Planner::\"planner\"", "Action::\"PlanAction\"", true, false, false)
}

/// Planner may NOT PlanAction on a non-synthetic plan.
pub fn planner_may_not_plan_real() -> Result<bool, String> {
    decide("Planner::\"planner\"", "Action::\"PlanAction\"", false, false, false)
}

/// PublishAction is denied when the plan is unverified, even if
/// a human approved it; and denied when verified but not approved.
pub fn publish_denied_unverified() -> Result<bool, String> {
    decide("Planner::\"planner\"", "Action::\"PublishAction\"", true, false, true)
}

pub fn publish_allowed_verified_and_approved() -> Result<bool, String> {
    decide("Human::\"human\"", "Action::\"PublishAction\"", true, true, true)
}
