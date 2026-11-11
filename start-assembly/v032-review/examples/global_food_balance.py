"""Reproduce the v0.3.1 global food-energy surplus from the loaded snapshot.

ISSUE-01: as shipped, the food example could only reproduce the 485
kcal/capita/day surplus if the caller independently knew to supply
2985/2500/0/0. This example takes every value from the versioned
snapshot loaded by contracts.plan_limits — nothing is hard-coded here —
and reproduces the v0.3.1 result: supply 2985, need 2500 (planning
assumption), surplus 485 kcal/capita/day, 19.4% of need, annual surplus
1.451605e15 kcal/yr for 8.2 billion people.

Run: python3 -m examples.global_food_balance
"""
from pprint import pprint
from contracts.plan_limits import get, load_plan_limits, load_snapshot
from domains.food import FoodDomain
from engine.planning_engine import PlanningEngine

limits = load_plan_limits()
rows = load_snapshot()
population = get(rows, "world_population", 2024) * 1_000_000_000
supply = get(rows, "global_food_supply_dietary_energy", 2022)
need = limits.food_need_default_kcal_per_capita_per_day

engine = PlanningEngine()
engine.register(FoodDomain())

request = {
    "population": population,
    "supply_kcal_per_capita_per_day": supply,
    "requirement_kcal_per_capita_per_day": need,
    "imports_kcal_per_capita_per_day": 0.0,
    "losses_fraction": 0.0,
    "source_ids": limits.source_ids,
    "geography": "global",
    "period": "2022",
}

result = engine.run("food", request)
metrics = result["calculation"]["metrics"]
print(f"snapshot_version: {limits.snapshot_version}")
print(f"constraint_set_version: {limits.constraint_set_version}")
print(f"population: {metrics['population']:.0f}")
print(f"supply: {metrics['supply_kcal_per_capita_per_day']} kcal/capita/day")
print(f"planning need: {metrics['requirement_kcal_per_capita_per_day']} kcal/capita/day (assumption)")
print(f"surplus: {metrics['surplus_kcal_per_capita_per_day']} kcal/capita/day")
print(f"surplus percent of need: {100 * metrics['surplus_kcal_per_capita_per_day'] / need:.1f}%")
print(f"annual surplus: {metrics['annual_gap_or_surplus_kcal']:.6g} kcal/yr")
print(f"overall_status: {result['evaluation']['overall_status']}")
pprint(result)
