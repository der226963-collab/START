"""REVIEW.md ISSUE-14 + ISSUE-37 — result semantics.

ISSUE-14: needs_human_decision=True is frozen at the type level on
ScenarioResult (no False construction, no post-construction flip, no
bogus calculation_status). PlanningResult carries neither field, so
there is no second unguarded path — asserted here so a future
addition of such a field is caught by review, not silently trusted.

ISSUE-37: engine ``ok`` split into calculation_ok / verified /
verified_ok, with ``ok`` kept as a deprecated alias for verified_ok.
A completed calculation in a domain with no independent verifier must
be distinguishable from a failed calculation.
"""
import unittest
from dataclasses import FrozenInstanceError

from contracts.scenarios import Scenario, ScenarioResult
from contracts.statuses import CalculationStatus
from contracts.models import PlanningResult, ConstraintResult, InternalStatus
from domains.base import DomainModule
from domains.food import FoodDomain
from engine.planning_engine import PlanningEngine

BASE = {
    "population": 100000,
    "supply_kcal_per_capita_per_day": 2800,
    "requirement_kcal_per_capita_per_day": 2500,
    "imports_kcal_per_capita_per_day": 100,
    "losses_fraction": 0.08,
}


class GenericDomain(DomainModule):
    """A correct domain with no independent verifier (cf. ISSUE-37)."""
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


