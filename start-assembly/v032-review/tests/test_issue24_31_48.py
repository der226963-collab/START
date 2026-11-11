"""Tests for the resources/contracts minors: ISSUE-24, ISSUE-31, ISSUE-48.

ISSUE-24: Flow start/end were compared lexicographically, so valid
non-padded ISO dates were rejected and reversed padded/non-padded
pairs constructed fine. Dates are now parsed to datetime.date and
compared as dates; unparseable values raise.

ISSUE-31: negative quantities were accepted for Stock/Flow (and
ProcessInput/ProcessOutput); VERIFIED status with quantity None
serialized misleadingly. Negative quantities now raise; VERIFIED
without a quantity now raises at construction. The Resource-negative
part was already done by the ISSUE-12 worker and is only verified
here, not re-implemented.

ISSUE-48: inconsistent id/unit validation across contracts. One rule
per concept, enforced in __post_init__ (see docs/ARCHITECTURE.md):
ids/names non-empty everywhere; unit required (known registry unit)
for quantity-bearing types even when quantity is None; unit optional
for Constraint/Objective.
"""
import unittest

from contracts.constraints import Constraint, Objective
from contracts.processes import Process, ProcessInput, ProcessOutput
from contracts.resources import Flow, Resource, Stock
from contracts.scenarios import Scenario, ScenarioResult
from contracts.statuses import DataStatus


class Issue24FlowDatesTest(unittest.TestCase):
    def test_non_padded_dates_construct_and_order_correctly(self):
        # The original repro: September precedes October, but
        # "2026-9-1" > "2026-10-1" lexicographically.
        f = Flow("f", "g", 10, "kg", "2026", start="2026-9-1", end="2026-10-1")
        self.assertEqual((f.start, f.end), ("2026-9-1", "2026-10-1"))

    def test_reversed_mixed_padding_raises(self):
        # The reverse repro: start after end constructed fine.
        with self.assertRaises(ValueError):
            Flow("f", "g", 10, "kg", "2026", start="2026-01-05", end="2026-1-4")

    def test_equal_dates_construct(self):
        Flow("f", "g", 10, "kg", "2026", start="2026-9-1", end="2026-09-01")

    def test_single_bound_validated_even_without_the_other(self):
        with self.assertRaises(ValueError):
            Flow("f", "g", 10, "kg", "2026", start="not-a-date")
        with self.assertRaises(ValueError):
            Flow("f", "g", 10, "kg", "2026", end="2026-13-01")
        Flow("f", "g", 10, "kg", "2026", start="2026-9-1")

    def test_impossible_calendar_date_raises(self):
        with self.assertRaises(ValueError):
            Flow("f", "g", 10, "kg", "2026", start="2026-02-30")

    def test_datetime_string_accepted_and_compared_by_date(self):
        f = Flow("f", "g", 10, "kg", "2026",
                 start="2026-09-01T10:00:00", end="2026-09-02")
        self.assertEqual(f.start, "2026-09-01T10:00:00")

    def test_non_string_bound_raises(self):
        with self.assertRaises(ValueError):
            Flow("f", "g", 10, "kg", "2026", start=20260901)


class Issue31NegativeAndVerifiedTest(unittest.TestCase):
    def test_negative_stock_and_flow_raise(self):
        with self.assertRaises(ValueError):
            Stock("s", "grain", -5, "kg", "2026-01-01")
        with self.assertRaises(ValueError):
            Flow("f", "g", -0.001, "kg", "2026")

    def test_negative_process_input_output_raise(self):
        with self.assertRaises(ValueError):
            ProcessInput("g", -2, "kg")
        with self.assertRaises(ValueError):
            ProcessOutput("g", -2, "kg")

    def test_negative_resource_still_raises_issue12_verified_done(self):
        # VERIFIED-DONE by the ISSUE-12 worker: verified live here,
        # not re-implemented.
        with self.assertRaises(ValueError):
            Resource("grain", "food", -5, "kg")

    def test_zero_and_none_quantities_still_allowed(self):
        self.assertEqual(Stock("s", "g", 0, "kg", "2026").quantity, 0)
        self.assertIsNone(Flow("f", "g", None, "kg", "2026").quantity)
        self.assertIsNone(ProcessInput("g", None, "kg").quantity)
        self.assertIsNone(ProcessOutput("g", None, "kg").quantity)

    def test_verified_without_quantity_raises(self):
        with self.assertRaises(ValueError):
            Resource("grain", "food", None, "kg", status=DataStatus.VERIFIED)
        with self.assertRaises(ValueError):
            Stock("s", "g", None, "kg", "2026", status=DataStatus.VERIFIED)
        with self.assertRaises(ValueError):
            Flow("f", "g", None, "kg", "2026", status=DataStatus.VERIFIED)

    def test_verified_with_quantity_still_constructs_and_reports(self):
        r = Resource("grain", "food", 10, "kg", status=DataStatus.VERIFIED)
        self.assertTrue(r.is_verified())
        self.assertEqual(r.to_dict()["status"], "verified")
        self.assertEqual(r.to_dict()["quantity"], 10)

    def test_unverified_statuses_with_none_quantity_still_allowed(self):
        for status in (DataStatus.UNKNOWN, DataStatus.OBSERVED, DataStatus.ESTIMATED):
            r = Resource("g", "food", None, "kg", status=status)
            self.assertFalse(r.is_verified())


