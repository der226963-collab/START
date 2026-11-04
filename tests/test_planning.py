import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_ai.planning import electricity_allocation, food_balance, load_snapshot, run_plan


def test_snapshot_loads_and_has_key_rows():
    rows = load_snapshot("data/real_planning_data.csv")
    indicators = {r["indicator"] for r in rows}
    assert "world_population" in indicators
    assert "global_cereals_production" in indicators
    assert "renewable_share_of_electricity" in indicators


def test_food_balance_supply_above_planning_need_on_average():
    rows = load_snapshot("data/real_planning_data.csv")
    result = food_balance(rows)
    assert result["supply_kcal_per_capita_per_day_2022"] == 2985
    assert result["surplus_kcal_per_capita_per_day"] == 485
    assert "warning" in result


def test_electricity_allocation_low_carbon_beats_current():
    current = electricity_allocation(30000, {"coal": 0.36, "gas": 0.23, "solar": 0.05, "wind": 0.08, "hydro": 0.15, "nuclear": 0.13})
    low = electricity_allocation(30000, {"coal": 0.10, "gas": 0.15, "solar": 0.30, "wind": 0.20, "hydro": 0.15, "nuclear": 0.10})
    assert low["total_co2_million_tonnes"] < current["total_co2_million_tonnes"]


def test_run_plan_is_calculation_not_language():
    result = run_plan("data/real_planning_data.csv")
    assert result["layer"].startswith("calculation")
    assert result["cereals_2023_million_tonnes"] == 3100
