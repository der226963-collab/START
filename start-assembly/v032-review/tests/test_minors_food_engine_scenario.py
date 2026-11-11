"""REVIEW.md minors — food/engine/scenario (ISSUE-19, 20, 21, 22, 23, 25,
26, 28, 29, 30, 33, 35, 36, 38, 43, 44), fixed 2026-11-11.

Each issue is reproduced live first (see the fix notes in the source),
then fixed; every test below pins the fixed behaviour. ISSUE-43's
second half (low-level vs domain-level defaulting) was verified
already-resolved by ISSUE-15 and is pinned here, not re-fixed.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from contracts.constraints import Constraint
from contracts.scenarios import Scenario
from contracts.statuses import CalculationStatus, CheckStatus
from domains.base import DomainModule
from domains.food import FoodDomain
from domains.food.evaluation import evaluate_food_result, describe_food_uncertainty
from domains.food.production import food_availability
from engine.planning_engine import PlanningEngine
from engine.verification import verify_domain_result, _independently_recalculate_food

ROOT = Path(__file__).resolve().parent.parent

BASE = {
    "population": 100000,
    "supply_kcal_per_capita_per_day": 2800,
    "requirement_kcal_per_capita_per_day": 2500,
    "imports_kcal_per_capita_per_day": 100,
    "losses_fraction": 0.08,
}

GLOBAL = {
    "population": 8_200_000_000,
    "supply_kcal_per_capita_per_day": 2985,
    "requirement_kcal_per_capita_per_day": 2500,
    "imports_kcal_per_capita_per_day": 0.0,
    "losses_fraction": 0.0,
}


class GenericDomain(DomainModule):
    """Correct generic domain with no independent verifier and no
    declared scenario-change fields (so no changes are permitted)."""
    domain_id = "generic"

    def validate_inputs(self, request):
        return {"ok": True, "problems": [], "warnings": [], "assumptions": []}

    def calculate(self, request):
        return {"calculation_status": "COMPLETED", "metrics": {},
                "display_metrics": {}, "assumptions": [], "limitations": []}

    def identify_constraints(self, request):
        return []

    def evaluate(self, calc):
        return {"overall_status": "PASS",
                "constraint_results": [{"constraint_id": "x", "status": "PASS"}],
                "warnings": []}

    def describe_uncertainty(self, calc):
        return []


class DeclaringDomain(GenericDomain):
    domain_id = "declaring"
    scenario_change_fields = frozenset({"population"})


class MisbehavingDomain(DomainModule):
    """validate_inputs returns a malformed report (ISSUE-28)."""
    domain_id = "stub"

    def validate_inputs(self, request):
        return {"ok": False, "problems": "oops-string", "assumptions": "also-a-string"}

    def calculate(self, request):
        return {}

    def identify_constraints(self, request):
        return []

    def evaluate(self, result):
        return {}

    def describe_uncertainty(self, result):
        return []


class Issue19OverflowTest(unittest.TestCase):
    def test_overflow_is_error_not_completed_inf(self):
        r = food_availability(1e308, 2800, 2500, 0.0, 0.0)
        self.assertEqual(r["calculation_status"], CalculationStatus.ERROR.value)
        self.assertEqual(r["metrics"], {})
        self.assertIn("not finite", r["error"])
        # The result must be strict-JSON serialisable (no Infinity).
        json.dumps(r, allow_nan=False)

    def test_finite_large_inputs_still_complete(self):
        r = food_availability(1e9, 2800, 2500, 0.0, 0.0)
        self.assertEqual(r["calculation_status"], CalculationStatus.COMPLETED.value)
        self.assertTrue(all(v == v and abs(v) != float("inf") for v in r["metrics"].values()))


class Issue20NonDictTest(unittest.TestCase):
    def test_calculate_non_dict_returns_insufficient_input(self):
        for bad in ("x", [], 42, None):
            with self.subTest(bad=repr(bad)):
                r = FoodDomain().calculate(bad)
                self.assertEqual(r["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)
                self.assertIn("request must be a dictionary", r["missing_fields"])

    def test_evaluate_non_dict_returns_not_checked(self):
        for bad in (None, "x", 42, []):
            with self.subTest(bad=repr(bad)):
                r = evaluate_food_result(bad)
                self.assertEqual(r["overall_status"], CheckStatus.NOT_CHECKED.value)
                self.assertEqual(r["constraint_results"], [])

    def test_describe_uncertainty_non_dict_does_not_crash(self):
        self.assertIsInstance(describe_food_uncertainty(None), list)


class Issue21ScenarioAssumptionsTest(unittest.TestCase):
    def test_string_assumptions_rejected_at_validation(self):
        req = {**BASE, "scenario_assumptions": "abc"}
        v = FoodDomain().validate_inputs(req)
        self.assertFalse(v["ok"])
        self.assertTrue(any("scenario_assumptions" in p for p in v["problems"]))

    def test_int_assumptions_rejected_at_validation(self):
        req = {**BASE, "scenario_assumptions": 42}
        v = FoodDomain().validate_inputs(req)
        self.assertFalse(v["ok"])
        self.assertTrue(any("scenario_assumptions" in p for p in v["problems"]))

    def test_list_of_strings_accepted_and_kept_whole(self):
        req = {**BASE, "scenario_assumptions": ["abc", "def"]}
        self.assertTrue(FoodDomain().validate_inputs(req)["ok"])
        calc = FoodDomain().calculate(req)
        self.assertIn("abc", calc["assumptions"])
        self.assertNotIn("a", calc["assumptions"])


class Issue22VerifierToleranceTest(unittest.TestCase):
    def test_global_true_annual_gap(self):
        calc = FoodDomain().calculate(GLOBAL)
        # True annual gap, verified live: 1,451,605,000,000,000.0 kcal/yr.
        self.assertEqual(calc["metrics"]["annual_gap_or_surplus_kcal"], 1451605000000000.0)

    def test_plus_100k_tamper_at_global_scale_fails(self):
        domain = FoodDomain()
        calc = domain.calculate(GLOBAL)
        ev = domain.evaluate(calc)
        tampered = dict(calc)
        tampered["metrics"] = dict(calc["metrics"])
        tampered["metrics"]["annual_gap_or_surplus_kcal"] += 100_000
        v = verify_domain_result("food", tampered, ev, GLOBAL)
        self.assertFalse(v["verified"])
        self.assertTrue(any("annual_gap_or_surplus_kcal" in i for i in v["issues"]))

    def test_untampered_global_still_verifies(self):
        domain = FoodDomain()
        calc = domain.calculate(GLOBAL)
        self.assertTrue(verify_domain_result("food", calc, domain.evaluate(calc), GLOBAL)["verified"])


class Issue23UnknownDomainShapeTest(unittest.TestCase):
    def test_run_unknown_domain_has_full_error_shape(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        r = engine.run("space", {})
        for key in ("domain", "calculation", "evaluation", "verification",
                    "limitations", "calculation_ok", "verified", "verified_ok", "ok"):
            self.assertIn(key, r, f"missing key {key}")
        self.assertEqual(r["calculation"]["calculation_status"], CalculationStatus.ERROR.value)
        self.assertEqual(r["evaluation"]["overall_status"], CheckStatus.NOT_CHECKED.value)
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["available_domains"], ["food"])
        self.assertTrue(r["needs_human_decision"])
        # The shape a caller relies on works on this path too.
        self.assertEqual(r["calculation"]["calculation_status"], "ERROR")

    def test_run_scenario_unknown_domain_matches_run_shape(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        s = Scenario("u", "U", metadata={"base_request": BASE})
        r = engine.run_scenario("space", s)
        self.assertEqual(r["calculation_status"], CalculationStatus.ERROR.value)
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["ok"])
        self.assertTrue(r["needs_human_decision"])
        self.assertIn("error", r)
        self.assertEqual(r["available_domains"], ["food"])


class Issue25FoodScenarioGeographyTest(unittest.TestCase):
    def test_base_geography_and_period_win(self):
        s = Scenario("s1", "x", metadata={"base_request": {**BASE, "geography": "real-place", "period": "2026-Q1"}})
        req = FoodDomain().scenario_request(s)
        self.assertEqual(req["geography"], "real-place")
        self.assertEqual(req["period"], "2026-Q1")

    def test_scenario_defaults_fill_missing_geography_period(self):
        s = Scenario("s1", "x", metadata={"base_request": BASE})
        req = FoodDomain().scenario_request(s)
        self.assertEqual(req["geography"], "unspecified")
        self.assertEqual(req["period"], "unspecified")


class Issue26NoRequestVerificationTest(unittest.TestCase):
    def test_food_verification_without_request_flags_missing_input(self):
        domain = FoodDomain()
        calc = domain.calculate(BASE)
        ev = domain.evaluate(calc)
        v = verify_domain_result("food", calc, ev)
        self.assertFalse(v["verified"])
        self.assertEqual(v["verification_status"], "FAILED")
        self.assertTrue(any("no request supplied; independent food arithmetic could not be performed" in i
                            for i in v["issues"]))

    def test_generic_verification_without_request_is_unchanged(self):
        # No independent arithmetic exists for generic domains, so no
        # spurious issue is recorded there.
        ev = {"overall_status": "PASS", "constraint_results": [{"constraint_id": "x", "status": "PASS"}]}
        v = verify_domain_result("other", {"calculation_status": "COMPLETED"}, ev)
        self.assertEqual(v["verification_status"], "PARTIALLY_VERIFIED")
        self.assertEqual(v["issues"], [])


class Issue28MisbehavingDomainTest(unittest.TestCase):
    def test_string_problems_coerced_not_crash(self):
        engine = PlanningEngine()
        engine.register(MisbehavingDomain())
        r = engine.run("stub", {})
        self.assertEqual(r["calculation"]["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)
        self.assertEqual(r["calculation"]["missing_fields"], ["oops-string"])
        self.assertEqual(r["calculation"]["assumptions"], ["also-a-string"])
        self.assertFalse(r["calculation_ok"])

    def test_non_string_problem_items_coerced(self):
        class Bad2(MisbehavingDomain):
            domain_id = "stub2"

            def validate_inputs(self, request):
                return {"ok": False, "problems": [42, None], "assumptions": []}

        engine = PlanningEngine()
        engine.register(Bad2())
        r = engine.run("stub2", {})
        self.assertEqual(r["calculation"]["missing_fields"], ["42", "None"])


class Issue29VerifierTypeCheckTest(unittest.TestCase):
    def test_bool_and_str_request_values_do_not_verify(self):
        domain = FoodDomain()
        calc = domain.calculate({**BASE, "population": 1})
        ev = domain.evaluate(calc)
        bad = {**BASE, "population": True, "supply_kcal_per_capita_per_day": "2800"}
        v = verify_domain_result("food", calc, ev, bad)
        self.assertFalse(v["verified"])
        self.assertTrue(any("must be a number" in i for i in v["issues"]))

    def test_fractional_population_request_does_not_verify(self):
        domain = FoodDomain()
        calc = domain.calculate(BASE)
        ev = domain.evaluate(calc)
        bad = {**BASE, "population": 100000.5}
        v = verify_domain_result("food", calc, ev, bad)
        self.assertFalse(v["verified"])

    def test_fully_stated_valid_request_still_verifies(self):
        domain = FoodDomain()
        calc = domain.calculate(BASE)
        self.assertTrue(verify_domain_result("food", calc, domain.evaluate(calc), BASE)["verified"])


class Issue30ExactEqualityTest(unittest.TestCase):
    def test_eq_at_zero_tolerance_is_exact_float_equality(self):
        # Documented behaviour (see Constraint docstring): 0.1 + 0.2 is
        # 0.30000000000000004, not 0.3, so == at tolerance 0.0 FAILS.
        c = Constraint(constraint_id="c", name="c", operator="==", bound=0.3)
        self.assertEqual(c.evaluate(0.1 + 0.2), CheckStatus.FAIL)

    def test_eq_with_explicit_tolerance_passes(self):
        c = Constraint(constraint_id="c", name="c", operator="==", bound=0.3, tolerance=1e-9)
        self.assertEqual(c.evaluate(0.1 + 0.2), CheckStatus.PASS)


class Issue33GenericScenarioAllowListTest(unittest.TestCase):
    def test_generic_rejects_injected_key(self):
        s = Scenario("s1", "x", proposed_changes={"population": 5, "__injected__": 1.0},
                     metadata={"base_request": {}})
        with self.assertRaises(ValueError) as ctx:
            GenericDomain().scenario_request(s)
        self.assertIn("__injected__", str(ctx.exception))

    def test_generic_rejects_any_undeclared_change(self):
        s = Scenario("s1", "x", proposed_changes={"population": 5}, metadata={"base_request": {}})
        with self.assertRaises(ValueError):
            GenericDomain().scenario_request(s)

    def test_food_rejects_injected_key_the_same_way(self):
        s = Scenario("s1", "x", proposed_changes={"__injected__": 1.0},
                     metadata={"base_request": BASE})
        with self.assertRaises(ValueError) as ctx:
            FoodDomain().scenario_request(s)
        self.assertIn("__injected__", str(ctx.exception))


class Issue35ToleranceSurfacingTest(unittest.TestCase):
    def test_tolerance_can_flip_fail_to_pass(self):
        c0 = Constraint(constraint_id="p", name="p", operator="<=", bound=6.2)
        c5 = Constraint(constraint_id="p", name="p", operator="<=", bound=6.2, tolerance=0.5)
        self.assertEqual(c0.evaluate(6.5), CheckStatus.FAIL)
        self.assertEqual(c5.evaluate(6.5), CheckStatus.PASS)

    def test_food_row_surfaces_tolerance_and_no_flip_by_default(self):
        calc = FoodDomain().calculate(BASE)
        row = evaluate_food_result(calc)["constraint_results"][0]
        self.assertEqual(row["tolerance"], 0.0)
        self.assertEqual(row["verdict_without_tolerance"], "PASS")
        self.assertFalse(row["tolerance_changed_verdict"])

    def test_food_row_warns_when_tolerance_flips_verdict(self):
        short = {**BASE, "supply_kcal_per_capita_per_day": 2400,
                 "imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0}
        calc = FoodDomain().calculate(short)
        plain = evaluate_food_result(calc)
        self.assertEqual(plain["constraint_results"][0]["status"], "FAIL")
        flipped = evaluate_food_result(calc, tolerance=100)
        row = flipped["constraint_results"][0]
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["tolerance"], 100)
        self.assertEqual(row["verdict_without_tolerance"], "FAIL")
        self.assertTrue(row["tolerance_changed_verdict"])
        self.assertTrue(any("Tolerance 100 changed the verdict" in w for w in flipped["warnings"]))


class Issue36SyntheticLabellingTest(unittest.TestCase):
    def test_synth_source_ids_labelled_synthetic(self):
        calc = FoodDomain().calculate({**BASE, "source_ids": ["SYNTH-example"]})
        self.assertEqual(calc["data_status"], "synthetic")
        self.assertTrue(any("synthetic" in lim.lower() for lim in calc["limitations"]))

    def test_unmarked_sources_are_unknown_not_observed(self):
        calc = FoodDomain().calculate({**BASE, "source_ids": ["real-source"]})
        self.assertEqual(calc["data_status"], "unknown")
        calc2 = FoodDomain().calculate(BASE)
        self.assertEqual(calc2["data_status"], "unknown")

    def test_low_level_labelling_agrees(self):
        r = food_availability(100, 2800, 2500, 0.0, 0.0, source_ids=["synth-pilot-1"])
        self.assertEqual(r["data_status"], "synthetic")


class Issue38ScenarioStrictnessTest(unittest.TestCase):
    def test_generic_and_food_reject_unknown_fields_alike(self):
        for domain, base in ((GenericDomain(), {}), (FoodDomain(), BASE)):
            with self.subTest(domain=domain.domain_id):
                s = Scenario("s1", "x", proposed_changes={"unknown_field": 1.0},
                             metadata={"base_request": base})
                with self.assertRaises(ValueError):
                    domain.scenario_request(s)

    def test_declared_field_is_permitted_for_generic_domain(self):
        s = Scenario("s1", "x", proposed_changes={"population": 5},
                     metadata={"base_request": {}})
        req = DeclaringDomain().scenario_request(s)
        self.assertEqual(req["population"], 5)
        self.assertNotIn("__injected__", req)

    def test_food_declared_fields_still_work(self):
        s = Scenario("s1", "x", proposed_changes={"supply_kcal_per_capita_per_day": 3100},
                     metadata={"base_request": BASE})
        req = FoodDomain().scenario_request(s)
        self.assertEqual(req["supply_kcal_per_capita_per_day"], 3100)


class Issue43CanonicalFormulaTest(unittest.TestCase):
    def test_production_and_verifier_agree_exactly(self):
        req = {"population": 100, "supply_kcal_per_capita_per_day": 2000,
               "requirement_kcal_per_capita_per_day": 1800,
               "imports_kcal_per_capita_per_day": 100, "losses_fraction": 0.08}
        prod = food_availability(**req)
        expected = _independently_recalculate_food(req)
        for key, value in expected.items():
            self.assertEqual(prod["metrics"][key], value, f"metric {key} differs")

    def test_none_imports_losses_refused_by_both_layers(self):
        # Second half of ISSUE-43: VERIFIED already-resolved by ISSUE-15
        # (no silent 0.0 defaulting anywhere); pinned, not re-fixed.
        self.assertEqual(food_availability(100, 2000, 1800)["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)
        req = {"population": 100, "supply_kcal_per_capita_per_day": 2000,
               "requirement_kcal_per_capita_per_day": 1800}
        self.assertEqual(FoodDomain().calculate(req)["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)


class Issue44ExampleGuardTest(unittest.TestCase):
    def test_importing_example_runs_nothing(self):
        proc = subprocess.run(
            [sys.executable, "-c", "import examples.food_balance; print('imported')"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "imported")

    def test_module_still_runs_the_same_way(self):
        proc = subprocess.run(
            [sys.executable, "-m", "examples.food_balance"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("COMPLETED", proc.stdout)
        self.assertIn("2676.0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
