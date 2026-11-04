import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_ai.planning import electricity_allocation, food_balance, load_snapshot, run_plan, soil_summary, systems_summary, weather_summary


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


def test_soil_summary_phosphorus_excess():
    rows = load_snapshot("data/real_planning_data.csv")
    result = soil_summary(rows)
    assert result["global_soils_degraded_percent"] == 33
    assert result["phosphorus_excess_tg_per_year"] == 12.0
    assert result["teaching_nutrient_balance_example"]["nitrogen_soil_change_units"] == 20


def test_systems_summary_ratios():
    rows = load_snapshot("data/real_planning_data.csv")
    result = systems_summary(rows)
    assert result["agricultural_land_hectares_per_person"] == 0.585
    assert result["cropland_hectares_per_person"] == 0.195
    assert result["road_transport_co2_million_tonnes_2023_approx"] == 6180.0
    assert result["unpaid_care_hours_per_day_billion"] == 16.4


def test_weather_summary_uses_real_anomaly_and_moisture_rule():
    rows = load_snapshot("data/real_planning_data.csv")
    result = weather_summary(rows, warming_degrees=1.0)
    assert result["global_temperature_anomaly_2024_vs_1951_1980_celsius"] == 1.28
    assert result["moisture_increase_percent_for_input_warming"] == 7.0
    assert "warning" in result
