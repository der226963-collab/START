"""Evaluation adapter: DeepEval, non-LLM metrics only, locally.

DeepEval (confident-ai/deepeval, Apache-2.0) is an LLM evaluation
framework. Its LLM-as-a-judge metrics (G-Eval, hallucination,
answer relevancy, ...) need an LLM API key and are OUT OF SCOPE
here — they are deferred, not claimed to have run.

What IS in scope locally: deterministic, non-LLM metrics that need
no API key and no model:
* exact-match accuracy on a small golden set (implemented here in
  plain Python, so the test does not depend on DeepEval at all);
* DeepEval's ExactMatchMetric, PatternMatchMetric and
  JsonCorrectnessMetric, if deepeval is installed and the metric
  runs without an API key — attempted, and the exact result is
  recorded in ASSEMBLY_REPORT.md. If it needs a key, it is
  reported blocked/stub, not faked. Note the JsonCorrectness
  correction: its default construction builds an OpenAI model and
  needs a key; only eval_mode="system_one" makes it key-free
  (see deepeval_json_correctness).

The golden set is synthetic and tiny on purpose: 4 cases, each a
(question, expected answer, actual answer) triple about the
synthetic food example. Accuracy = exact matches / total.
"""

GOLDEN = [
    ("delivered tonnes in the cross-solver example?", "614", "614"),
    ("shortage tonnes in the cross-solver example?", "57", "57"),
    ("which crop is more water-efficient?", "Potato", "Potato"),
    ("is water the binding constraint?", "yes", "no"),
]

# Pattern-match cases: (output, expected score) for the pattern
# r"\d+ tonnes". PatternMatchMetric uses re.fullmatch, NOT re.search,
# so "614 tonnes extra" scores 0.0 even though it contains a match.
PATTERN = r"\d+ tonnes"
PATTERN_CASES = [
    ("614 tonnes", 1.0),        # full match
    ("614 tonnes extra", 0.0),  # contains a match but is not a full match
    ("no tonnes here", 0.0),    # no match at all
]


try:
    from pydantic import BaseModel as _BaseModel

    class PlanJsonSchema(_BaseModel):
        """Expected schema for JsonCorrectness: a plan result as JSON.

        Original START schema (two integer fields), not copied from
        DeepEval or any candidate.
        """

        delivered: int
        shortage: int

except ImportError:  # pragma: no cover - pydantic ships with deepeval
    PlanJsonSchema = None


# JSON-correctness cases: (output, expected score). Scores are pure
# pydantic model_validate_json results (see deepeval_json_correctness):
# 1 = parses AND validates against PlanJsonSchema, 0 = otherwise.
# Pydantic quirks documented by the tests: the string "614" coerces
# to int 614 (score 1), and unknown extra keys are ignored (score 1).
JSON_CASES = [
    ('{"delivered": 614, "shortage": 57}', 1),   # valid JSON, valid schema
    ('{"delivered": 614,', 0),                   # malformed JSON
    ('{"delivered": 614}', 0),                   # valid JSON, missing field
    ('{"delivered": "abc", "shortage": 57}', 0),  # valid JSON, wrong type
    ('hello', 0),                                # not JSON at all
]


def exact_match_accuracy(cases=GOLDEN):
    """Deterministic exact-match accuracy. No LLM, no API key."""
    if not cases:
        return {"status": "NOT_CHECKED", "accuracy": None,
                "reason": "empty golden set: accuracy is never PASS on no cases"}
    matches = sum(1 for _, expected, actual in cases if expected == actual)
    return {"status": "PASS" if matches == len(cases) else "FAIL",
            "accuracy": matches / len(cases),
            "matches": matches, "total": len(cases),
            "metric": "exact-match (local, no LLM)"}


