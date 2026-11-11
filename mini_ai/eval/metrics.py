"""Metric registry for eval — original code.

Idea rebuilt from the LM-Eval-Harness description in the sweep
(``lm_eval/api/metrics.py``: named metrics computed over task
results). No lm-eval code was read or copied; the metric names are
the standard ones, the implementations here are original.

Three metric kinds, distinguished by what they take:

- ``pairwise`` — ``fn(prediction, reference) -> bool``.
  ``exact_match`` is the only pairwise metric: strict equality.
  Normalisation (case, whitespace) is the filter pipeline's job,
  not the metric's, so a score of ``False`` means "did not match
  after the task's filters", which is the honest statement.
- ``aggregate`` — ``fn(scores) -> float`` where ``scores`` is a list
  of per-item numbers (usually 0/1 from ``exact_match``).
  ``accuracy`` is the mean of the per-item scores.
- ``logprob`` — ``fn(log_probs=None, token_losses=None) -> float``.
  ``perplexity`` takes either per-token natural-log probabilities
  (each ``<= 0``) or per-token losses (each ``>= 0``, i.e. negative
  log-likelihoods). Exactly one of the two must be given::

      perplexity = exp(-mean(log_probs)) = exp(mean(token_losses))

  A model (or stub scorer) supplies log-probs per item; the runner
  averages the per-item perplexities. Perplexity needs a scorer
  that returns log-probs — a plain-text scorer simply has no
  perplexity, and the runner reports ``None`` with a note instead
  of inventing one.
"""

import math

__all__ = [
    "METRIC_REGISTRY",
    "MetricRegistry",
    "accuracy",
    "exact_match",
    "perplexity",
    "register_metric",
]


def exact_match(prediction, reference):
    """Strict equality of prediction and reference (both strings)."""
    if not isinstance(prediction, str) or not isinstance(reference, str):
        raise TypeError("exact_match compares two strings")
    return prediction == reference


def accuracy(scores):
    """Mean of per-item scores (each 0/1, True/False, or a float).

    ``scores`` must be non-empty. Returns a float in [0, 1] when the
    inputs are 0/1 values. This is the aggregation step: the runner
    feeds it the per-item ``exact_match`` results.
    """
    scores = list(scores)
    if not scores:
        raise ValueError("accuracy needs at least one score")
    return sum(float(s) for s in scores) / len(scores)


def perplexity(log_probs=None, token_losses=None):
    """Perplexity from per-token log-probs OR per-token losses.

    Exactly one argument must be given, and it must be non-empty.
    ``log_probs`` are natural-log probabilities (``<= 0``);
    ``token_losses`` are negative log-likelihoods (``>= 0``).
    A log-prob above 0, or a loss below 0, raises ``ValueError`` —
    both would mean the caller mixed up the two conventions.

    Hand-check: ``log_probs = [ln(0.5), ln(0.25)]`` gives
    ``exp(-(ln 0.5 + ln 0.25) / 2) = sqrt(8) ≈ 2.828427``.
    """
    if (log_probs is None) == (token_losses is None):
        raise ValueError("perplexity needs exactly one of log_probs / token_losses")
    if log_probs is not None:
        values = list(log_probs)
        if not values:
            raise ValueError("perplexity needs at least one log-prob")
        if any(v > 0 for v in values):
            raise ValueError("log-probs must be <= 0")
        return math.exp(-sum(values) / len(values))
    values = list(token_losses)
    if not values:
        raise ValueError("perplexity needs at least one token loss")
    if any(v < 0 for v in values):
        raise ValueError("token losses must be >= 0")
    return math.exp(sum(values) / len(values))


class MetricRegistry:
    """A name -> (function, kind, description) registry. One global
    instance exists as :data:`METRIC_REGISTRY`."""

    def __init__(self):
        self._metrics = {}

    def register(self, name, func, kind, description=""):
        """Register ``func`` under ``name`` with its ``kind``
        (``"pairwise"``, ``"aggregate"`` or ``"logprob"``)."""
        if kind not in ("pairwise", "aggregate", "logprob"):
            raise ValueError(f"unknown metric kind: {kind!r}")
        if not isinstance(name, str) or not name:
            raise ValueError("metric name must be a non-empty string")
        if not callable(func):
            raise TypeError("metric must be callable")
        self._metrics[name] = (func, kind, description)
        return func

    def get(self, name):
        """Return ``(func, kind, description)`` for ``name``."""
        try:
            return self._metrics[name]
        except KeyError:
            raise KeyError(f"unknown metric: {name!r}") from None

    def __contains__(self, name):
        return name in self._metrics

    def list(self):
        """Sorted list of registered metric names."""
        return sorted(self._metrics)


METRIC_REGISTRY = MetricRegistry()
METRIC_REGISTRY.register(
    "exact_match", exact_match, "pairwise",
    "Strict equality of filtered prediction and reference.",
)
METRIC_REGISTRY.register(
    "accuracy", accuracy, "aggregate",
    "Mean of the per-item exact-match scores.",
)
METRIC_REGISTRY.register(
    "perplexity", perplexity, "logprob",
    "exp(-mean log-prob) over per-token log-probs, or exp(mean loss).",
)


def register_metric(name, kind, description="", registry=None):
    """Register a metric function under ``name`` in ``registry``
    (default global). Usable as a decorator::

        @register_metric("my_metric", "aggregate", "What it measures")
        def my_metric(scores): ...
    """
    reg = registry if registry is not None else METRIC_REGISTRY

    def _register(func):
        reg.register(name, func, kind, description)
        return func

    return _register
