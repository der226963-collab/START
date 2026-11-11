"""Tests for the mini_ai/eval task/metric/filter registry.

These are unittest tests, so `python -m unittest discover -s tests`
picks them up. They check the registry end-to-end on a tiny synthetic
task with a stub scorer — no real model, no paid API, no lm-eval
dependency. Original code throughout; the design is rebuilt from the
sweep's description of LM-Eval-Harness, never from its source.
"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_ai.eval import (
    EvalTask,
    FilterRegistry,
    MetricRegistry,
    TaskRegistry,
    YamlSubsetError,
    accuracy,
    apply_filters,
    exact_match,
    load_builtin_tasks,
    load_task,
    parse_yaml_subset,
    perplexity,
    resolve_filter,
    results_to_json,
    run_task,
    run_task_by_name,
    task_from_dict,
)
from mini_ai.eval.filters import FILTER_REGISTRY
from mini_ai.eval.metrics import METRIC_REGISTRY
from mini_ai.eval.tasks import TASK_REGISTRY

HERE = os.path.dirname(__file__)
QA_TOY_PATH = os.path.join(HERE, "..", "mini_ai", "eval", "tasks", "qa_toy.yaml")


def _toy_task():
    return EvalTask(
        name="toy",
        description="Tiny synthetic task for tests.",
        prompt_template="Question: {question}\nAnswer:",
        items=[
            {"question": "What is the capital of France?", "answer": "paris"},
            {"question": "What is 2 + 3?", "answer": "5"},
            {"question": "What is the chemical symbol for water?", "answer": "h2o"},
            {"question": "What is the largest planet?", "answer": "jupiter"},
        ],
        metric_names=["exact_match", "accuracy"],
        filter_specs=["strip", "lowercase"],
    )


def _stub_scorer(prompt):
    """Stub scorer: right on 3 of 4, wrong on the planet question."""
    if "capital of France" in prompt:
        return " Paris "  # needs strip + lowercase to match
    if "2 + 3" in prompt:
        return "5"
    if "chemical symbol" in prompt:
        return "H2O"  # needs lowercase to match
    return "mars"  # wrong: reference is jupiter


class TestYamlSubset(unittest.TestCase):
    def test_plain_mapping_and_scalars(self):
        data = parse_yaml_subset("name: qa_toy\ncount: 4\nratio: 1.5\nok: true\nnothing: null\n")
        self.assertEqual(
            data, {"name": "qa_toy", "count": 4, "ratio": 1.5, "ok": True, "nothing": None}
        )

    def test_comments_and_quoted_strings(self):
        text = (
            "# full-line comment\n"
            'title: "Q&A: with a # inside quotes"  # trailing comment\n'
            "single: 'it''s quoted'\n"
        )
        data = parse_yaml_subset(text)
        self.assertEqual(data["title"], "Q&A: with a # inside quotes")
        self.assertEqual(data["single"], "it's quoted")

    def test_inline_list_and_nested_mapping(self):
        text = "metrics: [exact_match, accuracy]\nnested:\n  a: 1\n  b: two\n"
        data = parse_yaml_subset(text)
        self.assertEqual(data["metrics"], ["exact_match", "accuracy"])
        self.assertEqual(data["nested"], {"a": 1, "b": "two"})

    def test_list_of_mappings(self):
        text = (
            "filters:\n"
            "  - name: extract_after_marker\n"
            '    marker: "Answer:"\n'
            "  - strip\n"
        )
        data = parse_yaml_subset(text)
        self.assertEqual(
            data["filters"],
            [{"name": "extract_after_marker", "marker": "Answer:"}, "strip"],
        )

    def test_block_scalar_rejected(self):
        with self.assertRaises(YamlSubsetError):
            parse_yaml_subset("description: |\n  multi\n  line\n")

    def test_duplicate_key_rejected(self):
        with self.assertRaises(YamlSubsetError):
            parse_yaml_subset("name: a\nname: b\n")

    def test_empty_document_rejected(self):
        with self.assertRaises(YamlSubsetError):
            parse_yaml_subset("# only a comment\n")


class TestRegistries(unittest.TestCase):
    def test_task_register_and_retrieve_round_trip(self):
        registry = TaskRegistry()
        task = _toy_task()
        registry.register(task)
        self.assertIs(registry.get("toy"), task)
        self.assertIn("toy", registry.list())

    def test_unknown_task_raises_key_error(self):
        self.assertNotIn("no_such_task", TASK_REGISTRY)
        with self.assertRaises(KeyError):
            TASK_REGISTRY.get("no_such_task")

    def test_metric_register_and_retrieve_round_trip(self):
        registry = MetricRegistry()
        registry.register("double", lambda scores: 2.0 * sum(scores), "aggregate", "test only")
        func, kind, _desc = registry.get("double")
        self.assertEqual(kind, "aggregate")
        self.assertEqual(func([1, 0]), 2.0)
        self.assertIn("double", registry.list())

    def test_filter_register_and_retrieve_round_trip(self):
        registry = FilterRegistry()
        registry.register("shout", lambda text: text.upper())
        self.assertEqual(registry.get("shout")("abc"), "ABC")

    def test_builtins_registered(self):
        self.assertIn("exact_match", METRIC_REGISTRY.list())
        self.assertIn("accuracy", METRIC_REGISTRY.list())
        self.assertIn("perplexity", METRIC_REGISTRY.list())
        for name in ("strip", "lowercase", "take_first_line",
                     "collapse_whitespace", "extract_after_marker"):
            self.assertIn(name, FILTER_REGISTRY.list())


class TestFilters(unittest.TestCase):
    def test_strip_then_lowercase(self):
        self.assertEqual(apply_filters(" Paris ", ["strip", "lowercase"]), "paris")

    def test_filter_order_matters(self):
        # Extract first, then lowercase: marker matches, then case folds.
        forward = apply_filters(
            "Answer: Paris",
            [{"name": "extract_after_marker", "marker": "Answer:"}, "strip", "lowercase"],
        )
        self.assertEqual(forward, "paris")
        # Lowercase first: the case-sensitive marker no longer matches,
        # so nothing is extracted.
        reversed_order = apply_filters(
            "Answer: Paris",
            ["lowercase", {"name": "extract_after_marker", "marker": "Answer:"}, "strip"],
        )
        self.assertEqual(reversed_order, "answer: paris")

    def test_take_first_line_and_collapse_whitespace(self):
        self.assertEqual(apply_filters("  Paris\nsecond line", ["take_first_line", "strip"]), "Paris")
        self.assertEqual(apply_filters("a   b\t c", ["collapse_whitespace"]), "a b c")

    def test_unknown_filter_raises_key_error(self):
        with self.assertRaises(KeyError):
            resolve_filter("no_such_filter")

    def test_non_string_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            apply_filters(42, ["strip"])


class TestMetrics(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(exact_match("paris", "paris"))
        self.assertFalse(exact_match("Paris", "paris"))  # case-sensitive: filters normalise
        self.assertFalse(exact_match("paris ", "paris"))

    def test_accuracy_on_hand_scored_set(self):
        # 3 of 4 correct.
        self.assertAlmostEqual(accuracy([1, 1, 1, 0]), 0.75)
        self.assertAlmostEqual(accuracy([True, False]), 0.5)
        with self.assertRaises(ValueError):
            accuracy([])

    def test_perplexity_from_log_probs_hand_computed(self):
        # exp(-(ln 0.5 + ln 0.25) / 2) = sqrt(8).
        value = perplexity(log_probs=[math.log(0.5), math.log(0.25)])
        self.assertAlmostEqual(value, math.sqrt(8), places=9)
        self.assertAlmostEqual(value, 2.8284271247461903, places=9)

    def test_perplexity_from_token_losses_hand_computed(self):
        # exp((ln 2 + ln 4) / 2) = sqrt(8) — same value, other convention.
        value = perplexity(token_losses=[math.log(2), math.log(4)])
        self.assertAlmostEqual(value, math.sqrt(8), places=9)

    def test_perplexity_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            perplexity(log_probs=[])
        with self.assertRaises(ValueError):
            perplexity(log_probs=[0.5])  # positive: not a log-prob
        with self.assertRaises(ValueError):
            perplexity(token_losses=[-1.0])  # negative: not a loss
        with self.assertRaises(ValueError):
            perplexity()  # neither given
        with self.assertRaises(ValueError):
            perplexity(log_probs=[-1.0], token_losses=[1.0])  # both given


class TestTaskLoading(unittest.TestCase):
    def test_load_qa_toy_yaml(self):
        registry = TaskRegistry()
        task = load_task(QA_TOY_PATH, registry=registry)
        self.assertEqual(task.name, "qa_toy")
        self.assertEqual(len(task.items), 4)
        self.assertEqual(task.metric_names, ["exact_match", "accuracy"])
        self.assertEqual(task.filter_specs, ["strip", "lowercase"])
        self.assertEqual(task.items[0]["answer"], "paris")
        self.assertIs(registry.get("qa_toy"), task)

    def test_load_builtin_tasks(self):
        registry = TaskRegistry()
        loaded = load_builtin_tasks(registry=registry)
        self.assertEqual([t.name for t in loaded], ["qa_toy"])
        self.assertIn("qa_toy", registry.list())

    def test_task_from_dict_validates(self):
        with self.assertRaises(ValueError):  # missing answer
            task_from_dict({
                "name": "bad", "description": "d",
                "prompt_template": "Q: {question}",
                "items": [{"question": "x"}],
            })
        with self.assertRaises(KeyError):  # unknown metric
            task_from_dict({
                "name": "bad", "description": "d",
                "prompt_template": "Q: {question}",
                "items": [{"question": "x", "answer": "y"}],
                "metrics": ["no_such_metric"],
            })
        with self.assertRaises(KeyError):  # unknown filter
            task_from_dict({
                "name": "bad", "description": "d",
                "prompt_template": "Q: {question}",
                "items": [{"question": "x", "answer": "y"}],
                "filters": ["no_such_filter"],
            })

    def test_render_prompt_never_leaks_answer(self):
        task = _toy_task()
        prompt = task.render_prompt(task.items[0])
        self.assertIn("capital of France", prompt)
        self.assertNotIn("paris", prompt)


class TestRunner(unittest.TestCase):
    def test_end_to_end_toy_task_with_stub_scorer(self):
        task = _toy_task()
        results = run_task(task, _stub_scorer)
        self.assertEqual(results["task"], "toy")
        self.assertEqual(results["num_items"], 4)
        self.assertAlmostEqual(results["metrics"]["exact_match"], 0.75)
        self.assertAlmostEqual(results["metrics"]["accuracy"], 0.75)
        self.assertNotIn("perplexity", results["metrics"])  # not requested: no key at all
        self.assertEqual(results["per_item"][0]["filtered_prediction"], "paris")
        self.assertEqual(results["per_item"][3]["filtered_prediction"], "mars")
        self.assertFalse(results["per_item"][3]["exact_match"])
        # Governance flags are always present.
        self.assertTrue(results["needs_human_decision"])
        self.assertFalse(results["verified"])

    def test_end_to_end_qa_toy_yaml_with_stub_scorer(self):
        registry = TaskRegistry()
        load_task(QA_TOY_PATH, registry=registry)
        results = run_task_by_name("qa_toy", _stub_scorer, registry=registry)
        self.assertAlmostEqual(results["metrics"]["exact_match"], 0.75)
        self.assertAlmostEqual(results["metrics"]["accuracy"], 0.75)

    def test_end_to_end_perplexity_from_log_prob_scorer(self):
        task = _toy_task()

        def logprob_scorer(prompt):
            # Every item: two tokens at p=0.5 -> per-item ppl 2.0.
            return {"text": "x", "log_probs": [math.log(0.5), math.log(0.5)]}

        results = run_task(task, logprob_scorer, metric_names=["perplexity"])
        self.assertAlmostEqual(results["metrics"]["perplexity"], 2.0)

    def test_perplexity_none_when_scorer_has_no_log_probs(self):
        results = run_task(_toy_task(), _stub_scorer, metric_names=["perplexity"])
        self.assertIsNone(results["metrics"]["perplexity"])
        self.assertTrue(any("log-probs" in note for note in results["notes"]))

    def test_unknown_metric_raises_before_running(self):
        calls = []

        def counting_scorer(prompt):
            calls.append(prompt)
            return "x"

        with self.assertRaises(KeyError):
            run_task(_toy_task(), counting_scorer, metric_names=["no_such_metric"])
        self.assertEqual(calls, [])  # nothing scored

    def test_results_are_jsonable(self):
        results = run_task(_toy_task(), _stub_scorer)
        text = results_to_json(results)
        back = json.loads(text)
        self.assertEqual(back["metrics"]["exact_match"], 0.75)
        self.assertTrue(back["needs_human_decision"])
        self.assertFalse(back["verified"])


if __name__ == "__main__":
    unittest.main()
