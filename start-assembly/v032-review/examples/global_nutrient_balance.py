"""Reproduce the v0.3.1 global nutrient picture from the loaded snapshot.

ISSUE-34 (2026-11-13): every snapshot value here comes from the
versioned snapshot loaded by contracts.plan_limits — nothing is
hard-coded — and reproduces the v0.3.1 soil_summary numbers:
phosphorus application 18.2 Tg/yr against the 6.2 Tg/yr regional
boundary, excess 12.0 Tg/yr, ratio 2.94; nitrogen fixation 165
Tg/yr, always UNKNOWN ("more than twice its boundary", high-risk
zone, no exact boundary stored).

One honest limit, stated on its face: the snapshot carries NO
uptake or losses values, and this domain never invents them — so
the engine run below returns INSUFFICIENT_INPUT, listing the four
missing balance inputs, instead of a soil-change balance computed
from made-up numbers. The boundary reproduction is shown through
the domain's own constraint constructors evaluated on the snapshot
values, which need no uptake/losses. A real soil-change balance
needs caller-stated uptake and losses; see tests/
test_issue34_nutrients.py for a completed balance (including the
v0.3.1 teaching example, 100/50/30/20, labelled as such).

Run: python3 -m examples.global_nutrient_balance
"""
from pprint import pprint
from contracts.plan_limits import get, load_plan_limits, load_snapshot
from domains.nutrients import NutrientsDomain
from domains.nutrients.balance import default_nutrient_constraints, phosphorus_excess_and_ratio
from engine.planning_engine import PlanningEngine

limits = load_plan_limits()
rows = load_snapshot()
p_applied = get(rows, "phosphorus_application_to_cropland", 2025)
p_boundary = get(rows, "phosphorus_regional_boundary", 2025)
n_fixation = get(rows, "nitrogen_fixation", 2025)

engine = PlanningEngine()
engine.register(NutrientsDomain())

# Snapshot values only. No uptake/losses exist in the snapshot, and
# none are stated here — the domain must refuse the balance rather
# than silently zero them.
request = {
    "phosphorus_applied_tg_per_year": p_applied,
    "nitrogen_fixation_tg_per_year": n_fixation,
    "source_ids": limits.source_ids,
    "geography": "global",
    "period": "2025",
}

result = engine.run("nutrients", request)
print(f"snapshot_version: {limits.snapshot_version}")
print(f"constraint_set_version: {limits.constraint_set_version}")
print(f"phosphorus application: {p_applied} Tg/yr")
print(f"phosphorus regional boundary: {p_boundary} Tg/yr")
print(f"nitrogen fixation: {n_fixation} Tg/yr")
print(f"engine run calculation_status: {result['calculation']['calculation_status']}")
print("missing balance inputs (no uptake/losses in the snapshot, none invented):")
for problem in result["calculation"]["missing_fields"]:
    print(f"  - {problem}")

# The boundary check needs no uptake/losses: evaluate the domain's
# own constraints on the snapshot values.
constraints = {c.constraint_id: c for c in default_nutrient_constraints()}
p_check = constraints["phosphorus_application_tg_per_year"].evaluate(p_applied, "Tg/yr")
n_check = constraints["nitrogen_fixation_tg_per_year"].evaluate(n_fixation, "Tg/yr")
excess, ratio = phosphorus_excess_and_ratio(p_applied, p_boundary)
print(f"phosphorus check: {p_check.value} (applied {p_applied} Tg/yr vs boundary {p_boundary} Tg/yr)")
print(f"phosphorus excess: {excess} Tg/yr")
print(f"phosphorus ratio to boundary: {ratio}")
print(f"nitrogen check: {n_check.value} (fixation {n_fixation} Tg/yr; boundary unknown)")
print(f"nitrogen note: {constraints['nitrogen_fixation_tg_per_year'].notes}")
print(f"verification: {result['verification']['verification_status']} "
      f"(calculation did not complete; a completed nutrients run is "
      f"PARTIALLY_VERIFIED — no independent verifier exists for "
      f"nutrients, which is expected and honest)")
print(f"overall_status: {result['evaluation']['overall_status']}")
pprint(result)
