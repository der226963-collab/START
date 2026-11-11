"""Fault-injection experiment tests (Tumult experiment-pattern rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.fault_injection.synthetic_worker):
no network, no real plans, no Tumult daemon. Never claim a test
passed unless it ran here.
"""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import fault_injection as fi  # noqa: E402


class TestCrashFault(unittest.TestCase):
    def test_crash_restarts_once_then_recovers_but_stays_unverified(self):
        report = fi.run_experiment(
            "exp-crash-1",
            "the supervised run recovers from one worker crash",
            fi.make_fault("worker_crash", fail_attempts=1, max_restarts=2),
            fi.synthetic_worker)
        self.assertTrue(report["injected"])
        self.assertTrue(report["detected"])
        self.assertEqual(report["recovery"]["restarts"], 1)
        self.assertTrue(report["recovery"]["restarted"])
        # Recovered — but still UNKNOWN, never PASS: the restarted
        # worker's output still needs the verify step.
        self.assertEqual(report["outcome"], "UNKNOWN")
        self.assertIs(report["verified"], False)
        self.assertTrue(report["needs_human_decision"])
        self.assertEqual(report["result"],
                         {"delivered_t": 600, "shortage_t": 50})

    def test_crash_with_exhausted_restart_budget_is_fail(self):
        report = fi.run_experiment(
            "exp-crash-2",
            "a worker that keeps crashing exhausts its restart budget",
            fi.make_fault("worker_crash", fail_attempts=5, max_restarts=2),
            fi.synthetic_worker)
        self.assertEqual(report["recovery"]["restarts"], 2)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertIs(report["verified"], False)
        self.assertIsNone(report["result"])

    def test_crash_with_zero_restart_budget_is_fail_without_restart(self):
        report = fi.run_experiment(
            "exp-crash-3",
            "no restart budget means one crash is terminal",
            fi.make_fault("worker_crash", fail_attempts=1, max_restarts=0),
            fi.synthetic_worker)
        self.assertEqual(report["recovery"]["restarts"], 0)
        self.assertFalse(report["recovery"]["restarted"])
        self.assertEqual(report["outcome"], "FAIL")
        self.assertIs(report["verified"], False)

    def test_crash_fault_never_calls_worker_on_failed_attempt(self):
        seen = []

        def tracking_worker(attempt):
            seen.append(attempt)
            return {"delivered_t": 600, "shortage_t": 50}

        fi.run_experiment(
            "exp-crash-4",
            "the injected crash happens before the worker is called",
            fi.make_fault("worker_crash", fail_attempts=2, max_restarts=2),
            tracking_worker)
        # Attempts 1 and 2 are injected crashes; only attempt 3
        # reaches the worker.
        self.assertEqual(seen, [3])


class TestDelayFault(unittest.TestCase):
    def test_delay_past_timeout_is_detected_unknown_and_result_rejected(self):
        report = fi.run_experiment(
            "exp-delay-1",
            "a response slower than the timeout is not accepted",
            fi.make_fault("delayed_response", delay_ms=150, timeout_ms=100),
            fi.synthetic_worker)
        self.assertTrue(report["detected"])
        self.assertTrue(report["recovery"]["timed_out"])
        self.assertEqual(report["recovery"]["timeout_ms"], 100)
        self.assertEqual(report["outcome"], "UNKNOWN")
        self.assertIs(report["verified"], False)
        self.assertIsNone(report["result"])

    def test_delay_inside_timeout_is_not_detected_but_still_unverified(self):
        report = fi.run_experiment(
            "exp-delay-2",
            "a response inside the timeout is not a timeout",
            fi.make_fault("delayed_response", delay_ms=50, timeout_ms=100),
            fi.synthetic_worker)
        self.assertFalse(report["detected"])
        self.assertFalse(report["recovery"]["timed_out"])
        # Still UNKNOWN, never PASS: a fault run never verifies.
        self.assertEqual(report["outcome"], "UNKNOWN")
        self.assertIs(report["verified"], False)
        self.assertEqual(report["result"],
                         {"delivered_t": 600, "shortage_t": 50})

    def test_delay_exactly_at_timeout_is_not_a_timeout(self):
        # Boundary is strict: delay > timeout times out, delay ==
        # timeout does not (matches the Rust half exactly).
        self.assertFalse(fi.delay_exceeds_timeout(100, 100))
        self.assertTrue(fi.delay_exceeds_timeout(101, 100))
        self.assertFalse(fi.delay_exceeds_timeout(99, 100))


