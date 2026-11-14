"""Labour domain (ISSUE-34, Part 2b, 2026-11-13).

Paid work against the 48 h/week ILO long-hours threshold (stored
bound from contracts.plan_limits, never re-derived here); unpaid-care
split computed from the snapshot values (ILO 2018: 16.4 billion
hours/day, women's share 76.2%); per-person care hours only with an
explicit caller-supplied population; never-PASS-on-unknown; engine
run end-to-end (PARTIALLY_VERIFIED is the expected verification
status — no independent verifier exists for labour); scenario
changes to source_ids/geography/period accepted, a non-listed
non-numeric change rejected.
"""
import unittest

from contracts.plan_limits import get, load_plan_limits, load_snapshot
from contracts.scenarios import Scenario
from domains import LabourDomain
from domains.labour.evaluation import evaluate_labour_result
from domains.labour.labour import (
    default_labour_constraints,
    labour_balance,
    paid_work_threshold_hours_per_week,
)
from engine.planning_engine import PlanningEngine

# Snapshot values, loaded — never hard-coded in the tests either.
ROWS = load_snapshot()
CARE_TOTAL_BILLION = get(ROWS, "unpaid_care_hours_per_day", 2018) / 1000  # 16.4
WOMEN_SHARE = get(ROWS, "women_share_unpaid_care_work", 2018)  # 76.2
EMPLOYED_AVG = get(ROWS, "paid_work_hours_per_week_employed", 2026)  # 43
ALL_ADULTS_AVG = get(ROWS, "paid_work_hours_per_week_all_adults", 2026)  # 25
POPULATION = get(ROWS, "world_population", 2024) * 1_000_000_000  # 8.2e9


def _base(**overrides):
    req = {
        "unpaid_care_hours_per_day_billion": CARE_TOTAL_BILLION,
        "women_share_unpaid_care_percent": WOMEN_SHARE,
    }
    req.update(overrides)
    return req


class PaidWorkThresholdTest(unittest.TestCase):
    def test_threshold_is_the_stored_plan_limits_bound(self):
        # The 48 h/week threshold is a v0.3.1 code constant stored in
        # contracts.plan_limits — the domain reads it, never re-derives it.
        self.assertEqual(paid_work_threshold_hours_per_week(), 48.0)
        self.assertEqual(
            paid_work_threshold_hours_per_week(),
            load_plan_limits().constraint("paid_work_hours_per_week").bound)

    def test_constraint_uses_hours_per_week_registry_unit(self):
        constraint = default_labour_constraints(bound=48.0)[0]
        self.assertEqual(constraint.constraint_id, "paid_work_hours_per_week")
        self.assertEqual(constraint.operator, "<=")
        self.assertEqual(constraint.bound, 48.0)
        self.assertEqual(constraint.unit, "hours/week")

    def test_40_and_43_pass_55_fails(self):
        constraint = default_labour_constraints(bound=48.0)[0]
        self.assertEqual(constraint.evaluate(40, "hours/week").value, "PASS")
        self.assertEqual(constraint.evaluate(43, "hours/week").value, "PASS")
        self.assertEqual(constraint.evaluate(48, "hours/week").value, "PASS")
        self.assertEqual(constraint.evaluate(55, "hours/week").value, "FAIL")

    def test_boundless_constraint_never_passes(self):
        # bound=None is a deliberately bound-less constraint: always
        # UNKNOWN, never PASS (ISSUE-12).
        constraint = default_labour_constraints(bound=None)[0]
        self.assertTrue(constraint.boundless)
        self.assertEqual(constraint.evaluate(40, "hours/week").value, "UNKNOWN")
        self.assertEqual(constraint.evaluate(None, "hours/week").value, "UNKNOWN")


