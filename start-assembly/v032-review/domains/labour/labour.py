"""Deterministic labour-time calculations (not a full labour model).

Two pieces, both arithmetic on caller-stated figures:

* Paid work: the caller's ``paid_work_hours_per_week`` against the
  48 h/week ILO long-hours threshold. The threshold is NOT re-derived
  here: it is read from the stored plan limits
  (``contracts.plan_limits.load_plan_limits``, constraint
  ``paid_work_hours_per_week``) by :func:`paid_work_threshold_hours_per_week`
  — the single place the bound lives (a v0.3.1 code constant, not a
  snapshot CSV row; see ``data/SNAPSHOT_PROVENANCE.md``).
* Unpaid care: the stated total (billion hours/day) split by the
  stated women's share (percent)::

      women_hours = total * women_share / 100
      men_hours   = total * (1 - women_share / 100)

  With the snapshot values (ILO 2018: total 16.4 billion hours/day,
  women's share 76.2%) that is 12.4968 / 3.9032 billion hours/day.
  Per-person care hours are computed ONLY when the caller explicitly
  supplies a population; no population is ever assumed. Combining
  the 2018 care figures with a 2024 population is a year mismatch
  and is stated as a limitation whenever both are combined.
"""
from __future__ import annotations
from typing import Any, Optional
import math
from contracts.plan_limits import load_plan_limits
from contracts.statuses import CalculationStatus
from contracts.constraints import Constraint
from domains.food.production import data_status_for

# Registry units (contracts/units.py, ISSUE-34) used by this domain.
UNIT_HOURS_PER_WEEK = "hours/week"
UNIT_HOURS_PER_DAY = "hours/day"
UNIT_PERCENT = "percent"
UNIT_PERSON = "person"


def paid_work_threshold_hours_per_week() -> float:
    """The paid-work long-hours threshold, from the stored plan limits.

    48 h/week, the ILO long-hours threshold used in the sources, not
    a PCAC rule. It is a v0.3.1 code constant stored in
    ``contracts.plan_limits`` — read here, never re-derived or
    hard-coded in this domain, so a future correction to the stored
    bound is picked up by every caller.
    """
    return float(load_plan_limits().constraint("paid_work_hours_per_week").bound)


def _synthetic_limitation(source_ids: Optional[list[str]]) -> list[str]:
    if data_status_for(source_ids) == "synthetic":
        return ["Results derive from synthetic sources; they are teaching/test data and must not be used for a real allocation."]
    return []


