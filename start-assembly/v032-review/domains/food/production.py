"""Deterministic food-energy availability calculations (not a full food system model).

Formula (ISSUE-15, 2026-11-11) — v0.3.2::

    effective_supply = supply * (1 - losses_fraction)
    total_available  = effective_supply + imports_kcal_per_capita_per_day
    surplus          = total_available - requirement

v0.3.1 (``mini_ai/planning.py: food_balance()``) was ``surplus =
supply - need`` with no losses or imports. Worked numbers, verified
live: 2800/2500 gives 300 under v0.3.1 but total 2676.0 / surplus
176.0 under this formula with imports 100 and losses 0.08; the two
formulas agree ONLY at losses 0 / imports 0 (2985/2500/0/0 -> 485.0
in both). Losses/imports are the better model, so they are kept —
but they must be STATED, never silently zero: ``food_availability``
refuses a ``None``/missing imports or losses with
``INSUFFICIENT_INPUT`` (it never defaults them), and the domain layer
(``FoodDomain.validate_inputs``) now requires them too.
"""
from __future__ import annotations
from typing import Any, Optional
import math
from contracts.statuses import CalculationStatus
from contracts.constraints import Constraint


def data_status_for(source_ids: Optional[list[str]]) -> str:
    """ISSUE-36 (2026-11-11): SYNTHETIC labelling, not a provenance
    verdict. A result derives from synthetic sources iff any source_id
    carries the SYNTH marker (the v0.3.1 convention: synthetic pilot
    rows are marked SYNTH). Anything else is "unknown": source
    credibility is not independently assessed, so no result may claim
    "observed"/"verified" provenance it has not earned. The v0.3.1
    pilot guard itself (raise on a non-SYNTH household row) is
    intentionally deferred — the synthetic pilot file was deliberately
    NOT ported into this tree (see data/SNAPSHOT_PROVENANCE.md), so
    there is no pilot data in-tree to guard; see docs/ARCHITECTURE.md.
    """
    ids = list(source_ids or [])
    if any(isinstance(s, str) and "synth" in s.lower() for s in ids):
        return "synthetic"
    return "unknown"


def _synthetic_limitation(source_ids: Optional[list[str]]) -> list[str]:
    if data_status_for(source_ids) == "synthetic":
        return ["Results derive from synthetic sources; they are teaching/test data and must not be used for a real allocation."]
    return []


