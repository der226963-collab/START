"""Food-domain constraint evaluation and uncertainty reporting."""
from __future__ import annotations
from typing import Any
import math
from contracts.statuses import CheckStatus, CalculationStatus, overall_from_checks
from domains.food.production import default_food_constraints


def evaluate_food_result(result: dict[str, Any], tolerance: float = 0.0) -> dict[str, Any]:
    # ISSUE-20 (2026-11-11): a non-dict result used to raise
    # AttributeError on result.get(...). A non-dict is NOT_CHECKED,
    # never a crash — the mirror of FoodDomain.calculate returning
    # INSUFFICIENT_INPUT for non-dict requests.
    if not isinstance(result, dict):
        return {"overall_status": CheckStatus.NOT_CHECKED.value, "constraint_results": [],
                "warnings": ["No calculation result was supplied; constraint evaluation was not performed."]}
    status = result.get("calculation_status")
    if status != CalculationStatus.COMPLETED.value:
        check = CheckStatus.NOT_CHECKED if status == CalculationStatus.NOT_RUN.value else CheckStatus.INCOMPLETE
        return {"overall_status": check.value, "constraint_results": [],
                "warnings": ["Calculation was not completed; constraint evaluation was skipped."]}

    metrics = result.get("metrics") or {}
    available = metrics.get("total_available_kcal_per_capita_per_day")
    requirement = metrics.get("requirement_kcal_per_capita_per_day")
    # ISSUE-35 (2026-11-11): a caller-supplied tolerance can flip a
    # verdict (P 6.5 vs bound 6.2: FAIL at tolerance 0.0, PASS at 0.5),
    # and the food evaluation row used to hide the tolerance entirely
    # (Constraint.to_dict() includes it, the row did not). The row now
    # surfaces the tolerance, the verdict at tolerance 0.0, and whether
    # the tolerance changed the verdict; a flip is warned about in
    # words, not just in a field. The default tolerance stays 0.0 (see
    # ISSUE-30: == at 0.0 is exact float equality, by design); a
    # non-zero tolerance is an explicit caller choice, passed here as
    # an argument — it is never read from the request, so a request
    # cannot smuggle a tolerance past validation.
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    constraint = default_food_constraints(requirement, tolerance=tolerance)[0]
    check = constraint.evaluate(available, "kcal/capita/day")
    verdict_without_tolerance = default_food_constraints(requirement)[0].evaluate(available, "kcal/capita/day")
    tolerance_changed_verdict = verdict_without_tolerance != check
    row = {"constraint_id": constraint.constraint_id, "status": check.value,
           "operator": constraint.operator, "available": available,
           "requirement": requirement, "unit": constraint.unit,
           "tolerance": constraint.tolerance,
           "verdict_without_tolerance": verdict_without_tolerance.value,
           "tolerance_changed_verdict": tolerance_changed_verdict,
           "surplus": None if available is None or requirement is None else available - requirement,
           "detail": "Aggregate per-capita daily energy comparison; not a distributional adequacy test."}
    warnings = []
    if tolerance_changed_verdict:
        warnings.append(
            f"Tolerance {constraint.tolerance} changed the verdict from "
            f"{verdict_without_tolerance.value} to {check.value}; the result "
            f"passes only because of the tolerance, not on the raw comparison.")
    if check == CheckStatus.FAIL:
        warnings.append("Stated aggregate food-energy requirement is not met by available supply.")
    elif check != CheckStatus.PASS:
        warnings.append("Food-energy adequacy could not be established.")
    return {"overall_status": overall_from_checks([check]).value,
            "constraint_results": [row], "warnings": warnings}


def describe_food_uncertainty(result: dict[str, Any]) -> list[str]:
    # ISSUE-20, same crash class as evaluate_food_result: a non-dict
    # result is reported, not dereferenced.
    if not isinstance(result, dict):
        return ["No calculation result was supplied; uncertainty cannot be assessed."]
    statements = list(result.get("limitations", []))
    if result.get("calculation_status") != CalculationStatus.COMPLETED.value:
        statements.append("No completed calculation is available for uncertainty assessment.")
    statements.append("Input provenance is carried as source identifiers but source credibility is not independently assessed by this module.")
    return statements
