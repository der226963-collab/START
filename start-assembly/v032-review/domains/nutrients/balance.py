"""Deterministic nutrient stock-and-flow balances (ISSUE-34, 2026-11-13).

Balance (both nutrients, same shape)::

    soil_change = inputs - uptake - losses

where inputs is phosphorus applied or nitrogen fixed, all in Tg/yr.
The v0.3.1 teaching example (``domains/compat_v031.py`` soil_summary)
shows the arithmetic in abstract units — 100 applied, 50 uptake,
30 losses, 20 soil change — and is reused ONLY as a labelled test
input, never as real data.

Snapshot values used here (``data/real_planning_data.csv``, Planetary
Health Check 2025, PIK report):

* phosphorus application to cropland 18.2 Tg/yr (2025)
* phosphorus regional boundary 6.2 Tg/yr (2025)
* nitrogen fixation 165 Tg/yr (2025), "more than twice its boundary",
  high-risk zone — NO exact boundary stored.

Everything else is an explicit caller input. No figure is invented.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Any, Optional
import math
from contracts.constraints import Constraint
from contracts.plan_limits import load_plan_limits
from contracts.statuses import CalculationStatus
from domains.food.production import data_status_for

NUTRIENT_UNIT = "Tg/yr"
"""Registry unit for phosphorus and nitrogen quantities (ISSUE-34:
"Tg/yr" is dimension "mass_rate_year", base Tg/yr)."""

PHOSPHORUS_SOURCE_IDS = [
    "snapshot:phosphorus_application_to_cropland:2025",
    "snapshot:phosphorus_regional_boundary:2025",
]
NITROGEN_SOURCE_IDS = ["snapshot:nitrogen_fixation:2025"]

NITROGEN_BOUNDARY_NOTE = (
    "Snapshot records nitrogen fixation 165 Tg N/yr as more than twice "
    "its boundary (Planetary Health Check 2025, high-risk zone), but no "
    "exact boundary value is stored, so no pass/fail is claimed. A "
    "nitrogen check always evaluates UNKNOWN, never PASS."
)


@lru_cache(maxsize=1)
def stored_phosphorus_boundary() -> float:
    """The stored phosphorus regional boundary (6.2 Tg/yr, snapshot 2025).

    Loaded from the versioned snapshot via ``contracts.plan_limits``,
    never hard-coded: if the snapshot changes, the boundary follows
    it. Cached: the snapshot is versioned data, not a live feed.
    """
    return float(load_plan_limits().constraint(
        "phosphorus_application_tg_per_year").bound)


def soil_change_from_balance(applied_tg_per_year: float, uptake_tg_per_year: float,
                             losses_tg_per_year: float) -> float:
    """Pure stock-and-flow arithmetic: inputs - uptake - losses."""
    return applied_tg_per_year - uptake_tg_per_year - losses_tg_per_year


def phosphorus_excess_and_ratio(applied_tg_per_year: float,
                                boundary_tg_per_year: float) -> tuple[float, float]:
    """Excess over the boundary and ratio to it, snapshot conventions.

    Excess is full precision (18.2 - 6.2 is exactly 12.0 in float);
    the ratio is rounded to 2 decimals, mirroring
    ``domains/compat_v031.py`` soil_summary (18.2 / 6.2 -> 2.94).
    """
    return (applied_tg_per_year - boundary_tg_per_year,
            round(applied_tg_per_year / boundary_tg_per_year, 2))


def _error(message: str, assumptions: Optional[list[str]], source_ids: Optional[list[str]]) -> dict[str, Any]:
    return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [], "error": message,
            "metrics": {}, "display_metrics": {}, "assumptions": list(assumptions or []),
            "source_ids": list(source_ids or []), "data_status": data_status_for(source_ids),
            "limitations": [message]}


def nutrient_balance(
    nutrient: str,
    applied_tg_per_year: Optional[float],
    uptake_tg_per_year: Optional[float],
    losses_tg_per_year: Optional[float],
    assumptions: Optional[list[str]] = None,
    source_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Compute one nutrient's stock-and-flow balance in Tg/yr.

    ``nutrient`` is "phosphorus" (inputs keyed ``..._applied_...``)
    or "nitrogen" (inputs keyed ``..._fixation_...``). A ``None`` /
    missing uptake or losses returns INSUFFICIENT_INPUT — it is never
    silently treated as 0.0 (same rule as food imports/losses,
    ISSUE-15). Values are retained at full precision; display
    rounding is separate.
    """
    if nutrient not in ("phosphorus", "nitrogen"):
        return _error(f"unknown nutrient: {nutrient!r}", assumptions, source_ids)
    input_field = ("phosphorus_applied_tg_per_year" if nutrient == "phosphorus"
                   else "nitrogen_fixation_tg_per_year")
    required = {
        input_field: applied_tg_per_year,
        f"{nutrient}_uptake_tg_per_year": uptake_tg_per_year,
        f"{nutrient}_losses_tg_per_year": losses_tg_per_year,
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                "missing_fields": missing, "metrics": {}, "display_metrics": {},
                "assumptions": list(assumptions or []), "source_ids": list(source_ids or []),
                "data_status": data_status_for(source_ids),
                "limitations": ["Required numeric inputs were not supplied; no balance was calculated."]}

    invalid = [k for k, v in required.items() if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)]
    if invalid:
        return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [],
                "error": "Non-finite or non-numeric calculation input: " + ", ".join(invalid),
                "metrics": {}, "display_metrics": {}, "assumptions": list(assumptions or []),
                "source_ids": list(source_ids or []), "data_status": data_status_for(source_ids),
                "limitations": ["Calculation rejected invalid numeric input."]}
    if any(v < 0 for v in required.values()):
        return _error("Nutrient inputs, uptake and losses must be non-negative", assumptions, source_ids)

    soil_change = soil_change_from_balance(
        float(applied_tg_per_year), float(uptake_tg_per_year), float(losses_tg_per_year))
    metrics = {
        input_field: float(applied_tg_per_year),
        f"{nutrient}_uptake_tg_per_year": float(uptake_tg_per_year),
        f"{nutrient}_losses_tg_per_year": float(losses_tg_per_year),
        f"{nutrient}_soil_change_tg_per_year": soil_change,
    }
    # ISSUE-19 (food): a computed metric that overflows to inf is an
    # ERROR, never a result — json.dumps cannot emit Infinity.
    non_finite = [k for k, v in metrics.items() if not math.isfinite(v)]
    if non_finite:
        return _error("Computed metric(s) are not finite (overflow): " + ", ".join(non_finite),
                      assumptions, source_ids)
    display = {k: round(v, 2) for k, v in metrics.items()}
    limitations = [
        "This is an aggregate stock-and-flow balance, not a field-level nutrient plan.",
        "Global nutrient excess and local nutrient deficit exist at the same time. "
        "A global balance does not tell a farmer what a specific field needs.",
        "The model does not allocate nutrients or approve any plan.",
    ]
    return {
        "calculation_status": CalculationStatus.COMPLETED.value,
        "missing_fields": [], "metrics": metrics, "display_metrics": display,
        "assumptions": list(assumptions or []),
        "source_ids": list(source_ids or []),
        "data_status": data_status_for(source_ids),
        "limitations": limitations,
    }


