"""ISSUE-01 tests: versioned real-world snapshot and plan-limit constraint set.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import unittest
from contracts.plan_limits import (
    CO2_INTENSITY_G_PER_KWH,
    CONSTRAINT_SET_VERSION,
    SNAPSHOT_VERSION,
    check_plan_limits,
    get,
    load_plan_limits,
    load_snapshot,
)
from domains.food import FoodDomain
from engine.planning_engine import PlanningEngine


EXAMPLE_PLAN = {
    "phosphorus_application_tg_per_year": 5.0,
    "food_kcal_per_capita_per_day": 2600,
    "planning_need_kcal_per_capita_per_day": 2500,
    "paid_work_hours_per_week": 40,
}
FAILING_PLAN = {
    "phosphorus_application_tg_per_year": 18.2,
    "food_kcal_per_capita_per_day": 2600,
    "planning_need_kcal_per_capita_per_day": 2500,
    "paid_work_hours_per_week": 55,
}


class SnapshotTests(unittest.TestCase):
    def test_snapshot_loads_and_carries_provenance(self):
        rows = load_snapshot()
        self.assertEqual(len(rows), 58)
        row = next(r for r in rows if r["indicator"] == "global_food_supply_dietary_energy" and int(r["year"]) == 2022)
        self.assertEqual(row["source"], "FAO Food Balance Sheets 2010-2022")
        self.assertIn("CC-BY-4.0", row["licence_or_status"])

    def test_snapshot_key_values(self):
        rows = load_snapshot()
        self.assertEqual(get(rows, "global_food_supply_dietary_energy", 2022), 2985)
        self.assertEqual(get(rows, "phosphorus_regional_boundary", 2025), 6.2)
        self.assertEqual(get(rows, "phosphorus_application_to_cropland", 2025), 18.2)
        self.assertEqual(get(rows, "nitrogen_fixation", 2025), 165)
        self.assertEqual(get(rows, "global_temperature_anomaly_vs_1951_1980", 2024), 1.28)
        self.assertEqual(get(rows, "world_population", 2024), 8.2)

    def test_code_constant_values_ported_with_provenance(self):
        # 48 h and 820 g CO2/kWh are v0.3.1 code constants, not CSV rows.
        limits = load_plan_limits()
        self.assertEqual(limits.constraint("paid_work_hours_per_week").bound, 48.0)
        self.assertEqual(CO2_INTENSITY_G_PER_KWH["coal"], 820)
        self.assertEqual(CO2_INTENSITY_G_PER_KWH["gas"], 490)

    def test_snapshot_versions_recorded(self):
        limits = load_plan_limits()
        self.assertEqual(limits.snapshot_version, SNAPSHOT_VERSION)
        self.assertEqual(limits.constraint_set_version, CONSTRAINT_SET_VERSION)
        self.assertIn("nitrogen_fixation_tg_per_year", limits.unbounded)


class PlanLimitsTests(unittest.TestCase):
    def test_example_plan_passes(self):
        """Exact ISSUE-01 test: v0.3.1 example plan (P 5.0, food 2600/2500, work 40) PASSES."""
        result = check_plan_limits(EXAMPLE_PLAN)
        self.assertEqual(result["overall_status"], "PASS")
        self.assertTrue(result["passes_checked_limits"])
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual([c["status"] for c in result["checks"]], ["PASS", "PASS", "PASS"])
        self.assertEqual(result["snapshot_version"], SNAPSHOT_VERSION)

    def test_failing_plan_fails_with_count_two(self):
        """Exact ISSUE-01 test: (P 18.2, work 55) FAILS with count 2."""
        result = check_plan_limits(FAILING_PLAN)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertFalse(result["passes_checked_limits"])
        self.assertEqual(result["failed_count"], 2)
        failed = [c["limit"] for c in result["checks"] if c["status"] == "FAIL"]
        self.assertEqual(failed, ["phosphorus_application_tg_per_year", "paid_work_hours_per_week"])
        p_check = next(c for c in result["checks"] if c["limit"] == "phosphorus_application_tg_per_year")
        self.assertEqual(p_check["boundary"], 6.2)
        self.assertEqual(p_check["excess"], 12.0)

    def test_nitrogen_is_boundless_unknown_never_pass(self):
        result = check_plan_limits({"nitrogen_fixation_tg_per_year": 165})
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["status"], "UNKNOWN")
        self.assertIsNone(result["checks"][0]["boundary"])
        self.assertEqual(result["overall_status"], "UNKNOWN")
        self.assertEqual(result["failed_count"], 0)

    def test_bare_nitrogen_key_matches_no_limit_and_is_flagged(self):
        result = check_plan_limits({"nitrogen": 165})
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["unknown_plan_keys"], ["nitrogen"])
        self.assertEqual(result["overall_status"], "NOT_CHECKED")

    def test_food_need_defaults_to_loaded_2500_when_omitted(self):
        result = check_plan_limits({"food_kcal_per_capita_per_day": 2600})
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["boundary"], 2500)
        self.assertEqual(result["checks"][0]["bound_source"], "default-loaded")
        self.assertEqual(result["checks"][0]["status"], "PASS")

    def test_wrong_caller_bound_is_detected(self):
        # Phosphorus boundary entered as 62 instead of 6.2 must be caught, never applied.
        with self.assertRaises(ValueError) as ctx:
            check_plan_limits(EXAMPLE_PLAN, overrides={"phosphorus_application_tg_per_year": 62})
        self.assertIn("62", str(ctx.exception))
        self.assertIn("6.2", str(ctx.exception))
        # An override that exactly matches the stored bound is accepted.
        result = check_plan_limits(EXAMPLE_PLAN, overrides={"phosphorus_application_tg_per_year": 6.2})
        self.assertEqual(result["failed_count"], 0)
        # No override can create a bound for nitrogen.
        with self.assertRaises(ValueError):
            check_plan_limits({"nitrogen_fixation_tg_per_year": 165},
                              overrides={"nitrogen_fixation_tg_per_year": 100})


class EngineWiringTests(unittest.TestCase):
    def test_engine_loads_default_limits(self):
        engine = PlanningEngine()
        self.assertIsNotNone(engine.plan_limits)
        self.assertEqual(engine.plan_limits.snapshot_version, SNAPSHOT_VERSION)

    def test_engine_check_plan_uses_loaded_limits(self):
        engine = PlanningEngine()
        self.assertEqual(engine.check_plan(EXAMPLE_PLAN)["failed_count"], 0)
        self.assertEqual(engine.check_plan(FAILING_PLAN)["failed_count"], 2)
        with self.assertRaises(ValueError):
            engine.check_plan(EXAMPLE_PLAN, overrides={"phosphorus_application_tg_per_year": 62})

    def test_global_food_balance_reproduces_485_surplus(self):
        rows = load_snapshot()
        limits = load_plan_limits()
        engine = PlanningEngine()
        engine.register(FoodDomain())
        result = engine.run("food", {
            "population": get(rows, "world_population", 2024) * 1_000_000_000,
            "supply_kcal_per_capita_per_day": get(rows, "global_food_supply_dietary_energy", 2022),
            "requirement_kcal_per_capita_per_day": limits.food_need_default_kcal_per_capita_per_day,
            "imports_kcal_per_capita_per_day": 0.0,
            "losses_fraction": 0.0,
            "source_ids": limits.source_ids,
            "geography": "global",
            "period": "2022",
        })
        metrics = result["calculation"]["metrics"]
        self.assertEqual(metrics["surplus_kcal_per_capita_per_day"], 485.0)
        self.assertAlmostEqual(100 * metrics["surplus_kcal_per_capita_per_day"] / 2500, 19.4)
        # 485 * 8.2e9 * 365 in float arithmetic is 1451604999999999.8, not
        # exactly 1.451605e15; allow a 1e6 kcal/yr tolerance on a ~1.45e15 value.
        self.assertAlmostEqual(metrics["annual_gap_or_surplus_kcal"], 1.451605e15, delta=1e6)
        self.assertEqual(result["evaluation"]["overall_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
