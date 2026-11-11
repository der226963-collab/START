"""ISSUE-12 + ISSUE-13 (2026-11-11): construction strictness and the
food validate-vs-calculate None mismatch. Review copy only, local.

ISSUE-12 rules pinned here (see contracts/constraints.py __post_init__
and evaluate() for the recorded rules):
 (a) empty/whitespace constraint_id or name raises at construction.
 (b) missing bounds for the declared operator raise at construction;
     the only exception is an explicitly declared boundless=True
     constraint (bound must be None), which evaluates UNKNOWN by
     design — nitrogen (plan_limits, ISSUE-18) and an unstated food
     requirement are the only boundless cases in this tree.
 (c) a unit-less constraint may only be evaluated with NO value_unit
     supplied; a known value_unit supplied raises ValueError instead
     of a silent raw-number PASS. Unknown/empty/non-string value_unit
     still returns UNKNOWN.
 (d) population must be a whole number (bool and fractional floats
     rejected; integer-valued floats accepted, e.g. 8.2e9).
 (e) unknown request fields are REJECTED (validate ok False), not
     warned: no caller in this tree depends on extra fields (checked
     by grep before enforcing), so rejection cannot break a real
     caller and a warning would leave a misspelled field silently
     computing with the intended value missing.
 (f) Resource quantities must be non-negative when present; None
     (unknown) stays allowed. No Resource in this tree represents a
     signed balance — those are metrics, not Resources. Stock/Flow
     negativity is ISSUE-31's job; the intended rule for them is the
     same (see contracts/resources.py).
ISSUE-13: SUPERSEDED by ISSUE-15 (2026-11-11). ISSUE-13 made an
explicit None optional (imports/losses) validate as "assumed 0.0"
and had calculate() normalise it to that default, so the recorded
assumption was true. ISSUE-15 removes that policy entirely: imports/
losses are required stated inputs, missing or explicit None fails
validation, and the None -> 0.0 normalisation is removed from
calculate() and engine/verification.py (decision (b) — treating None
as missing everywhere; see tests/test_issue15_food_formula.py and
docs/BREAKING_CHANGES.md, ISSUE-15 section). The tests below are
updated to pin the NEW behaviour; the old expectations (ok=True,
COMPLETED, surplus 300.0 from a None) are preserved here only as
the superseded record in the test names/docstrings, not asserted.
"""
from __future__ import annotations
import unittest

from contracts.constraints import Constraint
from contracts.resources import Resource, Stock, Flow
from contracts.statuses import CheckStatus
from contracts.plan_limits import load_plan_limits, check_plan_limits
from contracts.models import check_plan_limits_typed
from domains.food import FoodDomain
from domains.food.production import default_food_constraints, food_availability
from engine.planning_engine import PlanningEngine

