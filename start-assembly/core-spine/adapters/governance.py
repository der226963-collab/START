"""Governance adapter: Cedar policy, authorise / deny.

The authoritative policy is `policies.cedar` (in this folder's
parent: core-spine/policies.cedar), written in real Cedar syntax
for cedar-policy/cedar (Apache-2.0). The Rust crate in rust/ is the
authoritative evaluator when it builds and its tests run.

This Python module is a MINIMAL, DOCUMENTED STUB evaluator for
exactly the two policies in policies.cedar — it is NOT Cedar, and
it must never be presented as Cedar. It exists so the Python test
suite can show the intended allow/deny behaviour locally even if
the Rust build is unavailable, and so a denied action stays denied
through the orchestration layer. Any policy outside the two
shapes below returns UNKNOWN (not authorised), never a silent pass.

Policies (see policies.cedar):
  permit: Planner may run PlanAction when the plan is synthetic
          (context.synthetic == true).
  forbid: any action on a plan whose context.verified == false is
          forbidden when the action would publish / execute it.
          (Here: PublishAction and ExecuteAction are denied unless
          context.verified == true AND context.human_approved == true.)
"""

from dataclasses import dataclass


@dataclass
class Decision:
    authorised: bool
    status: str  # "PASS" | "FAIL" | "UNKNOWN" — wire vocabulary
    reason: str


def authorise(principal: str, action: str, context: dict) -> Decision:
    """Evaluate the two core-spine policies for one action.

    Unknown principal/action/context -> UNKNOWN (not authorised).
    A denied action stays denied: there is no override path here.
    """
    if not isinstance(context, dict):
        return Decision(False, "UNKNOWN", "context is not an object")
    if action not in ("PlanAction", "PublishAction", "ExecuteAction"):
        return Decision(False, "UNKNOWN", f"unknown action: {action}")
    if principal not in ("Planner", "Verifier", "Human"):
        return Decision(False, "UNKNOWN", f"unknown principal: {principal}")

    if action == "PlanAction":
        if principal == "Planner" and context.get("synthetic") is True:
            return Decision(True, "PASS",
                            "permit: Planner may plan a synthetic plan")
        return Decision(False, "FAIL",
                        "deny: PlanAction requires Planner + synthetic plan")

    # Publish / Execute: forbid unless verified AND human-approved.
    if context.get("verified") is True and context.get("human_approved") is True:
        return Decision(True, "PASS",
                        f"permit: {action} verified and human-approved")
    return Decision(False, "FAIL",
                    f"deny: {action} requires verified=true and "
                    "human_approved=true (forbid policy)")