def default_nutrient_constraints(
    phosphorus_boundary: Optional[float] = None,
    geography: str = "global",
    period: str = "2025",
    tolerance: float = 0.0,
) -> list[Constraint]:
    """The nutrients constraint set: phosphorus bounded, nitrogen bound-less.

    ``phosphorus_boundary`` defaults to the STORED snapshot boundary
    (6.2 Tg/yr) loaded via :func:`stored_phosphorus_boundary`; a
    caller passing an explicit boundary is stating the same stored
    value (the domain layer rejects a differing one as a
    wrong-bound error). The nitrogen constraint is deliberately
    bound-less (``boundless=True``): the snapshot stores no exact
    nitrogen boundary, so it always evaluates UNKNOWN, never PASS
    (same construction as the nitrogen constraint in
    ``contracts/plan_limits.py``). ``tolerance`` applies to the
    phosphorus constraint only (ISSUE-35: a non-zero tolerance can
    flip a verdict, so it is an explicit caller choice, surfaced in
    the evaluation row — never read from the request); the nitrogen
    constraint has no bound for a tolerance to act on.
    """
    boundary = stored_phosphorus_boundary() if phosphorus_boundary is None else phosphorus_boundary
    return [
        Constraint(
            constraint_id="phosphorus_application_tg_per_year",
            name="Phosphorus application to cropland within regional boundary",
            resource_id="phosphorus", operator="<=", bound=boundary,
            unit=NUTRIENT_UNIT, geography=geography, period=period,
            source_ids=list(PHOSPHORUS_SOURCE_IDS),
            tolerance=tolerance,
            notes="Tg P per year. Regional boundary, Planetary Health Check 2025 (PIK report). "
                  "Snapshot application 18.2 Tg P/yr is about 3x this boundary.",
        ),
        Constraint(
            constraint_id="nitrogen_fixation_tg_per_year",
            name="Nitrogen fixation against its boundary",
            resource_id="nitrogen", operator="<=", bound=None, boundless=True,
            unit=NUTRIENT_UNIT, geography=geography, period=period,
            source_ids=list(NITROGEN_SOURCE_IDS),
            notes=NITROGEN_BOUNDARY_NOTE,
        ),
    ]
