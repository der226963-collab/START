"""Tests for the ready-made CLI example inputs in ``examples/cli-inputs/``.

Every case runs the real CLI in a subprocess against a shipped
example file and asserts the outcome documented in
``examples/cli-inputs/README.md``. These tests exist so the example
inputs cannot go stale silently: if a domain, a snapshot value, or
the CLI's envelope rules change, the affected example fails here
instead of misleading a user.

Outputs go to a temp directory; the shipped inputs are never modified.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "examples" / "cli-inputs"


def run_cli(*args: str, out_dir: Path) -> tuple[int, Path | None]:
    """Run ``python -m cli`` with the given args; return (exit code, out path or None)."""
    out = None
    argv = [sys.executable, "-m", "cli"]
    for i, arg in enumerate(args):
        argv.append(arg)
        if arg == "--out" and i + 1 < len(args):
            out = Path(args[i + 1])
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, out


def read_result(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["payload"]


class CliExamplesTest(unittest.TestCase):
    def test_inputs_exist(self):
        expected = [
            "plan-pass.json",
            "plan-fail.json",
            "plan-overrides-match.json",
            "food-request.json",
            "food-scenario-lower-losses.json",
            "food-scenario-higher-supply.json",
            "labour-request.json",
            "nutrients-request.json",
            "nutrients-teaching-request.json",
        ]
        for name in expected:
            self.assertTrue((INPUTS / name).is_file(), f"missing example input: {name}")

    def test_plan_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("check-plan", "--plan", str(INPUTS / "plan-pass.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["overall_status"], "PASS")
            self.assertEqual(result["failed_count"], 0)

    def test_plan_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("check-plan", "--plan", str(INPUTS / "plan-fail.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["overall_status"], "FAIL")
            self.assertEqual(result["failed_count"], 2)

    def test_plan_pass_with_matching_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("check-plan", "--plan", str(INPUTS / "plan-pass.json"),
                              "--overrides", str(INPUTS / "plan-overrides-match.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            self.assertEqual(read_result(out)["overall_status"], "PASS")

    def test_food_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("run", "--domain", "food",
                              "--request", str(INPUTS / "food-request.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
            self.assertEqual(result["evaluation"]["overall_status"], "PASS")

    def test_labour_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("run", "--domain", "labour",
                              "--request", str(INPUTS / "labour-request.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
            metrics = result["calculation"]["metrics"]
            self.assertAlmostEqual(metrics["women_unpaid_care_hours_per_day_billion"], 12.4968, places=4)
            self.assertAlmostEqual(metrics["men_unpaid_care_hours_per_day_billion"], 3.9032, places=4)
            self.assertAlmostEqual(metrics["unpaid_care_hours_per_person_per_day"], 2.0, places=4)

    def test_nutrients_request_snapshot_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("run", "--domain", "nutrients",
                              "--request", str(INPUTS / "nutrients-request.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["calculation"]["calculation_status"], "INSUFFICIENT_INPUT")
            missing = result["calculation"]["missing_fields"]
            self.assertEqual(len(missing), 4)
            self.assertTrue(any("phosphorus_uptake_tg_per_year" in m for m in missing))
            self.assertTrue(any("nitrogen_losses_tg_per_year" in m for m in missing))

    def test_nutrients_teaching_request_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("run", "--domain", "nutrients",
                              "--request", str(INPUTS / "nutrients-teaching-request.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")
            self.assertEqual(
                result["calculation"]["metrics"]["nitrogen_soil_change_tg_per_year"], 20.0)

    def test_food_scenario_lower_losses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("run-scenario", "--domain", "food",
                              "--scenario", str(INPUTS / "food-scenario-lower-losses.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(result["calculation_status"], "COMPLETED")
            self.assertEqual(result["scenario_id"], "food-scenario-lower-losses")

    def test_compare_food_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            code, _ = run_cli("compare-scenarios", "--domain", "food",
                              "--scenarios",
                              str(INPUTS / "food-scenario-lower-losses.json"),
                              str(INPUTS / "food-scenario-higher-supply.json"),
                              "--out", str(out), out_dir=Path(tmp))
            self.assertEqual(code, 0)
            result = read_result(out)
            self.assertEqual(len(result["results"]), 2)
            # The comparison reports consequences; it never selects.
            self.assertIsNone(result["selection"])


if __name__ == "__main__":
    unittest.main()
