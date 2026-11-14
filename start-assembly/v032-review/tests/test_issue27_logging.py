"""REVIEW.md ISSUE-27 — structured JSON-lines logging (instrumentation).

Covers the engine/contracts instrumentation only: a run emits JSON-lines
records with the required keys, INFO records carry metadata only (no
request or result payload), validation failures log at WARNING, domain
execution exceptions log at ERROR with the exception type only, and
importing the engine configures nothing (no handlers on the ``start``
logger by import alone — checked in a subprocess, since this test
process attaches its own capturing handler).
"""
import io
import json
import logging
import subprocess
import sys
import unittest
from pathlib import Path

from contracts.plan_limits import check_plan_limits
from contracts.scenarios import Scenario
from domains.base import DomainModule
from domains.food import FoodDomain
from engine.event_log import JsonFormatter
from engine.planning_engine import PlanningEngine

TREE_ROOT = Path(__file__).resolve().parent.parent

BASE = {
    # Distinctive population: must never appear in any log record.
    "population": 123456789,
    "supply_kcal_per_capita_per_day": 2800,
    "requirement_kcal_per_capita_per_day": 2500,
    "imports_kcal_per_capita_per_day": 100,
    "losses_fraction": 0.08,
}


class FailingValidationDomain(DomainModule):
    """Validation fails; calculation must never run."""
    domain_id = "failing"

    def validate_inputs(self, request):
        return {"ok": False, "problems": ["missing sentinel field"],
                "warnings": [], "assumptions": []}

    def calculate(self, request):
        raise AssertionError("calculate must not run after failed validation")

    def identify_constraints(self, request):
        return []

    def evaluate(self, calc):
        return {"overall_status": "PASS", "constraint_results": [], "warnings": []}

    def describe_uncertainty(self, calc):
        return []


class ExplodingDomain(DomainModule):
    """Validation passes; calculation raises."""
    domain_id = "exploding"

    def validate_inputs(self, request):
        return {"ok": True, "problems": [], "warnings": [], "assumptions": []}

    def calculate(self, request):
        raise RuntimeError("boom-sentinel")

    def identify_constraints(self, request):
        return []

    def evaluate(self, calc):
        return {"overall_status": "PASS", "constraint_results": [], "warnings": []}

    def describe_uncertainty(self, calc):
        return []