class TestIssue14ScenarioResultFrozen(unittest.TestCase):
    def test_bogus_calculation_status_rejected(self):
        with self.assertRaises(ValueError):
            ScenarioResult("s", "food", calculation_status="BOGUS")

    def test_lowercase_status_rejected(self):
        with self.assertRaises(ValueError):
            ScenarioResult("s", "food", calculation_status="completed")

    def test_non_string_status_rejected(self):
        with self.assertRaises(ValueError):
            ScenarioResult("s", "food", calculation_status=42)

    def test_needs_human_decision_false_rejected(self):
        with self.assertRaises(ValueError):
            ScenarioResult("s", "food", needs_human_decision=False)

    def test_needs_human_decision_truthy_non_true_rejected(self):
        # `1` is truthy but is not True; the freeze is exact.
        with self.assertRaises(ValueError):
            ScenarioResult("s", "food", needs_human_decision=1)

    def test_every_valid_status_accepted(self):
        for status in CalculationStatus:
            r = ScenarioResult("s", "food", calculation_status=status)
            self.assertEqual(r.calculation_status, status.value)
            r2 = ScenarioResult("s", "food", calculation_status=status.value)
            self.assertEqual(r2.calculation_status, status.value)

    def test_default_is_true_and_not_run(self):
        r = ScenarioResult("s", "food")
        self.assertIs(r.needs_human_decision, True)
        self.assertEqual(r.calculation_status, "NOT_RUN")
        self.assertTrue(r.to_dict()["needs_human_decision"])

    def test_flag_cannot_be_flipped_after_construction(self):
        r = ScenarioResult("s", "food")
        with self.assertRaises(FrozenInstanceError):
            r.needs_human_decision = False
        with self.assertRaises(FrozenInstanceError):
            r.calculation_status = "BOGUS"

    def test_engine_always_sets_true(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        r = engine.run("food", BASE)
        self.assertTrue(r["needs_human_decision"])
        s = Scenario("s1", "S", metadata={"base_request": BASE})
        rs = engine.run_scenario("food", s)
        self.assertTrue(rs["needs_human_decision"])
        self.assertEqual(rs["calculation_status"], "COMPLETED")

    def test_direct_domain_scenario_helper_still_true(self):
        s = Scenario("direct", "Direct", metadata={"base_request": BASE})
        r = FoodDomain().run_scenario(s)
        self.assertTrue(r.needs_human_decision)
        self.assertFalse(r.verification.get("verified"))

    def test_planning_result_carries_no_human_decision_claim(self):
        # ISSUE-14 second-path check: PlanningResult has no
        # needs_human_decision field and no calculation_status, so it
        # cannot claim no human decision is needed. Its `passes` means
        # only "no checked limit was breached", never "approved".
        r = PlanningResult("s", [ConstraintResult("p", InternalStatus.PASS, "ok")])
        self.assertTrue(r.passes)
        self.assertNotIn("needs_human_decision", r.to_dict())
        self.assertNotIn("calculation_status", r.to_dict())
        self.assertFalse(hasattr(r, "needs_human_decision"))


class TestIssue37EngineOkSplit(unittest.TestCase):
    def setUp(self):
        self.engine = PlanningEngine()
        self.engine.register(FoodDomain())
        self.engine.register(GenericDomain())

    def test_generic_completed_calculation_is_distinguishable_from_failure(self):
        r = self.engine.run("generic", {})
        self.assertEqual(r["calculation"]["calculation_status"], "COMPLETED")
        self.assertEqual(r["evaluation"]["overall_status"], "PASS")
        self.assertEqual(r["verification"]["verification_status"], "PARTIALLY_VERIFIED")
        self.assertTrue(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        # Deprecated alias keeps its old meaning (completed AND verified).
        self.assertFalse(r["ok"])
        self.assertEqual(r["ok"], r["verified_ok"])
        self.assertTrue(r["needs_human_decision"])

    def test_food_happy_path_is_calculation_ok_and_verified(self):
        r = self.engine.run("food", BASE)
        self.assertTrue(r["calculation_ok"])
        self.assertTrue(r["verified"])
        self.assertTrue(r["verified_ok"])
        self.assertTrue(r["ok"])

    def test_failed_calculation_has_calculation_ok_false(self):
        r = self.engine.run("food", {"population": 100})
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["calculation"]["calculation_status"], "INSUFFICIENT_INPUT")

    def test_unknown_domain_flags_all_false(self):
        r = self.engine.run("space", {})
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        self.assertFalse(r["ok"])

    def test_broken_domain_error_result_flags(self):
        class Broken(FoodDomain):
            def calculate(self, request):
                raise RuntimeError("test crash")
        engine = PlanningEngine()
        engine.register(Broken())
        r = engine.run("food", BASE)
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["ok"])

    def test_run_scenario_generic_aligned_with_run(self):
        s = Scenario("g", "Generic", metadata={"base_request": {}})
        r = self.engine.run_scenario("generic", s)
        self.assertEqual(r["calculation_status"], "COMPLETED")
        self.assertTrue(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        self.assertFalse(r["ok"])
        self.assertTrue(r["needs_human_decision"])

    def test_run_scenario_food_verified(self):
        s = Scenario("f", "Food", metadata={"base_request": BASE})
        r = self.engine.run_scenario("food", s)
        self.assertTrue(r["calculation_ok"])
        self.assertTrue(r["verified"])
        self.assertTrue(r["verified_ok"])
        self.assertTrue(r["ok"])

    def test_run_scenario_unknown_domain_flags(self):
        s = Scenario("u", "U", metadata={"base_request": BASE})
        r = self.engine.run_scenario("space", s)
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["ok"])

    def test_run_scenario_exception_path_flags(self):
        class BadScenario:
            scenario_id = "bad"
        # scenario_request raises (no base_request) -> exception path.
        r = self.engine.run_scenario("food", BadScenario())
        self.assertEqual(r["calculation_status"], "ERROR")
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["ok"])
        self.assertTrue(r["needs_human_decision"])

    def test_compare_scenarios_splits_flags(self):
        scenarios = [
            Scenario("a", "A", metadata={"base_request": {}}),
            Scenario("b", "B", metadata={"base_request": {}}),
        ]
        r = self.engine.compare_scenarios("generic", scenarios)
        # Every scenario completed, none independently verified.
        self.assertTrue(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["verified_ok"])
        self.assertFalse(r["ok"])
        self.assertIsNone(r["selection"])

    def test_compare_scenarios_empty_flags(self):
        r = self.engine.compare_scenarios("food", [])
        self.assertFalse(r["calculation_ok"])
        self.assertFalse(r["verified"])
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
