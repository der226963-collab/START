"""End-to-end eval runner — original code.

Runs one registered task against a caller-supplied scorer and
returns a plain JSON-able results dict. The scorer is any callable
``scorer(prompt) -> str`` or ``scorer(prompt) -> {"text": str,
"log_probs": [float, ...]}`` — a stub scorer in tests, a real model
wrapper in real use. The runner never imports a model and never
calls a paid API; there is no model backend in this package at all.

Governance, stated in the results themselves so it cannot be
missed:

- Every result carries ``needs_human_decision: True`` and
  ``verified: False``. Eval scores are model results, never
  verified plans. Nothing in this package marks anything verified,
  and no score here may bypass the verify step.
- Perplexity is reported only when the scorer actually supplied
  per-token log-probs; otherwise it is ``None`` with a note. A
  missing measurement is reported as missing, not invented.
"""

import json

from .filters import apply_filters
from .metrics import METRIC_REGISTRY, exact_match
from .tasks import TASK_REGISTRY

__all__ = ["results_to_json", "run_task", "run_task_by_name"]


def _normalise_scorer_output(output, prompt):
    """Split a scorer return into ``(text, log_probs-or-None)``."""
    if isinstance(output, str):
        return output, None
    if isinstance(output, dict):
        if "text" not in output or not isinstance(output["text"], str):
            raise ValueError(
                f"scorer for prompt {prompt!r} returned a dict without a 'text' string"
            )
        log_probs = output.get("log_probs")
        if log_probs is not None:
            if not isinstance(log_probs, list) or not all(
                isinstance(v, (int, float)) for v in log_probs
            ):
                raise ValueError(
                    f"scorer for prompt {prompt!r} returned non-numeric log_probs"
                )
            log_probs = [float(v) for v in log_probs]
        return output["text"], log_probs
    raise TypeError(
        f"scorer must return a string or a dict with 'text', got {type(output).__name__}"
    )


def run_task(task, scorer, metric_names=None, filter_specs=None):
    """Run ``task`` (an :class:`EvalTask`) against ``scorer``.

    Returns a JSON-able dict::

        {
          "task": <name>, "description": <str>, "num_items": <int>,
          "filters_applied": [<specs>],
          "metrics": {"exact_match": 0.75, "accuracy": 0.75,
                      "perplexity": 2.0 or None},
          "per_item": [{"prompt": ..., "prediction": ...,   # raw
                        "filtered_prediction": ..., "reference": ...,
                        "exact_match": True, "log_probs": [...] or None}],
          "notes": [<str>, ...],
          "needs_human_decision": True,
          "verified": False,
        }

    ``metric_names`` / ``filter_specs`` default to the task's own.
    Unknown metric names raise ``KeyError`` before any item runs.
    How each metric kind is computed (see :mod:`mini_ai.eval.metrics`
    for the kinds):

    - ``pairwise`` (e.g. ``exact_match``): applied per item to the
      filtered prediction and the reference; the reported value is
      the mean match rate over items.
    - ``aggregate`` (e.g. ``accuracy``): applied to the per-item
      exact-match 0/1 scores.
    - ``logprob`` (e.g. ``perplexity``): applied per item to that
      item's log-probs, then averaged over the items that supplied
      log-probs (``None`` with a note when none did).
    """
    if not callable(scorer):
        raise TypeError("scorer must be callable")
    names = list(metric_names) if metric_names is not None else list(task.metric_names)
    specs = list(filter_specs) if filter_specs is not None else list(task.filter_specs)
    for name in names:
        METRIC_REGISTRY.get(name)  # KeyError on unknown metric, up front.

    per_item = []
    notes = []
    exact_scores = []
    per_item_log_probs = []
    for item in task.items:
        prompt = task.render_prompt(item)
        raw_text, log_probs = _normalise_scorer_output(scorer(prompt), prompt)
        filtered = apply_filters(raw_text, specs)
        matched = exact_match(filtered, item["answer"])
        exact_scores.append(1 if matched else 0)
        per_item.append({
            "prompt": prompt,
            "prediction": raw_text,
            "filtered_prediction": filtered,
            "reference": item["answer"],
            "exact_match": matched,
            "log_probs": log_probs,
        })
        if log_probs:
            per_item_log_probs.append(log_probs)

    metrics = {}
    for name in names:
        func, kind, _description = METRIC_REGISTRY.get(name)
        if kind == "pairwise":
            values = [
                1 if func(rec["filtered_prediction"], rec["reference"]) else 0
                for rec in per_item
            ]
            metrics[name] = sum(values) / len(values) if values else 0.0
        elif kind == "aggregate":
            metrics[name] = func(exact_scores)
        elif kind == "logprob":
            if per_item_log_probs:
                per_item_values = [func(log_probs=lp) for lp in per_item_log_probs]
                metrics[name] = sum(per_item_values) / len(per_item_values)
            else:
                metrics[name] = None
                notes.append(
                    f"{name} is None: the scorer supplied no per-token log-probs."
                )

    return {
        "task": task.name,
        "description": task.description,
        "num_items": len(task.items),
        "filters_applied": specs,
        "metrics": metrics,
        "per_item": per_item,
        "notes": notes,
        "needs_human_decision": True,
        "verified": False,
    }


def run_task_by_name(name, scorer, metric_names=None, filter_specs=None,
                     registry=None):
    """Run the task registered as ``name`` against ``scorer``."""
    reg = registry if registry is not None else TASK_REGISTRY
    return run_task(reg.get(name), scorer,
                    metric_names=metric_names, filter_specs=filter_specs)


def results_to_json(results):
    """Serialise a results dict to a JSON string (round-trip check)."""
    return json.dumps(results, indent=2, sort_keys=True)