class TestCorruptionFault(unittest.TestCase):
    def test_corrupted_delivered_value_is_detected_fail_and_rejected(self):
        report = fi.run_experiment(
            "exp-corrupt-1",
            "a candidate altered in transit must be rejected",
            fi.make_fault("corrupted_value", received_t=650),
            fi.synthetic_worker)
        self.assertTrue(report["detected"])
        self.assertEqual(report["outcome"], "FAIL")
        self.assertIs(report["verified"], False)
        # The corrupted value is discarded, never accepted.
        self.assertIsNone(report["result"])

    def test_corrupted_shortage_value_is_also_a_mismatch(self):
        self.assertTrue(fi.value_is_corrupted(600, 650))
        self.assertTrue(fi.value_is_corrupted(50, 51))
        self.assertFalse(fi.value_is_corrupted(600, 600))

    def test_uncorrupted_value_is_not_detected_but_still_unverified(self):
        report = fi.run_experiment(
            "exp-corrupt-2",
            "an unaltered candidate is not corruption",
            fi.make_fault("corrupted_value", received_t=600),
            fi.synthetic_worker)
        self.assertFalse(report["detected"])
        self.assertEqual(report["outcome"], "UNKNOWN")
        self.assertIs(report["verified"], False)
        self.assertEqual(report["result"],
                         {"delivered_t": 600, "shortage_t": 50})


class TestGovernance(unittest.TestCase):
    def test_no_pass_outcome_can_be_constructed(self):
        with self.assertRaises(ValueError):
            fi.validate_outcome("PASS")
        with self.assertRaises(ValueError):
            fi.validate_outcome("pass")
        self.assertEqual(fi.validate_outcome("FAIL"), "FAIL")
        self.assertEqual(fi.validate_outcome("UNKNOWN"), "UNKNOWN")

    def test_unknown_fault_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            fi.make_fault("drop_message")
        with self.assertRaises(ValueError):
            fi.run_experiment("exp-x", "h", {"kind": "drop_message"},
                              fi.synthetic_worker)

    def test_fault_injector_source_never_sets_verified_true(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "adapters", "fault_injection.py")
        with open(path) as handle:
            source = handle.read()
        self.assertNotIn("verified = True", source)
        self.assertNotIn("verified=True", source)
        self.assertNotIn('"verified": True', source)
        self.assertNotIn("'verified': True", source)
        # The only verified assignment in the module is False.
        self.assertIn('"verified": False', source)

    def test_report_json_round_trip_keeps_verified_false(self):
        report = fi.run_experiment(
            "exp-gov-1", "corruption is rejected",
            fi.make_fault("corrupted_value", received_t=650),
            fi.synthetic_worker)
        back = fi.report_from_json(fi.report_to_json(report))
        self.assertIs(back["verified"], False)
        self.assertEqual(back["outcome"], "FAIL")
        self.assertEqual(back["fault_kind"], "corrupted_value")
        self.assertEqual(back["baseline"],
                         {"delivered_t": 600, "shortage_t": 50})
        # Same keys as the Rust half's report shape.
        self.assertEqual(
            set(back),
            {"schema_version", "experiment_id", "hypothesis",
             "baseline", "fault_kind", "injected", "detected",
             "outcome", "verified", "needs_human_decision",
             "recovery", "result", "licence", "provenance",
             "synthetic"})


class TestEvidenceJournal(unittest.TestCase):
    def test_journal_records_five_phases_in_order(self):
        report = fi.run_experiment(
            "exp-journal-1", "one crash, then recovery",
            fi.make_fault("worker_crash", fail_attempts=1, max_restarts=2),
            fi.synthetic_worker)
        journal = fi.EvidenceJournal()
        journal.record_experiment(report)
        self.assertEqual(len(journal), 5)
        phases = [e["phase"] for e in journal.entries()]
        self.assertEqual(phases, ["hypothesis", "baseline",
                                  "fault_injected", "recovery_measured",
                                  "verdict"])
        verdict = journal.entries()[-1]
        self.assertIn("outcome=UNKNOWN", verdict["detail"])
        self.assertIn("verified=false", verdict["detail"])

    def test_journal_entries_are_all_unverified_and_append_only(self):
        journal = fi.EvidenceJournal()
        journal.record("exp-j-2", "hypothesis", "h")
        self.assertTrue(all(e["verified"] is False
                            for e in journal.entries()))
        # No delete or edit method exists; mutating the returned
        # copy does not change the log.
        copy = journal.entries()
        copy.clear()
        self.assertEqual(len(journal), 1)
        self.assertFalse(hasattr(journal, "delete"))
        self.assertFalse(hasattr(journal, "remove"))
        with self.assertRaises(ValueError):
            journal.record("exp-j-2", "not_a_phase", "x")

    def test_journal_json_round_trip(self):
        journal = fi.EvidenceJournal()
        journal.record("exp-j-3", "hypothesis", "h")
        journal.record("exp-j-3", "verdict",
                       "outcome=FAIL detected=True verified=false")
        back = json.loads(journal.to_json())
        self.assertEqual(len(back), 2)
        self.assertTrue(all(e["verified"] is False for e in back))
        self.assertEqual(back[1]["phase"], "verdict")

    def test_experiment_validation_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            fi.run_experiment("", "h",
                              fi.make_fault("worker_crash"),
                              fi.synthetic_worker)
        with self.assertRaises(ValueError):
            fi.run_experiment("exp-v", "",
                              fi.make_fault("worker_crash"),
                              fi.synthetic_worker)
        with self.assertRaises(TypeError):
            fi.run_experiment("exp-v", "h",
                              fi.make_fault("worker_crash"), None)


if __name__ == "__main__":
    unittest.main()