class CareSplitTest(unittest.TestCase):
    def test_split_computed_exactly_from_snapshot_values(self):
        result = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE)
        self.assertEqual(result["calculation_status"], "COMPLETED")
        metrics = result["metrics"]
        # 16.4 * 0.762 = 12.4968 and 16.4 * 0.238 = 3.9032; float
        # arithmetic gives 12.496799999999999 / 3.9031999999999996,
        # so the comparison is to 9 decimal places, not exact.
        self.assertAlmostEqual(metrics["women_unpaid_care_hours_per_day_billion"], 12.4968, places=9)
        self.assertAlmostEqual(metrics["men_unpaid_care_hours_per_day_billion"], 3.9032, places=9)
        self.assertAlmostEqual(
            metrics["women_unpaid_care_hours_per_day_billion"]
            + metrics["men_unpaid_care_hours_per_day_billion"],
            CARE_TOTAL_BILLION, places=9)
        self.assertEqual(result["display_metrics"]["women_unpaid_care_hours_per_day_billion"], 12.4968)
        self.assertEqual(result["display_metrics"]["men_unpaid_care_hours_per_day_billion"], 3.9032)

    def test_split_uses_stated_share_not_a_default(self):
        result = labour_balance(10.0, 50.0)
        self.assertAlmostEqual(result["metrics"]["women_unpaid_care_hours_per_day_billion"], 5.0)
        self.assertAlmostEqual(result["metrics"]["men_unpaid_care_hours_per_day_billion"], 5.0)

    def test_metric_units_use_registry_units(self):
        result = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE,
                                paid_work_hours_per_week=40, population=POPULATION)
        units = result["metric_units"]
        self.assertEqual(units["paid_work_hours_per_week"], "hours/week")
        self.assertEqual(units["unpaid_care_hours_per_day_billion"], "hours/day")
        self.assertEqual(units["women_unpaid_care_hours_per_day_billion"], "hours/day")
        self.assertEqual(units["women_share_unpaid_care_percent"], "percent")
        self.assertEqual(units["unpaid_care_hours_per_person_per_day"], "hours/day")
        self.assertEqual(units["population"], "person")


class CarePerPersonTest(unittest.TestCase):
    def test_per_person_only_with_explicit_population(self):
        result = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE, population=POPULATION)
        metrics = result["metrics"]
        # 16.4e9 / 8.2e9 = 2.0 hours/person/day.
        self.assertAlmostEqual(metrics["unpaid_care_hours_per_person_per_day"], 2.0, places=9)
        self.assertAlmostEqual(metrics["women_unpaid_care_hours_per_person_per_day"], 1.524, places=9)
        self.assertAlmostEqual(metrics["men_unpaid_care_hours_per_person_per_day"], 0.476, places=9)

    def test_no_per_person_metric_without_population(self):
        result = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE)
        self.assertNotIn("unpaid_care_hours_per_person_per_day", result["metrics"])
        self.assertNotIn("population", result["metrics"])
        self.assertNotIn("unpaid_care_hours_per_person_per_day", result["metric_units"])

    def test_year_mismatch_stated_when_population_combined(self):
        with_pop = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE, population=POPULATION)
        self.assertTrue(any("Year mismatch" in lim and "2018" in lim and "2024" in lim
                            for lim in with_pop["limitations"]))
        without_pop = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE)
        self.assertFalse(any("Year mismatch" in lim for lim in without_pop["limitations"]))


class SnapshotContextTest(unittest.TestCase):
    def test_snapshot_averages_reported_as_context_not_checked(self):
        result = labour_balance(
            CARE_TOTAL_BILLION, WOMEN_SHARE, paid_work_hours_per_week=EMPLOYED_AVG,
            snapshot_paid_work_hours_per_week_employed=EMPLOYED_AVG,
            snapshot_paid_work_hours_per_week_all_adults=ALL_ADULTS_AVG)
        metrics = result["metrics"]
        self.assertEqual(metrics["snapshot_paid_work_hours_per_week_employed"], 43.0)
        self.assertEqual(metrics["snapshot_paid_work_hours_per_week_all_adults"], 25.0)
        self.assertEqual(metrics["paid_work_hours_per_week"], 43.0)
        self.assertTrue(any("context only" in lim for lim in result["limitations"]))

    def test_snapshot_context_absent_when_not_supplied(self):
        result = labour_balance(CARE_TOTAL_BILLION, WOMEN_SHARE)
        self.assertNotIn("snapshot_paid_work_hours_per_week_employed", result["metrics"])
        self.assertFalse(any("context only" in lim for lim in result["limitations"]))


