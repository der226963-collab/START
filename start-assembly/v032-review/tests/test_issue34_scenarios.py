"""Non-numeric scenario changes (ISSUE-34, Part 3, 2026-11-13).

Extends the ISSUE-33/38 change allow-list so a scenario may change
non-numeric fields — but ONLY fields the target domain has explicitly
allow-listed in DomainModule.scenario_non_numeric_change_fields.
The injection guard is not weakened: a non-numeric change to a
non-listed field (including an injected key with a string value)
still raises ValueError, exactly as for numeric changes.

The nutrients/labour domains are not in this tree yet, so the
end-to-end tests run against a small test-only domain below that
declares the same allow-list those domains will declare
(frozenset({"source_ids", "geography", "period"})); the real domains
still need a final check once they land.
"""
import math
import unittest

from contracts.scenarios import Scenario
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


class NonNumericDomain(DomainModule):
    """Test-only domain declaring the nutrients/labour allow-list."""
    domain_id = "non-numeric-test"
    display_name = "Non-numeric test domain"
    scenario_change_fields = frozenset({"population"})
    scenario_non_numeric_change_fields = frozenset({"source_ids", "geography", "period"})

    def validate_inputs(self, request):
        problems = []
        if not isinstance(request.get("source_ids", []), list):
            problems.append("source_ids must be a list")
        for field in ("geography", "period"):
            if field in request and not isinstance(request[field], str):
                problems.append(f"{field} must be a string identifier")
        return {"ok": not problems, "problems": problems,
                "warnings": [], "assumptions": []}

    def calculate(self, request):
        return {"calculation_status": "COMPLETED",
                "metrics": {"population": request.get("population"),
                            "source_ids": list(request.get("source_ids", [])),
                            "geography": request.get("geography"),
                            "period": request.get("period")},
                "display_metrics": {}, "assumptions": [],
                "source_ids": list(request.get("source_ids", [])),
                "limitations": []}

    def identify_constraints(self, request):
        return []

    def evaluate(self, calc):
        return {"overall_status": "PASS", "constraint_results": [], "warnings": []}

    def describe_uncertainty(self, result):
        return []


def _scenario(changes, base=None, **kwargs):
    return Scenario("s1", "test scenario", proposed_changes=changes,
                    metadata={"base_request": dict(base if base is not None else {})},
                    **kwargs)


