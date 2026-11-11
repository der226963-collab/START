"""Independent checks for planning results.

This module independently re-derives the food pilot's arithmetic from the
original request. For domains without an independent verifier it reports
PARTIALLY_VERIFIED rather than claiming a complete verification.
"""
from __future__ import annotations
from typing import Any
import math
from contracts.statuses import CheckStatus, CalculationStatus, VerificationStatus, overall_from_checks


FOOD_METRICS = (
    "effective_supply_after_losses",
    "total_available_kcal_per_capita_per_day",
    "surplus_kcal_per_capita_per_day",
    "annual_gap_or_surplus_kcal",
)


def _strict_number(request: dict[str, Any], field: str) -> float:
    """ISSUE-29 (2026-11-11): the verifier's independent recalculation
    must not accept what validation rejects. ``float()`` coerces
    ``True`` -> 1.0 and ``"2800"`` -> 2800.0, so a calculation built
    with population=1 used to verify VERIFIED against a request with
    population=True, supply="2800" — values validation would reject.
    Only real (non-bool) finite numbers are accepted here; anything
    else raises, and the caller records it as a verification issue.
    Population must additionally be a whole number, the same rule
    validate_inputs enforces (ISSUE-12(d)).
    """
    value = request[field]  # KeyError propagates: missing field is an issue, not a default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"request field {field!r} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"request field {field!r} must be finite")
    if field == "population" and not math.isclose(float(value), round(float(value)),
                                                  rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("request field 'population' must be a whole number")
    return float(value)


# ISSUE-22 (2026-11-11): per-metric verification tolerances. The old
# single rule — rel_tol=1e-10, abs_tol=1e-8 for every metric — let a
# +100,000 kcal tamper pass at global scale, because the true annual
# gap is 1,451,605,000,000,000.0 kcal/yr and 1e-10 of that is
# ~145,160 kcal/yr of slack. Numbers, verified live:
#   * per-capita metrics (kcal/capita/day, ~1e3 scale): rel 1e-10,
#     abs 1e-8 — unchanged; the formula-difference noise between the
#     production and verifier expressions is ~1 ulp (~5e-13).
#   * annual_gap_or_surplus_kcal: rel 1e-11, abs 1e-6 kcal/yr. At the
#     global scale that allows ~14,516 kcal/yr of deviation — 10,000x
#     the ~1-2 kcal/yr noise from the two expressions differing in
#     the last bits, but 7x SMALLER than the +100,000 kcal tamper,
#     which now fails. The absolute cap is deliberately < 1: the
#     existing +1 kcal tamper test (BASE scale, annual ~6.4e9, allowed
#     ~0.064) must still fail, and abs_tol=1.0 would have let a +1
#     tamper pass exactly at the boundary (isclose uses <=).
#   * input echoes (population, supply, requirement, imports): rel
#     1e-10, abs 1e-8 — except population, abs 1.0 (one person): an
#     echo is a copied input, not a computation, so a whole-person
#     deviation is the smallest meaningful absolute slack.
#   * annualization_days: exact (365.0).
FOOD_METRIC_TOLERANCES: dict[str, tuple[float, float]] = {
    "effective_supply_after_losses": (1e-10, 1e-8),
    "total_available_kcal_per_capita_per_day": (1e-10, 1e-8),
    "surplus_kcal_per_capita_per_day": (1e-10, 1e-8),
    "annual_gap_or_surplus_kcal": (1e-11, 1e-6),
    "population": (1e-10, 1.0),
    "supply_kcal_per_capita_per_day": (1e-10, 1e-8),
    "requirement_kcal_per_capita_per_day": (1e-10, 1e-8),
    "imports_kcal_per_capita_per_day": (1e-10, 1e-8),
    "annualization_days": (0.0, 0.0),
}


def _independently_recalculate_food(request: dict[str, Any]) -> dict[str, float]:
    """Separate implementation of the food balance equations for cross-checking."""
    population = _strict_number(request, "population")
    domestic = _strict_number(request, "supply_kcal_per_capita_per_day")
    requirement = _strict_number(request, "requirement_kcal_per_capita_per_day")
    # ISSUE-15 (decision (b), 2026-11-11): the ISSUE-13 None -> 0.0
    # normalisation is REMOVED here too. Imports/losses are required
    # stated inputs now, so a request missing them, or passing None,
    # must NOT verify silently against a 0.0 recalculation: direct
    # indexing raises KeyError (missing) and float(None) raises
    # TypeError, both caught by the caller below and recorded as a
    # verification issue. Keeping the old default would let a
    # calculation built on unstated losses/imports verify as if they
    # had been stated as zero.
    imports = _strict_number(request, "imports_kcal_per_capita_per_day")
    loss_rate = _strict_number(request, "losses_fraction")
    # ISSUE-43 (2026-11-11): ONE canonical expression for the
    # effective supply, shared with domains/food/production.py:
    # supply * (1 - losses). The verifier used to compute
    # domestic - (domestic * loss_rate), which differs in floating
    # point (absorbed in practice by the tolerance, but an
    # "independent" re-derivation that is textually a different
    # formula is fragile by construction). The total is
    # math.fsum((effective, imports)) in production vs a plain + here;
    # for two operands both are correctly rounded, so they agree
    # exactly — the canonicalisation that matters is the (1 - loss)
    # factor, done here.
    after_loss = domestic * (1.0 - loss_rate)
    available = after_loss + imports
    difference = available - requirement
    return {
        "effective_supply_after_losses": after_loss,
        "total_available_kcal_per_capita_per_day": available,
        "surplus_kcal_per_capita_per_day": difference,
        "annual_gap_or_surplus_kcal": difference * population * 365.0,
    }


def verify_domain_result(
    domain_id: str,
    calculation: dict[str, Any],
    evaluation: dict[str, Any],
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    checks: list[str] = []
    calc_status = calculation.get("calculation_status")
    claimed = evaluation.get("overall_status")
    valid_statuses = {s.value for s in CheckStatus}

    if calc_status not in {s.value for s in CalculationStatus}:
        issues.append(f"Unrecognized calculation_status: {calc_status!r}")
    if claimed not in valid_statuses:
        issues.append(f"Unrecognized overall evaluation status: {claimed!r}")

    rows = evaluation.get("constraint_results")
    if not isinstance(rows, list):
        issues.append("constraint_results must be a list")
        rows = []
    row_statuses: list[CheckStatus] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"constraint_results[{index}] must be an object")
            continue
        status = row.get("status")
        if status not in valid_statuses:
            issues.append(f"constraint_results[{index}] has invalid status {status!r}")
            continue
        row_statuses.append(CheckStatus(status))

    derived = overall_from_checks(row_statuses)
    if calc_status == CalculationStatus.COMPLETED.value:
        if not rows:
            issues.append("Completed calculation has no evaluated constraints; empty checks cannot pass.")
        if claimed != derived.value:
            issues.append(f"Claimed overall status {claimed!r} does not match derived status {derived.value!r}.")
    else:
        if claimed == CheckStatus.PASS.value:
            issues.append("A non-completed calculation cannot have an overall PASS.")
        if any(s == CheckStatus.PASS for s in row_statuses):
            issues.append("A non-completed calculation cannot contain a passing constraint result.")

    if calc_status == CalculationStatus.INSUFFICIENT_INPUT.value and claimed not in {
        CheckStatus.INCOMPLETE.value, CheckStatus.UNKNOWN.value, CheckStatus.NOT_CHECKED.value
    }:
        issues.append("INSUFFICIENT_INPUT must remain visibly incomplete, unknown or not checked.")
    checks.append("status_and_structure")

    independent_math = False
    if domain_id == "food" and calc_status == CalculationStatus.COMPLETED.value and isinstance(request, dict):
        try:
            expected = _independently_recalculate_food(request)
            metrics = calculation.get("metrics")
            if not isinstance(metrics, dict):
                issues.append("Food calculation metrics must be an object.")
            else:
                expected_values = {
                    **expected,
                    # ISSUE-29: echoes go through the same strict
                    # number check — a bool/str echo must fail
                    # verification, not be float()-coerced into one.
                    # ISSUE-15: stated inputs, direct indexing — a
                    # missing/None imports value fails verification
                    # (KeyError/TypeError -> issue) instead of
                    # silently verifying against an assumed 0.0.
                    "population": _strict_number(request, "population"),
                    "supply_kcal_per_capita_per_day": _strict_number(request, "supply_kcal_per_capita_per_day"),
                    "requirement_kcal_per_capita_per_day": _strict_number(request, "requirement_kcal_per_capita_per_day"),
                    "imports_kcal_per_capita_per_day": _strict_number(request, "imports_kcal_per_capita_per_day"),
                    "annualization_days": 365.0,
                }
                for key, expected_value in expected_values.items():
                    actual = metrics.get(key)
                    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
                        issues.append(f"Food metric {key!r} is missing or non-finite.")
                    else:
                        # ISSUE-22: per-metric tolerances (see
                        # FOOD_METRIC_TOLERANCES above), not one
                        # relative tolerance for every scale.
                        rel_tol, abs_tol = FOOD_METRIC_TOLERANCES[key]
                        if not math.isclose(float(actual), expected_value, rel_tol=rel_tol, abs_tol=abs_tol):
                            issues.append(f"Food metric {key!r} failed independent verification: expected {expected_value!r}, got {actual!r}.")
                expected_check = CheckStatus.PASS if expected["total_available_kcal_per_capita_per_day"] >= _strict_number(request, "requirement_kcal_per_capita_per_day") else CheckStatus.FAIL
                adequacy_rows = [row for row in rows if isinstance(row, dict) and row.get("constraint_id") == "food_energy_adequacy"]
                if len(adequacy_rows) != 1:
                    issues.append("Food result must contain exactly one food_energy_adequacy constraint result.")
                elif adequacy_rows[0].get("status") != expected_check.value:
                    issues.append("Food adequacy constraint status does not match the independently recomputed balance.")
                independent_math = not any("Food metric" in item or "Food adequacy" in item for item in issues)
            checks.append("independent_food_arithmetic")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            issues.append(f"Independent food recalculation could not be completed: {type(exc).__name__}: {exc}")
    elif calc_status == CalculationStatus.COMPLETED.value:
        # ISSUE-26 (2026-11-11): for food, a COMPLETED calculation with
        # no request means the independent arithmetic — the feature the
        # food verifier exists for — was skipped with no issue recorded,
        # and the result looked like a clean PARTIALLY_VERIFIED. Record
        # the missing input explicitly; the result is FAILED, not a
        # clean partial verification. (For non-food domains there is no
        # independent arithmetic to skip, so nothing is recorded.)
        if domain_id == "food":
            issues.append("no request supplied; independent food arithmetic could not be performed")
        # The generic engine cannot claim mathematical verification for an
        # arbitrary domain merely because its own outputs are well-formed.
        pass

    if issues:
        status = VerificationStatus.FAILED
    elif calc_status != CalculationStatus.COMPLETED.value:
        status = VerificationStatus.NOT_VERIFIABLE
    elif independent_math:
        status = VerificationStatus.VERIFIED
    else:
        status = VerificationStatus.PARTIALLY_VERIFIED

    return {
        "domain_id": domain_id,
        "verification_status": status.value,
        "verified": status == VerificationStatus.VERIFIED,
        "checks_performed": checks,
        "issues": issues,
        "derived_overall_status": derived.value,
        "claimed_overall_status": claimed,
        "note": "Verification scope is explicit. Food arithmetic is independently re-derived; generic status checks do not establish source truth, model validity or real-world adequacy.",
    }
