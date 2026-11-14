"""Labour-domain constraint evaluation and uncertainty reporting."""
from __future__ import annotations
from typing import Any
import math
from contracts.statuses import CheckStatus, CalculationStatus, overall_from_checks
from domains.labour.labour import (
    UNIT_HOURS_PER_WEEK,
    default_labour_constraints,
)


def evaluate_labour_result(
    result: dict[str, Any],
    bound: float | None = None,
    tolerance: float = 0.0,
) -> dict[str, Any]:
    # ISSUE-20 (2026-11-11), as in food: a non-dict result used to
    # raise AttributeError on result.get(...). A non-dict is
    # NOT_CHECKED, never a crash.
    if not isinstance(result, dict):
        return {"overall_status": CheckStatus.NOT_CHECKED.value, "constraint_results": [],
                "warnings": ["No calculation result was supplied; constraint evaluation was not performed."]}
    status = result.get("calculation_status")
    if status != CalculationStatus.COMPLETED.value:
        check = CheckStatus.NOT_CHECKED if status == CalculationStatus.NOT_RUN.value else CheckStatus.INCOMPLETE
        return {"overall_status": check.value, "constraint_results": [],
                "warnings": ["Calculation was not completed; constraint evaluation was skipped."]}

    metrics = result.get("metrics") or {}
    paid_work = metrics.get("paid_work_hours_per_week")
    # ISSUE-35 (2026-11-11), as in food: a caller-supplied tolerance
    # can flip a verdict, so the row surfaces the tolerance, the
    # verdict at tolerance 0.0, and whether the tolerance changed
    # the verdict; a flip is warned about in words, not just in a
    # field. The default tolerance stays 0.0; a non-zero tolerance
    # is an explicit caller choice, passed here as an argument —
    # it is never read from the request.
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    if isinstance(bound, bool) or (bound is not None and (not isinstance(bound, (int, float)) or not math.isfinite(bound))):
        raise ValueError("bound must be a finite number or None")
    constraint = default_labour_constraints(bound=bound, tolerance=tolerance)[0]
    check = constraint.evaluate(paid_work, UNIT_HOURS_PER_WEEK)
    verdict_without_tolerance = default_labour_constraints(bound=bound)[0].evaluate(paid_work, UNIT_HOURS_PER_WEEK)
    tolerance_changed_verdict = verdict_without_tolerance != check
    row = {"constraint_id": constraint.constraint_id, "status": check.value,
           "operator": constraint.operator, "paid_work_hours_per_week": paid_work,
           "threshold_hours_per_week": bound, "unit": constraint.unit,
           "tolerance": constraint.tolerance,
           "verdict_without_tolerance": verdict_without_tolerance.value,
           "tolerance_changed_verdict": tolerance_changed_verdict,
           "detail": "Caller-stated paid-work hours against the ILO long-hours threshold; "
                     "the snapshot employed/all-adults averages are context only and are not checked here."}
    warnings = []
    if tolerance_changed_verdict:
        warnings.append(
            f"Tolerance {constraint.tolerance} changed the verdict from "
            f"{verdict_without_tolerance.value} to {check.value}; the result "
            f"passes only because of the tolerance, not on the raw comparison.")
    if check == CheckStatus.FAIL:
        warnings.append("Stated paid-work hours exceed the 48 h/week ILO long-hours threshold.")
    elif check != CheckStatus.PASS:
        warnings.append("Paid-work hours were not supplied or could not be established; "
                        "the long-hours check is UNKNOWN, never PASS.")
    return {"overall_status": overall_from_checks([check]).value,
            "constraint_results": [row], "warnings": warnings}


def describe_labour_uncertainty(result: dict[str, Any]) -> list[str]:
    # ISSUE-20, same crash class as evaluate_labour_result: a non-dict
    # result is reported, not dereferenced.
    if not isinstance(result, dict):
        return ["No calculation result was supplied; uncertainty cannot be assessed."]
    statements = list(result.get("limitations", []))
    if result.get("calculation_status") != CalculationStatus.COMPLETED.value:
        statements.append("No completed calculation is available for uncertainty assessment.")
    statements.append("Input provenance is carried as source identifiers but source credibility is not independently assessed by this module.")
    return statements
