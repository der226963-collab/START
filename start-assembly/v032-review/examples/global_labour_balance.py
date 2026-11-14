"""Reproduce the global unpaid-care split and paid-work check from the loaded snapshot.

ISSUE-34: this example takes every value from the versioned snapshot
loaded by contracts.plan_limits — nothing is hard-coded here — and
reproduces the ILO 2018 care split: total 16.4 billion hours/day,
women's share 76.2%, so women 12.4968 / men 3.9032 billion
hours/day. The paid-work figure checked is the snapshot's employed
average, 43 h/week (2026, Gethin and Saez IMF dataset), which passes
the 48 h/week ILO long-hours threshold; the all-adults average of
25 h/week is reported as snapshot context, not checked. Per-person
care hours (2.0 hours/person/day for 8.2 billion people) combine the
2018 care figures with the 2024 population — a year mismatch the
result states as a limitation.

Run: python3 -m examples.global_labour_balance
"""
from pprint import pprint
from contracts.plan_limits import get, load_plan_limits, load_snapshot
from domains.labour import LabourDomain
from engine.planning_engine import PlanningEngine

limits = load_plan_limits()
rows = load_snapshot()
population = get(rows, "world_population", 2024) * 1_000_000_000
# Snapshot stores the care total in million hours/day; the domain
# takes billion hours/day (the same /1000 conversion
# domains/compat_v031.py systems_summary() uses).
care_total_billion = get(rows, "unpaid_care_hours_per_day", 2018) / 1000
women_share = get(rows, "women_share_unpaid_care_work", 2018)
paid_work_employed = get(rows, "paid_work_hours_per_week_employed", 2026)
paid_work_all_adults = get(rows, "paid_work_hours_per_week_all_adults", 2026)

engine = PlanningEngine()
engine.register(LabourDomain())

request = {
    "unpaid_care_hours_per_day_billion": care_total_billion,
    "women_share_unpaid_care_percent": women_share,
    "paid_work_hours_per_week": paid_work_employed,
    "population": population,
    "snapshot_paid_work_hours_per_week_employed": paid_work_employed,
    "snapshot_paid_work_hours_per_week_all_adults": paid_work_all_adults,
    "source_ids": limits.source_ids,
    "geography": "global",
    "period": "2018",
}

result = engine.run("labour", request)
metrics = result["calculation"]["metrics"]
print(f"snapshot_version: {limits.snapshot_version}")
print(f"constraint_set_version: {limits.constraint_set_version}")
print(f"unpaid care total: {metrics['unpaid_care_hours_per_day_billion']} billion hours/day (ILO 2018)")
print(f"women's share: {metrics['women_share_unpaid_care_percent']}% (ILO 2018)")
print(f"women's care: {metrics['women_unpaid_care_hours_per_day_billion']} billion hours/day")
print(f"men's care: {metrics['men_unpaid_care_hours_per_day_billion']} billion hours/day")
print(f"care per person: {metrics['unpaid_care_hours_per_person_per_day']} hours/person/day "
      f"(2018 care / 2024 population of {metrics['population']:.0f} — year mismatch, see limitations)")
print(f"paid work (employed average): {metrics['paid_work_hours_per_week']} hours/week")
print(f"paid work (all-adults average, snapshot context): "
      f"{metrics['snapshot_paid_work_hours_per_week_all_adults']} hours/week")
print(f"overall_status: {result['evaluation']['overall_status']}")
print(f"verification_status: {result['verification']['verification_status']} "
      f"(no independent verifier exists for labour — expected)")
pprint(result)
