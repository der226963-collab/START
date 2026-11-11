"""ISSUE-17 compatibility suite: the v0.3.1 tests, ported.

Ports ``~/workspace/ai-starter/tests/test_planning.py`` (9 functions,
9/9 pass, reproduced live from the read-only v0.3.1 tree before
porting) against the v0.3.2 review copy. Mapping, verdicts, data
decisions and deliberate differences are recorded in
``docs/COMPAT_V031_MAPPING.md`` — read that first.

Where a v0.3.2 equivalent exists the test goes through it (snapshot
loading and plan limits via ``contracts.plan_limits``; food 485 via
the ``FoodDomain``/engine path). Where none exists the test goes
through the ported calculation in ``domains/compat_v031.py`` (restored
v0.3.1 logic, provenance in that module's docstring).

Deliberate differences asserted here as DOCUMENTED v0.3.2 behaviour,
never the old behaviour as if current:
- Aggregation (ISSUE-02): v0.3.1 nitrogen-only plan returned
  ``passes_checked_limits: True``; v0.3.2 returns ``overall_status:
  UNKNOWN`` (UNKNOWN blocks a pass) and an empty plan returns
  ``NOT_CHECKED``. Status strings are uppercase in v0.3.2
  (``"UNKNOWN"``) vs lowercase in v0.3.1 (``"unknown"``).
- Food formula (ISSUE-15): v0.3.2 surplus includes losses/imports;
  it agrees with v0.3.1 only at losses 0/imports 0. The 2800/2500
  divergence (v0.3.1 300 vs v0.3.2 176.0 at imports 100/losses 0.08)
  is asserted as the v0.3.2 number with the v0.3.1 number noted.

Run: python3 -m pytest tests/test_compat_v031.py -q
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from contracts.plan_limits import check_plan_limits, get, load_snapshot
from domains import compat_v031
from domains.compat_v031 import (
    backtest_climate,
    climate_trend,
    electricity_allocation,
    energy_and_materials,
    food_balance,
    pilot_summary,
    run_plan,
    soil_summary,
    systems_summary,
    weather_summary,
)
from domains.food import FoodDomain
from engine.planning_engine import PlanningEngine

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TIME_SERIES_SELECTED = DATA / "time_series.csv"

CURRENT_MIX = {"coal": 0.36, "gas": 0.23, "solar": 0.05, "wind": 0.08, "hydro": 0.15, "nuclear": 0.13}
LOW_CARBON_MIX = {"coal": 0.10, "gas": 0.15, "solar": 0.30, "wind": 0.20, "hydro": 0.15, "nuclear": 0.10}


def _rows():
    return load_snapshot()


class Test01SnapshotLoads(unittest.TestCase):
    """v0.3.1 test 1 — already-equivalent via ISSUE-01."""

    def test_snapshot_loads_and_has_key_rows(self):
        rows = _rows()
        indicators = {r["indicator"] for r in rows}
        self.assertIn("world_population", indicators)
        self.assertIn("global_cereals_production", indicators)
        self.assertIn("renewable_share_of_electricity", indicators)
        self.assertEqual(len(rows), 58)


class Test02FoodBalance(unittest.TestCase):
    """v0.3.1 test 2 — already-equivalent at the tested point (2985/2500/0/0)."""

    def test_food_balance_supply_above_planning_need_via_engine(self):
        # v0.3.2 engine path, values taken from the loaded snapshot.
        rows = _rows()
        population = get(rows, "world_population", 2024) * 1_000_000_000
        supply = get(rows, "global_food_supply_dietary_energy", 2022)
        engine = PlanningEngine()
        engine.register(FoodDomain())
        result = engine.run("food", {
            "population": population,
            "supply_kcal_per_capita_per_day": supply,
            "requirement_kcal_per_capita_per_day": 2500,
            "imports_kcal_per_capita_per_day": 0.0,
            "losses_fraction": 0.0,
            "source_ids": ["snapshot:global_food_supply_dietary_energy:2022"],
            "geography": "global", "period": "2022",
        })
        metrics = result["calculation"]["metrics"]
        self.assertEqual(metrics["supply_kcal_per_capita_per_day"], 2985)
        self.assertEqual(metrics["surplus_kcal_per_capita_per_day"], 485)
        self.assertIn("warning", food_balance(rows))
        self.assertEqual(result["evaluation"]["overall_status"], "PASS")

    def test_food_balance_compat_reference_reproduces_v031_numbers(self):
        result = food_balance(_rows())
        self.assertEqual(result["supply_kcal_per_capita_per_day_2022"], 2985)
        self.assertEqual(result["surplus_kcal_per_capita_per_day"], 485)
        self.assertEqual(result["surplus_percent_of_need"], 19.4)
        self.assertEqual(result["supply_kcal_per_year_trillion"], 8934.1)
        self.assertIn("warning", result)

    def test_food_formula_divergence_is_documented_v032_behaviour(self):
        # ISSUE-15: 2800/2500 is 300 under the v0.3.1 formula but
        # 176.0 under v0.3.2 with imports 100 / losses 0.08. Assert
        # the v0.3.2 number; the v0.3.1 number is the compat reference.
        self.assertEqual(food_balance(_rows(), 2500)["surplus_kcal_per_capita_per_day"], 485)
        engine = PlanningEngine()
        engine.register(FoodDomain())
        result = engine.run("food", {
            "population": 1000,
            "supply_kcal_per_capita_per_day": 2800,
            "requirement_kcal_per_capita_per_day": 2500,
            "imports_kcal_per_capita_per_day": 100,
            "losses_fraction": 0.08,
            "source_ids": ["compat-test"], "geography": "global", "period": "2022",
        })
        self.assertEqual(result["calculation"]["metrics"]["total_available_kcal_per_capita_per_day"], 2676.0)
        self.assertEqual(result["calculation"]["metrics"]["surplus_kcal_per_capita_per_day"], 176.0)


class Test03ElectricityAllocation(unittest.TestCase):
    """v0.3.1 test 3 — portable; no v0.3.2 equivalent existed."""

    def test_electricity_allocation_low_carbon_beats_current(self):
        current = electricity_allocation(30000, CURRENT_MIX)
        low = electricity_allocation(30000, LOW_CARBON_MIX)
        self.assertEqual(current["total_co2_million_tonnes"], 12485.7)
        self.assertEqual(low["total_co2_million_tonnes"], 5280.0)
        self.assertLess(low["total_co2_million_tonnes"], current["total_co2_million_tonnes"])
        self.assertEqual(current["allocation"]["coal"]["co2_million_tonnes"], 8856.0)
        self.assertEqual(low["allocation"]["solar"]["twh"], 9000.0)

    def test_electricity_allocation_rejects_mix_not_summing_to_one(self):
        with self.assertRaises(ValueError):
            electricity_allocation(30000, {"coal": 0.5, "gas": 0.4})


class Test04RunPlan(unittest.TestCase):
    """v0.3.1 test 4 — portable; no v0.3.2 equivalent existed."""

    def test_run_plan_is_calculation_not_language(self):
        result = run_plan()
        self.assertTrue(result["layer"].startswith("calculation"))
        self.assertEqual(result["cereals_2023_million_tonnes"], 3100)
        # Every sub-summary the v0.3.1 run_plan assembled is present.
        for key in ("food", "weather", "soil", "systems", "climate_trend",
                    "pilot_example", "energy_and_materials", "backtest_climate",
                    "example_plan_check"):
            self.assertIn(key, result)
        self.assertEqual(result["food"]["surplus_kcal_per_capita_per_day"], 485)
        self.assertEqual(result["example_plan_check"]["passes_checked_limits"], True)
        self.assertEqual(result["example_plan_check"]["overall_status"], "PASS")

    def test_run_plan_is_json_wire(self):
        # Wire format stays JSON: the whole result serialises, no inf/NaN.
        text = json.dumps(run_plan(), allow_nan=False)
        self.assertIn("3100", text)


class Test05SoilSummary(unittest.TestCase):
    """v0.3.1 test 5 — portable; no v0.3.2 equivalent existed."""

    def test_soil_summary_phosphorus_excess(self):
        result = soil_summary(_rows())
        self.assertEqual(result["global_soils_degraded_percent"], 33)
        self.assertEqual(result["phosphorus_excess_tg_per_year"], 12.0)
        self.assertEqual(result["teaching_nutrient_balance_example"]["nitrogen_soil_change_units"], 20)
        self.assertEqual(result["phosphorus_application_tg_per_year"], 18.2)
        self.assertEqual(result["phosphorus_regional_boundary_tg_per_year"], 6.2)
        self.assertEqual(result["phosphorus_ratio_to_boundary"], 2.94)
        self.assertEqual(result["nitrogen_fixation_tg_per_year"], 165)
        self.assertEqual(result["food_grown_in_soil_percent"], 95)
        self.assertIn("warning", result)


class Test06SystemsSummary(unittest.TestCase):
    """v0.3.1 test 6 — portable; no v0.3.2 equivalent existed."""

    def test_systems_summary_ratios(self):
        result = systems_summary(_rows())
        self.assertEqual(result["agricultural_land_hectares_per_person"], 0.585)
        self.assertEqual(result["cropland_hectares_per_person"], 0.195)
        self.assertEqual(result["road_transport_co2_million_tonnes_2023_approx"], 6180.0)
        self.assertEqual(result["unpaid_care_hours_per_day_billion"], 16.4)
        self.assertEqual(result["agriculture_share_freshwater_withdrawals_percent"], 70)
        self.assertEqual(result["people_lacking_drinking_water_percent_of_population"], 26.8)
        self.assertEqual(result["transport_co2_million_tonnes_2023"], 8240)
        self.assertEqual(result["women_share_unpaid_care_percent"], 76.2)
        self.assertIn("warning", result)


class Test07ClimateTrendAndPilot(unittest.TestCase):
    """v0.3.1 test 7 — portable; required porting both data files (see mapping)."""

    def test_climate_trend(self):
        trend = climate_trend()
        self.assertEqual(trend["years_in_series"], 146)
        self.assertEqual(trend["first_year"], 1880)
        self.assertEqual(trend["last_year"], 2025)
        self.assertEqual(trend["co2_1959_ppm"], 315.98)
        self.assertEqual(trend["co2_2025_ppm"], 427.35)
        self.assertEqual(trend["co2_increase_ppm_1959_2025"], 111.37)
        self.assertEqual(trend["mean_anomaly_1880_1899_c"], -0.225)
        self.assertEqual(trend["mean_anomaly_2000_2025_c"], 0.781)
        self.assertEqual(trend["anomaly_change_c"], 1.005)

    def test_climate_trend_needs_full_series_not_selected_years(self):
        # data/time_series.csv (15 selected years) cannot supply the
        # 1959 CO2 value or the 1880-1899 mean — this is why the full
        # series was ported. It raises KeyError, not a wrong number.
        with self.assertRaises(KeyError):
            climate_trend(TIME_SERIES_SELECTED)

    def test_pilot_example(self):
        pilot = pilot_summary()
        self.assertEqual(pilot["people"], 20)
        self.assertTrue(pilot["status"].startswith("SYNTHETIC"))
        self.assertEqual(pilot["data_status"], "synthetic")
        self.assertEqual(pilot["households"], 5)
        self.assertEqual(pilot["land_hectares"], 2.5)
        self.assertEqual(pilot["food_kcal_needed_per_day"], 50000)
        self.assertEqual(pilot["energy_kwh_needed_per_year"], 15300)
        self.assertEqual(pilot["care_hours_per_week"], 105)
        self.assertEqual(pilot["households_with_inadequate_housing"], 2)

    def test_pilot_guard_raises_on_non_synthetic_row(self):
        # ISSUE-36 guard, re-assessed and enforced now the file exists.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pilot.csv"
            with open(DATA / "local_pilot_example.csv", newline="") as src, open(path, "w", newline="") as dst:
                rows = list(csv.DictReader(src))
                writer = csv.DictWriter(dst, fieldnames=list(rows[0]))
                writer.writeheader()
                rows[0]["household_id"] = "REAL-001"
                writer.writerows(rows)
            with self.assertRaises(ValueError):
                pilot_summary(path)


class Test08BacktestAndPlanLimits(unittest.TestCase):
    """v0.3.1 test 8 — backtest portable; plan limits already-equivalent
    except the documented ISSUE-02 aggregate breaking change."""

    def test_backtest_temperature_underpredicts_recent_warming(self):
        back = backtest_climate()
        temp = back["temperature_anomaly"]
        self.assertEqual(temp["test_years"], "2000-2025")
        self.assertEqual(temp["train_years"], "1880-1999")
        self.assertLess(temp["bias_mean_predicted_minus_actual"], 0,
                        "Linear trend should under-predict recent warming")
        self.assertEqual(temp["bias_mean_predicted_minus_actual"], -0.453)
        self.assertEqual(temp["slope_per_year"], 0.0054)
        self.assertEqual(temp["rmse"], 0.489)
        self.assertEqual(temp["last_test_year_predicted"], 0.4)
        self.assertEqual(temp["last_test_year_actual"], 1.18)

    def test_backtest_co2_also_underpredicts(self):
        co2 = backtest_climate()["mauna_loa_co2"]
        self.assertEqual(co2["test_years"], "2000-2025")
        self.assertEqual(co2["train_years"], "1959-1999")
        self.assertLess(co2["bias_mean_predicted_minus_actual"], 0)
        self.assertEqual(co2["bias_mean_predicted_minus_actual"], -13.079)
        self.assertEqual(co2["slope_per_year"], 1.3385)
        self.assertEqual(co2["rmse"], 14.917)
        self.assertEqual(co2["last_test_year_predicted"], 400.34)
        self.assertEqual(co2["last_test_year_actual"], 427.35)

    def test_plan_limits_pass_and_fail(self):
        ok = check_plan_limits({"phosphorus_application_tg_per_year": 5.0, "paid_work_hours_per_week": 40})
        self.assertTrue(ok["passes_checked_limits"])
        self.assertEqual(ok["overall_status"], "PASS")
        bad = check_plan_limits({"phosphorus_application_tg_per_year": 18.2, "paid_work_hours_per_week": 55})
        self.assertFalse(bad["passes_checked_limits"])
        self.assertEqual(bad["failed_count"], 2)
        self.assertEqual(bad["overall_status"], "FAIL")

    def test_plan_limits_nitrogen_unknown_never_passes_overall(self):
        # v0.3.1 asserted checks[0]["status"] == "unknown" (lowercase)
        # and that same call still returned passes_checked_limits True.
        # v0.3.2 keeps the per-check UNKNOWN (uppercase) but the
        # aggregate is the documented ISSUE-02 breaking change: UNKNOWN
        # blocks a pass, so overall_status is UNKNOWN, not PASS.
        unknown = check_plan_limits({"nitrogen_fixation_tg_per_year": 165})
        self.assertEqual(unknown["checks"][0]["status"], "UNKNOWN")
        self.assertIsNone(unknown["checks"][0]["boundary"])
        self.assertEqual(unknown["overall_status"], "UNKNOWN")
        self.assertTrue(unknown["passes_checked_limits"])  # no check failed; not a pass claim

    def test_plan_limits_empty_plan_is_not_a_pass(self):
        # ISSUE-02: v0.3.1 {} -> passes_checked_limits True (the bug
        # v0.3.2 fixes). v0.3.2: empty -> NOT_CHECKED.
        empty = check_plan_limits({})
        self.assertEqual(empty["overall_status"], "NOT_CHECKED")
        self.assertEqual(empty["checks"], [])


class Test09WeatherSummary(unittest.TestCase):
    """v0.3.1 test 9 — portable; no v0.3.2 equivalent existed."""

    def test_weather_summary_uses_real_anomaly_and_moisture_rule(self):
        result = weather_summary(_rows())
        self.assertEqual(result["global_temperature_anomaly_2024_vs_1951_1980_celsius"], 1.28)
        self.assertEqual(result["moisture_increase_percent_for_input_warming"], 7.0)
        self.assertEqual(result["global_temperature_anomaly_2024_vs_1850_1900_celsius"], 1.47)
        self.assertEqual(result["record_monthly_streak_months_jun2023_aug2024"], 15)
        self.assertIn("warning", result)

    def test_weather_summary_moisture_scales_with_warming(self):
        self.assertEqual(weather_summary(_rows(), warming_degrees=2.0)["moisture_increase_percent_for_input_warming"], 14.0)


class TestEnergyAndMaterials(unittest.TestCase):
    """Not itself a v0.3.1 test function, but part of run_plan (test 4)."""

    def test_energy_and_materials_examples(self):
        result = energy_and_materials(_rows())
        self.assertEqual(result["electricity_example_current_mix_co2"]["total_co2_million_tonnes"], 12485.7)
        self.assertEqual(result["electricity_example_low_carbon_mix_co2"]["total_co2_million_tonnes"], 5280.0)
        self.assertEqual(result["renewable_share_of_electricity_2023_percent"], 30)
        self.assertEqual(result["steel_plus_cement_co2_million_tonnes"], 5100)


if __name__ == "__main__":
    unittest.main()
