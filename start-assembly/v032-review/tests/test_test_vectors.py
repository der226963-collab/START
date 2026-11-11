"""Consuming tests for the shared test vectors (ISSUE-04 integration, 2026-11-11).

Loads interop/test-vectors.json — the file the four 2026-11-11 decisions
(m3/L convert, kcal/day in the registry, range on the wire, same-major
versions accepted) were recorded in — and runs every case through this
language's evaluator. A disagreement between the file and the evaluator
is a test FAILURE.

Run: python -m unittest discover -s tests -v   (from start_v03_work/)
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path

from adapters.python.contracts import (
    evaluate_constraint_request,
    validate_constraint_request,
)
from contracts.statuses import CheckStatus, overall_from_checks

VECTORS_PATH = Path(__file__).resolve().parent.parent / "interop" / "test-vectors.json"


def load_vectors() -> dict:
    with VECTORS_PATH.open() as f:
        return json.load(f)


class TestVectorsFileTest(unittest.TestCase):
    """The shared file itself: all four decisions recorded, all three
    languages verified to the same status on every case."""

    def test_all_decided_cases_are_must_agree(self):
        data = load_vectors()
        decided = {"volume-m3-vs-litre", "kcal-per-day-invented-unit",
                   "range-operator", "version-patch", "version-minor"}
        seen = {c["id"] for c in data["cases"] if c["conformance"] == "must_agree"}
        seen |= {c["id"] for c in data["version_cases"] if c["conformance"] == "must_agree"}
        self.assertTrue(decided <= seen, f"decided cases not must_agree: {decided - seen}")
        self.assertFalse(
            any(c["conformance"] == "open_decision"
                for c in data["cases"] + data["version_cases"]),
            "an open_decision remains after the 2026-11-11 decisions")

    def test_all_three_languages_agree_on_every_case(self):
        data = load_vectors()
        for case in data["cases"]:
            statuses = {
                case["python_verified_2026-11-11"]["status"],
                case["rust_verified_2026-11-11"]["status"],
                case["julia_verified_2026-11-11"]["status"],
                case["julia_expected"]["status"],
            }
            self.assertEqual(len(statuses), 1, f"{case['id']}: languages disagree in file: {statuses}")
        for vc in data["version_cases"]:
            accepted = {
                vc["python_verified_2026-11-11"]["accepted"],
                vc["rust_verified_2026-11-11"]["accepted"],
                vc["julia_verified_2026-11-11"]["accepted"],
            }
            self.assertEqual(len(accepted), 1, f"{vc['id']}: languages disagree in file")
        for ac in data["aggregation_cases"]:
            statuses = {
                ac["python_verified_2026-11-11"]["status"],
                ac["rust_verified_2026-11-11"]["status"],
                ac["julia_verified_2026-11-11"]["status"],
            }
            self.assertEqual(len(statuses), 1, f"{ac['id']}: languages disagree in file")


class TestVectorsWireCasesTest(unittest.TestCase):
    """All 8 wire cases, driven from the file through the Python adapter."""

    def test_wire_cases(self):
        data = load_vectors()
        self.assertEqual(len(data["cases"]), 8)
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                expected = case["python_expected"]["status"]
                got = evaluate_constraint_request(case["request"])
                self.assertEqual(got.value, expected,
                                 f"{case['id']}: evaluator {got.value} != file {expected}")

    def test_range_wire_shape_has_bounds_not_bound(self):
        # The decided wire shape carries bound_low/bound_high, no "bound".
        data = load_vectors()
        rng = next(c for c in data["cases"] if c["id"] == "range-operator")
        self.assertEqual(rng["request"]["operator"], "range")
        self.assertEqual(rng["request"]["bound_low"], 2)
        self.assertEqual(rng["request"]["bound_high"], 8)
        self.assertNotIn("bound", rng["request"])


class TestVectorsVersionCasesTest(unittest.TestCase):
    """All 3 version cases, driven from the file through the Python adapter."""

    def _payload(self, version: str) -> dict:
        return {
            "schema_version": version, "constraint_id": "water_limit",
            "operator": "<=", "value": 8.0, "value_unit": "L",
            "bound": 10.0, "bound_unit": "L", "tolerance": 0.0,
        }

    def test_version_cases(self):
        data = load_vectors()
        self.assertEqual(len(data["version_cases"]), 3)
        for vc in data["version_cases"]:
            with self.subTest(case=vc["id"]):
                version = vc["request_schema_version"]
                if vc["expected"]["accepted"]:
                    validate_constraint_request(self._payload(version))
                else:
                    with self.assertRaises(ValueError) as ctx:
                        validate_constraint_request(self._payload(version))
                    self.assertEqual(str(ctx.exception), vc["expected"]["error"])
                    self.assertNotEqual(str(ctx.exception), "unsupported schema version")


class TestVectorsAggregationCasesTest(unittest.TestCase):
    """Both aggregation cases, driven from the file through overall_from_checks."""

    def test_aggregation_cases(self):
        data = load_vectors()
        self.assertEqual(len(data["aggregation_cases"]), 2)
        for ac in data["aggregation_cases"]:
            with self.subTest(case=ac["id"]):
                checks = [CheckStatus(s) for s in ac["input"]["checks"]]
                got = overall_from_checks(checks)
                self.assertEqual(got.value, ac["python_expected"]["status"])


if __name__ == "__main__":
    unittest.main()
