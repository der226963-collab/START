"""ISSUE-34 (Part 2a, nutrients, 2026-11-13): phosphorus + nitrogen domain.

One domain, "nutrients", covering both nutrients. Snapshot values
(data/real_planning_data.csv, Planetary Health Check 2025, PIK
report): phosphorus application 18.2 Tg/yr, phosphorus regional
boundary 6.2 Tg/yr, nitrogen fixation 165 Tg/yr ("more than twice
its boundary", high-risk zone, NO exact boundary stored). Uptake and
losses are NEVER in the snapshot — in the tests below they are
explicit caller inputs, labelled as such, never snapshot values.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import unittest

from contracts.plan_limits import get, load_plan_limits, load_snapshot
from contracts.scenarios import Scenario
from contracts.statuses import CheckStatus
from domains.nutrients import NutrientsDomain
from domains.nutrients.balance import (
    NUTRIENT_UNIT,
    default_nutrient_constraints,
    nutrient_balance,
    phosphorus_excess_and_ratio,
    stored_phosphorus_boundary,
)
from domains.nutrients.evaluation import evaluate_nutrients_result
from engine.planning_engine import PlanningEngine

# Caller-stated balance inputs for the tests below. These are TEST
# inputs, not snapshot data: the snapshot carries no uptake/losses.
P_UPTAKE, P_LOSSES = 10.0, 5.0
N_UPTAKE, N_LOSSES = 100.0, 40.0

SNAPSHOT_SOURCE_IDS = [
    "snapshot:phosphorus_application_to_cropland:2025",
    "snapshot:phosphorus_regional_boundary:2025",
    "snapshot:nitrogen_fixation:2025",
]

FULL_PASSING_P = {
    "phosphorus_applied_tg_per_year": 5.0,
    "phosphorus_uptake_tg_per_year": P_UPTAKE,
    "phosphorus_losses_tg_per_year": P_LOSSES,
    "nitrogen_fixation_tg_per_year": 165.0,
    "nitrogen_uptake_tg_per_year": N_UPTAKE,
    "nitrogen_losses_tg_per_year": N_LOSSES,
    "source_ids": list(SNAPSHOT_SOURCE_IDS),
    "geography": "global",
    "period": "2025",
}

FULL_SNAPSHOT_P = dict(FULL_PASSING_P, phosphorus_applied_tg_per_year=18.2)


def _engine():
    engine = PlanningEngine()
    engine.register(NutrientsDomain())
    return engine


class SnapshotValuesTest(unittest.TestCase):
    def test_snapshot_nutrient_values(self):
        rows = load_snapshot()
        self.assertEqual(get(rows, "phosphorus_application_to_cropland", 2025), 18.2)
        self.assertEqual(get(rows, "phosphorus_regional_boundary", 2025), 6.2)
        self.assertEqual(get(rows, "nitrogen_fixation", 2025), 165)
        # The nitrogen note is the ONLY boundary information the
        # snapshot carries: a qualitative "more than twice", no number.
        row = next(r for r in rows if r["indicator"] == "nitrogen_fixation" and int(r["year"]) == 2025)
        self.assertIn("More than twice its boundary", row["note"])
        self.assertIn("high-risk zone", row["note"])

    def test_stored_phosphorus_boundary_comes_from_snapshot(self):
        self.assertEqual(stored_phosphorus_boundary(), 6.2)
        self.assertEqual(
            load_plan_limits().constraint("phosphorus_application_tg_per_year").bound, 6.2)


class PhosphorusBalanceTest(unittest.TestCase):
    def test_balance_is_inputs_minus_uptake_minus_losses(self):
        result = nutrient_balance("phosphorus", 18.2, P_UPTAKE, P_LOSSES,
                                  source_ids=SNAPSHOT_SOURCE_IDS[:2])
        self.assertEqual(result["calculation_status"], "COMPLETED")
        self.assertAlmostEqual(result["metrics"]["phosphorus_soil_change_tg_per_year"], 3.2)
        self.assertEqual(result["metrics"]["phosphorus_applied_tg_per_year"], 18.2)
        self.assertEqual(result["metrics"]["phosphorus_uptake_tg_per_year"], P_UPTAKE)
        self.assertEqual(result["metrics"]["phosphorus_losses_tg_per_year"], P_LOSSES)

    def test_teaching_example_balance_labelled_as_teaching(self):
        # v0.3.1 teaching example (domains/compat_v031.py
        # soil_summary): 100 applied, 50 uptake, 30 losses, 20 soil
        # change — abstract units, a labelled teaching input, NEVER
        # real data. Reused here only to pin the balance arithmetic.
        result = nutrient_balance("nitrogen", 100, 50, 30)
        self.assertEqual(result["calculation_status"], "COMPLETED")
        self.assertEqual(result["metrics"]["nitrogen_soil_change_tg_per_year"], 20)

    def test_missing_uptake_or_losses_is_insufficient_input_never_zero(self):
        for kwargs in ({"uptake_tg_per_year": None, "losses_tg_per_year": 5.0},
                       {"uptake_tg_per_year": 10.0, "losses_tg_per_year": None},
                       {"uptake_tg_per_year": None, "losses_tg_per_year": None}):
            with self.subTest(**kwargs):
                result = nutrient_balance("phosphorus", 18.2, **kwargs)
                self.assertEqual(result["calculation_status"], "INSUFFICIENT_INPUT")
                self.assertEqual(result["metrics"], {})

    def test_negative_input_is_error(self):
        result = nutrient_balance("phosphorus", 18.2, -1.0, 5.0)
        self.assertEqual(result["calculation_status"], "ERROR")


class PhosphorusConstraintTest(unittest.TestCase):
    def test_five_passes_and_snapshot_fails_against_stored_boundary(self):
        constraints = default_nutrient_constraints()
        p = constraints[0]
        self.assertEqual(p.constraint_id, "phosphorus_application_tg_per_year")
        self.assertEqual(p.bound, 6.2)
        self.assertEqual(p.unit, "Tg/yr")
        self.assertEqual(p.evaluate(5.0, "Tg/yr"), CheckStatus.PASS)
        self.assertEqual(p.evaluate(18.2, "Tg/yr"), CheckStatus.FAIL)
        self.assertEqual(p.evaluate(6.2, "Tg/yr"), CheckStatus.PASS)

    def test_excess_and_ratio_reproduced_exactly_from_snapshot(self):
        rows = load_snapshot()
        applied = get(rows, "phosphorus_application_to_cropland", 2025)
        boundary = get(rows, "phosphorus_regional_boundary", 2025)
        excess, ratio = phosphorus_excess_and_ratio(applied, boundary)
        self.assertEqual(excess, 12.0)
        self.assertEqual(ratio, 2.94)

    def test_domain_evaluation_row_carries_excess_ratio_and_sources(self):
        result = _engine().run("nutrients", FULL_SNAPSHOT_P)
        rows = result["evaluation"]["constraint_results"]
        p_row = next(r for r in rows if r["constraint_id"] == "phosphorus_application_tg_per_year")
        self.assertEqual(p_row["status"], "FAIL")
        self.assertEqual(p_row["excess_tg_per_year"], 12.0)
        self.assertEqual(p_row["ratio_to_boundary"], 2.94)
        self.assertEqual(p_row["unit"], "Tg/yr")
        self.assertEqual(p_row["source_ids"], SNAPSHOT_SOURCE_IDS[:2])
        self.assertEqual(p_row["tolerance"], 0.0)
        self.assertFalse(p_row["tolerance_changed_verdict"])

    def test_tolerance_flip_is_surfaced_not_silent(self):
        # ISSUE-35 (food): 6.5 vs bound 6.2 FAILs at tolerance 0.0 and
        # PASSes at 0.5 — the row must say so in words and in fields.
        calc = {"calculation_status": "COMPLETED",
                "metrics": {"phosphorus_applied_tg_per_year": 6.5}}
        at_zero = evaluate_nutrients_result(calc)
        self.assertEqual(at_zero["constraint_results"][0]["status"], "FAIL")
        flipped = evaluate_nutrients_result(calc, tolerance=0.5)
        row = flipped["constraint_results"][0]
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["verdict_without_tolerance"], "FAIL")
        self.assertTrue(row["tolerance_changed_verdict"])
        self.assertTrue(any("Tolerance 0.5 changed the phosphorus verdict" in w
                            for w in flipped["warnings"]))


class NitrogenAlwaysUnknownTest(unittest.TestCase):
    def test_nitrogen_constraint_is_boundless_and_always_unknown(self):
        constraints = default_nutrient_constraints()
        n = constraints[1]
        self.assertEqual(n.constraint_id, "nitrogen_fixation_tg_per_year")
        self.assertTrue(n.boundless)
        self.assertIsNone(n.bound)
        self.assertEqual(n.unit, "Tg/yr")
        for value in (165.0, 1.0, 0.0):
            with self.subTest(value=value):
                self.assertEqual(n.evaluate(value, "Tg/yr"), CheckStatus.UNKNOWN)

    def test_nitrogen_never_passes_through_domain_evaluation(self):
        result = _engine().run("nutrients", FULL_PASSING_P)
        rows = result["evaluation"]["constraint_results"]
        n_row = next(r for r in rows if r["constraint_id"] == "nitrogen_fixation_tg_per_year")
        self.assertEqual(n_row["status"], "UNKNOWN")
        self.assertIsNone(n_row["boundary"])
        self.assertIn("more than twice its boundary", n_row["detail"])
        self.assertEqual(n_row["source_ids"], ["snapshot:nitrogen_fixation:2025"])

    def test_passing_phosphorus_plus_unknown_nitrogen_is_unknown_overall(self):
        # The nitrogen UNKNOWN blocks a pass: it is not ignored.
        result = _engine().run("nutrients", FULL_PASSING_P)
        self.assertEqual(result["evaluation"]["overall_status"], "UNKNOWN")

    def test_no_nitrogen_boundary_field_exists(self):
        # There is nothing a caller could correctly state for a
        # nitrogen boundary, so the field does not exist at all.
        request = dict(FULL_PASSING_P, nitrogen_boundary_tg_per_year=80.0)
        validation = NutrientsDomain().validate_inputs(request)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("nitrogen_boundary_tg_per_year" in p
                            for p in validation["problems"]))


class StatedInputsTest(unittest.TestCase):
    def test_missing_uptake_or_losses_is_insufficient_input(self):
        for request in (
            {"phosphorus_applied_tg_per_year": 18.2},
            {"nitrogen_fixation_tg_per_year": 165.0},
            dict(FULL_PASSING_P, phosphorus_losses_tg_per_year=None),
            dict(FULL_PASSING_P, nitrogen_uptake_tg_per_year=None),
            {"phosphorus_applied_tg_per_year": 18.2,
             "nitrogen_fixation_tg_per_year": 165.0},
        ):
            with self.subTest(request=request):
                result = _engine().run("nutrients", request)
                self.assertEqual(result["calculation"]["calculation_status"],
                                 "INSUFFICIENT_INPUT", result)
                self.assertEqual(result["calculation"]["metrics"], {})

    def test_half_stated_nutrient_is_a_problem_not_ignored(self):
        request = {"phosphorus_applied_tg_per_year": 5.0,
                   "phosphorus_uptake_tg_per_year": 3.0,
                   "phosphorus_losses_tg_per_year": 1.0,
                   "nitrogen_uptake_tg_per_year": 100.0}
        validation = NutrientsDomain().validate_inputs(request)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("nitrogen_uptake_tg_per_year" in p
                            for p in validation["problems"]))

    def test_request_stating_neither_nutrient_is_rejected(self):
        validation = NutrientsDomain().validate_inputs({"geography": "global"})
        self.assertFalse(validation["ok"])
        self.assertTrue(any("at least one nutrient" in p
                            for p in validation["problems"]))

    def test_unknown_field_rejected_and_non_dict_is_insufficient(self):
        validation = NutrientsDomain().validate_inputs(
            dict(FULL_PASSING_P, phosphorus_aplied_tg_per_year=5.0))
        self.assertFalse(validation["ok"])
        self.assertTrue(any("unknown request field" in p for p in validation["problems"]))
        result = _engine().run("nutrients", "not a request")
        self.assertEqual(result["calculation"]["calculation_status"], "ERROR")

    def test_wrong_phosphorus_boundary_is_refused_never_applied(self):
        request = dict(FULL_PASSING_P, phosphorus_boundary_tg_per_year=62.0)
        validation = NutrientsDomain().validate_inputs(request)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("conflicts with the stored limit" in p
                            for p in validation["problems"]))
        # An exact confirmation of the stored bound is accepted.
        confirmed = dict(FULL_PASSING_P, phosphorus_boundary_tg_per_year=6.2)
        self.assertTrue(NutrientsDomain().validate_inputs(confirmed)["ok"])

    def test_explicit_zero_uptake_and_losses_are_allowed(self):
        # Stating 0.0 explicitly is the caller asserting "none" —
        # allowed, like food's explicit 0.0 imports/losses.
        request = dict(FULL_PASSING_P,
                       phosphorus_uptake_tg_per_year=0.0,
                       phosphorus_losses_tg_per_year=0.0)
        result = _engine().run("nutrients", request)
        self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
        self.assertEqual(
            result["calculation"]["metrics"]["phosphorus_soil_change_tg_per_year"], 5.0)


class EngineEndToEndTest(unittest.TestCase):
    def test_snapshot_phosphorus_run_is_completed_failed_partially_verified(self):
        result = _engine().run("nutrients", FULL_SNAPSHOT_P)
        self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
        self.assertTrue(result["calculation_ok"])
        # No independent verifier exists for nutrients: the expected
        # honest status is PARTIALLY_VERIFIED, verified False — a
        # limit of verification coverage, not a failed calculation.
        self.assertEqual(result["verification"]["verification_status"], "PARTIALLY_VERIFIED")
        self.assertFalse(result["verified"])
        self.assertFalse(result["verified_ok"])
        self.assertTrue(result["needs_human_decision"])
        self.assertEqual(result["evaluation"]["overall_status"], "FAIL")
        metrics = result["calculation"]["metrics"]
        self.assertEqual(metrics["phosphorus_excess_tg_per_year"], 12.0)
        self.assertEqual(metrics["phosphorus_ratio_to_boundary"], 2.94)
        self.assertIsNone(metrics["nitrogen_boundary_tg_per_year"])
        self.assertAlmostEqual(metrics["nitrogen_soil_change_tg_per_year"], 25.0)

    def test_phosphorus_only_request_completes_with_one_row(self):
        request = {k: v for k, v in FULL_PASSING_P.items()
                   if not k.startswith("nitrogen")}
        result = _engine().run("nutrients", request)
        self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
        self.assertEqual(len(result["evaluation"]["constraint_results"]), 1)
        self.assertEqual(result["evaluation"]["overall_status"], "PASS")

    def test_identify_constraints_returns_both_with_snapshot_sources(self):
        constraints = NutrientsDomain().identify_constraints(FULL_PASSING_P)
        by_id = {c["constraint_id"]: c for c in constraints}
        self.assertEqual(set(by_id), {"phosphorus_application_tg_per_year",
                                      "nitrogen_fixation_tg_per_year"})
        self.assertEqual(by_id["phosphorus_application_tg_per_year"]["unit"], "Tg/yr")
        self.assertEqual(by_id["phosphorus_application_tg_per_year"]["bound"], 6.2)
        self.assertEqual(by_id["phosphorus_application_tg_per_year"]["source_ids"],
                         SNAPSHOT_SOURCE_IDS[:2])
        self.assertTrue(by_id["nitrogen_fixation_tg_per_year"]["boundless"])
        self.assertEqual(by_id["nitrogen_fixation_tg_per_year"]["source_ids"],
                         ["snapshot:nitrogen_fixation:2025"])

    def test_unit_is_the_registry_tg_per_year(self):
        self.assertEqual(NUTRIENT_UNIT, "Tg/yr")


class ScenarioAllowListTest(unittest.TestCase):
    def test_domain_declares_both_allow_lists(self):
        self.assertEqual(NutrientsDomain.scenario_change_fields,
                         frozenset({
                             "phosphorus_applied_tg_per_year",
                             "phosphorus_uptake_tg_per_year",
                             "phosphorus_losses_tg_per_year",
                             "nitrogen_fixation_tg_per_year",
                             "nitrogen_uptake_tg_per_year",
                             "nitrogen_losses_tg_per_year",
                             "phosphorus_boundary_tg_per_year",
                         }))
        self.assertEqual(NutrientsDomain.scenario_non_numeric_change_fields,
                         frozenset({"source_ids", "geography", "period"}))

    def test_non_numeric_changes_accepted_end_to_end(self):
        engine = _engine()
        scenario = Scenario(
            "s1", "nutrient scenario",
            proposed_changes={"source_ids": ["src-a", "src-b"],
                              "geography": "riverport", "period": "2026"},
            metadata={"base_request": dict(FULL_PASSING_P)})
        result = engine.run_scenario("nutrients", scenario)
        self.assertTrue(result["calculation_ok"], result)
        self.assertEqual(result["metrics"]["calculation"]["source_ids"],
                         ["src-a", "src-b"])
        request = NutrientsDomain().scenario_request(scenario)
        self.assertEqual(request["geography"], "riverport")
        self.assertEqual(request["period"], "2026")

    def test_explicit_geography_change_wins_over_base_request(self):
        scenario = Scenario(
            "s1", "explicit geo change",
            proposed_changes={"geography": "new-geo", "period": "2030"},
            metadata={"base_request": dict(FULL_PASSING_P, geography="base-geo",
                                           period="2020")})
        request = NutrientsDomain().scenario_request(scenario)
        self.assertEqual(request["geography"], "new-geo")
        self.assertEqual(request["period"], "2030")

    def test_base_request_still_wins_over_scenario_defaults(self):
        # ISSUE-25: with no explicit change proposed, the base
        # request's geography/period win over the scenario's.
        scenario = Scenario(
            "s1", "no explicit geo change",
            geography="scenario-geo", period="scenario-period",
            metadata={"base_request": dict(FULL_PASSING_P, geography="base-geo",
                                           period="2020")})
        request = NutrientsDomain().scenario_request(scenario)
        self.assertEqual(request["geography"], "base-geo")
        self.assertEqual(request["period"], "2020")

    def test_non_numeric_change_to_non_listed_field_is_rejected(self):
        scenario = Scenario(
            "s1", "injected",
            proposed_changes={"__injected__": "pwned"},
            metadata={"base_request": dict(FULL_PASSING_P)})
        with self.assertRaises(ValueError) as ctx:
            NutrientsDomain().scenario_request(scenario)
        self.assertIn("__injected__", str(ctx.exception))
        self.assertIn("scenario_non_numeric_change_fields", str(ctx.exception))
        result = _engine().run_scenario("nutrients", scenario)
        self.assertFalse(result["calculation_ok"])
        self.assertEqual(result["calculation_status"], "ERROR")

    def test_numeric_change_to_non_numeric_only_field_is_rejected(self):
        scenario = Scenario(
            "s1", "number for source_ids",
            proposed_changes={"source_ids": 42},
            metadata={"base_request": dict(FULL_PASSING_P)})
        with self.assertRaises(ValueError):
            NutrientsDomain().scenario_request(scenario)

    def test_string_change_to_numeric_only_field_is_rejected(self):
        scenario = Scenario(
            "s1", "string for applied",
            proposed_changes={"phosphorus_applied_tg_per_year": "18.2"},
            metadata={"base_request": dict(FULL_PASSING_P)})
        with self.assertRaises(ValueError):
            NutrientsDomain().scenario_request(scenario)

    def test_numeric_allow_listed_change_still_passes(self):
        scenario = Scenario(
            "s1", "lower phosphorus",
            proposed_changes={"phosphorus_applied_tg_per_year": 4.0},
            metadata={"base_request": dict(FULL_PASSING_P)})
        request = NutrientsDomain().scenario_request(scenario)
        self.assertEqual(request["phosphorus_applied_tg_per_year"], 4.0)
        result = _engine().run_scenario("nutrients", scenario)
        self.assertTrue(result["calculation_ok"], result)
        p_row = next(r for r in result["constraint_results"]
                     if r["constraint_id"] == "phosphorus_application_tg_per_year")
        self.assertEqual(p_row["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
