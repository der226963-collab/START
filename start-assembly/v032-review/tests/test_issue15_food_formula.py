"""ISSUE-15 (2026-11-11): food formula change documented + losses/imports
must be stated, never silently zero. Review copy only, local.

v0.3.1 (``mini_ai/planning.py: food_balance()``): ``surplus = supply -
need``, no losses/imports. v0.3.2 (``domains/food/production.py``):
``effective = supply * (1 - losses)``, ``total = effective + imports``,
``surplus = total - requirement``. Verified live at fix time:

- v0.3.1 2985/2500 -> 485.0; v0.3.1 2800/2500 -> 300.
- v0.3.2 2800/2500, imports 100, losses 0.08 -> total 2676.0, surplus 176.0.
- v0.3.2 2985/2500, explicitly stated 0/0 -> 485.0 (the formulas agree
  ONLY at losses 0 / imports 0).

The old v0.3.1 formula is reproduced here arithmetically
(``supply - need``), not by calling the read-only v0.3.1 source, to
document the difference — the test asserts the two formulas DIFFER
on 2800/2500, not that they agree.
"""
from __future__ import annotations
import unittest

from contracts.statuses import CalculationStatus
from domains.food import FoodDomain
from domains.food.production import food_availability
from engine.planning_engine import PlanningEngine
from engine.verification import verify_domain_result


def v031_surplus(supply, need):
    """v0.3.1 formula, arithmetic only: surplus = supply - need."""
    return supply - need


BASE = {"population": 1000, "supply_kcal_per_capita_per_day": 2800,
        "requirement_kcal_per_capita_per_day": 2500,
        "imports_kcal_per_capita_per_day": 100, "losses_fraction": 0.08}


