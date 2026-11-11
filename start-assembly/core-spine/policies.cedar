// START core spine — Cedar policies (cedar-policy/cedar, Apache-2.0).
// Authoritative policy file, in standard Cedar syntax. The Rust
// crate in rust/ evaluates these with the real Cedar engine.
// The Python module adapters/governance.py is a minimal stub
// evaluator for exactly these two policies — it is NOT Cedar.
//
// Entities: Planner::"planner", Plan::"plan1" with attributes
// synthetic (bool), verified (bool), human_approved (bool).
// Actions: Action::"PlanAction", Action::"PublishAction",
// Action::"ExecuteAction".

// A planner may plan, but only on synthetic (non-real) plans.
permit (
  principal == Planner::"planner",
  action == Action::"PlanAction",
  resource == Plan::"plan1"
) when { resource.synthetic == true };

// Nothing may be published or executed unless it is verified
// AND a human has approved it. (Cedar `forbid` wins over `permit`.)
forbid (
  principal,
  action in [Action::"PublishAction", Action::"ExecuteAction"],
  resource == Plan::"plan1"
) when { resource.verified == false || resource.human_approved == false };

// Publishing / executing IS permitted when the plan is verified
// AND a human has approved it. (Without this permit, Cedar's
// default-deny would deny even a verified, approved publish —
// that was a bug in the first draft of this file, caught by the
// Rust test `cedar_publish_allowed_when_verified_and_approved`.)
permit (
  principal,
  action in [Action::"PublishAction", Action::"ExecuteAction"],
  resource == Plan::"plan1"
) when { resource.verified == true && resource.human_approved == true };
