"""Fault-injection test tooling (Module 24) — original Python,
stdlib only.

Design inspiration: Tumult (mwigge/tumult, Apache-2.0, 151,498
lines — verified in the sweep from its own LICENSE file). The
sweep's verdict for it was INSPIRATION-REBUILD: rebuild the
experiment pattern (hypothesis -> baseline -> fault -> recovery
measurement -> evidence journal) as original small Rust/Python
test tooling. The full Tumult platform (daemon, web UI, MCP
server, ClickHouse/K8s integrations, optional paid-LLM tutor)
is deferred as heavyweight and is NOT adopted. **No Tumult code
was copied** — this module was written from the pattern
description only, and mirrors the Rust half
(``rust/src/fault_injection.rs``) with the same fault taxonomy
and the same report shape (same keys, same outcome values).

What an experiment is here (original, defined in this file):
- An experiment states a hypothesis ("the supervised run
  recovers from a worker crash within the restart budget"), a
  baseline (the expected candidate: delivered 600 t / shortage
  50 t — the spine's known LP optimum), one fault, and a
  restart/timeout budget.
- A fault is one of three kinds, the same taxonomy as the Rust
  half: ``"worker_crash"`` (the worker fails before returning),
  ``"delayed_response"`` (the response arrives after the
  timeout), ``"corrupted_value"`` (a candidate value is altered
  in transit, so it no longer matches the baseline).
- The runner injects the fault around a clean worker callable:
  a crash is raised by the harness on the first ``fail_attempts``
  attempts (the worker itself is never asked to fail); a delay
  is a real sleep of ``delay_ms`` before the worker's result is
  returned, measured against ``timeout_ms`` with a monotonic
  clock; a corruption alters the returned candidate's
  ``delivered_t`` in transit, before the detector sees it.
  The detector then compares the received candidate against
  the baseline and rejects any mismatch.
- Running a fault produces a report dict: whether the fault was
  injected, whether it was detected, an ``outcome`` that is
  always ``"FAIL"`` or ``"UNKNOWN"`` (there is no ``"PASS"``
  value — :func:`validate_outcome` rejects anything else), and
  a recovery measurement (restarts observed, timed out or not).
- An :class:`EvidenceJournal` is an append-only list of phase
  entries (hypothesis -> baseline -> fault -> recovery ->
  verdict), serialised to JSON. There is no delete or edit
  method.

Governance — this is TEST-ONLY tooling:
- It never runs outside tests, never touches real plans, and
  never calls the verify step. A fault-injection run's output
  is a report about the supervision behaviour, never a plan
  verdict.
- ``verified`` on every report and journal entry is always
  ``False``: the value is the literal ``False`` in the report
  constructor and there is no function that sets it True
  (pinned by a test that reads this source file). A corrupted
  value is caught and reported FAIL, never PASS. A crash is
  reported as a restart (or FAIL when the restart budget is
  exhausted), a delay as UNKNOWN (timed out).
- Recovery never promotes anything: even a worker that
  recovers after a restart reports UNKNOWN, not PASS — its
  output still needs the separate verify step and human
  approval, exactly as the supervision module requires of a
  restarted worker.

Wire format stays JSON: reports and journal entries are plain
JSON-able dicts (schema_version "1.0.0"). All data here is
synthetic; no real plans, no network, no Tumult daemon.
"""

import json
import time

SCHEMA_VERSION = "1.0.0"
LICENCE = "Apache-2.0"
PROVENANCE = ("START original — Tumult experiment pattern "
              "(hypothesis -> baseline -> fault -> recovery "
              "measurement -> evidence journal) as inspiration "
              "only, no code copied")

FAULT_KINDS = ("worker_crash", "delayed_response", "corrupted_value")
OUTCOMES = ("FAIL", "UNKNOWN")  # There is deliberately no "PASS".
JOURNAL_PHASES = ("hypothesis", "baseline", "fault_injected",
                  "recovery_measured", "verdict")

# The baseline every fault run is measured against: the spine's
# known LP optimum, delivered 600 t / shortage 50 t.
BASELINE = {"delivered_t": 600, "shortage_t": 50}


def validate_outcome(outcome):
    """Accept only "FAIL" or "UNKNOWN"; reject anything else.

    There is no PASS outcome for a fault-injection run, so a
    caller cannot smuggle one in through this module.
    """
    if outcome not in OUTCOMES:
        raise ValueError(
            f"fault-injection outcome must be one of {list(OUTCOMES)}, "
            f"got {outcome!r} — a fault run can never report PASS")
    return outcome


