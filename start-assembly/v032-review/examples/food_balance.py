"""Run the START food-energy pilot with a fully specified example request.

ISSUE-44 (2026-11-11): this module used to execute on import
(module-level engine construction, run, and pprint), so importing it
as a module ran the planning run and printed. The run now lives in
main(), guarded by ``if __name__ == "__main__":``; importing the
module runs nothing. Run it the same way as before:
``python -m examples.food_balance``.
"""
from pprint import pprint
from domains.food import FoodDomain
from engine.planning_engine import PlanningEngine


def main() -> dict:
    engine = PlanningEngine()
    engine.register(FoodDomain())

    request = {
        "population": 100_000,
        "supply_kcal_per_capita_per_day": 2_800,
        "requirement_kcal_per_capita_per_day": 2_500,
        "imports_kcal_per_capita_per_day": 100,
        "losses_fraction": 0.08,
        "source_ids": ["example-source-not-real"],
        "geography": "community-example",
        "period": "2026",
    }

    result = engine.run("food", request)
    pprint(result)
    return result


if __name__ == "__main__":
    main()