def labour_balance(
    unpaid_care_hours_per_day_billion: Optional[float],
    women_share_unpaid_care_percent: Optional[float],
    paid_work_hours_per_week: Optional[float] = None,
    population: Optional[float] = None,
    snapshot_paid_work_hours_per_week_employed: Optional[float] = None,
    snapshot_paid_work_hours_per_week_all_adults: Optional[float] = None,
    assumptions: Optional[list[str]] = None,
    source_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Split stated unpaid-care time by gender; echo stated paid work.

    The care total is in billion hours per day and the women's share
    is a percent (0-100). Values are retained at full precision;
    display rounding is separate. Per-person care hours are computed
    only when ``population`` is explicitly supplied.
    """
    required = {
        "unpaid_care_hours_per_day_billion": unpaid_care_hours_per_day_billion,
        "women_share_unpaid_care_percent": women_share_unpaid_care_percent,
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                "missing_fields": missing, "metrics": {}, "display_metrics": {},
                "metric_units": {}, "assumptions": list(assumptions or []),
                "source_ids": list(source_ids or []),
                "data_status": data_status_for(source_ids),
                "limitations": ["Required numeric inputs were not supplied; no balance was calculated."] + _synthetic_limitation(source_ids)}

    values: dict[str, Any] = dict(required)
    for key, value in (
        ("paid_work_hours_per_week", paid_work_hours_per_week),
        ("population", population),
        ("snapshot_paid_work_hours_per_week_employed", snapshot_paid_work_hours_per_week_employed),
        ("snapshot_paid_work_hours_per_week_all_adults", snapshot_paid_work_hours_per_week_all_adults),
    ):
        if value is not None:
            values[key] = value
    invalid = [k for k, v in values.items() if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)]
    if invalid:
        return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [],
                "error": "Non-finite or non-numeric calculation input: " + ", ".join(invalid),
                "metrics": {}, "display_metrics": {}, "metric_units": {},
                "assumptions": list(assumptions or []), "source_ids": list(source_ids or []),
                "data_status": data_status_for(source_ids),
                "limitations": ["Calculation rejected invalid numeric input."] + _synthetic_limitation(source_ids)}
    if unpaid_care_hours_per_day_billion < 0:
        return _error("unpaid_care_hours_per_day_billion must be non-negative", assumptions, source_ids)
    if not 0.0 <= women_share_unpaid_care_percent <= 100.0:
        return _error("women_share_unpaid_care_percent must be between 0 and 100 inclusive", assumptions, source_ids)
    if paid_work_hours_per_week is not None and paid_work_hours_per_week < 0:
        return _error("paid_work_hours_per_week must be non-negative", assumptions, source_ids)
    if population is not None:
        if population <= 0:
            return _error("population must be greater than zero", assumptions, source_ids)
        # ISSUE-12(d), low-level mirror of the validate_inputs rule:
        # population counts people, so a fractional population is an
        # error here too (direct callers bypass validate_inputs).
        # Tolerance-based, as in food: a snapshot-derived 8.2e9
        # arrives as 8199999999.999999 through float multiplication.
        if not math.isclose(float(population), round(float(population)),
                            rel_tol=1e-9, abs_tol=1e-6):
            return _error("population must be a whole number", assumptions, source_ids)
    for key in ("snapshot_paid_work_hours_per_week_employed",
                "snapshot_paid_work_hours_per_week_all_adults"):
        if values.get(key) is not None and values[key] < 0:
            return _error(f"{key} must be non-negative", assumptions, source_ids)

    total = float(unpaid_care_hours_per_day_billion)
    share = float(women_share_unpaid_care_percent)
    women_hours = total * share / 100.0
    men_hours = total * (1.0 - share / 100.0)
    metrics: dict[str, Any] = {
        "unpaid_care_hours_per_day_billion": total,
        "women_share_unpaid_care_percent": share,
        "women_unpaid_care_hours_per_day_billion": women_hours,
        "men_unpaid_care_hours_per_day_billion": men_hours,
    }
    metric_units: dict[str, str] = {
        "unpaid_care_hours_per_day_billion": UNIT_HOURS_PER_DAY,
        "women_share_unpaid_care_percent": UNIT_PERCENT,
        "women_unpaid_care_hours_per_day_billion": UNIT_HOURS_PER_DAY,
        "men_unpaid_care_hours_per_day_billion": UNIT_HOURS_PER_DAY,
    }
    if paid_work_hours_per_week is not None:
        metrics["paid_work_hours_per_week"] = float(paid_work_hours_per_week)
        metric_units["paid_work_hours_per_week"] = UNIT_HOURS_PER_WEEK
    if population is not None:
        total_hours_per_day = total * 1_000_000_000
        metrics["population"] = float(population)
        metric_units["population"] = UNIT_PERSON
        metrics["unpaid_care_hours_per_person_per_day"] = total_hours_per_day / float(population)
        metrics["women_unpaid_care_hours_per_person_per_day"] = women_hours * 1_000_000_000 / float(population)
        metrics["men_unpaid_care_hours_per_person_per_day"] = men_hours * 1_000_000_000 / float(population)
        metric_units["unpaid_care_hours_per_person_per_day"] = UNIT_HOURS_PER_DAY
        metric_units["women_unpaid_care_hours_per_person_per_day"] = UNIT_HOURS_PER_DAY
        metric_units["men_unpaid_care_hours_per_person_per_day"] = UNIT_HOURS_PER_DAY
    for key in ("snapshot_paid_work_hours_per_week_employed",
                "snapshot_paid_work_hours_per_week_all_adults"):
        if values.get(key) is not None:
            metrics[key] = float(values[key])
            metric_units[key] = UNIT_HOURS_PER_WEEK
    # ISSUE-19 (2026-11-11), as in food: inputs are checked finite
    # above, but the COMPUTED metrics can still overflow — check
    # every computed metric is finite before claiming COMPLETED.
    non_finite = [k for k, v in metrics.items() if not math.isfinite(v)]
    if non_finite:
        return _error("Computed metric(s) are not finite (overflow): " + ", ".join(non_finite),
                      assumptions, source_ids)
    display = {k: round(v, 4) for k, v in metrics.items() if k != "population"}
    if "population" in metrics:
        pop = metrics["population"]
        # Tolerance-based, as in the whole-number validation: a
        # snapshot-derived 8.2e9 arrives as 8199999999.999999 through
        # float multiplication, and displaying that as a headcount
        # would be a float artefact, not a real figure.
        display["population"] = int(round(pop)) if math.isclose(
            float(pop), round(float(pop)), rel_tol=1e-9, abs_tol=1e-6) else pop
    limitations = [
        "This is an aggregate labour-time summary, not a model of any household, workplace, or labour market.",
        "Global averages hide distribution by region, income, gender, and household; use them for scale, then get consented local data for a real plan.",
        "The model does not allocate labour or approve any plan.",
    ]
    if population is not None:
        # The care figures are 2018 (ILO) and the population figure
        # the example supplies is 2024 (UN) — combining them is a
        # year mismatch, stated here whenever both are combined.
        limitations.append(
            "Year mismatch: the unpaid-care figures are 2018 (ILO) while the population "
            "figure is 2024 (UN World Population Prospects) — per-person care hours "
            "combine different years and are a scale illustration, not a same-year measurement.")
    if (snapshot_paid_work_hours_per_week_employed is not None
            or snapshot_paid_work_hours_per_week_all_adults is not None):
        limitations.append(
            "Snapshot context values are 2026 averages from the Gethin and Saez IMF "
            "dataset, supplied by the caller from the snapshot; they are context only — "
            "not the caller's paid-work figure and not checked against the threshold.")
    limitations += _synthetic_limitation(source_ids)
    return {
        "calculation_status": CalculationStatus.COMPLETED.value,
        "missing_fields": [], "metrics": metrics, "display_metrics": display,
        "metric_units": metric_units,
        "assumptions": list(assumptions or []) + [
            "Women's and men's care hours are computed by splitting the stated total "
            "by the stated women's share; men's share is 100 minus women's share.",
        ],
        "source_ids": list(source_ids or []),
        "data_status": data_status_for(source_ids),
        "limitations": limitations,
    }


def _error(message: str, assumptions: Optional[list[str]], source_ids: Optional[list[str]]) -> dict[str, Any]:
    return {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [], "error": message,
            "metrics": {}, "display_metrics": {}, "metric_units": {},
            "assumptions": list(assumptions or []),
            "source_ids": list(source_ids or []), "data_status": data_status_for(source_ids),
            "limitations": [message] + _synthetic_limitation(source_ids)}


def default_labour_constraints(
    bound: Optional[float] = None,
    tolerance: float = 0.0,
) -> list[Constraint]:
    """The paid-work long-hours constraint.

    ``bound`` is the threshold in hours/week, supplied by the caller
    of this function — the domain passes the stored bound from
    ``paid_work_threshold_hours_per_week()``. ``bound=None`` is a
    deliberately bound-less constraint (no threshold stated -> always
    UNKNOWN, never PASS), so boundless=True is passed explicitly;
    an accidental missing bound now raises at construction instead
    (ISSUE-12). A stated paid-work figure of None likewise evaluates
    UNKNOWN: no figure, no pass.
    """
    return [Constraint(
        constraint_id="paid_work_hours_per_week",
        name="Paid work hours within long-hours threshold",
        resource_id="labour_time", operator="<=", bound=bound,
        boundless=bound is None,
        unit=UNIT_HOURS_PER_WEEK,
        tolerance=tolerance,
        notes="Hours per week. 48 hours is the ILO long-hours threshold used in the "
              "sources, not a PCAC rule. Bound is a v0.3.1 code constant stored in "
              "contracts.plan_limits, not a snapshot CSV row.",
    )]
