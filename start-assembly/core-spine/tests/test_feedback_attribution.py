"""Feedback-attribution tests (Trace feedback-propagation rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.feedback_attribution.synthetic_*):
no network, no LLM, no paid API, no Trace code. Never claim a
test passed unless it ran here.
"""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import feedback_attribution as fa  # noqa: E402


class TestTraceRecording(unittest.TestCase):
    def test_synthetic_trace_has_three_steps_in_order(self):
        trace = fa.synthetic_trace()
        self.assertEqual(trace["trace_id"], "synthetic-food-lp-trace")
        self.assertEqual([s["step_id"] for s in trace["steps"]],
                         ["s1", "s2", "s3"])
        self.assertEqual(trace["steps"][0]["task_id"], "food-lp")
        self.assertEqual(trace["steps"][0]["metric"], "exact-match")
        self.assertEqual(trace["steps"][0]["input_id"],
                         "delivered-tonnes")
        self.assertEqual(trace["steps"][0]["component"], "optimisation")
        self.assertEqual(trace["steps"][0]["output_id"], "delivered-600t")
        self.assertEqual(trace["steps"][1]["input_id"], "shortage-tonnes")
        self.assertEqual(trace["steps"][2]["metric"], "pattern-match")
        self.assertEqual(trace["steps"][2]["component"], "evaluation")
        self.assertIs(trace["verified"], False)
        self.assertTrue(trace["needs_human_decision"])

    def test_duplicate_step_id_is_rejected(self):
        trace = fa.synthetic_trace()
        with self.assertRaises(ValueError):
            fa.record_step(trace, "s1", "food-lp", "exact-match",
                           "delivered-tonnes", "optimisation")
        self.assertEqual(len(trace["steps"]), 3)

    def test_empty_ids_and_bad_trace_are_rejected(self):
        trace = fa.synthetic_trace()
        with self.assertRaises(ValueError):
            fa.record_step(trace, "s4", "", "exact-match",
                           "delivered-tonnes", "optimisation")
        with self.assertRaises(ValueError):
            fa.record_step(trace, "s4", "food-lp", "exact-match",
                           "delivered-tonnes", "")
        with self.assertRaises(ValueError):
            fa.record_step({"steps": "not a list"}, "s4", "food-lp",
                           "exact-match", "delivered-tonnes",
                           "optimisation")
        with self.assertRaises(ValueError):
            fa.new_trace("  ")


class TestEvaluationResult(unittest.TestCase):
    def test_failing_result_is_fail_below_threshold(self):
        result = fa.synthetic_failing_result()
        self.assertEqual(result["task_id"], "food-lp")
        self.assertEqual(result["metric"], "exact-match")
        self.assertEqual(result["input_id"], "delivered-tonnes")
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["threshold"], 1.0)
        self.assertIs(result["passed"], False)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(fa.is_failure(result))
        self.assertIs(result["verified"], False)
        self.assertTrue(result["needs_human_decision"])
        json.dumps(result)

    def test_passing_result_and_custom_threshold(self):
        result = fa.synthetic_passing_result()
        self.assertEqual(result["status"], "PASS")
        self.assertIs(result["passed"], True)
        self.assertFalse(fa.is_failure(result))
        # A partial score passes a lower threshold and fails 1.0.
        partial = fa.make_evaluation_result(
            "food-lp", "exact-match", "delivered-tonnes",
            score=0.6, threshold=0.5)
        self.assertEqual(partial["status"], "PASS")
        strict = fa.make_evaluation_result(
            "food-lp", "exact-match", "delivered-tonnes",
            score=0.6, threshold=1.0)
        self.assertEqual(strict["status"], "FAIL")
        self.assertTrue(fa.is_failure(strict))

    def test_missing_score_is_unknown_not_failure(self):
        result = fa.make_evaluation_result(
            "food-lp", "exact-match", "delivered-tonnes", score=None)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIs(result["passed"], False)
        self.assertFalse(fa.is_failure(result))

    def test_out_of_range_score_or_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            fa.make_evaluation_result("food-lp", "exact-match",
                                      "delivered-tonnes", score=1.5)
        with self.assertRaises(ValueError):
            fa.make_evaluation_result("food-lp", "exact-match",
                                      "delivered-tonnes", score=-0.1)
        with self.assertRaises(ValueError):
            fa.make_evaluation_result("food-lp", "exact-match",
                                      "delivered-tonnes", score=0.0,
                                      threshold=2.0)
        with self.assertRaises(ValueError):
            fa.make_evaluation_result("food-lp", "exact-match",
                                      "delivered-tonnes", score=True)