def validate_fault_kind(kind):
    """Accept only the three kinds in the shared taxonomy."""
    if kind not in FAULT_KINDS:
        raise ValueError(
            f"fault kind must be one of {list(FAULT_KINDS)}, got {kind!r}")
    return kind


def delay_exceeds_timeout(delay_ms, timeout_ms):
    """Whether a delayed response exceeds its timeout (exact: >)."""
    return delay_ms > timeout_ms


def value_is_corrupted(expected_t, received_t):
    """Whether a received value is corrupted (exact: any difference)."""
    return expected_t != received_t


def make_fault(kind, **params):
    """Build a fault dict: kind plus its defining parameters.

    - worker_crash: ``fail_attempts`` (attempts the harness fails
      before letting the worker run; default 1), ``max_restarts``
      (restart budget; default 2).
    - delayed_response: ``delay_ms``, ``timeout_ms``.
    - corrupted_value: ``received_t`` (the altered delivered_t;
      the expected value is the baseline's 600 t).
    """
    validate_fault_kind(kind)
    fault = {"kind": kind}
    if kind == "worker_crash":
        fault["fail_attempts"] = int(params.get("fail_attempts", 1))
        fault["max_restarts"] = int(params.get("max_restarts", 2))
        if fault["fail_attempts"] < 0 or fault["max_restarts"] < 0:
            raise ValueError("fail_attempts and max_restarts must be >= 0")
    elif kind == "delayed_response":
        fault["delay_ms"] = int(params["delay_ms"])
        fault["timeout_ms"] = int(params["timeout_ms"])
        if fault["delay_ms"] < 0 or fault["timeout_ms"] < 0:
            raise ValueError("delay_ms and timeout_ms must be >= 0")
    elif kind == "corrupted_value":
        fault["received_t"] = int(params["received_t"])
    return fault


def _report(experiment_id, hypothesis, fault_kind, detected, outcome,
            recovery, result=None):
    """Build a report dict. ``verified`` is the literal False here,
    and no function in this module ever writes True to it."""
    validate_outcome(outcome)
    report = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "hypothesis": hypothesis,
        "baseline": dict(BASELINE),
        "fault_kind": fault_kind,
        "injected": True,
        "detected": detected,
        "outcome": outcome,
        "verified": False,
        "needs_human_decision": True,
        "recovery": recovery,
        "result": result,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "synthetic": True,
    }
    json.dumps(report)  # must be plain JSON-able, or raise here
    return report


def run_experiment(experiment_id, hypothesis, fault, worker):
    """Run one fault-injection experiment around a clean worker.

    ``worker`` is a callable ``worker(attempt) -> candidate dict``
    with the baseline shape (``delivered_t`` / ``shortage_t``);
    the fault is injected by this runner, never by the worker.
    Returns a report dict (see module docstring for the shape).
    The returned ``result`` is the accepted candidate, or None:
    a timed-out or corrupted result is never accepted.
    """
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError("experiment_id must be a non-empty string")
    if not isinstance(hypothesis, str) or not hypothesis:
        raise ValueError("hypothesis must be a non-empty string")
    if not callable(worker):
        raise TypeError("worker must be callable")
    if not isinstance(fault, dict) or "kind" not in fault:
        raise ValueError("fault must be a fault dict from make_fault()")
    kind = validate_fault_kind(fault["kind"])

    if kind == "worker_crash":
        return _run_crash(experiment_id, hypothesis, fault, worker)
    if kind == "delayed_response":
        return _run_delay(experiment_id, hypothesis, fault, worker)
    return _run_corruption(experiment_id, hypothesis, fault, worker)


def _run_crash(experiment_id, hypothesis, fault, worker):
    """Crash fault: the harness fails the first ``fail_attempts``
    attempts, restarting the worker each time, up to
    ``max_restarts`` restarts. Recovery (worker completes after a
    restart) is UNKNOWN — recovered but unverified. Exhausting
    the budget is FAIL."""
    fail_attempts = fault["fail_attempts"]
    max_restarts = fault["max_restarts"]
    restarts = 0
    attempt = 0
    while True:
        attempt += 1
        if attempt <= fail_attempts:
            # Injected crash: the worker is never called on this
            # attempt; the supervisor restarts it instead.
            if restarts >= max_restarts:
                return _report(
                    experiment_id, hypothesis, "worker_crash", True,
                    "FAIL",
                    {"restarted": restarts > 0, "restarts": restarts,
                     "timed_out": False, "timeout_ms": None},
                    result=None)
            restarts += 1
            continue
        result = worker(attempt)
        return _report(
            experiment_id, hypothesis, "worker_crash", True,
            "UNKNOWN",
            {"restarted": restarts > 0, "restarts": restarts,
             "timed_out": False, "timeout_ms": None},
            result=result)


