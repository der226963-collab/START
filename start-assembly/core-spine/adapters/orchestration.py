"""Orchestration adapter: plan -> verify -> report.

State machine with three nodes. Verification is a SEPARATE step
that cannot be bypassed by the planner: the graph only reaches
`report` through `verify`, and `report` refuses to run unless the
state carries a verification result. A plan that fails verification
is reported as failed, never as passed. `needs_human_decision`
is always True in every report (v0.3.2 ISSUE-14 invariant).

If LangGraph (langchain-ai/langgraph, MIT) is installed, the graph
is built with real LangGraph StateGraph. If it is not installed,
`build_graph()` raises RuntimeError and the component is stub_only;
the pure-Python `run_pipeline()` below is the same three steps in
plain code, used by the tests to prove the no-bypass property
independently of LangGraph. The two must agree on outcomes.
"""

from .governance import authorise
from .statuses import ConstraintResult, InternalStatus, PlanningResult

STEPS = ("plan", "verify", "report")


def plan_step(state: dict) -> dict:
    """Planner node: produce a candidate plan. It may NOT verify it."""
    if not authorise("Planner", "PlanAction",
                     {"synthetic": state.get("synthetic", True)}).authorised:
        return {**state, "plan": None, "plan_error": "governance denied PlanAction"}
    return {**state, "plan": {
        "scenario_id": state.get("scenario_id", "synthetic-1-site-2-crop"),
        "delivered_t": state.get("delivered_t", 600.0),
        "demand_t": 650.0,
        "shortage_t": state.get("shortage_t", 50.0),
    }}


def verify_step(state: dict) -> dict:
    """Verifier node: independent check of the plan. Separate from plan."""
    plan = state.get("plan")
    if plan is None:
        check = ConstraintResult(
            "plan-exists", InternalStatus.INCOMPLETE,
            "no plan to verify: planner produced nothing",
            evidence=["verify ran; plan was None"])
        return {**state, "verification": PlanningResult(
            scenario_id=state.get("scenario_id", "unknown"), checks=[check])}
    checks = []
    delivered, demand = plan["delivered_t"], plan["demand_t"]
    shortage = plan["shortage_t"]
    # Independent re-derivation: delivered + shortage must equal demand.
    if abs((delivered + shortage) - demand) <= 0.01:
        checks.append(ConstraintResult(
            "delivered-plus-shortage-equals-demand", InternalStatus.PASS,
            f"{delivered} + {shortage} = {demand} t",
            actual_value=delivered + shortage, required_value=demand, unit="t",
            evidence=["independent re-derivation in verify_step"]))
    else:
        checks.append(ConstraintResult(
            "delivered-plus-shortage-equals-demand", InternalStatus.FAIL,
            f"{delivered} + {shortage} != {demand} t",
            actual_value=delivered + shortage, required_value=demand, unit="t",
            evidence=["independent re-derivation in verify_step"]))
    if shortage < 0 or delivered < 0:
        checks.append(ConstraintResult(
            "non-negative-quantities", InternalStatus.FAIL,
            "negative delivered or shortage", actual_value=shortage, unit="t"))
    else:
        checks.append(ConstraintResult(
            "non-negative-quantities", InternalStatus.PASS,
            "delivered and shortage are non-negative", unit="t"))
    return {**state, "verification": PlanningResult(
        scenario_id=plan["scenario_id"], checks=checks)}


def report_step(state: dict) -> dict:
    """Report node: refuses to run without a verification result."""
    verification = state.get("verification")
    if verification is None:
        raise RuntimeError(
            "report refused: no verification result — verification "
            "cannot be bypassed")
    return {**state, "report": {
        "scenario_id": verification.scenario_id,
        "overall_status": verification.overall_status.value,
        "overall_verdict": verification.overall_verdict.value,
        "passes": verification.passes,
        "failed_count": verification.failed_count,
        "needs_human_decision": True,
        "checks": [c.to_dict() for c in verification.checks],
    }}


def run_pipeline(state: dict) -> dict:
    """Plain-Python plan -> verify -> report, in that fixed order."""
    state = plan_step(state)
    state = verify_step(state)
    return report_step(state)


def build_graph():
    """Build the same pipeline as a real LangGraph StateGraph.

    Raises RuntimeError if langgraph is not installed.
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError as exc:
        raise RuntimeError(
            "langgraph not installed: orchestration is stub-only") from exc

    graph = StateGraph(dict)
    graph.add_node("plan", plan_step)
    graph.add_node("verify", verify_step)
    graph.add_node("report", report_step)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "verify")
    graph.add_edge("verify", "report")
    graph.add_edge("report", END)
    return graph.compile()


def run_graph(state: dict) -> dict:
    """Run the LangGraph graph. Raises RuntimeError if not installed."""
    return build_graph().invoke(state)
