"""Run every core-spine adapter once and print a summary.

Usage, from core-spine/:
    .venv/bin/python examples/run_spine.py
Exit code 0 only if every assembled adapter passes its check.
Stub / NOT RUN components are reported, not claimed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import interop, optimisation as opt  # noqa: E402
from adapters import evaluation, governance, orchestration  # noqa: E402
from adapters.statuses import ConstraintResult, InternalStatus  # noqa: E402


def main():
    ok = True

    scipy = opt.solve_scipy_highs(loss=0.0)
    print("HiGHS (SciPy):", json.dumps(scipy))
    ok &= opt.check_totals(scipy, opt.EXPECTED_CROSS).passes

    try:
        cvx = opt.solve_cvxpy()
        print("CVXPY:", json.dumps(cvx))
        ok &= opt.check_totals(cvx, opt.EXPECTED_CROSS).passes
    except Exception as exc:
        print("CVXPY: blocked:", exc)
        ok = False

    try:
        cpm = opt.solve_cpmpy()
        print("CPMpy:", json.dumps(cpm))
        ok &= opt.check_totals(cpm, opt.EXPECTED_CROSS).passes
    except Exception as exc:
        print("CPMpy: blocked:", exc)
        ok = False

    rows = [ConstraintResult("food", InternalStatus.PASS, "ok",
                             actual_value=2800, required_value=2500,
                             unit="kcal/capita/day")]
    back = interop.arrow_round_trip(rows)
    print("Arrow round-trip:", json.dumps(back))
    ok &= back[0]["status"] == "PASS"

    grpc_r = interop.evaluate_remote({
        "schema_version": "1.0.0", "constraint_id": "mass",
        "operator": "<=", "value": 8, "value_unit": "t",
        "bound": 10, "bound_unit": "t", "tolerance": 0})
    print("gRPC:", json.dumps(grpc_r))
    ok &= grpc_r["status"] == "PASS"

    d = governance.authorise("Planner", "PublishAction",
                             {"verified": False, "human_approved": True})
    print("Governance (publish unverified): authorised =", d.authorised)
    ok &= not d.authorised

    out = orchestration.run_pipeline({"scenario_id": "s1"})
    print("Orchestration:", json.dumps(out["report"]))
    ok &= out["report"]["passes"] and out["report"]["needs_human_decision"]

    em = evaluation.exact_match_accuracy()
    print("Evaluation (exact-match, local):", json.dumps(em))
    ok &= em["matches"] == 3 and em["total"] == 4

    print("ALL ASSEMBLED ADAPTERS PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