BASE = {"population": 1000, "supply_kcal_per_capita_per_day": 2800,
        "requirement_kcal_per_capita_per_day": 2500,
        "imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0}


class Issue12ConstraintConstructionTest(unittest.TestCase):
    def test_empty_id_and_name_raise(self):
        for cid, name in (("", "x"), ("   ", "x"), (None, "x"),
                          ("c", ""), ("c", "   "), ("c", None)):
            with self.subTest(cid=repr(cid), name=repr(name)):
                with self.assertRaises(ValueError):
                    Constraint(cid, name, operator="<=", bound=10, unit="kg")

    def test_missing_bound_raises_for_each_operator(self):
        for operator in ("<=", ">=", "=="):
            with self.subTest(operator=operator):
                with self.assertRaises(ValueError):
                    Constraint("c", "x", operator=operator, unit="kg")

    def test_range_missing_either_bound_raises(self):
        with self.assertRaises(ValueError):
            Constraint("r", "x", operator="range", unit="L")
        with self.assertRaises(ValueError):
            Constraint("r", "x", operator="range", bound_low=2, unit="L")
        with self.assertRaises(ValueError):
            Constraint("r", "x", operator="range", bound_high=8, unit="L")

    def test_boundless_must_be_explicit_and_bound_must_be_none(self):
        with self.assertRaises(ValueError):  # bound supplied + boundless
            Constraint("c", "x", operator="<=", bound=10, unit="kg",
                       boundless=True)
        with self.assertRaises(ValueError):  # range can never be boundless
            Constraint("r", "x", operator="range", unit="L", boundless=True)
        boundless = Constraint("c", "x", operator="<=", unit="kg",
                               boundless=True)
        self.assertEqual(boundless.evaluate(5, "kg"), CheckStatus.UNKNOWN)

    def test_valid_constraints_still_construct_and_evaluate(self):
        c = Constraint("c", "x", operator="<=", bound=10, unit="kg")
        self.assertEqual(c.evaluate(5, "kg"), CheckStatus.PASS)
        self.assertEqual(c.evaluate(12, "kg"), CheckStatus.FAIL)
        r = Constraint("r", "x", operator="range", bound_low=2,
                       bound_high=8, unit="L")
        self.assertEqual(r.evaluate(5, "L"), CheckStatus.PASS)

    def test_plan_limits_and_typed_path_still_construct(self):
        # Nitrogen is the intentional boundless case; the typed path
        # and the other stored constraints must still construct.
        limits = load_plan_limits()
        nitrogen = limits.constraint("nitrogen_fixation_tg_per_year")
        self.assertTrue(nitrogen.boundless)
        self.assertIsNone(nitrogen.bound)
        self.assertEqual(nitrogen.evaluate(165), CheckStatus.UNKNOWN)
        result = check_plan_limits(
            {"nitrogen_fixation_tg_per_year": 165,
             "phosphorus_application_tg_per_year": 5.0})
        self.assertEqual(
            [c for c in result["checks"]
             if c["constraint_id"] == "nitrogen_fixation_tg_per_year"][0]["status"],
            "UNKNOWN")
        typed = check_plan_limits_typed(
            {"nitrogen_fixation_tg_per_year": 165,
             "phosphorus_application_tg_per_year": 5.0})
        self.assertEqual(typed.overall_status, CheckStatus.UNKNOWN)

    def test_unstated_food_requirement_is_boundless_unknown(self):
        c = default_food_constraints(None)[0]
        self.assertTrue(c.boundless)
        self.assertEqual(c.evaluate(2800, "kcal/capita/day"),
                         CheckStatus.UNKNOWN)
        c2 = default_food_constraints(2500)[0]
        self.assertFalse(c2.boundless)
        self.assertEqual(c2.evaluate(2800, "kcal/capita/day"),
                         CheckStatus.PASS)


class Issue12UnitlessEvaluationTest(unittest.TestCase):
    def test_unitless_with_supplied_known_unit_raises(self):
        c = Constraint("c", "x", operator="<=", bound=10, unit="")
        with self.assertRaises(ValueError):
            c.evaluate(5, "kg")

    def test_unitless_without_unit_still_compares_raw(self):
        # Plan-limits phosphorus/work-hours constraints rely on this:
        # unit-less, no value_unit supplied -> raw comparison.
        c = Constraint("c", "x", operator="<=", bound=10, unit="")
        self.assertEqual(c.evaluate(5), CheckStatus.PASS)
        self.assertEqual(c.evaluate(12), CheckStatus.FAIL)

    def test_unitless_with_unknown_or_empty_unit_is_unknown(self):
        c = Constraint("c", "x", operator="<=", bound=10, unit="")
        self.assertEqual(c.evaluate(5, "bucket"), CheckStatus.UNKNOWN)
        self.assertEqual(c.evaluate(5, ""), CheckStatus.UNKNOWN)
        self.assertEqual(c.evaluate(5, 5), CheckStatus.UNKNOWN)


class Issue12ResourceTest(unittest.TestCase):
    def test_negative_resource_quantity_raises(self):
        with self.assertRaises(ValueError):
            Resource("g", "food", -5, "kg")
        with self.assertRaises(ValueError):
            Resource("g", "food", -0.001, "kg")

    def test_zero_none_and_positive_resource_quantities_allowed(self):
        self.assertEqual(Resource("g", "food", 0, "kg").quantity, 0)
        self.assertIsNone(Resource("g", "food", None, "kg").quantity)
        self.assertEqual(Resource("g", "food", 5, "kg").quantity, 5)

    def test_stock_flow_negativity_now_rejected(self):
        # ISSUE-31 (2026-11-11) landed: Stock/Flow negativity is now
        # rejected, same rule as Resource. This test used to pin the
        # old behaviour (negative Stock/Flow constructing fine) with
        # a note that ISSUE-31 owned the change; it now pins the new
        # behaviour instead.
        with self.assertRaises(ValueError):
            Stock("s", "g", -5, "kg", "2026")
        with self.assertRaises(ValueError):
            Flow("f", "g", -5, "kg", "2026")
        self.assertEqual(Stock("s", "g", 0, "kg", "2026").quantity, 0)
        self.assertIsNone(Flow("f", "g", None, "kg", "2026").quantity)


class Issue12FoodValidationTest(unittest.TestCase):
    def setUp(self):
        self.domain = FoodDomain()

    def test_fractional_population_rejected(self):
        v = self.domain.validate_inputs({**BASE, "population": 1000.5})
        self.assertFalse(v["ok"])
        self.assertTrue(any("whole number" in p for p in v["problems"]))

    def test_bool_population_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                self.assertFalse(
                    self.domain.validate_inputs({**BASE, "population": bad})["ok"])

    def test_integer_valued_population_accepted(self):
        self.assertTrue(self.domain.validate_inputs({**BASE, "population": 1000})["ok"])
        self.assertTrue(self.domain.validate_inputs({**BASE, "population": 1000.0})["ok"])
        self.assertTrue(self.domain.validate_inputs(
            {**BASE, "population": 8.2e9})["ok"])
        # Snapshot-derived: 8.2 (bn, from CSV) * 1e9 in float is
        # 8199999999.999999, a whole number within float error.
        self.assertTrue(self.domain.validate_inputs(
            {**BASE, "population": 8199999999.999999})["ok"])

    def test_low_level_fractional_population_is_error(self):
        r = food_availability(1000.5, 2800, 2500, 0.0, 0.0)
        self.assertEqual(r["calculation_status"], "ERROR")

    def test_unknown_fields_rejected(self):
        v = self.domain.validate_inputs(
            {**BASE, "suply_kcal_per_capita_per_day": 9999, "typo": 1})
        self.assertFalse(v["ok"])
        self.assertTrue(any("suply_kcal_per_capita_per_day" in p for p in v["problems"]))
        self.assertTrue(any("typo" in p for p in v["problems"]))

    def test_known_fields_still_validate(self):
        # Every field a real caller passes (examples, scenarios,
        # engine runs) must still be accepted.
        req = {**BASE, "geography": "global", "period": "2022",
               "source_ids": ["s"], "scenario_assumptions": ["a"],
               "scenario_id": "s1"}
        self.assertTrue(self.domain.validate_inputs(req)["ok"])

    def test_engine_rejects_misspelled_field_instead_of_silently_using_default(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        r = engine.run("food", {**BASE, "suply_kcal_per_capita_per_day": 9999,
                                "typo": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["calculation"]["calculation_status"],
                         "INSUFFICIENT_INPUT")


class Issue13NoneMismatchTest(unittest.TestCase):
    """ISSUE-13 tests, SUPERSEDED by ISSUE-15 (2026-11-11).

    The old versions of these tests asserted that an explicit None
    imports/losses validated ok=True as "assumed 0.0" and calculated
    COMPLETED with surplus 300.0. That policy is removed: None is
    now treated as missing everywhere (decision (b) — the ISSUE-13
    normalisation in calculate()/verification.py is deleted, not
    kept as a backstop). These tests now pin the new behaviour.
    """

    def setUp(self):
        self.domain = FoodDomain()

    def _req(self, **overrides):
        req = {"population": 1000, "supply_kcal_per_capita_per_day": 2800,
               "requirement_kcal_per_capita_per_day": 2500,
               "imports_kcal_per_capita_per_day": None,
               "losses_fraction": 0.0}
        req.update(overrides)
        return req

    def test_issue_repro_imports_none(self):
        # Was: ok=True, "assumed to be 0.0", COMPLETED, surplus 300.0.
        # Now: missing required field, INSUFFICIENT_INPUT, no silent 0.0.
        req = self._req()
        validation = self.domain.validate_inputs(req)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("missing required field: imports_kcal_per_capita_per_day" in p
                            for p in validation["problems"]))
        self.assertNotIn("assumed to be 0.0", " ".join(validation["assumptions"]))
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"], "INSUFFICIENT_INPUT")

    def test_losses_none(self):
        req = self._req(imports_kcal_per_capita_per_day=0.0,
                        losses_fraction=None)
        self.assertFalse(self.domain.validate_inputs(req)["ok"])
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"], "INSUFFICIENT_INPUT")

    def test_both_none(self):
        req = self._req(losses_fraction=None)
        self.assertFalse(self.domain.validate_inputs(req)["ok"])
        calc = self.domain.calculate(req)
        self.assertEqual(calc["calculation_status"], "INSUFFICIENT_INPUT")

    def test_none_optionals_verify_through_engine(self):
        # Was: engine ok=True, verified=True, PASS. Now the engine
        # refuses the request at validation: not ok, INSUFFICIENT_INPUT.
        engine = PlanningEngine()
        engine.register(FoodDomain())
        r = engine.run("food", self._req())
        self.assertFalse(r["ok"])
        self.assertEqual(r["calculation"]["calculation_status"],
                         "INSUFFICIENT_INPUT")
        self.assertFalse(r["verification"]["verified"])

    def test_low_level_still_refuses_missing_optionals(self):
        # food_availability itself is unchanged: None means missing
        # there. The domain layer now agrees with it instead of
        # normalising None to the (removed) assumed default.
        r = food_availability(100, 2000, 1800)
        self.assertEqual(r["calculation_status"], "INSUFFICIENT_INPUT")
        self.assertIn("imports_kcal_per_capita_per_day", r["missing_fields"])


if __name__ == "__main__":
    unittest.main()