class TestAttributeFailing(unittest.TestCase):
    def test_failing_score_attributes_to_the_right_step(self):
        trace = fa.synthetic_trace()
        result = fa.synthetic_failing_result()
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["attributed"], True)
        self.assertEqual(attribution["status"], "ATTRIBUTED")
        self.assertEqual(attribution["step_id"], "s1")
        self.assertEqual(attribution["component"], "optimisation")
        self.assertEqual(attribution["output_id"], "delivered-600t")
        self.assertEqual(attribution["task_id"], "food-lp")
        self.assertEqual(attribution["metric"], "exact-match")
        self.assertEqual(attribution["input_id"], "delivered-tonnes")
        self.assertEqual(attribution["score"], 0.0)
        self.assertEqual(attribution["threshold"], 1.0)
        self.assertIs(attribution["is_failure"], True)
        self.assertIn("s1", attribution["feedback"])
        self.assertIn("0.0", attribution["feedback"])
        json.dumps(attribution)

    def test_attribution_never_invents_a_cause(self):
        trace = fa.synthetic_trace()
        attribution = fa.attribute(fa.synthetic_failing_result(), trace)
        self.assertIs(attribution["cause"], None)
        self.assertIs(attribution["cause_inferred"], False)
        # The feedback states observed facts only: no causal claim.
        self.assertIn("cause not inferred", attribution["feedback"])
        self.assertNotIn("because", attribution["feedback"].lower())

    def test_passing_result_attributes_but_reports_no_failure(self):
        trace = fa.synthetic_trace()
        attribution = fa.attribute(fa.synthetic_passing_result(), trace)
        self.assertIs(attribution["attributed"], True)
        self.assertEqual(attribution["step_id"], "s2")
        self.assertEqual(attribution["component"], "optimisation")
        self.assertIs(attribution["is_failure"], False)
        self.assertIn("no failure to propagate", attribution["feedback"])
        self.assertIs(attribution["cause"], None)

    def test_metric_distinguishes_steps_on_the_same_input(self):
        # s1 and s3 share task + input but differ in metric; the
        # pattern-match result must land on s3, not s1.
        trace = fa.synthetic_trace()
        result = fa.make_evaluation_result(
            "food-lp", "pattern-match", "delivered-tonnes",
            score=0.0, threshold=1.0)
        attribution = fa.attribute(result, trace)
        self.assertEqual(attribution["step_id"], "s3")
        self.assertEqual(attribution["component"], "evaluation")


class TestUnattributed(unittest.TestCase):
    def test_unknown_task_is_unattributed_not_guessed(self):
        trace = fa.synthetic_trace()
        result = fa.make_evaluation_result(
            "unknown-task", "exact-match", "delivered-tonnes",
            score=0.0, threshold=1.0)
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["attributed"], False)
        self.assertEqual(attribution["status"], "UNATTRIBUTED")
        self.assertIs(attribution["step_id"], None)
        self.assertIs(attribution["component"], None)
        self.assertIs(attribution["output_id"], None)
        self.assertIs(attribution["is_failure"], True)
        self.assertIs(attribution["cause"], None)
        self.assertIs(attribution["cause_inferred"], False)
        self.assertIn("unattributed", attribution["feedback"].lower())

    def test_partial_match_is_unattributed(self):
        # Right task and metric, wrong input: not the same source,
        # so it must not attribute to s1.
        trace = fa.synthetic_trace()
        result = fa.make_evaluation_result(
            "food-lp", "exact-match", "water-tonnes",
            score=0.0, threshold=1.0)
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["attributed"], False)
        self.assertIs(attribution["step_id"], None)
        self.assertIn("water-tonnes", attribution["reason"])

    def test_missing_key_is_unattributed(self):
        trace = fa.synthetic_trace()
        result = dict(fa.synthetic_failing_result())
        del result["input_id"]
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["attributed"], False)
        self.assertEqual(attribution["status"], "UNATTRIBUTED")
        self.assertIn("input_id", attribution["reason"])

    def test_ambiguous_match_is_unattributed(self):
        # Two steps with different ids but the same task, metric
        # and input: no single source can be identified, so the
        # module must not pick one.
        trace = fa.new_trace("ambiguous-trace")
        fa.record_step(trace, "a1", "food-lp", "exact-match",
                       "delivered-tonnes", "optimisation")
        fa.record_step(trace, "a2", "food-lp", "exact-match",
                       "delivered-tonnes", "optimisation")
        attribution = fa.attribute(fa.synthetic_failing_result(), trace)
        self.assertIs(attribution["attributed"], False)
        self.assertIs(attribution["step_id"], None)
        self.assertIn("2 steps", attribution["reason"])