class ScenarioNonNumericConstructionTest(unittest.TestCase):
    def test_str_and_list_str_changes_construct(self):
        s = _scenario({"geography": "riverport", "source_ids": ["src-a", "src-b"]})
        self.assertEqual(s.proposed_changes["geography"], "riverport")
        self.assertEqual(s.proposed_changes["source_ids"], ["src-a", "src-b"])

    def test_numeric_changes_still_construct(self):
        s = _scenario({"population": 5, "supply": 1.5})
        self.assertEqual(s.proposed_changes, {"population": 5, "supply": 1.5})

    def test_bool_change_rejected(self):
        with self.assertRaises(ValueError):
            _scenario({"geography": True})

    def test_none_change_rejected(self):
        with self.assertRaises(ValueError):
            _scenario({"geography": None})

    def test_dict_change_rejected(self):
        with self.assertRaises(ValueError):
            _scenario({"geography": {"a": 1}})

    def test_tuple_change_rejected(self):
        with self.assertRaises(ValueError):
            _scenario({"source_ids": ("a", "b")})

    def test_set_change_rejected(self):
        with self.assertRaises(ValueError):
            _scenario({"source_ids": {"a", "b"}})

    def test_non_finite_numeric_rejected(self):
        for bad in (math.inf, -math.inf, math.nan):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _scenario({"population": bad})

    def test_list_with_non_string_item_rejected(self):
        for bad in (["a", 1], [None], [True], [["nested"]]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _scenario({"source_ids": bad})

    def test_empty_string_value_rejected(self):
        for bad in ("", "   "):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _scenario({"geography": bad})

    def test_empty_or_whitespace_string_inside_list_rejected(self):
        for bad in (["a", ""], ["   "], ["a", " "]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _scenario({"source_ids": bad})

    def test_empty_list_constructs(self):
        # The spec rejects empty strings INSIDE a list, not an empty
        # list itself: [] is a list of non-empty strings vacuously,
        # and food's validate_inputs accepts an empty source_ids.
        # It is a no-op change, not an invalid value.
        s = _scenario({"source_ids": []})
        self.assertEqual(s.proposed_changes["source_ids"], [])


class ScenarioRoundTripTest(unittest.TestCase):
    def test_to_dict_round_trips_str_and_list_str_changes(self):
        s = Scenario("s1", "mixed changes",
                     proposed_changes={"geography": "riverport",
                                       "period": "2026",
                                       "source_ids": ["src-a", "src-b"],
                                       "population": 42},
                     geography="base-geo", period="2025",
                     source_ids=["orig"],
                     metadata={"base_request": {"population": 100}})
        rebuilt = Scenario(**s.to_dict())
        self.assertEqual(rebuilt, s)
        self.assertEqual(rebuilt.proposed_changes["geography"], "riverport")
        self.assertEqual(rebuilt.proposed_changes["source_ids"], ["src-a", "src-b"])
        self.assertEqual(rebuilt.proposed_changes["population"], 42)


class NonNumericAllowListTest(unittest.TestCase):
    def test_allow_listed_non_numeric_changes_pass_end_to_end(self):
        engine = PlanningEngine()
        engine.register(NonNumericDomain())
        s = _scenario({"source_ids": ["src-a", "src-b"],
                       "geography": "riverport", "period": "2026"},
                      base={"population": 100})
        result = engine.run_scenario("non-numeric-test", s)
        self.assertTrue(result["calculation_ok"], result)
        metrics = result["metrics"]["calculation"]["metrics"]
        self.assertEqual(metrics["source_ids"], ["src-a", "src-b"])
        self.assertEqual(metrics["geography"], "riverport")
        self.assertEqual(metrics["period"], "2026")

    def test_explicit_geography_change_wins_over_base_request(self):
        # An EXPLICIT proposed change to geography/period is a change,
        # not a default: it must win over the base request's value.
        # (ISSUE-25 is about scenario DEFAULTS, not explicit changes —
        # the base still wins over the scenario's geography/period
        # defaults when no explicit change is proposed; see next test.)
        s = _scenario({"geography": "new-geo", "period": "2030"},
                      base={"population": 100, "geography": "base-geo",
                            "period": "2020"})
        req = NonNumericDomain().scenario_request(s)
        self.assertEqual(req["geography"], "new-geo")
        self.assertEqual(req["period"], "2030")

    def test_issue25_base_still_wins_over_scenario_defaults(self):
        s = Scenario("s1", "no explicit geo change",
                     geography="scenario-geo", period="scenario-period",
                     metadata={"base_request": {"population": 100,
                                                "geography": "base-geo",
                                                "period": "2020"}})
        req = NonNumericDomain().scenario_request(s)
        self.assertEqual(req["geography"], "base-geo")
        self.assertEqual(req["period"], "2020")

    def test_scenario_defaults_fill_missing_base_geography_period(self):
        s = Scenario("s1", "base lacks geo",
                     geography="scenario-geo", period="scenario-period",
                     metadata={"base_request": {"population": 100}})
        req = NonNumericDomain().scenario_request(s)
        self.assertEqual(req["geography"], "scenario-geo")
        self.assertEqual(req["period"], "scenario-period")

    def test_non_numeric_change_to_non_listed_field_raises(self):
        s = _scenario({"__injected__": "pwned"}, base={"population": 100})
        with self.assertRaises(ValueError) as ctx:
            NonNumericDomain().scenario_request(s)
        self.assertIn("__injected__", str(ctx.exception))
        self.assertIn("scenario_non_numeric_change_fields", str(ctx.exception))

    def test_string_injected_key_rejected_through_engine_too(self):
        engine = PlanningEngine()
        engine.register(NonNumericDomain())
        s = _scenario({"__injected__": "pwned"}, base={"population": 100})
        result = engine.run_scenario("non-numeric-test", s)
        self.assertFalse(result["calculation_ok"])
        self.assertEqual(result["calculation_status"], "ERROR")

    def test_str_change_to_numeric_only_field_raises(self):
        # "population" is in scenario_change_fields but NOT in the
        # non-numeric allow-list: a str value for it must be rejected,
        # not silently applied to a numeric field.
        s = _scenario({"population": "100"}, base={"population": 100})
        with self.assertRaises(ValueError):
            NonNumericDomain().scenario_request(s)

    def test_list_change_to_numeric_only_field_raises(self):
        s = _scenario({"population": ["100"]}, base={"population": 100})
        with self.assertRaises(ValueError):
            NonNumericDomain().scenario_request(s)

    def test_numeric_change_to_non_numeric_only_field_raises(self):
        # The two allow-lists are per value shape: a number for
        # "source_ids" (non-numeric-only) must be rejected too.
        s = _scenario({"source_ids": 42}, base={"population": 100})
        with self.assertRaises(ValueError):
            NonNumericDomain().scenario_request(s)

    def test_numeric_allow_listed_change_still_passes(self):
        s = _scenario({"population": 250}, base={"population": 100})
        req = NonNumericDomain().scenario_request(s)
        self.assertEqual(req["population"], 250)


class FoodStaysNumericOnlyTest(unittest.TestCase):
    def test_food_declares_no_non_numeric_changes(self):
        self.assertIsNone(FoodDomain.scenario_non_numeric_change_fields)

    def test_food_rejects_source_ids_scenario_change(self):
        s = _scenario({"source_ids": ["src-a"]}, base=BASE)
        with self.assertRaises(ValueError) as ctx:
            FoodDomain().scenario_request(s)
        self.assertIn("source_ids", str(ctx.exception))
        self.assertIn("scenario_non_numeric_change_fields", str(ctx.exception))

    def test_food_rejects_geography_scenario_change(self):
        s = _scenario({"geography": "riverport"}, base=BASE)
        with self.assertRaises(ValueError):
            FoodDomain().scenario_request(s)

    def test_food_numeric_scenario_change_still_works(self):
        s = _scenario({"supply_kcal_per_capita_per_day": 3100}, base=BASE)
        req = FoodDomain().scenario_request(s)
        self.assertEqual(req["supply_kcal_per_capita_per_day"], 3100)


if __name__ == "__main__":
    unittest.main()
