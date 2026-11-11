"""Evaluation adapter: DeepEval, non-LLM metrics only, locally.

DeepEval (confident-ai/deepeval, Apache-2.0) is an LLM evaluation
framework. Its LLM-as-a-judge metrics (G-Eval, hallucination,
answer relevancy, ...) need an LLM API key and are OUT OF SCOPE
here — they are deferred, not claimed to have run.

What IS in scope locally: deterministic, non-LLM metrics that need
no API key and no model:
* exact-match accuracy on a small golden set (implemented here in
  plain Python, so the test does not depend on DeepEval at all);
* DeepEval's ExactMatchMetric, if deepeval is installed and its
  metric runs without an API key — attempted, and the exact result
  is recorded in ASSEMBLY_REPORT.md. If it needs a key, it is
  reported blocked/stub, not faked.

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
