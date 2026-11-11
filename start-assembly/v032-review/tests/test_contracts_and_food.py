"""Acceptance-oriented tests for START v0.3 corrected edition.

Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations
import math
import unittest
from contracts.statuses import CheckStatus, CalculationStatus, DataStatus, overall_from_checks
from contracts.resources import Resource, Stock, Flow
from contracts.constraints import Constraint, Objective
from contracts.units import convert, are_compatible
from contracts.scenarios import Scenario
from domains.food import FoodDomain
from domains.food.production import food_availability
from engine.planning_engine import PlanningEngine
from engine.verification import verify_domain_result


BASE = {"population": 1000, "supply_kcal_per_capita_per_day": 2800,
        "requirement_kcal_per_capita_per_day": 2500,
        "imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0}


class StatusTests(unittest.TestCase):
    def test_empty_checks_are_not_pass(self): self.assertEqual(overall_from_checks([]), CheckStatus.NOT_CHECKED)
    def test_fail_dominates(self): self.assertEqual(overall_from_checks([CheckStatus.PASS, CheckStatus.FAIL]), CheckStatus.FAIL)
    def test_unknown_dominates_pass(self): self.assertEqual(overall_from_checks([CheckStatus.PASS, CheckStatus.UNKNOWN]), CheckStatus.UNKNOWN)
    def test_incomplete_dominates_unknown(self): self.assertEqual(overall_from_checks([CheckStatus.UNKNOWN, CheckStatus.INCOMPLETE]), CheckStatus.INCOMPLETE)


class UnitsAndContractsTests(unittest.TestCase):
    def test_unit_conversion(self): self.assertAlmostEqual(convert(1, "tonne", "kg"), 1000)
    def test_incompatible_units_rejected(self): self.assertFalse(are_compatible("kg", "L"))
    def test_resource_known_is_not_verified(self):
        r = Resource("grain", "food", 10, "kg", status=DataStatus.OBSERVED)
        self.assertTrue(r.is_known()); self.assertFalse(r.is_verified())
    def test_resource_verified_explicitly(self):
        r = Resource("grain", "food", 10, "kg", status=DataStatus.VERIFIED)
        self.assertTrue(r.is_verified())
    def test_stock_requires_time(self):
        with self.assertRaises(ValueError): Stock("s", "grain", 10, "kg", "")
    def test_flow_requires_period(self):
        with self.assertRaises(ValueError): Flow("f", "grain", 10, "kg", "")
    def test_constraint_unit_conversion(self):
        c = Constraint("c", "mass cap", operator="<=", bound=1, unit="tonne")
        self.assertEqual(c.evaluate(1000, "kg"), CheckStatus.PASS)
    def test_constraint_unknown_incompatible_units(self):
        c = Constraint("c", "mass cap", operator="<=", bound=1, unit="tonne")
        self.assertEqual(c.evaluate(10, "L"), CheckStatus.UNKNOWN)
    def test_objective_validation(self):
        with self.assertRaises(ValueError): Objective("o", "bad", direction="sideways")


class FoodDomainTests(unittest.TestCase):
    def setUp(self): self.domain = FoodDomain()
    def test_missing_inputs_rejected(self): self.assertFalse(self.domain.validate_inputs({})["ok"])
    def test_completed_balance(self):
        r = self.domain.calculate({**BASE, "losses_fraction": 0.1, "supply_kcal_per_capita_per_day": 3000})
        self.assertEqual(r["calculation_status"], CalculationStatus.COMPLETED.value)
        self.assertAlmostEqual(r["metrics"]["effective_supply_after_losses"], 2700)
        self.assertEqual(self.domain.evaluate(r)["overall_status"], CheckStatus.PASS.value)
    def test_shortfall_fails(self):
        r = self.domain.calculate({**BASE, "supply_kcal_per_capita_per_day": 2000})
        self.assertEqual(self.domain.evaluate(r)["overall_status"], CheckStatus.FAIL.value)
    def test_missing_imports_or_losses_fail_validation(self):
        # ISSUE-15 (2026-11-11): imports/losses are REQUIRED, never
        # silently zero. This replaces the old
        # test_missing_optional_values_are_explicit_assumptions, which
        # pinned the removed "assumed 0.0" policy: omitting either
        # field used to validate ok=True with 2 assumptions; now it
        # fails validation and calculate() returns INSUFFICIENT_INPUT.
        for omitted in ("imports_kcal_per_capita_per_day", "losses_fraction"):
            req = {k: v for k, v in BASE.items() if k != omitted}
            validation = self.domain.validate_inputs(req)
            self.assertFalse(validation["ok"])
            self.assertTrue(any(f"missing required field: {omitted}" in p for p in validation["problems"]))
            self.assertEqual(self.domain.calculate(req)["calculation_status"],
                             CalculationStatus.INSUFFICIENT_INPUT.value)
        # Both omitted: both fields named as missing.
        req = {k: v for k, v in BASE.items() if k not in {"imports_kcal_per_capita_per_day", "losses_fraction"}}
        validation = self.domain.validate_inputs(req)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("imports_kcal_per_capita_per_day" in p for p in validation["problems"]))
        self.assertTrue(any("losses_fraction" in p for p in validation["problems"]))
    def test_boolean_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "population": True})["ok"])
    def test_nan_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "population": math.nan})["ok"])
    def test_infinity_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "supply_kcal_per_capita_per_day": math.inf})["ok"])
    def test_zero_population_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "population": 0})["ok"])
    def test_negative_imports_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "imports_kcal_per_capita_per_day": -1})["ok"])
    def test_invalid_loss_fraction_rejected(self): self.assertFalse(self.domain.validate_inputs({**BASE, "losses_fraction": 1.1})["ok"])
    def test_low_level_calculation_does_not_silently_default_optional_inputs(self):
        r = food_availability(100, 2000, 1800)
        self.assertEqual(r["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)
        self.assertIn("imports_kcal_per_capita_per_day", r["missing_fields"])
    def test_full_precision_used_for_evaluation(self):
        req = {**BASE, "supply_kcal_per_capita_per_day": 2499.996}
        calc = self.domain.calculate(req)
        self.assertEqual(self.domain.evaluate(calc)["overall_status"], CheckStatus.FAIL.value)
        self.assertEqual(calc["display_metrics"]["total_available_kcal_per_capita_per_day"], 2500.0)
    def test_failed_calculation_stays_incomplete(self):
        calc = self.domain.calculate({"population": 100})
        self.assertEqual(calc["calculation_status"], CalculationStatus.INSUFFICIENT_INPUT.value)
        self.assertEqual(self.domain.evaluate(calc)["overall_status"], CheckStatus.INCOMPLETE.value)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.domain = FoodDomain(); self.calc = self.domain.calculate(BASE); self.eval = self.domain.evaluate(self.calc)
    def test_food_arithmetic_independently_verified(self):
        v = verify_domain_result("food", self.calc, self.eval, BASE)
        self.assertTrue(v["verified"])
    def test_wrong_metric_fails_verification(self):
        bad = dict(self.calc); bad["metrics"] = dict(self.calc["metrics"]); bad["metrics"]["annual_gap_or_surplus_kcal"] += 1
        self.assertFalse(verify_domain_result("food", bad, self.eval, BASE)["verified"])
    def test_input_echo_mismatch_fails_verification(self):
        bad = dict(self.calc); bad["metrics"] = dict(self.calc["metrics"]); bad["metrics"]["population"] = 1
        self.assertFalse(verify_domain_result("food", bad, self.eval, BASE)["verified"])
    def test_claimed_status_must_match_all_checks(self):
        ev = {"overall_status": "FAIL", "constraint_results": [{"constraint_id": "x", "status": "PASS"}]}
        self.assertFalse(verify_domain_result("other", {"calculation_status": "COMPLETED"}, ev)["verified"])
    def test_invalid_status_not_ignored(self):
        ev = {"overall_status": "PASS", "constraint_results": [{"constraint_id": "x", "status": "MAYBE"}]}
        self.assertFalse(verify_domain_result("other", {"calculation_status": "COMPLETED"}, ev)["verified"])
    def test_empty_constraints_cannot_pass(self):
        ev = {"overall_status": "PASS", "constraint_results": []}
        self.assertFalse(verify_domain_result("other", {"calculation_status": "COMPLETED"}, ev)["verified"])
    def test_false_food_pass_detected(self):
        ev = {"overall_status": "PASS", "constraint_results": [{"constraint_id": "food_energy_adequacy", "status": "PASS"}]}
        low = {**BASE, "supply_kcal_per_capita_per_day": 100}
        calc = self.domain.calculate(low)
        self.assertFalse(verify_domain_result("food", calc, ev, low)["verified"])


class EngineAndScenarioTests(unittest.TestCase):
    def setUp(self):
        self.engine = PlanningEngine(); self.engine.register(FoodDomain())
    def test_unknown_domain(self):
        r = self.engine.run("space", {}); self.assertFalse(r["ok"]); self.assertTrue(r["needs_human_decision"])
    def test_food_happy_path(self):
        r = self.engine.run("food", BASE)
        self.assertTrue(r["ok"]); self.assertEqual(r["evaluation"]["overall_status"], "PASS")
        self.assertTrue(r["verification"]["verified"]); self.assertTrue(r["needs_human_decision"])
    def test_missing_inputs(self):
        r = self.engine.run("food", {"population": 100})
        self.assertFalse(r["ok"]); self.assertEqual(r["evaluation"]["overall_status"], "INCOMPLETE")
        self.assertFalse(r["verification"]["verified"])
    def test_calculation_exception_is_structured(self):
        class Broken(FoodDomain):
            def calculate(self, request): raise RuntimeError("test crash")
        engine = PlanningEngine(); engine.register(Broken())
        r = engine.run("food", BASE)
        self.assertFalse(r["ok"]); self.assertEqual(r["calculation"]["calculation_status"], "ERROR")
    def test_scenario_runs_from_baseline_and_overrides(self):
        s = Scenario("s1", "higher supply", proposed_changes={"supply_kcal_per_capita_per_day": 3100}, metadata={"base_request": BASE})
        r = self.engine.run_scenario("food", s)
        self.assertEqual(r["calculation_status"], "COMPLETED")
        self.assertTrue(r["verification"]["verified"])
        self.assertEqual(r["metrics"]["calculation"]["metrics"]["supply_kcal_per_capita_per_day"], 3100)
    def test_direct_domain_scenario_helper_does_not_claim_verification(self):
        s = Scenario("direct", "Direct", metadata={"base_request": BASE})
        r = FoodDomain().run_scenario(s)
        self.assertFalse(r.verification.get("verified"))
    def test_scenario_comparison_does_not_select(self):
        scenarios = [Scenario("a", "A", metadata={"base_request": BASE}), Scenario("b", "B", proposed_changes={"supply_kcal_per_capita_per_day": 2000}, metadata={"base_request": BASE})]
        r = self.engine.compare_scenarios("food", scenarios)
        self.assertIsNone(r["selection"]); self.assertEqual(len(r["results"]), 2)


class TestVectorDecisionsVolume(unittest.TestCase):
    """Decision 1 (2026-11-11): m3/L — CONVERT (Python's answer)."""

    def test_m3_to_litre_conversion_passes(self):
        c = Constraint("vol", "volume cap", operator="<=", bound=10, unit="L")
        self.assertEqual(c.evaluate(0.008, "m3"), CheckStatus.PASS)  # 0.008 m3 = 8 L

    def test_m3_to_litre_discriminating_fail(self):
        # Catches a no-conversion evaluator: 0.02 m3 = 20 L > 10 L, so FAIL;
        # without conversion 0.02 <= 10 would wrongly PASS.
        c = Constraint("vol", "volume cap", operator="<=", bound=10, unit="L")
        self.assertEqual(c.evaluate(0.02, "m3"), CheckStatus.FAIL)

    def test_litre_to_m3_other_direction(self):
        # The registry table already covers L -> m3 (same volume dimension).
        c = Constraint("vol", "volume cap", operator="<=", bound=0.01, unit="m3")
        self.assertEqual(c.evaluate(8, "L"), CheckStatus.PASS)   # 8 L = 0.008 m3
        self.assertEqual(c.evaluate(12, "L"), CheckStatus.FAIL)  # 12 L = 0.012 m3


class TestVectorDecisionsKcalDay(unittest.TestCase):
    """Decision 2 (2026-11-11): kcal/day — ADD TO PYTHON'S REGISTRY."""

    def test_kcal_per_day_passes(self):
        self.assertAlmostEqual(convert(1, "kcal/day", "kcal/capita/day"), 1.0)
        c = Constraint("kday", "energy adequacy", operator=">=", bound=2500, unit="kcal/day")
        self.assertEqual(c.evaluate(2800, "kcal/day"), CheckStatus.PASS)

    def test_kcal_per_day_below_bound_fails(self):
        c = Constraint("kday", "energy adequacy", operator=">=", bound=2500, unit="kcal/day")
        self.assertEqual(c.evaluate(2000, "kcal/day"), CheckStatus.FAIL)


class TestVectorDecisionsRange(unittest.TestCase):
    """Decision 3 (2026-11-11): range — ADD TO THE SCHEMA (+ bound_low/bound_high).

    Native behaviour (contracts/constraints.py): the range is INCLUSIVE,
    widened by tolerance on both sides.
    """

    def _range_constraint(self):
        return Constraint("rng", "range", operator="range", bound_low=2, bound_high=8, unit="L")

    def test_range_native_in_range_passes(self):
        self.assertEqual(self._range_constraint().evaluate(5, "L"), CheckStatus.PASS)

    def test_range_native_boundaries_pass_inclusive(self):
        c = self._range_constraint()
        self.assertEqual(c.evaluate(2, "L"), CheckStatus.PASS)
        self.assertEqual(c.evaluate(8, "L"), CheckStatus.PASS)

    def test_range_native_out_of_range_fails(self):
        c = self._range_constraint()
        self.assertEqual(c.evaluate(1, "L"), CheckStatus.FAIL)
        self.assertEqual(c.evaluate(9, "L"), CheckStatus.FAIL)

    def test_range_native_missing_bounds_raise_at_construction(self):
        # ISSUE-12 (2026-11-11): supersedes the ISSUE-07 / test-vector
        # pin that a range without bounds constructed fine and
        # evaluated UNKNOWN — missing range bounds are now a
        # construction error. A range can never be boundless.
        with self.assertRaises(ValueError):
            Constraint("rng", "range", operator="range", unit="L")
        with self.assertRaises(ValueError):
            Constraint("rng", "range", operator="range", bound_low=2, unit="L")

    def test_range_wire_request_accepted_and_evaluated(self):
        from adapters.python.contracts import validate_constraint_request, evaluate_constraint_request
        payload = {
            "schema_version": "1.0.0", "constraint_id": "rng", "operator": "range",
            "value": 5, "value_unit": "L", "bound_unit": "L",
            "bound_low": 2, "bound_high": 8, "tolerance": 0.0,
        }
        validate_constraint_request(payload)  # no "bound" key; must not raise
        self.assertEqual(evaluate_constraint_request(payload), CheckStatus.PASS)
        payload["value"] = 2
        self.assertEqual(evaluate_constraint_request(payload), CheckStatus.PASS)
        payload["value"] = 8
        self.assertEqual(evaluate_constraint_request(payload), CheckStatus.PASS)
        payload["value"] = 1
        self.assertEqual(evaluate_constraint_request(payload), CheckStatus.FAIL)
        payload["value"] = 9
        self.assertEqual(evaluate_constraint_request(payload), CheckStatus.FAIL)

    def test_range_wire_request_missing_bounds_rejected(self):
        from adapters.python.contracts import validate_constraint_request
        base = {
            "schema_version": "1.0.0", "constraint_id": "rng", "operator": "range",
            "value": 5, "value_unit": "L", "bound_unit": "L", "tolerance": 0.0,
        }
        for missing in ("bound_low", "bound_high"):
            payload = {**base, "bound_low": 2, "bound_high": 8}
            del payload[missing]
            with self.assertRaises(ValueError):
                validate_constraint_request(payload)

    def test_range_wire_request_inverted_bounds_rejected(self):
        from adapters.python.contracts import validate_constraint_request
        payload = {
            "schema_version": "1.0.0", "constraint_id": "rng", "operator": "range",
            "value": 5, "value_unit": "L", "bound_unit": "L",
            "bound_low": 8, "bound_high": 2, "tolerance": 0.0,
        }
        with self.assertRaises(ValueError):
            validate_constraint_request(payload)

    def test_range_in_wire_schema(self):
        import json
        from pathlib import Path
        schema = json.loads((Path(__file__).resolve().parent.parent
                             / "interop" / "schemas"
                             / "constraint-evaluation.schema.json").read_text())
        self.assertIn("range", schema["properties"]["operator"]["enum"])
        self.assertIn("bound_low", schema["properties"])
        self.assertIn("bound_high", schema["properties"])


class TestVectorDecisionsVersions(unittest.TestCase):
    """Decision 4 (2026-11-11): ACCEPT SAME-MAJOR patch/minor per CONTRACT_VERSIONING.md."""

    def _payload(self, version):
        return {
            "schema_version": version, "constraint_id": "water_limit", "operator": "<=",
            "value": 8.0, "value_unit": "L", "bound": 10.0, "bound_unit": "L", "tolerance": 0.0,
        }

    def test_version_1_0_0_still_accepted(self):
        from adapters.python.contracts import validate_constraint_request
        validate_constraint_request(self._payload("1.0.0"))

    def test_version_patch_accepted(self):
        from adapters.python.contracts import validate_constraint_request
        validate_constraint_request(self._payload("1.0.1"))

    def test_version_minor_accepted(self):
        from adapters.python.contracts import validate_constraint_request
        validate_constraint_request(self._payload("1.1.0"))

    def test_version_major_rejected_with_distinct_error(self):
        from adapters.python.contracts import validate_constraint_request
        with self.assertRaises(ValueError) as ctx:
            validate_constraint_request(self._payload("2.0.0"))
        self.assertIn("unsupported major schema version", str(ctx.exception))
        self.assertNotEqual(str(ctx.exception), "unsupported schema version")

    def test_version_malformed_rejected(self):
        from adapters.python.contracts import validate_constraint_request
        for bad in ("1.0", "1", "one", "", 1.0):
            with self.assertRaises((ValueError, TypeError)):
                validate_constraint_request(self._payload(bad))


class TestVectorRegression(unittest.TestCase):
    """Already-agreeing and must-agree wire cases still agree; aggregation unchanged."""

    def _wire(self, constraint_id, operator, value, value_unit, bound, bound_unit):
        return {
            "schema_version": "1.0.0", "constraint_id": constraint_id, "operator": operator,
            "value": value, "value_unit": value_unit, "bound": bound,
            "bound_unit": bound_unit, "tolerance": 0.0,
        }

    def test_already_agreeing_wire_cases(self):
        from adapters.python.contracts import evaluate_constraint_request
        self.assertEqual(evaluate_constraint_request(
            self._wire("eq", "==", 10, "kg", 10, "kg")), CheckStatus.PASS)
        self.assertEqual(evaluate_constraint_request(
            self._wire("fail", "<=", 12, "L", 10, "L")), CheckStatus.FAIL)
        self.assertEqual(evaluate_constraint_request(
            self._wire("incomp", "<=", 5, "L", 10, "kg")), CheckStatus.UNKNOWN)

    def test_must_agree_food_and_tonne_cases(self):
        from adapters.python.contracts import evaluate_constraint_request
        self.assertEqual(evaluate_constraint_request(
            self._wire("food_energy_adequacy", ">=", 2800, "kcal/capita/day", 2500, "kcal/capita/day")),
            CheckStatus.PASS)
        self.assertEqual(evaluate_constraint_request(
            self._wire("mass", "<=", 8, "t", 10, "t")), CheckStatus.PASS)

    def test_aggregation_cases_unchanged(self):
        self.assertEqual(overall_from_checks([]), CheckStatus.NOT_CHECKED)
        self.assertEqual(overall_from_checks([CheckStatus.UNKNOWN]), CheckStatus.UNKNOWN)


class InteropContractTests(unittest.TestCase):
    def test_constraint_request_boundary(self):
        from adapters.python.contracts import validate_constraint_request
        payload = {
            "schema_version": "1.0.0", "constraint_id": "water_limit", "operator": "<=",
            "value": 8.0, "value_unit": "L", "bound": 10.0, "bound_unit": "L", "tolerance": 0.0,
        }
        validate_constraint_request(payload)
        payload["value"] = float("nan")
        with self.assertRaises(ValueError):
            validate_constraint_request(payload)

    def test_constraint_result_rejects_unknown_status(self):
        from adapters.python.contracts import validate_constraint_result
        with self.assertRaises(ValueError):
            validate_constraint_result({"schema_version": "1.0.0", "status": "APPROVED"})


class Issue46RawStringsTest(unittest.TestCase):
    """ISSUE-46 (2026-11-11): overall_from_checks promises
    Iterable[CheckStatus]; a raw string is not a CheckStatus, so it
    must map to UNKNOWN, never to the status it spells. Repro before
    the fix: overall_from_checks(["PASS"]) -> CheckStatus.PASS via
    str-Enum equality; overall_from_checks(["bogus"]) -> UNKNOWN only
    by the fall-through. All production callers pass real CheckStatus
    values (checked by grep: contracts/models.py, plan_limits.py,
    domains/food/evaluation.py, engine/verification.py), so no caller
    needed updating — the typed path is unchanged."""

    def test_raw_string_pass_is_unknown_not_pass(self):
        self.assertEqual(overall_from_checks(["PASS"]), CheckStatus.UNKNOWN)

    def test_raw_string_fail_is_unknown_not_fail(self):
        # A raw "FAIL" must not dominate the aggregate either.
        self.assertEqual(overall_from_checks([CheckStatus.PASS, "FAIL"]), CheckStatus.UNKNOWN)

    def test_unrecognised_value_is_unknown(self):
        self.assertEqual(overall_from_checks(["bogus"]), CheckStatus.UNKNOWN)
        self.assertEqual(overall_from_checks([None]), CheckStatus.UNKNOWN)
        self.assertEqual(overall_from_checks([42]), CheckStatus.UNKNOWN)

    def test_typed_path_still_works(self):
        self.assertEqual(overall_from_checks([CheckStatus.PASS]), CheckStatus.PASS)
        self.assertEqual(overall_from_checks([CheckStatus.PASS, CheckStatus.FAIL]), CheckStatus.FAIL)
        self.assertEqual(overall_from_checks([CheckStatus.PASS, CheckStatus.UNKNOWN]), CheckStatus.UNKNOWN)
        self.assertEqual(overall_from_checks([]), CheckStatus.NOT_CHECKED)

    def test_single_string_argument_is_unknown_not_its_letters(self):
        # overall_from_checks("PASS") iterates the letters; each is a
        # non-CheckStatus, so the aggregate is UNKNOWN, not PASS.
        self.assertEqual(overall_from_checks("PASS"), CheckStatus.UNKNOWN)


class Issue47ConvertOverflowTest(unittest.TestCase):
    """ISSUE-47 (2026-11-11): convert() silently returned inf on
    overflow. Repro before the fix: convert(1e308, "tonne", "g")
    -> inf. Fix: the result must be finite; overflow raises
    ValueError, consistent with convert's other errors (all
    ValueError: non-finite input, unknown unit, incompatible units).
    Constraint.evaluate catches that ValueError and returns UNKNOWN,
    so an overflowing evaluation is UNKNOWN in Python, matching
    Rust/Julia (NON_FINITE / UNKNOWN, never PASS)."""

    def test_overflow_raises_value_error(self):
        with self.assertRaises(ValueError):
            convert(1e308, "tonne", "g")

    def test_overflow_in_the_other_direction_too(self):
        # 1e308 g -> tonne divides (finite); the overflowing direction
        # is the small-to-large-factor one, and the largest factor
        # pair in the registry must not silently produce inf either.
        with self.assertRaises(ValueError):
            convert(1e308, "MWh", "kcal")

    def test_just_below_overflow_still_converts(self):
        # 1e305 tonne = 1e311 g would overflow; 1e300 tonne = 1e306 g
        # is finite and must keep working (approximate: float
        # arithmetic need not reproduce the decimal exactly).
        got = convert(1e300, "tonne", "g")
        self.assertTrue(math.isfinite(got))
        self.assertAlmostEqual(got, 1e306, delta=1e300)

    def test_overflowing_constraint_evaluates_unknown_never_pass(self):
        c = Constraint("ovf", "overflow", operator=">=", bound=1.0, unit="g")
        # 1e308 tonne overflows converting to g; must be UNKNOWN,
        # never the PASS a silent inf would give for ">=".
        self.assertEqual(c.evaluate(1e308, "tonne"), CheckStatus.UNKNOWN)


class Issue42PythonToleranceBoundariesTest(unittest.TestCase):
    """ISSUE-42, Python side (2026-11-11): the audit found the
    Python coverage of the ISSUE-42 list adequate except for the
    tolerance boundaries and the exact ">=" boundary — ">=" itself
    was only exercised well away from its bound (2800 vs 2500),
    "==" only at exact equality / one in-tolerance float case, and
    no operator had a test at exactly bound +/- tolerance (passes)
    versus just beyond it (fails). Negative tolerance, empty/
    whitespace id, wrong schema version, unknown bound unit and
    range are already covered (test_issue07_status_mapping.py,
    test_issue09_10_11_54.py, test_test_vectors.py) and are not
    duplicated here."""

    def test_ge_exact_boundary_passes_and_below_fails(self):
        c = Constraint("ge", "at least", operator=">=", bound=2500, unit="kcal/day")
        self.assertEqual(c.evaluate(2500, "kcal/day"), CheckStatus.PASS)
        self.assertEqual(c.evaluate(2499.999, "kcal/day"), CheckStatus.FAIL)

    def test_le_tolerance_boundary(self):
        c = Constraint("le", "at most", operator="<=", bound=10, unit="L", tolerance=0.5)
        self.assertEqual(c.evaluate(10.5, "L"), CheckStatus.PASS)   # exactly bound + tol
        self.assertEqual(c.evaluate(10.5000001, "L"), CheckStatus.FAIL)  # just beyond

    def test_ge_tolerance_boundary(self):
        c = Constraint("ge", "at least", operator=">=", bound=10, unit="L", tolerance=0.5)
        self.assertEqual(c.evaluate(9.5, "L"), CheckStatus.PASS)    # exactly bound - tol
        self.assertEqual(c.evaluate(9.4999999, "L"), CheckStatus.FAIL)   # just beyond

    def test_eq_tolerance_boundary(self):
        c = Constraint("eq", "equal", operator="==", bound=10, unit="kg", tolerance=0.5)
        self.assertEqual(c.evaluate(10.5, "kg"), CheckStatus.PASS)  # |diff| == tol
        self.assertEqual(c.evaluate(9.5, "kg"), CheckStatus.PASS)
        self.assertEqual(c.evaluate(10.5000001, "kg"), CheckStatus.FAIL)
        self.assertEqual(c.evaluate(9.4999999, "kg"), CheckStatus.FAIL)


if __name__ == "__main__":
    unittest.main()