class TestVerifiedCarried(unittest.TestCase):
    def test_verified_false_is_carried_unchanged(self):
        trace = fa.synthetic_trace()
        attribution = fa.attribute(fa.synthetic_failing_result(), trace)
        self.assertIs(attribution["verified"], False)
        self.assertTrue(attribution["needs_human_decision"])

    def test_verified_flag_arriving_affirmative_is_carried_not_set(self):
        # A result that arrives with the flag set carries it
        # through attribution unchanged; the module never sets
        # it — the source pin below proves no code path writes
        # it affirmatively. Human decision is still required.
        trace = fa.synthetic_trace()
        result = fa.make_evaluation_result(
            "food-lp", "exact-match", "delivered-tonnes",
            score=0.0, threshold=1.0, verified=True)
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["verified"], True)
        self.assertTrue(attribution["needs_human_decision"])
        self.assertEqual(attribution["step_id"], "s1")

    def test_missing_verified_flag_defaults_to_unverified(self):
        trace = fa.synthetic_trace()
        result = dict(fa.synthetic_failing_result())
        del result["verified"]
        attribution = fa.attribute(result, trace)
        self.assertIs(attribution["verified"], False)


class TestPropagateFeedback(unittest.TestCase):
    def test_summary_counts_are_hand_computed(self):
        trace = fa.synthetic_trace()
        results = [
            fa.synthetic_failing_result(),          # FAIL, s1
            fa.synthetic_passing_result(),          # PASS, s2
            fa.make_evaluation_result(              # FAIL, unknown
                "unknown-task", "exact-match", "delivered-tonnes",
                score=0.0, threshold=1.0),
        ]
        envelope = fa.propagate_feedback(results, trace)
        self.assertEqual(envelope["summary"], {
            "total": 3,
            "failures": 2,
            "attributed": 2,
            "unattributed": 1,
            "attributed_failures": 1,
            "unattributed_failures": 1,
        })
        self.assertEqual([a["step_id"] for a in envelope["attributions"]],
                         ["s1", "s2", None])
        self.assertEqual(envelope["trace_id"], "synthetic-food-lp-trace")
        self.assertIs(envelope["verified"], False)
        self.assertTrue(envelope["needs_human_decision"])
        json.dumps(envelope)

    def test_empty_list_propagates_to_empty_summary(self):
        envelope = fa.propagate_feedback([], fa.synthetic_trace())
        self.assertEqual(envelope["summary"], {
            "total": 0, "failures": 0, "attributed": 0,
            "unattributed": 0, "attributed_failures": 0,
            "unattributed_failures": 0,
        })
        with self.assertRaises(ValueError):
            fa.propagate_feedback("not a list", fa.synthetic_trace())
        with self.assertRaises(ValueError):
            fa.attribute("not a result", fa.synthetic_trace())


class TestSourcePin(unittest.TestCase):
    def test_module_source_never_sets_verified_affirmative(self):
        here = os.path.dirname(__file__)
        path = os.path.join(here, "..", "adapters",
                            "feedback_attribution.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("verified=True", source)
        self.assertNotIn("verified = True", source)
        self.assertNotIn('"verified": True', source)
        self.assertIn('carried_verified = bool(result.get("verified", False))',
                      source)
        self.assertIn('"verified": carried_verified', source)
        # No Trace code, no LLM, no paid API, no new dependency:
        # stdlib only (json), and no Trace/optimizer import.
        self.assertNotIn("import openai", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import litellm", source)
        self.assertNotIn("from opto", source)
        self.assertNotIn("import opto", source)
        self.assertNotIn("from trace", source)
        self.assertNotIn("import trace", source)
        self.assertIn("cause_inferred", source)


if __name__ == "__main__":
    unittest.main()