def food_availability(
    population: Optional[float],
    supply_kcal_per_capita_per_day: Optional[float],
    requirement_kcal_per_capita_per_day: Optional[float],
    imports_kcal_per_capita_per_day: Optional[float] = None,
    losses_fraction: Optional[float] = None,
    assumptions: Optional[list[str]] = None,
    source_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Compute a per-capita daily energy balance and annualized aggregate gap.

    Inputs are kcal/capita/day except population and the dimensionless loss fraction.
    Values are retained at full precision; display rounding is separate.
    """
    required = {
        "population": population,
        "supply_kcal_per_capita_per_day": supply_kcal_per_capita_per_day,
        "requirement_kcal_per_capita_per_day": requirement_kcal_per_capita_per_day,
        "imports_kcal_per_capita_per_day": imports_kcal_per_capita_per_day,
        "losses_fraction": losses_fraction,
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                "missing_fields": missing, "metrics": {}, "display_metrics": {},
                "assumptions": list(assumptions or []), "source_ids": list(source_ids or []),
                "data_status": data_status_for(source_ids),
                "limitations": ["Required numeric inputs were not supplied; no balance was calculated."] + _synthetic_limitation(source_ids)}

    values = required
    invalid = [k for k, v in values.items() if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)]
    if invalid:
        return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [],
                "error": "Non-finite or non-numeric calculation input: " + ", ".join(invalid),
                "metrics": {}, "display_metrics": {}, "assumptions": list(assumptions or []),
                "source_ids": list(source_ids or []), "data_status": data_status_for(source_ids),
                "limitations": ["Calculation rejected invalid numeric input."] + _synthetic_limitation(source_ids)}
    if population <= 0:
        return _error("population must be greater than zero", assumptions, source_ids)
    # ISSUE-12(d), low-level mirror of the validate_inputs rule:
    # population counts people, so a fractional population is an
    # error here too (direct callers bypass validate_inputs).
    # Tolerance-based, as in validate_inputs: a snapshot-derived
    # 8.2e9 arrives as 8199999999.999999 through float multiplication.
    if not math.isclose(float(population), round(float(population)),
                        rel_tol=1e-9, abs_tol=1e-6):
        return _error("population must be a whole number", assumptions, source_ids)
    if supply_kcal_per_capita_per_day < 0 or requirement_kcal_per_capita_per_day < 0 or imports_kcal_per_capita_per_day < 0:
        return _error("Supply, requirement and imports must be non-negative", assumptions, source_ids)
    if not 0.0 <= losses_fraction <= 1.0:
        return _error("losses_fraction must be between 0 and 1 inclusive", assumptions, source_ids)

    effective_supply = supply_kcal_per_capita_per_day * (1.0 - losses_fraction)
    total_available = math.fsum((effective_supply, imports_kcal_per_capita_per_day))
    surplus = total_available - requirement_kcal_per_capita_per_day
    annual_gap = surplus * population * 365.0
    metrics = {
        "population": float(population),
        "supply_kcal_per_capita_per_day": float(supply_kcal_per_capita_per_day),
        "effective_supply_after_losses": effective_supply,
        "imports_kcal_per_capita_per_day": float(imports_kcal_per_capita_per_day),
        "total_available_kcal_per_capita_per_day": total_available,
        "requirement_kcal_per_capita_per_day": float(requirement_kcal_per_capita_per_day),
        "surplus_kcal_per_capita_per_day": surplus,
        "annual_gap_or_surplus_kcal": annual_gap,
        "annualization_days": 365.0,
    }
    # ISSUE-19 (2026-11-11): inputs are checked finite above, but the
    # COMPUTED metrics can still overflow — e.g. food_availability(
    # 1e308, 2800, 2500, 0.0, 0.0) used to return COMPLETED with
    # annual_gap_or_surplus_kcal = inf, which json.dumps emits as
    # invalid JSON (Infinity). Check every computed metric is finite
    # before claiming COMPLETED; overflow is an ERROR, never a result.
    non_finite = [k for k, v in metrics.items() if not math.isfinite(v)]
    if non_finite:
        return _error("Computed metric(s) are not finite (overflow): " + ", ".join(non_finite),
                      assumptions, source_ids)
    display = {k: round(v, 2) for k, v in metrics.items() if k != "population" and k != "annualization_days"}
    display["population"] = int(population) if float(population).is_integer() else population
    display["annualization_days"] = 365
    return {
        "calculation_status": CalculationStatus.COMPLETED.value,
        "missing_fields": [], "metrics": metrics, "display_metrics": display,
        "assumptions": list(assumptions or []) + [
            f"Annual aggregate balance annualized using 365 days; this is a modelling convention."
        ],
        "source_ids": list(source_ids or []),
        "data_status": data_status_for(source_ids),
        "limitations": [
            "This is an aggregate food-energy balance, not proof that every household is fed.",
            "Distribution, access, intra-community inequality, micronutrient adequacy, dietary quality and seasonality are not modelled.",
            "The model does not allocate food or approve any plan.",
        ] + _synthetic_limitation(source_ids),
    }


def _error(message: str, assumptions: Optional[list[str]], source_ids: Optional[list[str]]) -> dict[str, Any]:
    return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [], "error": message,
            "metrics": {}, "display_metrics": {}, "assumptions": list(assumptions or []),
            "source_ids": list(source_ids or []), "data_status": data_status_for(source_ids),
            "limitations": [message] + _synthetic_limitation(source_ids)}


def default_food_constraints(requirement: Optional[float] = None, tolerance: float = 0.0) -> list[Constraint]:
    # ISSUE-12: requirement=None is a deliberately bound-less
    # constraint (no requirement stated -> always UNKNOWN, never
    # PASS), so boundless=True is passed explicitly; an accidental
    # missing bound now raises at construction instead.
    # ISSUE-35: tolerance defaults to 0.0 and is surfaced in the food
    # evaluation row (see domains/food/evaluation.py); a non-zero
    # tolerance is an explicit caller choice, never a request field.
    return [Constraint(
        constraint_id="food_energy_adequacy",
        name="Per-capita food energy meets stated requirement",
        resource_id="food_energy", operator=">=", bound=requirement,
        boundless=requirement is None,
        unit="kcal/capita/day",
        tolerance=tolerance,
        notes="Compares aggregate daily available energy with the supplied planning requirement; not a household-level guarantee.",
    )]
