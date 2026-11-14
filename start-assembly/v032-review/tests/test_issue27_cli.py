"""End-to-end tests for the ISSUE-27 CLI (``python -m cli``).

Every case runs the real CLI in a subprocess with cwd set to the tree
root and temp files, so the entry point, envelope handling, exit codes
and the no-output-on-failure rule are all exercised as the user sees
them. Envelopes are written by hand as plain JSON (the wire format)
so the tests do not depend on the persistence writer's behaviour;
the CLI's own writes are read back as plain JSON the same way.

Exit-code contract (see cli/__main__.py): 0 on success, including a
FAIL/UNKNOWN plan outcome; 2 for usage/validation errors; 1 for
runtime failures. Refusing to overwrite an existing output file
without --force is exit 1 (output cannot be written as asked).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FOOD_REQUEST = {
    "population": 100_000,
    "supply_kcal_per_capita_per_day": 2_800,
    "requirement_kcal_per_capita_per_day": 2_500,
    "imports_kcal_per_capita_per_day": 100,
    "losses_fraction": 0.08,
    "source_ids": ["example-source-not-real"],
    "geography": "community-example",
    "period": "2026",
}

FOOD_SCENARIO = {
    "scenario_id": "cli-test-scenario",
    "name": "CLI test scenario",
    "description": "Higher supply than the base request.",
    "assumptions": ["test-only assumption"],
    "proposed_changes": {"supply_kcal_per_capita_per_day": 3000},
    "geography": "community-example",
    "period": "2026",
    "source_ids": ["example-source-not-real"],
    "metadata": {"base_request": FOOD_REQUEST},
}


def write_envelope(path: Path, kind: str, payload, schema_version: str = "1.0.0") -> Path:
    envelope = {
        "schema_version": schema_version,
        "kind": kind,
        "saved_at": "2026-11-14T00:00:00Z",
        "payload": payload,
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def read_envelope(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CliTestCase(unittest.TestCase):
    def run_cli(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "cli", *argv],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )

    def assert_no_output(self, out: Path) -> None:
        self.assertFalse(out.exists(), f"output file must not appear on failure: {out}")

    # -- success paths -------------------------------------------------

    def test_check_plan_pass_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0})
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = read_envelope(out)
            self.assertEqual(result["kind"], "result")
            self.assertEqual(result["payload"]["overall_status"], "PASS")

    def test_check_plan_fail_exits_zero(self):
        # A FAIL outcome is data, not a CLI failure.
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 18.2})
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = read_envelope(out)
            self.assertEqual(result["payload"]["overall_status"], "FAIL")

    def test_check_plan_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            overrides = Path(tmp) / "overrides.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0})
            write_envelope(overrides, "plan_overrides",
                           {"phosphorus_application_tg_per_year": 6.2})
            proc = self.run_cli("check-plan", "--plan", str(plan),
                                "--overrides", str(overrides), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(read_envelope(out)["payload"]["overall_status"], "PASS")

    def test_run_food_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            out = Path(tmp) / "out.json"
            write_envelope(request, "plan_request", FOOD_REQUEST)
            proc = self.run_cli("run", "--domain", "food",
                                "--request", str(request), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = read_envelope(out)["payload"]
            self.assertEqual(payload["domain"], "food")
            self.assertEqual(payload["calculation"]["calculation_status"], "COMPLETED")
            self.assertIs(payload["needs_human_decision"], True)

    def test_run_scenario_food_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.json"
            out = Path(tmp) / "out.json"
            write_envelope(scenario, "scenario", FOOD_SCENARIO)
            proc = self.run_cli("run-scenario", "--domain", "food",
                                "--scenario", str(scenario), "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = read_envelope(out)["payload"]
            self.assertEqual(payload["scenario_id"], "cli-test-scenario")
            self.assertEqual(payload["calculation_status"], "COMPLETED")

    def test_compare_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "s1.json"
            second = Path(tmp) / "s2.json"
            out = Path(tmp) / "out.json"
            write_envelope(first, "scenario", FOOD_SCENARIO)
            other = dict(FOOD_SCENARIO)
            other["scenario_id"] = "cli-test-scenario-2"
            other["name"] = "CLI test scenario 2"
            other["proposed_changes"] = {"supply_kcal_per_capita_per_day": 2600}
            write_envelope(second, "scenario", other)
            proc = self.run_cli("compare-scenarios", "--domain", "food",
                                "--scenarios", str(first), str(second),
                                "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = read_envelope(out)["payload"]
            self.assertEqual(len(payload["results"]), 2)
            self.assertIsNone(payload["selection"])

    def test_list_domains(self):
        proc = self.run_cli("list-domains")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.split()
        self.assertEqual(lines, ["food", "labour", "nutrients"])

    def test_verbose_logs_to_stderr(self):
        proc = self.run_cli("--verbose", "list-domains")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("cli_invoked", proc.stderr)

    def test_log_file_gets_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "cli.log"
            # --verbose: cli_invoked is an INFO event, and the default
            # level (WARNING) would filter it out of the log.
            proc = self.run_cli("--verbose", "--log-file", str(log_file), "list-domains")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertTrue(lines)
            record = json.loads(lines[0])
            self.assertEqual(record["event"], "cli_invoked")

    # -- failure modes: exit 2, no output file ------------------------

    def test_missing_input_file_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            proc = self.run_cli("check-plan", "--plan",
                                str(Path(tmp) / "no-such-file.json"),
                                "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("not found", proc.stderr)
            self.assert_no_output(out)

    def test_bad_json_input_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            plan.write_text("{not valid json", encoding="utf-8")
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assert_no_output(out)

    def test_major_version_mismatch_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0},
                           schema_version="2.0.0")
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assert_no_output(out)

    def test_unknown_domain_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            out = Path(tmp) / "out.json"
            write_envelope(request, "plan_request", FOOD_REQUEST)
            proc = self.run_cli("run", "--domain", "bogus",
                                "--request", str(request), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("food", proc.stderr)
            self.assertIn("nutrients", proc.stderr)
            self.assertIn("labour", proc.stderr)
            self.assert_no_output(out)

    def test_bare_payload_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            plan.write_text(
                json.dumps({"phosphorus_application_tg_per_year": 5.0}),
                encoding="utf-8")
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("envelope", proc.stderr)
            self.assertIn("schema_version", proc.stderr)
            self.assert_no_output(out)

    def test_wrong_kind_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            out = Path(tmp) / "out.json"
            write_envelope(request, "scenario", FOOD_SCENARIO)
            proc = self.run_cli("run", "--domain", "food",
                                "--request", str(request), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("plan_request", proc.stderr)
            self.assert_no_output(out)

    def test_bad_scenario_fields_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp) / "scenario.json"
            out = Path(tmp) / "out.json"
            write_envelope(scenario, "scenario",
                           {"scenario_id": "   ", "name": "No id"})
            proc = self.run_cli("run-scenario", "--domain", "food",
                                "--scenario", str(scenario), "--out", str(out))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assert_no_output(out)

    def test_missing_required_flag_is_exit_2(self):
        proc = self.run_cli("check-plan", "--plan", "x.json")
        self.assertEqual(proc.returncode, 2)

    # -- failure modes: exit 1, no output file ------------------------

    def test_unwritable_out_path_is_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "no-such-dir" / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0})
            proc = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assert_no_output(out)

    def test_overwrite_refused_without_force_is_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0})
            first = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(first.returncode, 0, first.stderr)
            before = out.read_text(encoding="utf-8")
            second = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(second.returncode, 1, second.stderr)
            self.assertIn("--force", second.stderr)
            self.assertEqual(out.read_text(encoding="utf-8"), before)

    def test_force_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            out = Path(tmp) / "out.json"
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 5.0})
            first = self.run_cli("check-plan", "--plan", str(plan), "--out", str(out))
            self.assertEqual(first.returncode, 0, first.stderr)
            write_envelope(plan, "plan_request",
                           {"phosphorus_application_tg_per_year": 18.2})
            second = self.run_cli("--force", "check-plan",
                                  "--plan", str(plan), "--out", str(out))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(read_envelope(out)["payload"]["overall_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