class NeverPassOnUnknownTest(unittest.TestCase):
    def test_no_paid_work_figure_is_unknown_never_pass(self):
        # Paid work is optional: omitted means the long-hours check
        # is UNKNOWN, never PASS.
        domain = LabourDomain()
        result = domain.calculate(_base())
        self.assertEqual(result["calculation_status"], "COMPLETED")
        evaluation = domain.evaluate(result)
        self.assertEqual(evaluation["overall_status"], "UNKNOWN")
        row = evaluation["constraint_results"][0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertIsNone(row["paid_work_hours_per_week"])

    def test_missing_care_figure_is_insufficient_input_never_pass(self):
        domain = LabourDomain()
        for req in ({}, {"unpaid_care_hours_per_day_billion": CARE_TOTAL_BILLION},
                    {"women_share_unpaid_care_percent": WOMEN_SHARE},
                    _base(unpaid_care_hours_per_day_billion=None),
                    _base(women_share_unpaid_care_percent=None)):
            result = domain.calculate(req)
            self.assertEqual(result["calculation_status"], "INSUFFICIENT_INPUT", req)
            evaluation = domain.evaluate(result)
            self.assertNotEqual(evaluation["overall_status"], "PASS", req)
            self.assertEqual(evaluation["constraint_results"], [], req)

    def test_non_dict_request_is_insufficient_input(self):
        domain = LabourDomain()
        for bad in ("x", 42, None, ["a"]):
            result = domain.calculate(bad)
            self.assertEqual(result["calculation_status"], "INSUFFICIENT_INPUT", bad)
            self.assertNotEqual(domain.evaluate(result)["overall_status"], "PASS", bad)

    def test_non_dict_evaluation_is_not_checked(self):
        self.assertEqual(evaluate_labour_result(None)["overall_status"], "NOT_CHECKED")
        self.assertEqual(evaluate_labour_result("x")["overall_status"], "NOT_CHECKED")


class ValidationTest(unittest.TestCase):
    def test_unknown_field_rejected(self):
        domain = LabourDomain()
        validation = domain.validate_inputs(_base(paid_work_hours_per_weak=40))
        self.assertFalse(validation["ok"])
        self.assertTrue(any("paid_work_hours_per_weak" in p for p in validation["problems"]))

    def test_share_out_of_range_rejected(self):
        domain = LabourDomain()
        for bad_share in (-1, 100.5, 150):
            validation = domain.validate_inputs(_base(women_share_unpaid_care_percent=bad_share))
            self.assertFalse(validation["ok"], bad_share)
            self.assertTrue(any("women_share_unpaid_care_percent" in p
                                for p in validation["problems"]), bad_share)

    def test_negative_care_and_paid_work_rejected(self):
        domain = LabourDomain()
        self.assertFalse(domain.validate_inputs(
            _base(unpaid_care_hours_per_day_billion=-1))["ok"])
        self.assertFalse(domain.validate_inputs(
            _base(paid_work_hours_per_week=-5))["ok"])

    def test_fractional_population_rejected(self):
        domain = LabourDomain()
        validation = domain.validate_inputs(_base(population=1000.5))
        self.assertFalse(validation["ok"])
        self.assertTrue(any("population" in p for p in validation["problems"]))

    def test_snapshot_derived_population_accepted(self):
        # 8.2e9 arrives as 8199999999.999999 through float
        # multiplication — a whole number within float error.
        domain = LabourDomain()
        self.assertTrue(domain.validate_inputs(_base(population=POPULATION))["ok"])


class EngineEndToEndTest(unittest.TestCase):
    def _engine(self):
        engine = PlanningEngine()
        engine.register(LabourDomain())
        return engine

    def test_engine_run_passes_paid_work_and_reports_care_split(self):
        engine = self._engine()
        result = engine.run("labour", _base(
            paid_work_hours_per_week=40, population=POPULATION,
            snapshot_paid_work_hours_per_week_employed=EMPLOYED_AVG,
            snapshot_paid_work_hours_per_week_all_adults=ALL_ADULTS_AVG,
            source_ids=["snapshot:unpaid_care_hours_per_day:2018"],
            geography="global", period="2018"))
        self.assertTrue(result["calculation_ok"], result)
        self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
        self.assertEqual(result["evaluation"]["overall_status"], "PASS")
        row = result["evaluation"]["constraint_results"][0]
        self.assertEqual(row["constraint_id"], "paid_work_hours_per_week")
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["threshold_hours_per_week"], 48.0)
        self.assertEqual(row["unit"], "hours/week")
        metrics = result["calculation"]["metrics"]
        self.assertAlmostEqual(metrics["women_unpaid_care_hours_per_day_billion"], 12.4968, places=9)
        self.assertAlmostEqual(metrics["unpaid_care_hours_per_person_per_day"], 2.0, places=9)
        self.assertTrue(result["needs_human_decision"])

    def test_engine_run_55_hours_fails(self):
        engine = self._engine()
        result = engine.run("labour", _base(paid_work_hours_per_week=55))
        self.assertTrue(result["calculation_ok"], result)
        self.assertEqual(result["evaluation"]["overall_status"], "FAIL")
        self.assertEqual(result["evaluation"]["constraint_results"][0]["status"], "FAIL")

    def test_engine_run_is_partially_verified_by_design(self):
        # No independent verifier exists for labour (ARCHITECTURE.md,
        # "Adding a domain" rule 5): PARTIALLY_VERIFIED and verified
        # False even when the calculation completed correctly.
        engine = self._engine()
        result = engine.run("labour", _base(paid_work_hours_per_week=43))
        self.assertTrue(result["calculation_ok"], result)
        self.assertEqual(result["verification"]["verification_status"], "PARTIALLY_VERIFIED")
        self.assertFalse(result["verification"]["verified"])
        self.assertFalse(result["verified"])
        self.assertFalse(result["verified_ok"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["verification"]["issues"], [])

    def test_engine_identifies_paid_work_constraint(self):
        engine = self._engine()
        result = engine.run("labour", _base(paid_work_hours_per_week=40))
        constraints = result["constraints_identified"]
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0]["constraint_id"], "paid_work_hours_per_week")
        self.assertEqual(constraints[0]["unit"], "hours/week")
        self.assertEqual(constraints[0]["bound"], 48.0)