def _run_delay(experiment_id, hypothesis, fault, worker):
    """Delay fault: the harness sleeps ``delay_ms`` before the
    worker's result is returned, and measures the elapsed time
    against ``timeout_ms`` with a monotonic clock. A delay past
    the timeout is detected and UNKNOWN, and the result is not
    accepted (None). A delay inside the timeout is not detected
    — but the run is still UNKNOWN, never PASS."""
    delay_ms = fault["delay_ms"]
    timeout_ms = fault["timeout_ms"]
    start = time.monotonic()
    time.sleep(delay_ms / 1000.0)
    result = worker(1)
    elapsed_ms = (time.monotonic() - start) * 1000.0
    timed_out = elapsed_ms > timeout_ms
    detected = timed_out or delay_exceeds_timeout(delay_ms, timeout_ms)
    return _report(
        experiment_id, hypothesis, "delayed_response", detected,
        "UNKNOWN",
        {"restarted": False, "restarts": 0,
         "timed_out": timed_out, "timeout_ms": timeout_ms},
        result=None if timed_out else result)


def _run_corruption(experiment_id, hypothesis, fault, worker):
    """Corruption fault: the harness alters the worker's returned
    candidate in transit (``delivered_t`` becomes
    ``received_t``), then the detector compares it against the
    baseline. A mismatch is detected, the value is rejected
    (result None), and the outcome is FAIL. An unaltered value
    is not detected — but the run is still UNKNOWN, never PASS."""
    result = worker(1)
    received = dict(result)
    received["delivered_t"] = fault["received_t"]
    detected = value_is_corrupted(BASELINE["delivered_t"],
                                  received["delivered_t"])
    outcome = "FAIL" if detected else "UNKNOWN"
    return _report(
        experiment_id, hypothesis, "corrupted_value", detected,
        outcome,
        {"restarted": False, "restarts": 0,
         "timed_out": False, "timeout_ms": None},
        result=None if detected else received)


def report_to_json(report):
    """Serialise a report to a JSON string (sorted keys)."""
    return json.dumps(report, sort_keys=True)


def report_from_json(text):
    """Deserialise a report. Flags carried as stored."""
    return json.loads(text)


class EvidenceJournal:
    """Append-only evidence journal for fault experiments.

    Entries are added in Tumult's phase order (hypothesis ->
    baseline -> fault -> recovery -> verdict). There is no delete
    or edit method, and every entry carries verified=False.
    """

    def __init__(self):
        self._entries = []

    def record(self, experiment_id, phase, detail):
        """Append one entry; ``phase`` must be a known phase."""
        if phase not in JOURNAL_PHASES:
            raise ValueError(
                f"journal phase must be one of {list(JOURNAL_PHASES)}, "
                f"got {phase!r}")
        self._entries.append({
            "schema_version": SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "phase": phase,
            "detail": detail,
            "verified": False,
        })

    def record_experiment(self, report):
        """Record the five phases of one experiment, in order."""
        experiment_id = report["experiment_id"]
        recovery = report["recovery"]
        self.record(experiment_id, "hypothesis", report["hypothesis"])
        self.record(experiment_id, "baseline",
                    "delivered_t={} shortage_t={}".format(
                        report["baseline"]["delivered_t"],
                        report["baseline"]["shortage_t"]))
        self.record(experiment_id, "fault_injected",
                    "fault_kind={} injected=true".format(
                        report["fault_kind"]))
        self.record(experiment_id, "recovery_measured",
                    "restarted={} restarts={} timed_out={}".format(
                        recovery["restarted"], recovery["restarts"],
                        recovery["timed_out"]))
        self.record(experiment_id, "verdict",
                    "outcome={} detected={} verified=false".format(
                        report["outcome"], report["detected"]))

    def entries(self):
        """A deep copy of the entries (callers cannot mutate the log)."""
        return json.loads(json.dumps(self._entries))

    def __len__(self):
        return len(self._entries)

    def to_json(self):
        """Serialise the whole journal to a JSON string."""
        return json.dumps(self._entries, sort_keys=True)


def synthetic_worker(attempt=1):
    """A clean synthetic worker: returns the baseline candidate.

    Hand-computed case: delivered 600 t / shortage 50 t, the
    spine's known LP optimum. The worker never fails, never
    delays, never corrupts — every fault is injected by the
    runner around it, never by the worker itself.
    """
    return {"delivered_t": 600, "shortage_t": 50}