def deepeval_exact_match():
    """Try DeepEval's ExactMatchMetric on the golden set.

    Returns a dict with status assembled / blocked and the exact
    error if it could not run without an API key. Never claims a
    DeepEval run that did not happen.
    """
    try:
        from deepeval.metrics import ExactMatchMetric
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:
        return {"status": "blocked", "metric": "deepeval ExactMatchMetric",
                "reason": f"deepeval not installed: {exc}"}
    try:
        metric = ExactMatchMetric()
        scores = []
        for question, expected, actual in GOLDEN:
            case = LLMTestCase(input=question, actual_output=actual,
                               expected_output=expected)
            metric.measure(case)
            scores.append(metric.score)
        return {"status": "assembled", "metric": "deepeval ExactMatchMetric",
                "scores": scores,
                "accuracy": sum(scores) / len(scores) if scores else None}
    except Exception as exc:
        return {"status": "blocked", "metric": "deepeval ExactMatchMetric",
                "reason": f"{type(exc).__name__}: {exc}"}


def deepeval_pattern_match(pattern=PATTERN, cases=PATTERN_CASES,
                           ignore_case=False):
    """Try DeepEval's PatternMatchMetric on the pattern cases.

    Verified in deepeval 4.3.3: PatternMatchMetric exists, takes no
    model and no API key, and scores with re.fullmatch (1.0 full
    match, else 0.0). An invalid regex raises ValueError at
    construction — that is reported as blocked, never faked.
    """
    try:
        from deepeval.metrics import PatternMatchMetric
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:
        return {"status": "blocked", "metric": "deepeval PatternMatchMetric",
                "reason": f"deepeval not installed: {exc}"}
    try:
        metric = PatternMatchMetric(pattern=pattern, ignore_case=ignore_case)
    except ValueError as exc:
        return {"status": "blocked", "metric": "deepeval PatternMatchMetric",
                "reason": f"ValueError: {exc}"}
    try:
        scores = []
        for output, _ in cases:
            case = LLMTestCase(input="pattern check", actual_output=output)
            metric.measure(case)
            scores.append(metric.score)
        return {"status": "assembled", "metric": "deepeval PatternMatchMetric",
                "pattern": pattern, "scores": scores,
                "accuracy": sum(scores) / len(scores) if scores else None}
    except Exception as exc:
        return {"status": "blocked", "metric": "deepeval PatternMatchMetric",
                "reason": f"{type(exc).__name__}: {exc}"}


def deepeval_json_correctness(cases=JSON_CASES):
    """Try DeepEval's JsonCorrectnessMetric on the JSON cases.

    CORRECTION to the sweep: the sweep called JsonCorrectnessMetric
    a model-free metric, but in deepeval 4.3.3 its default
    construction calls initialize_model(None), which builds a
    default OpenAIModel and raises DeepEvalError ("OpenAI API key
    is not configured") when no key is set. The score itself is
    deterministic — pure pydantic model_validate_json against the
    expected schema — but the metric is only key-free via
    eval_mode="system_one", which makes initialize_model return
    (None, True) and the reason fall back to the pydantic
    validation error instead of an LLM-generated reason. That is
    the route used here, with async_mode=False so the synchronous
    _validate path runs; model is None, so no LLM call is possible
    on any code path taken. If construction ever fails, the result
    is reported blocked with the exact error, never faked.
    """
    if PlanJsonSchema is None:
        return {"status": "blocked",
                "metric": "deepeval JsonCorrectnessMetric",
                "reason": "pydantic not installed"}
    try:
        from deepeval.metrics import JsonCorrectnessMetric
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:
        return {"status": "blocked",
                "metric": "deepeval JsonCorrectnessMetric",
                "reason": f"deepeval not installed: {exc}"}
    try:
        metric = JsonCorrectnessMetric(
            expected_schema=PlanJsonSchema, eval_mode="system_one",
            async_mode=False)
    except Exception as exc:
        return {"status": "blocked",
                "metric": "deepeval JsonCorrectnessMetric",
                "reason": f"{type(exc).__name__}: {exc}"}
    try:
        scores = []
        reasons = []
        for output, _ in cases:
            case = LLMTestCase(input="json check", actual_output=output)
            metric.measure(case)
            scores.append(metric.score)
            reasons.append(metric.reason)
        return {"status": "assembled",
                "metric": "deepeval JsonCorrectnessMetric",
                "model": None, "eval_mode": "system_one",
                "scores": scores, "reasons": reasons,
                "accuracy": sum(scores) / len(scores) if scores else None}
    except Exception as exc:
        return {"status": "blocked",
                "metric": "deepeval JsonCorrectnessMetric",
                "reason": f"{type(exc).__name__}: {exc}"}