class Issue15StatedInputsTest(unittest.TestCase):
    def setUp(self):
        self.domain = FoodDomain()

    def test_omitting_imports_fails_validation(self):
        req = {k: v for k, v in BASE.items()
               if k != "imports_kcal_per_capita_per_day"}
        validation = self.domain.validate_inputs(req)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("missing required field: imports_kcal_per_capita_per_day" in p
                            for p in validation["problems"]))
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)

    def test_omitting_losses_fails_validation(self):
        req = {k: v for k, v in BASE.items() if k != "losses_fraction"}
        validation = self.domain.validate_inputs(req)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("missing required field: losses_fraction" in p
                            for p in validation["problems"]))
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)

    def test_explicit_none_imports_fails_validation(self):
        req = {**BASE, "imports_kcal_per_capita_per_day": None}
        self.assertFalse(self.domain.validate_inputs(req)["ok"])
        self.assertEqual(self.domain.calculate(req)["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)

    def test_explicit_none_losses_fails_validation(self):
        req = {**BASE, "losses_fraction": None}
        self.assertFalse(self.domain.validate_inputs(req)["ok"])
        self.assertEqual(self.domain.calculate(req)["calculation_status"],
                         CalculationStatus.INSUFFICIENT_INPUT.value)

    def test_engine_run_omitting_imports_is_not_ok(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        req = {k: v for k, v in BASE.items()
               if k != "imports_kcal_per_capita_per_day"}
        r = engine.run("food", req)
        self.assertFalse(r["ok"])
        self.assertEqual(r["calculation"]["calculation_status"],
                         "INSUFFICIENT_INPUT")

    def test_no_silent_zero_assumption_recorded(self):
        # The removed policy recorded "assumed to be 0.0"; no such
        # assumption may appear for a request that states both fields,
        # and omitting them must fail rather than assume.
        validation = self.domain.validate_inputs(BASE)
        self.assertTrue(validation["ok"])
        self.assertNotIn("assumed to be 0.0", " ".join(validation["assumptions"]))
        omitted = {k: v for k, v in BASE.items()
                   if k != "imports_kcal_per_capita_per_day"}
        self.assertNotIn("assumed to be 0.0",
                         " ".join(self.domain.validate_inputs(omitted)["assumptions"]))


class Issue15WorkedNumbersTest(unittest.TestCase):
    def setUp(self):
        self.domain = FoodDomain()

    def test_stated_zero_zero_reproduces_485(self):
        # ISSUE-01 global-balance reproduction: the formulas agree
        # only at losses 0 / imports 0, stated explicitly.
        req = {"population": 1000, "supply_kcal_per_capita_per_day": 2985,
               "requirement_kcal_per_capita_per_day": 2500,
               "imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0}
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"], CalculationStatus.COMPLETED.value)
        self.assertAlmostEqual(calc["metrics"]["total_available_kcal_per_capita_per_day"], 2985.0)
        self.assertAlmostEqual(calc["metrics"]["surplus_kcal_per_capita_per_day"], 485.0)

    def test_stated_100_and_008_gives_176(self):
        calc = self.domain.calculate(BASE)
        self.assertEqual(calc["calculation_status"], CalculationStatus.COMPLETED.value)
        self.assertAlmostEqual(calc["metrics"]["effective_supply_after_losses"], 2576.0)
        self.assertAlmostEqual(calc["metrics"]["total_available_kcal_per_capita_per_day"], 2676.0)
        self.assertAlmostEqual(calc["metrics"]["surplus_kcal_per_capita_per_day"], 176.0)

    def test_old_v031_formula_on_2800_2500_gives_300_not_176(self):
        # Documents the difference: the old formula gives 300 on the
        # same 2800/2500 inputs that give 176.0 under v0.3.2 with
        # imports 100 / losses 0.08. Asserting inequality, not equality.
        self.assertEqual(v031_surplus(2800, 2500), 300)
        calc = self.domain.calculate(BASE)
        self.assertAlmostEqual(calc["metrics"]["surplus_kcal_per_capita_per_day"], 176.0)
        self.assertNotEqual(v031_surplus(2800, 2500),
                            calc["metrics"]["surplus_kcal_per_capita_per_day"])

    def test_old_and_new_agree_only_at_zero_zero(self):
        self.assertEqual(v031_surplus(2985, 2500), 485.0)
        req = {"population": 1000, "supply_kcal_per_capita_per_day": 2985,
               "requirement_kcal_per_capita_per_day": 2500,
               "imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0}
        self.assertAlmostEqual(
            self.domain.calculate(req)["metrics"]["surplus_kcal_per_capita_per_day"], 485.0)


class Issue15LowLevelAndVerifierTest(unittest.TestCase):
    def test_low_level_still_refuses_none_or_missing_optionals(self):
        # food_availability() is unchanged by ISSUE-15: None/missing
        # imports/losses -> INSUFFICIENT_INPUT, never a silent 0.0.
        # The domain layer now agrees with it instead of normalising
        # around it (ISSUE-13 normalisation removed, decision (b)).
        r = food_availability(100, 2000, 1800)
        self.assertEqual(r["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)
        self.assertIn("imports_kcal_per_capita_per_day", r["missing_fields"])
        self.assertIn("losses_fraction", r["missing_fields"])
        r = food_availability(100, 2000, 1800, None, 0.0)
        self.assertEqual(r["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)

    def test_verifier_does_not_silently_assume_zero(self):
        # A calculation verified against a request that omits imports
        # must NOT verify against an assumed 0.0: the independent
        # recalculation now fails with an issue instead.
        domain = FoodDomain()
        calc = domain.calculate(BASE)
        ev = domain.evaluate(calc)
        incomplete = {k: v for k, v in BASE.items()
                      if k != "imports_kcal_per_capita_per_day"}
        v = verify_domain_result("food", calc, ev, incomplete)
        self.assertFalse(v["verified"])
        self.assertTrue(any("recalculation could not be completed" in i
                            for i in v["issues"]))
        none_req = {**BASE, "imports_kcal_per_capita_per_day": None}
        v = verify_domain_result("food", calc, ev, none_req)
        self.assertFalse(v["verified"])

    def test_verifier_still_verifies_fully_stated_request(self):
        domain = FoodDomain()
        calc = domain.calculate(BASE)
        ev = domain.evaluate(calc)
        self.assertTrue(verify_domain_result("food", calc, ev, BASE)["verified"])


if __name__ == "__main__":
    unittest.main()