class ScenarioTest(unittest.TestCase):
    def test_allow_lists_declared(self):
        domain = LabourDomain()
        self.assertEqual(domain.scenario_change_fields,
                         frozenset({"unpaid_care_hours_per_day_billion",
                                    "women_share_unpaid_care_percent",
                                    "paid_work_hours_per_week",
                                    "population",
                                    "snapshot_paid_work_hours_per_week_employed",
                                    "snapshot_paid_work_hours_per_week_all_adults"}))
        self.assertEqual(domain.scenario_non_numeric_change_fields,
                         frozenset({"source_ids", "geography", "period"}))

    def _engine(self):
        engine = PlanningEngine()
        engine.register(LabourDomain())
        return engine

    def test_numeric_scenario_change_accepted_end_to_end(self):
        # Base 40 h/week (PASS) -> scenario 55 h/week (FAIL).
        engine = self._engine()
        scenario = Scenario(
            "s-labour-1", "longer working week",
            proposed_changes={"paid_work_hours_per_week": 55},
            metadata={"base_request": _base(paid_work_hours_per_week=40)})
        result = engine.run_scenario("labour", scenario)
        self.assertTrue(result["calculation_ok"], result)
        self.assertEqual(result["metrics"]["evaluation"]["overall_status"], "FAIL")
        self.assertEqual(
            result["metrics"]["calculation"]["metrics"]["paid_work_hours_per_week"], 55)

    def test_non_numeric_scenario_changes_accepted_end_to_end(self):
        engine = self._engine()
        scenario = Scenario(
            "s-labour-2", "relabelled run",
            proposed_changes={"source_ids": ["src-a", "src-b"],
                              "geography": "riverport", "period": "2026"},
            metadata={"base_request": _base(paid_work_hours_per_week=40)})
        result = engine.run_scenario("labour", scenario)
        self.assertTrue(result["calculation_ok"], result)
        metrics = result["metrics"]["calculation"]["metrics"]
        self.assertEqual(result["metrics"]["calculation"]["source_ids"], ["src-a", "src-b"])
        self.assertEqual(metrics["paid_work_hours_per_week"], 40)

    def test_explicit_geography_change_wins_over_base_request(self):
        scenario = Scenario(
            "s-labour-3", "explicit geography",
            proposed_changes={"geography": "new-geo", "period": "2030"},
            metadata={"base_request": _base(paid_work_hours_per_week=40,
                                            geography="base-geo", period="2020")})
        req = LabourDomain().scenario_request(scenario)
        self.assertEqual(req["geography"], "new-geo")
        self.assertEqual(req["period"], "2030")

    def test_non_listed_non_numeric_change_rejected(self):
        scenario = Scenario(
            "s-labour-4", "injected change",
            proposed_changes={"__injected__": "pwned"},
            metadata={"base_request": _base(paid_work_hours_per_week=40)})
        with self.assertRaises(ValueError) as ctx:
            LabourDomain().scenario_request(scenario)
        self.assertIn("__injected__", str(ctx.exception))
        self.assertIn("scenario_non_numeric_change_fields", str(ctx.exception))

    def test_non_listed_numeric_change_rejected(self):
        scenario = Scenario(
            "s-labour-5", "injected numeric change",
            proposed_changes={"__injected__": 1.5},
            metadata={"base_request": _base(paid_work_hours_per_week=40)})
        with self.assertRaises(ValueError) as ctx:
            LabourDomain().scenario_request(scenario)
        self.assertIn("__injected__", str(ctx.exception))
        self.assertIn("scenario_change_fields", str(ctx.exception))

    def test_string_change_to_numeric_field_rejected(self):
        # "paid_work_hours_per_week" is numeric-only: a str value for
        # it must be rejected, not silently applied.
        scenario = Scenario(
            "s-labour-6", "string for numeric field",
            proposed_changes={"paid_work_hours_per_week": "40"},
            metadata={"base_request": _base(paid_work_hours_per_week=40)})
        with self.assertRaises(ValueError):
            LabourDomain().scenario_request(scenario)


if __name__ == "__main__":
    unittest.main()