class CaptureLogs(unittest.TestCase):
    """Attach a JSON-lines capturing handler to the ``start`` logger."""

    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())
        self.start_logger = logging.getLogger("start")
        self._old_level = self.start_logger.level
        self.start_logger.setLevel(logging.INFO)
        self.start_logger.addHandler(self.handler)
        # Keep WARNING/ERROR records from reaching logging.lastResort
        # (stderr) during the run; the capturing handler still sees them.
        self._root_null = logging.NullHandler()
        logging.getLogger().addHandler(self._root_null)

    def tearDown(self):
        self.start_logger.removeHandler(self.handler)
        self.start_logger.setLevel(self._old_level)
        logging.getLogger().removeHandler(self._root_null)
        self.handler.close()

    def records(self):
        """Captured records, parsed from the JSON-lines stream."""
        lines = [line for line in self.stream.getvalue().splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    def events(self, name):
        return [r for r in self.records() if r.get("event") == name]

    def record_text(self):
        return self.stream.getvalue()


class TestIssue27EngineRunLogging(CaptureLogs):
    def test_run_emits_json_lines_with_required_keys(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        result = engine.run("food", BASE)
        self.assertEqual(result["calculation"]["calculation_status"], "COMPLETED")

        started = self.events("engine.run.started")
        completed = self.events("engine.run.completed")
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)

        for record in self.records():
            for key in ("timestamp", "level", "logger", "event", "message"):
                self.assertIn(key, record, record)
            self.assertEqual(record["logger"], "start.engine")
            self.assertTrue(record["timestamp"].endswith("Z"))
        self.assertEqual(started[0]["level"], "INFO")
        self.assertEqual(started[0]["domain_id"], "food")
        self.assertEqual(completed[0]["level"], "INFO")
        self.assertEqual(completed[0]["domain_id"], "food")
        self.assertEqual(completed[0]["calculation_status"], "COMPLETED")
        self.assertEqual(completed[0]["overall_status"], "PASS")
        self.assertIs(completed[0]["needs_human_decision"], True)

    def test_info_records_contain_no_request_or_result_payload(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        engine.run("food", BASE)

        text = self.record_text()
        # The distinctive request values must not appear anywhere.
        self.assertNotIn("123456789", text)
        self.assertNotIn("2800", text)
        for record in self.records():
            if record["level"] == "INFO":
                # No payload-shaped keys on any INFO record.
                for banned in ("plan", "request", "result", "metrics",
                               "calculation", "evaluation"):
                    self.assertNotIn(banned, record, record)

    def test_validation_failure_emits_warning(self):
        engine = PlanningEngine()
        engine.register(FailingValidationDomain())
        result = engine.run("failing", {"anything": 1})
        self.assertEqual(result["calculation"]["calculation_status"],
                         "INSUFFICIENT_INPUT")

        failed = self.events("engine.run.validation_failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["level"], "WARNING")
        self.assertEqual(failed[0]["domain_id"], "failing")
        self.assertEqual(failed[0]["reason"], "validation_failed")
        self.assertEqual(failed[0]["problem_count"], 1)

    def test_unknown_domain_emits_warning(self):
        engine = PlanningEngine()
        result = engine.run("no-such-domain", {})
        self.assertEqual(result["calculation"]["calculation_status"], "ERROR")

        unknown = self.events("engine.run.unknown_domain")
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["level"], "WARNING")
        self.assertEqual(unknown[0]["domain_id"], "no-such-domain")

    def test_domain_execution_exception_emits_error_with_type_only(self):
        engine = PlanningEngine()
        engine.register(ExplodingDomain())
        result = engine.run("exploding", {})
        self.assertEqual(result["calculation"]["calculation_status"], "ERROR")

        errors = self.events("engine.run.domain_error")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["level"], "ERROR")
        self.assertEqual(errors[0]["domain_id"], "exploding")
        self.assertEqual(errors[0]["exception_type"], "RuntimeError")
        # The exception message is payload-adjacent: type only, never text.
        self.assertNotIn("boom-sentinel", self.record_text())

    def test_run_scenario_emits_started_and_completed(self):
        engine = PlanningEngine()
        engine.register(FoodDomain())
        scenario = Scenario("s1", "S", metadata={"base_request": BASE})
        result = engine.run_scenario("food", scenario)
        self.assertEqual(result["calculation_status"], "COMPLETED")

        started = self.events("engine.run_scenario.started")
        completed = self.events("engine.run_scenario.completed")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["scenario_id"], "s1")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["scenario_id"], "s1")
        self.assertEqual(completed[0]["calculation_status"], "COMPLETED")
        self.assertIs(completed[0]["needs_human_decision"], True)


class TestIssue27CheckPlanLogging(CaptureLogs):
    def test_check_plan_emits_completed_with_status_and_count_only(self):
        engine = PlanningEngine()
        # Distinctive plan value: must never appear in a log record.
        result = engine.check_plan({
            "phosphorus_application_tg_per_year": 4.321,
            "food_kcal_per_capita_per_day": 2600,
            "paid_work_hours_per_week": 40,
        })
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["failed_count"], 0)

        completed = self.events("engine.check_plan.completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["overall_status"], "PASS")
        self.assertEqual(completed[0]["failed_count"], 0)
        self.assertNotIn("4.321", self.record_text())
        self.assertNotIn("2600", self.record_text())

    def test_check_plan_limits_direct_emits_one_info_event(self):
        result = check_plan_limits({
            "phosphorus_application_tg_per_year": 4.321,
            "food_kcal_per_capita_per_day": 2600,
        })
        self.assertEqual(result["overall_status"], "PASS")

        completed = self.events("contracts.check_plan_limits.completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["logger"], "start.contracts")
        self.assertEqual(completed[0]["level"], "INFO")
        self.assertEqual(completed[0]["overall_status"], "PASS")
        self.assertEqual(completed[0]["failed_count"], 0)
        self.assertEqual(completed[0]["check_count"], 2)
        self.assertNotIn("4.321", self.record_text())


class TestIssue27ImportConfiguresNothing(unittest.TestCase):
    def test_import_adds_no_handlers_to_start_logger(self):
        # Subprocess: this test process has already attached its own
        # capturing handler to `start`, so only a fresh interpreter
        # can prove that importing configures nothing.
        code = (
            "import engine.planning_engine, engine.event_log, "
            "contracts.plan_limits, contracts.models; "
            "import logging; "
            "print(len(logging.getLogger('start').handlers))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(TREE_ROOT), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "0", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