class Issue48IdAndUnitRulesTest(unittest.TestCase):
    def test_empty_and_whitespace_ids_raise_everywhere(self):
        bad = ["", "   "]
        for value in bad:
            with self.assertRaises(ValueError, msg=f"Resource {value!r}"):
                Resource(value, "food", 1, "kg")
            with self.assertRaises(ValueError, msg=f"Stock {value!r}"):
                Stock(value, "g", 1, "kg", "2026")
            with self.assertRaises(ValueError, msg=f"Flow {value!r}"):
                Flow(value, "g", 1, "kg", "2026")
            with self.assertRaises(ValueError, msg=f"Process {value!r}"):
                Process(value, "name")
            with self.assertRaises(ValueError, msg=f"Objective {value!r}"):
                Objective(value, "name")
            with self.assertRaises(ValueError, msg=f"Scenario {value!r}"):
                Scenario(value, "name")
            with self.assertRaises(ValueError, msg=f"ScenarioResult {value!r}"):
                ScenarioResult(value, "food")

    def test_empty_reference_ids_raise(self):
        with self.assertRaises(ValueError):
            Stock("s", "", 1, "kg", "2026")
        with self.assertRaises(ValueError):
            Flow("f", "", 1, "kg", "2026")
        with self.assertRaises(ValueError):
            ProcessInput("", 1, "kg")
        with self.assertRaises(ValueError):
            ProcessOutput("", 1, "kg")

    def test_empty_names_raise(self):
        with self.assertRaises(ValueError):
            Process("p", "")
        with self.assertRaises(ValueError):
            Process("p", "   ")
        with self.assertRaises(ValueError):
            Objective("o", "")
        with self.assertRaises(ValueError):
            Scenario("s", "   ")

    def test_non_string_ids_raise(self):
        with self.assertRaises(ValueError):
            Resource(5, "food", 1, "kg")  # type: ignore[arg-type]

    def test_unit_required_for_quantity_types_even_with_none(self):
        # Deliberate rule (ISSUE-48): the unit is part of the
        # observation's identity, so it is required even when the
        # quantity is unknown. No existing caller needs otherwise.
        with self.assertRaises(ValueError):
            Resource("g", "food", None, "")
        with self.assertRaises(ValueError):
            Stock("s", "g", None, "", "2026")
        with self.assertRaises(ValueError):
            Flow("f", "g", None, "", "2026")
        with self.assertRaises(ValueError):
            ProcessInput("g", None, "")
        with self.assertRaises(ValueError):
            ProcessOutput("g", None, "")

    def test_unknown_unit_still_rejected_for_quantity_types(self):
        with self.assertRaises(ValueError):
            Resource("g", "food", None, "furlongs")

    def test_unit_optional_for_constraint_and_objective(self):
        # The plan_limits unit-less constraints (phosphorus,
        # work-hours) must keep constructing.
        c = Constraint("p", "phosphorus", operator="<=", bound=6.2, unit="")
        self.assertEqual(c.unit, "")
        o = Objective("o", "x", unit="")
        self.assertEqual(o.unit, "")
        # ... but a non-empty unit must still be a known one.
        with self.assertRaises(ValueError):
            Constraint("c", "x", operator="<=", bound=1, unit="bucket")
        with self.assertRaises(ValueError):
            Objective("o", "x", unit="bucket")


if __name__ == "__main__":
    unittest.main()
