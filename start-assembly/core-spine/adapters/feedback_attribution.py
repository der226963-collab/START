"""Feedback attribution (Module 22) — original Python, stdlib only.

Design inspiration: Trace / Microsoft (microsoft/Trace, MIT —
verified in the sweep from the repo's own LICENSE file,
Copyright (c) Microsoft Corporation; 10,917 lines of Python in
``opto/trace/`` and ``opto/optimizers/``, last commit
2025-08-14). The sweep's verdict for it was DEFER: every
optimisation step needs a paid LLM API via LiteLLM, the project
is inactive since 2025-08, and an optimiser that rewrites
prompts or code has no fencing from governance, verification or
self-edit files — an LLM rewriting the rules it is judged by
would collapse the Planning / Evaluation / Verification /
Governance trust boundary. So the whole tool is NOT adopted:
no dependency, no ``trace-opt`` install, and **no Trace code
was copied** — this module was written from the design idea
only (trace-based feedback propagation: recording which step
of a plan's execution a failed verify or a bad score belongs
to). No new dependency was added (stdlib only), no LLM, no
paid API, no downloads, no real data — synthetic test data
only. The sibling Module 22 candidate DeepEval is already
assembled as a dependency for its deterministic metrics
(``adapters/evaluation.py``); this module accepts a DeepEval
deterministic metric score (ExactMatch, PatternMatch,
JsonCorrectness) as an evaluation result, but it does not
import or call DeepEval — the score is supplied by the caller.

Semantics (original, defined here, not copied):
- A ``trace`` is an ordered record of the steps that produced
  the outputs being evaluated. Each step names the task it
  belongs to, the metric that will judge it, the input it ran
  on, and the component that produced it (for example
  ``"optimisation"`` or ``"planning-search"``). A step is
  identified by its ``step_id``; duplicate step ids are
  rejected, because two steps with one id would make
  attribution ambiguous by construction.
- An ``evaluation result`` is a plain dict with ``task_id``,
  ``metric``, ``input_id``, ``score`` (a number in [0, 1], or
  ``None`` when no score was produced) and ``threshold`` (the
  score at or above which the result passes; default 1.0, the
  exact-match semantics — any miss fails). ``passed`` is
  ``score is not None and score >= threshold``; ``status`` is
  ``"PASS"``, ``"FAIL"`` or ``"UNKNOWN"`` (no score). A result
  with a score outside [0, 1], or a threshold outside [0, 1],
  is rejected with ``ValueError`` rather than silently
  rescaled — a score that cannot be read as a 0-to-1 metric
  score is not a score this module will attribute.
- ``attribute(result, trace)`` propagates the feedback back
  to its source. Attribution is an EXACT match on all three
  keys at once — task, metric and input — against the steps
  recorded in the trace:
  * exactly one matching step -> ATTRIBUTED, naming that
    step (``step_id``, ``component``, ``output_id``);
  * no matching step -> UNATTRIBUTED, with ``step_id``,
    ``component`` and ``output_id`` all ``None`` and a reason
    stating which keys found no step — the failure is
    reported as unattributed, never guessed;
  * more than one matching step -> UNATTRIBUTED, with a
    reason stating how many steps matched — the module never
    picks one of several identical candidates arbitrarily;
  * a result missing any of task, metric or input ->
    UNATTRIBUTED, naming the missing key — a partial key
    never attributes (a task-plus-metric match with a
    different input is not the same source).
- This module NEVER invents a cause. Every attribution
  carries ``cause`` set to ``None`` and ``cause_inferred``
  set to ``False``. The ``feedback`` string states only
  observed facts — the score, the threshold, and the step
  it was attributed to (or that it was unattributed and
  why). It never says why the score was low, which
  component was at fault beyond the step that produced the
  output, or what should change. Attributing a failure to
  a step is not blaming that step: it says only that the
  output judged by this score came from that step.
- GOVERNANCE: the verified flag is CARRIED, never set.
  ``attribute()`` copies the ``verified`` flag from the
  evaluation result it was handed, verbatim
  (``bool(result.get("verified", False))``); a result that
  arrives without the flag is treated as unverified. No
  code path in this module writes the verified flag to the
  affirmative — a carried affirmative flag is a claim from
  outside this module, not a verdict of this module, and
  it does not make the attribution verified in any stronger
  sense: ``needs_human_decision`` is always ``True`` on
  every result this module produces, including one carrying
  an affirmative flag. The trace record itself and the
  ``propagate_feedback()`` envelope are new records made
  here, so they carry the flag as ``False``. This module
  never calls verify, never certifies an output, and never
  touches self-edit or guardrail files.
- ``propagate_feedback(results, trace)`` attributes a list
  of evaluation results and returns an envelope with the
  per-result attributions plus a hand-checkable summary
  (total, failures, attributed, unattributed,
  attributed failures, unattributed failures). Passing
  results are attributed the same way as failing ones
  when their source is known — attribution identifies a
  source, it does not only fire on failure — but the
  feedback for a passing result states there is no failure
  to propagate.

Wire format stays JSON: traces, evaluation results,
attributions and envelopes are plain JSON-able dicts
(schema_version "1.0.0"). All data here is synthetic; no
real evaluation runs, no LLM, no paid API.
"""

