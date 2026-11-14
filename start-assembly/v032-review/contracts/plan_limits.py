"""Versioned, sourced real-world snapshot and plan-limit constraint set.

ISSUE-01 fix. Ports the v0.3.1 global snapshot
(`data/real_planning_data.csv`, byte-identical copy of
``~/workspace/ai-starter/data/real_planning_data.csv``) into the review
copy as versioned data, and builds the versioned constraint set the
engine loads by default, so a plan check no longer depends entirely on
caller-supplied bounds.

Provenance for every value lives in ``data/SNAPSHOT_PROVENANCE.md`` and
in the CSV itself (``source`` / ``licence_or_status`` / ``note`` columns).
Nothing here invents a value: limits come from the snapshot CSV, except
where the provenance note says otherwise (48 h and 820 g CO2/kWh are
v0.3.1 code constants, labelled as such; 2500 kcal/day is a stated
planning assumption, not a FAO figure; nitrogen has NO boundary).

Wrong-bound detection: the stored limits are authoritative. A caller may
pass ``overrides`` naming a bound, but an override that differs from the
stored bound raises ``ValueError`` instead of being silently accepted —
so a phosphorus boundary entered as 62 instead of 6.2 is caught, never
applied. An override that exactly matches the stored bound is accepted
as a no-op confirmation. No override can create a bound for nitrogen:
its boundary is unknown and stays unknown.

UNKNOWN/INCOMPLETE are never converted to PASS. ``verified`` is never set
here: passing these checks means only that the plan did not breach the
stored limits checked here; it does not mean a plan is good, fair, or
decided, and human approval is still required for any decision.
Wire format stays JSON: :func:`check_plan_limits` returns plain dicts.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constraints import Constraint
from .statuses import CheckStatus, overall_from_checks

SNAPSHOT_VERSION = "v0.3.1-2026-11-04"
"""The v0.3.1 snapshot as it stood when the v0.3.2 review was written."""

SNAPSHOT_SOURCE = "~/workspace/ai-starter/data/real_planning_data.csv"
CONSTRAINT_SET_VERSION = "1.0.0"

DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "real_planning_data.csv"

# Lifecycle CO2 intensities, g CO2 per kWh, ported verbatim from v0.3.1
# mini_ai/planning.py. IPCC median-style ILLUSTRATIVE values, stated here
# so they can be challenged. They are NOT in the real snapshot CSV, and
# they are NOT real-time grid data.
CO2_INTENSITY_G_PER_KWH = {
    "coal": 820,
    "gas": 490,
    "solar": 45,
    "wind": 11,
    "hydro": 24,
    "nuclear": 12,
}

# Plan keys accepted by check_plan_limits, exactly as v0.3.1
# mini_ai/planning.py:check_plan_limits() spelled them. The bare key
# "nitrogen" matches nothing and is rejected as unknown (see below):
# the nitrogen value must be keyed "nitrogen_fixation_tg_per_year".
PLAN_KEYS = (
    "phosphorus_application_tg_per_year",
    "food_kcal_per_capita_per_day",
    "planning_need_kcal_per_capita_per_day",
    "paid_work_hours_per_week",
    "nitrogen_fixation_tg_per_year",
)

# Which plan key each stored constraint governs. The food need is NOT a
# stored limit in this mapping: it is a plan assumption with a loaded
# default (see PlanLimits.food_need_default_kcal_per_capita_per_day).
_LIMIT_PLAN_KEYS = {
    "phosphorus_application_tg_per_year": "phosphorus_application_tg_per_year",
    "paid_work_hours_per_week": "paid_work_hours_per_week",
}


def load_snapshot(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the versioned snapshot CSV as rows keyed by indicator+year.

    Values are floats; source/licence/note columns are preserved verbatim.
    The file is read, never written, by this module.
    """
    snapshot_path = Path(path) if path is not None else DEFAULT_SNAPSHOT_PATH
    rows: list[dict[str, Any]] = []
    with open(snapshot_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["value"] = float(row["value"])
            rows.append(row)
    return rows


def get(rows: list[dict[str, Any]], indicator: str, year: int) -> float:
    for row in rows:
        if row["indicator"] == indicator and int(row["year"]) == year:
            return float(row["value"])
    raise KeyError(f"{indicator} {year} not found in snapshot")


@dataclass
class PlanLimits:
    """The versioned constraint set built from the loaded snapshot."""

    snapshot_version: str
    constraint_set_version: str
    constraints: list[Constraint] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    # Stored numeric bounds by constraint_id, for override validation.
    bounds: dict[str, float] = field(default_factory=dict)
    # Constraint ids that are explicitly bound-less / unknown.
    unbounded: list[str] = field(default_factory=list)
    # Default food planning need (kcal/capita/day). A stated planning
    # assumption, NOT a FAO figure (see data/SNAPSHOT_PROVENANCE.md).
    food_need_default_kcal_per_capita_per_day: float = 2500.0

    def constraint(self, constraint_id: str) -> Constraint:
        for c in self.constraints:
            if c.constraint_id == constraint_id:
                return c
        raise KeyError(f"unknown constraint in plan limits: {constraint_id}")


def load_plan_limits(snapshot_path: str | Path | None = None) -> PlanLimits:
    """Build the versioned constraint set from the loaded snapshot.

    P 6.2 Tg/yr and the food need 2500 come from the snapshot CSV values
    (phosphorus boundary row; food supply row context). Work 48 h is the
    ILO long-hours threshold hard-coded in v0.3.1 planning.py, stored here
    as a bound with that provenance. Nitrogen is explicitly bound-less.
    """
    rows = load_snapshot(snapshot_path)
    p_boundary = get(rows, "phosphorus_regional_boundary", 2025)
    constraints = [
        Constraint(
            constraint_id="phosphorus_application_tg_per_year",
            name="Phosphorus application to cropland within regional boundary",
            resource_id="phosphorus", operator="<=", bound=p_boundary,
            geography="global", period="2025",
            source_ids=["snapshot:phosphorus_regional_boundary:2025"],
            notes="Tg P per year. Regional boundary, Planetary Health Check 2025 (PIK report). "
                  "Snapshot application 18.2 Tg P/yr is about 3x this boundary.",
        ),
        Constraint(
            constraint_id="food_supply_meets_planning_need",
            name="Per-capita food energy meets planning need",
            resource_id="food_energy", operator=">=", bound=2500.0,
            unit="kcal/capita/day",
            geography="global", period="2022",
            source_ids=["snapshot:global_food_supply_dietary_energy:2022"],
            notes="Planning need 2500 kcal/capita/day is a round planning assumption "
                  "(above the WFP-style 2100 minimum, below the 2022 supply average 2985), "
                  "not a FAO figure. Supply 2985 kcal/capita/day, FAO Food Balance Sheets 2010-2022.",
        ),
        Constraint(
            constraint_id="paid_work_hours_per_week",
            name="Paid work hours within long-hours threshold",
            resource_id="labour_time", operator="<=", bound=48.0,
            geography="global", period="2026",
            source_ids=["v0.3.1 planning.py check_plan_limits"],
            notes="Hours per week. 48 hours is the ILO long-hours threshold used in the "
                  "sources, not a PCAC rule. Bound is a v0.3.1 code constant, not a CSV row.",
        ),
        Constraint(
            constraint_id="nitrogen_fixation_tg_per_year",
            name="Nitrogen fixation against its boundary",
            resource_id="nitrogen", operator="<=", bound=None, boundless=True,
            geography="global", period="2025",
            source_ids=["snapshot:nitrogen_fixation:2025"],
            notes="BOUND-LESS / UNKNOWN: snapshot records nitrogen fixation 165 Tg N/yr as "
                  "more than twice its boundary (Planetary Health Check 2025, high-risk zone), "
                  "but no exact boundary value is stored, so no pass/fail is claimed. "
                  "A nitrogen check always evaluates UNKNOWN, never PASS.",
        ),
    ]
    return PlanLimits(
        snapshot_version=SNAPSHOT_VERSION,
        constraint_set_version=CONSTRAINT_SET_VERSION,
        constraints=constraints,
        source_ids=["data/real_planning_data.csv", "data/real_planning_sources.md",
                    "data/SNAPSHOT_PROVENANCE.md"],
        bounds={
            "phosphorus_application_tg_per_year": p_boundary,
            "paid_work_hours_per_week": 48.0,
            "food_supply_meets_planning_need": 2500.0,
        },
        unbounded=["nitrogen_fixation_tg_per_year"],
        food_need_default_kcal_per_capita_per_day=2500.0,
    )


def _validate_overrides(limits: PlanLimits, overrides: dict[str, Any] | None) -> None:
    """Reject any caller-supplied bound that contradicts a stored bound.

    An override equal to the stored bound is accepted (confirmation only).
    An override for a bound-less constraint, or for an unknown constraint
    id, is rejected. This is what catches a phosphorus boundary entered
    as 62 instead of 6.2: it raises instead of silently passing.
    """
    if not overrides:
        return
    for constraint_id, supplied in overrides.items():
        if constraint_id in limits.unbounded:
            raise ValueError(
                f"caller-supplied bound for {constraint_id} rejected: "
                f"that constraint is bound-less/unknown in constraint set "
                f"{limits.constraint_set_version} (no stored boundary exists to override)"
            )
        stored = limits.bounds.get(constraint_id)
        if stored is None:
            raise ValueError(
                f"caller-supplied bound for unknown constraint {constraint_id!r}; "
                f"known bounds: {sorted(limits.bounds)}"
            )
        if isinstance(supplied, bool) or not isinstance(supplied, (int, float)):
            raise ValueError(f"caller-supplied bound for {constraint_id} must be numeric")
        if float(supplied) != float(stored):
            raise ValueError(
                f"caller-supplied bound for {constraint_id} conflicts with the stored limit: "
                f"supplied {supplied}, stored {stored} "
                f"(constraint set {limits.constraint_set_version}, snapshot {limits.snapshot_version}). "
                f"Refusing to check against a contradicted bound."
            )


def check_plan_limits(
    plan: dict[str, Any],
    limits: PlanLimits | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check a proposed plan against the versioned stored limits.

    ``plan`` uses the v0.3.1 keys, e.g.::

        {"phosphorus_application_tg_per_year": 5.0,
         "food_kcal_per_capita_per_day": 2600,
         "planning_need_kcal_per_capita_per_day": 2500,
         "paid_work_hours_per_week": 40}

    Only limits with a stored boundary are pass/fail. Nitrogen is
    reported UNKNOWN, not silently passed. The food need defaults to the
    loaded 2500 kcal/capita/day when the caller omits
    ``planning_need_kcal_per_capita_per_day``; a caller-supplied need is
    a plan assumption (recorded as such) and is NOT validated against the
    stored bound — the stored bounds that ARE authoritative are the
    phosphorus and work-hours limits, validated via ``overrides``.

    Unrecognised plan keys are reported in ``unknown_plan_keys`` and
    produce no check — a bare ``"nitrogen"`` key, for example, matches
    no limit and is flagged instead of silently yielding zero checks.

    Returns plain JSON-able dicts. ``overall_status`` comes from
    :func:`contracts.statuses.overall_from_checks` (empty -> NOT_CHECKED,
    any UNKNOWN -> UNKNOWN, any FAIL -> FAIL). ``passes_checked_limits``
    is True only when no check failed; it is NOT a pass claim when the
    overall status is UNKNOWN or NOT_CHECKED. This checks a plan; it
    does not approve or decide it.
    """
    if limits is None:
        limits = load_plan_limits()
    _validate_overrides(limits, overrides)
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dictionary")

    unknown_keys = sorted(set(plan) - set(PLAN_KEYS))
    checks: list[dict[str, Any]] = []

    if "phosphorus_application_tg_per_year" in plan:
        constraint = limits.constraint("phosphorus_application_tg_per_year")
        status = constraint.evaluate(plan["phosphorus_application_tg_per_year"])
        checks.append({
            "limit": "phosphorus_application_tg_per_year",
            "constraint_id": constraint.constraint_id,
            "proposed": plan["phosphorus_application_tg_per_year"],
            "boundary": constraint.bound,
            "unit": "Tg P per year",
            "status": status.value,
            "excess": round(plan["phosphorus_application_tg_per_year"] - constraint.bound, 2)
                      if status == CheckStatus.FAIL else 0.0,
            "source_ids": constraint.source_ids,
        })
    if "food_kcal_per_capita_per_day" in plan:
        constraint = limits.constraint("food_supply_meets_planning_need")
        need = plan.get("planning_need_kcal_per_capita_per_day")
        need_source = "caller"
        if need is None:
            need = limits.food_need_default_kcal_per_capita_per_day
            need_source = "default-loaded"
        supply = plan["food_kcal_per_capita_per_day"]
        status = CheckStatus.PASS if supply >= need else CheckStatus.FAIL
        checks.append({
            "limit": "food_supply_meets_planning_need",
            "constraint_id": constraint.constraint_id,
            "proposed": supply,
            "boundary": need,
            "bound_source": need_source,
            "unit": "kcal/capita/day",
            "status": status.value,
            "source_ids": constraint.source_ids,
        })
    if "paid_work_hours_per_week" in plan:
        constraint = limits.constraint("paid_work_hours_per_week")
        status = constraint.evaluate(plan["paid_work_hours_per_week"])
        checks.append({
            "limit": "paid_work_hours_per_week",
            "constraint_id": constraint.constraint_id,
            "proposed": plan["paid_work_hours_per_week"],
            "boundary": constraint.bound,
            "unit": "hours per week",
            "status": status.value,
            "note": "48 hours is the ILO long-hours threshold used in the sources, not a PCAC rule.",
            "source_ids": constraint.source_ids,
        })
    if "nitrogen_fixation_tg_per_year" in plan:
        constraint = limits.constraint("nitrogen_fixation_tg_per_year")
        status = constraint.evaluate(plan["nitrogen_fixation_tg_per_year"])
        checks.append({
            "limit": "nitrogen_fixation_tg_per_year",
            "constraint_id": constraint.constraint_id,
            "proposed": plan["nitrogen_fixation_tg_per_year"],
            "boundary": None,
            "unit": "Tg N per year",
            "status": status.value,
            "note": "Snapshot records nitrogen as more than twice its boundary, but no exact "
                    "boundary value is stored, so no pass/fail is claimed.",
            "source_ids": constraint.source_ids,
        })

    statuses = [CheckStatus(c["status"]) for c in checks]
    overall = overall_from_checks(statuses)
    failed = [c for c in checks if c["status"] == CheckStatus.FAIL.value]
    # ISSUE-27: one metadata-only INFO event per check — overall status
    # and failed count only, never plan values or check rows. The import
    # is lazy: engine/__init__ imports planning_engine, which imports
    # this module, so a top-level `from engine.event_log import ...`
    # would cycle (contracts.models already lazy-imports this module
    # for the same reason).
    from engine.event_log import log_event
    log_event("contracts", "contracts.check_plan_limits.completed",
              message="Plan limits check completed",
              overall_status=overall.value, failed_count=len(failed),
              check_count=len(checks), unknown_key_count=len(unknown_keys))
    return {
        "checks": checks,
        "overall_status": overall.value,
        "passes_checked_limits": not failed,
        "failed_count": len(failed),
        "unknown_plan_keys": unknown_keys,
        "snapshot_version": limits.snapshot_version,
        "constraint_set_version": limits.constraint_set_version,
        "note": "Passing these checks does not mean a plan is good, fair, or decided. "
                "It means it did not breach the stored limits checked here. "
                "UNKNOWN is not a pass; human approval is still required for any decision.",
    }
