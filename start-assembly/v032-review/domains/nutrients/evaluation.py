"""Nutrients-domain constraint evaluation and uncertainty reporting."""
from __future__ import annotations
from typing import Any
import math
from contracts.statuses import CheckStatus, CalculationStatus, overall_from_checks
from domains.nutrients.balance import (
    NITROGEN_BOUNDARY_NOTE,
    NUTRIENT_UNIT,
    default_nutrient_constraints,
    phosphorus_excess_and_ratio,
)


def evaluate_nutrients_result(result: dict[str, Any], tolerance: float = 0.0) -> dict[str, Any]:
    """Evaluate the phosphorus and nitrogen constraints on a balance result.

    Phosphorus is pass/fail against the stored 6.2 Tg/yr boundary
    (tolerance surfaced exactly as in food, ISSUE-35: the row carries
    the tolerance, the verdict at tolerance 0.0, and whether the
    tolerance changed the verdict). Nitrogen is ALWAYS UNKNOWN: its
    constraint is bound-less by design, and no tolerance or value
    can turn it into a PASS. Overall status comes from
    ``overall_from_checks``: a passing phosphorus check plus an
    UNKNOWN nitrogen check is UNKNOWN overall, never PASS — the
    nitrogen unknown blocks a pass, it is not ignored.
    """
    # ISSUE-20 (food): a non-dict result is NOT_CHECKED, never a crash.
    if not isinstance(result, dict):
        return {"overall_status": CheckStatus.NOT_CHECKED.value, "constraint_results": [],
                "warnings": ["No calculation result was supplied; constraint evaluation was not performed."]}
    status = result.get("calculation_status")
    if status != CalculationStatus.COMPLETED.value:
        check = CheckStatus.NOT_CHECKED if status == CalculationStatus.NOT_RUN.value else CheckStatus.INCOMPLETE
        return {"overall_status": check.value, "constraint_results": [],
                "warnings": ["Calculation was not completed; constraint evaluation was skipped."]}

    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be a finite non-negative number")

    metrics = result.get("metrics") or {}
    constraints = {c.constraint_id: c for c in default_nutrient_constraints(tolerance=tolerance)}
    rows: list[dict[str, Any]] = []
    checks: list[CheckStatus] = []
    warnings: list[str] = []

    if "phosphorus_applied_tg_per_year" in metrics:
        constraint = constraints["phosphorus_application_tg_per_year"]
        applied = metrics["phosphorus_applied_tg_per_year"]
        boundary = constraint.bound
        check = constraint.evaluate(applied, NUTRIENT_UNIT)
        verdict_without_tolerance = default_nutrient_constraints()[0].evaluate(applied, NUTRIENT_UNIT)
        tolerance_changed_verdict = verdict_without_tolerance != check
        excess, ratio = phosphorus_excess_and_ratio(applied, boundary)
        rows.append({
            "constraint_id": constraint.constraint_id, "status": check.value,
            "operator": constraint.operator, "applied": applied,
            "boundary": boundary, "unit": constraint.unit,
            "tolerance": constraint.tolerance,
            "verdict_without_tolerance": verdict_without_tolerance.value,
            "tolerance_changed_verdict": tolerance_changed_verdict,
            "excess_tg_per_year": excess, "ratio_to_boundary": ratio,
            "source_ids": list(constraint.source_ids),
            "detail": "Phosphorus application to cropland against the stored regional boundary; not a field-level plan.",
        })
        checks.append(check)
        if tolerance_changed_verdict:
            warnings.append(
                f"Tolerance {constraint.tolerance} changed the phosphorus verdict from "
                f"{verdict_without_tolerance.value} to {check.value}; the result "
                f"passes only because of the tolerance, not on the raw comparison.")
        if check == CheckStatus.FAIL:
            warnings.append(
                f"Phosphorus application {applied} Tg/yr exceeds the regional boundary "
                f"{boundary} Tg/yr by {excess} Tg/yr (ratio {ratio}).")

    if "nitrogen_fixation_tg_per_year" in metrics:
        constraint = constraints["nitrogen_fixation_tg_per_year"]
        fixation = metrics["nitrogen_fixation_tg_per_year"]
        # Bound-less by construction: evaluate() returns UNKNOWN for
        # any value, including 0.0 — a low fixation figure is not a
        # pass against a boundary that does not exist.
        check = constraint.evaluate(fixation, NUTRIENT_UNIT)
        rows.append({
            "constraint_id": constraint.constraint_id, "status": check.value,
            "operator": constraint.operator, "fixation": fixation,
            "boundary": None, "unit": constraint.unit,
            "source_ids": list(constraint.source_ids),
            "detail": NITROGEN_BOUNDARY_NOTE,
        })
        checks.append(check)
        warnings.append(
            "Nitrogen fixation cannot be judged pass/fail: the snapshot records it as "
            "more than twice its boundary but stores no exact boundary value.")

    return {"overall_status": overall_from_checks(checks).value,
            "constraint_results": rows, "warnings": warnings}


def describe_nutrients_uncertainty(result: dict[str, Any]) -> list[str]:
    # ISSUE-20, same crash class as evaluate_nutrients_result: a
    # non-dict result is reported, not dereferenced.
    if not isinstance(result, dict):
        return ["No calculation result was supplied; uncertainty cannot be assessed."]
    statements = list(result.get("limitations", []))
    if result.get("calculation_status") != CalculationStatus.COMPLETED.value:
        statements.append("No completed calculation is available for uncertainty assessment.")
    statements.append(
        "Nitrogen has no stored boundary: its evaluation is UNKNOWN by design, "
        "and no value of nitrogen fixation can make it PASS.")
    statements.append("Input provenance is carried as source identifiers but source credibility is not independently assessed by this module.")
    return statements