import json

SCHEMA_VERSION = "1.0.0"
LICENCE = "MIT"
PROVENANCE = ("START original — Trace feedback-propagation idea "
              "as design inspiration only, no code copied")

DEFAULT_THRESHOLD = 1.0


def new_trace(trace_id):
    """Create an empty trace record.

    ``trace_id`` must be a non-empty string. The trace is a
    plain dict with an ordered ``steps`` list. It is a record
    made here, so it carries the verified flag as False.
    """
    if not isinstance(trace_id, str) or not trace_id.strip():
        raise ValueError("trace_id must be a non-empty string")
    return {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "trace_id": trace_id,
        "steps": [],
        "verified": False,
        "needs_human_decision": True,
    }


def record_step(trace, step_id, task_id, metric, input_id, component,
                output_id=None):
    """Record one step in a trace and return the step dict.

    All of ``step_id``, ``task_id``, ``metric``, ``input_id``
    and ``component`` must be non-empty strings; ``output_id``,
    when given, must be a non-empty string. A ``step_id``
    already present in the trace raises ``ValueError`` —
    duplicate ids would make attribution ambiguous. The step
    is appended to the trace in call order; the returned step
    dict is the same object stored in the trace, so callers
    must not mutate a step after recording it.
    """
    if not isinstance(trace, dict) or not isinstance(
            trace.get("steps"), list):
        raise ValueError("trace must be a trace dict from new_trace()")
    for name, value in (("step_id", step_id), ("task_id", task_id),
                        ("metric", metric), ("input_id", input_id),
                        ("component", component)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if output_id is not None and (
            not isinstance(output_id, str) or not output_id.strip()):
        raise ValueError("output_id must be a non-empty string or None")
    if any(step["step_id"] == step_id for step in trace["steps"]):
        raise ValueError(f"duplicate step_id in trace: {step_id!r}")
    step = {
        "step_id": step_id,
        "task_id": task_id,
        "metric": metric,
        "input_id": input_id,
        "component": component,
        "output_id": output_id,
    }
    trace["steps"].append(step)
    return step


def _check_0_to_1(name, value):
    """Validate a 0-to-1 number; ``None`` is allowed for scores."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in [0, 1] or None")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")


def make_evaluation_result(task_id, metric, input_id, score,
                           threshold=DEFAULT_THRESHOLD, verified=False):
    """Build an evaluation result from a metric score.

    ``score`` is the metric score in [0, 1] (for example a
    DeepEval deterministic metric score: ExactMatch 1.0 or
    0.0), or ``None`` when no score was produced.
    ``threshold`` is the score at or above which the result
    passes (default 1.0, exact-match semantics). ``verified``
    is the flag the result arrived with — it is recorded
    here, never decided here. Returns a plain JSON-able dict
    with ``passed`` and ``status`` derived from score and
    threshold: ``"PASS"`` if the score meets the threshold,
    ``"FAIL"`` if it is below it, ``"UNKNOWN"`` if there is
    no score. Scores and thresholds outside [0, 1] raise
    ``ValueError``.
    """
    for name, value in (("task_id", task_id), ("metric", metric),
                        ("input_id", input_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    _check_0_to_1("score", score)
    if isinstance(threshold, bool) or not isinstance(
            threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be a number in [0, 1], "
                         f"got {threshold!r}")
    passed = score is not None and score >= threshold
    status = ("PASS" if passed else
              "UNKNOWN" if score is None else "FAIL")
    result = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "task_id": task_id,
        "metric": metric,
        "input_id": input_id,
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "status": status,
        "verified": bool(verified),
        "needs_human_decision": True,
    }
    json.dumps(result)  # must be plain JSON-able, or raise here
    return result


def is_failure(result):
    """True only for an evaluation result with status "FAIL".

    A passing result is not a failure, and a result with no
    score (status "UNKNOWN") is not a failure either — an
    absent score is missing evidence, not a failed check.
    """
    if not isinstance(result, dict):
        raise ValueError("result must be a dict")
    return result.get("status") == "FAIL"


def attribute(result, trace):
    """Attribute one evaluation result to the step that produced it.

    Returns a plain JSON-able attribution dict. The source is
    found by exact match on task, metric and input together
    (see the module docstring for the four outcomes). The
    attribution always carries ``cause`` as ``None`` and
    ``cause_inferred`` as ``False`` — this module never invents
    a cause — and it carries the ``verified`` flag from the
    result it was handed, verbatim; ``needs_human_decision``
    is always ``True``. A result that is not a dict, or a
    trace that is not a trace dict, raises ``ValueError``.
    """
    if not isinstance(result, dict):
        raise ValueError("result must be a dict")
    if not isinstance(trace, dict) or not isinstance(
            trace.get("steps"), list):
        raise ValueError("trace must be a trace dict from new_trace()")
    task_id = result.get("task_id")
    metric = result.get("metric")
    input_id = result.get("input_id")
    score = result.get("score")
    threshold = result.get("threshold")
    failure = is_failure(result)
    # The verified flag is carried from the result handed in,
    # verbatim — never set here.
    carried_verified = bool(result.get("verified", False))
    attribution = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "task_id": task_id if isinstance(task_id, str) else None,
        "metric": metric if isinstance(metric, str) else None,
        "input_id": input_id if isinstance(input_id, str) else None,
        "score": score,
        "threshold": threshold,
        "is_failure": failure,
        "attributed": False,
        "status": "UNATTRIBUTED",
        "step_id": None,
        "component": None,
        "output_id": None,
        "cause": None,
        "cause_inferred": False,
        "reason": "",
        "feedback": "",
        "verified": carried_verified,
        "needs_human_decision": True,
    }
    missing = [name for name, value in
               (("task_id", task_id), ("metric", metric),
                ("input_id", input_id))
               if not isinstance(value, str) or not value.strip()]
    if missing:
        attribution["reason"] = (
            "unattributed: result is missing "
            + ", ".join(missing)
            + "; a partial key never attributes a source")
        attribution["feedback"] = attribution["reason"]
        json.dumps(attribution)
        return attribution
    matches = [step for step in trace["steps"]
               if step["task_id"] == task_id
               and step["metric"] == metric
               and step["input_id"] == input_id]
    if not matches:
        attribution["reason"] = (
            f"unattributed: no step in trace "
            f"{trace.get('trace_id')!r} matches task {task_id!r}, "
            f"metric {metric!r}, input {input_id!r}")
        attribution["feedback"] = attribution["reason"]
        json.dumps(attribution)
        return attribution
    if len(matches) > 1:
        attribution["reason"] = (
            f"unattributed: {len(matches)} steps in trace "
            f"{trace.get('trace_id')!r} match task {task_id!r}, "
            f"metric {metric!r}, input {input_id!r}; no single "
            f"source can be identified")
        attribution["feedback"] = attribution["reason"]
        json.dumps(attribution)
        return attribution
    step = matches[0]
    attribution["attributed"] = True
    attribution["status"] = "ATTRIBUTED"
    attribution["step_id"] = step["step_id"]
    attribution["component"] = step["component"]
    attribution["output_id"] = step["output_id"]
    attribution["reason"] = (
        f"attributed to step {step['step_id']!r} "
        f"(component {step['component']!r})")
    if failure:
        attribution["feedback"] = (
            f"failure attributed to step {step['step_id']!r} "
            f"(component {step['component']!r}): metric "
            f"{metric!r} scored {score} below threshold "
            f"{threshold} for input {input_id!r} of task "
            f"{task_id!r}; cause not inferred")
    else:
        attribution["feedback"] = (
            f"no failure to propagate: metric {metric!r} "
            f"scored {score} against threshold {threshold} "
            f"for input {input_id!r} of task {task_id!r}, "
            f"attributed to step {step['step_id']!r} "
            f"(component {step['component']!r}); cause not "
            f"inferred")
    json.dumps(attribution)
    return attribution


def propagate_feedback(results, trace):
    """Attribute a list of evaluation results to their sources.

    Returns a plain JSON-able envelope with the per-result
    attributions (in the order the results were given) and a
    summary with hand-checkable counts: ``total`` results,
    ``failures`` (results with status FAIL), ``attributed``
    and ``unattributed`` (by attribution status), and the
    split of failures into ``attributed_failures`` and
    ``unattributed_failures``. The envelope is a new record
    made here, so it carries the verified flag as False and
    needs_human_decision as True; the per-result attributions
    inside it each carry the flag from their own result.
    ``results`` must be a list; anything else raises
    ``ValueError``.
    """
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    attributions = [attribute(result, trace) for result in results]
    failures = [a for a in attributions if a["is_failure"]]
    summary = {
        "total": len(attributions),
        "failures": len(failures),
        "attributed": sum(1 for a in attributions if a["attributed"]),
        "unattributed": sum(1 for a in attributions
                            if not a["attributed"]),
        "attributed_failures": sum(
            1 for a in failures if a["attributed"]),
        "unattributed_failures": sum(
            1 for a in failures if not a["attributed"]),
    }
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "trace_id": trace.get("trace_id") if isinstance(trace, dict)
        else None,
        "attributions": attributions,
        "summary": summary,
        "verified": False,
        "needs_human_decision": True,
    }
    json.dumps(envelope)  # must be plain JSON-able, or raise here
    return envelope


# Synthetic example (clearly synthetic, not a real evaluation
# run): the food-planning LP from the spine's synthetic example
# (delivered 600 t, shortage 50 t), judged by exact-match.
SYNTHETIC_TRACE_ID = "synthetic-food-lp-trace"


def synthetic_trace():
    """Build the synthetic 3-step trace used by the tests.

    Steps (in order):
    * ``s1`` — task "food-lp", metric "exact-match", input
      "delivered-tonnes", component "optimisation", output
      "delivered-600t";
    * ``s2`` — task "food-lp", metric "exact-match", input
      "shortage-tonnes", component "optimisation", output
      "shortage-50t";
    * ``s3`` — task "food-lp", metric "pattern-match", input
      "delivered-tonnes", component "evaluation", output
      "pattern-delivered".
    """
    trace = new_trace(SYNTHETIC_TRACE_ID)
    record_step(trace, "s1", "food-lp", "exact-match",
                "delivered-tonnes", "optimisation",
                output_id="delivered-600t")
    record_step(trace, "s2", "food-lp", "exact-match",
                "shortage-tonnes", "optimisation",
                output_id="shortage-50t")
    record_step(trace, "s3", "food-lp", "pattern-match",
                "delivered-tonnes", "evaluation",
                output_id="pattern-delivered")
    return trace


def synthetic_failing_result():
    """A hand-computed failing result for the synthetic trace.

    Exact-match on "delivered-tonnes": the expected answer
    ("614" in the golden set's loss case) was not produced
    exactly, so the score is 0.0 against a threshold of 1.0
    — status FAIL, attributed to step ``s1``.
    """
    return make_evaluation_result(
        "food-lp", "exact-match", "delivered-tonnes",
        score=0.0, threshold=1.0)


def synthetic_passing_result():
    """A hand-computed passing result for the synthetic trace.

    Exact-match on "shortage-tonnes": score 1.0 against a
    threshold of 1.0 — status PASS, attributed to step ``s2``.
    """
    return make_evaluation_result(
        "food-lp", "exact-match", "shortage-tonnes",
        score=1.0, threshold=1.0)
