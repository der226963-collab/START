"""Monitoring event bus (Module 8) — original Python, stdlib only.

Design inspiration: Beam-Telemetry (beam-telemetry/telemetry,
Apache-2.0 — verified in the sweep from the repo's own LICENSE
file; core is src/telemetry.erl, 482 lines, whole repo 1,445
lines of Erlang). The sweep's verdict for it was
INSPIRATION-REBUILD: rebuild the execute/attach/detach event
bus as original Python. **No Beam-Telemetry code was copied**
— this module was written from the event-bus design only
(execute an event by name, attach/detach handlers, handlers
receive measurements plus a metadata map). The Erlang library
itself was NOT adopted: START's v0.3.2 allocation has no BEAM
runtime, so it cannot be used as a dependency as-is. Nothing
was installed: no new dependency, ``requirements.txt``
unchanged. No network, no real telemetry backend.

Semantics (original, defined here, not copied):
- ``attach(event_name, handler)`` / ``detach(event_name,
  handler)`` / ``execute(event_name, event)`` — handlers are
  plain callables; execute dispatches to all handlers attached
  to that event name, in attach order, and returns a dispatch
  record (a plain JSON-able dict).
- Events are plain JSON-able dicts carrying: event name
  (``"event"``), a payload, licence and provenance fields, and
  a ``verified`` flag (True/False) plus
  ``needs_human_decision`` — following the assembly's existing
  pattern (verified=false on model results). ``make_event()``
  builds one; ``execute()`` validates that the event's name
  matches the event it is executed under, so an event cannot
  be silently misrouted to the wrong handlers.
- HANDLERS NEVER MARK A RESULT VERIFIED. A handler receives a
  deep copy of the event, never the bus's own copy, so mutating
  its input cannot change what the bus stored or what later
  handlers see. A handler's return value is never used as
  event data — handlers are observers (logging / metrics),
  not producers. If a handler returns a dict whose ``verified``
  flag differs from the flag as dispatched (promotion
  false -> true, or demotion true -> false), or if it mutates
  the ``verified`` flag of the copy it was handed, that
  handler's outcome is recorded as ``"rejected"`` in the
  dispatch log with a reason, its return is discarded, and
  the bus's stored/logged flag stays exactly as dispatched.
  Promotion attempts are therefore REJECTED (not silently
  ignored) and auditable — see the governance rule below.
  Mutations to any other field of the handler's copy are
  harmless by construction (the copy is discarded) and do not
  change the outcome; only the ``verified`` flag is guarded.
- The bus keeps an in-memory dispatch log: one entry per
  handler invocation, with event name, handler name, the
  verified flag as dispatched, and whether the handler's
  return was accepted, rejected, or errored. Promotion
  attempts are never silent.
- A handler raising an exception does not stop other handlers
  and does not lose the event: the exception is recorded in
  the dispatch log (outcome ``"error"`` with the exception
  text) and dispatch continues to the remaining handlers.
- Events carry licence/provenance through the round trip
  unchanged: the bus never rewrites those fields, and the
  dispatch record and log carry the same values that went in.

Wire format stays JSON: events, dispatch records and log
entries are plain JSON-able dicts (schema_version "1.0.0").
All data here is synthetic; no real telemetry backend.
"""

import copy
import json

SCHEMA_VERSION = "1.0.0"
LICENCE = "Apache-2.0"
PROVENANCE = ("START original — Beam-Telemetry event bus as design "
              "inspiration only, no code copied")


def make_event(event_name, payload, licence=LICENCE,
               provenance=PROVENANCE, verified=False,
               needs_human_decision=True, synthetic=True):
    """Build a well-formed event dict.

    ``payload`` must be JSON-able (checked by ``json.dumps``).
    ``verified`` is carried as given — this function never
    upgrades it, and no function in this module sets it True
    except by carrying a caller-supplied True through unchanged
    (a stored verified=true is a claim from outside this
    module, not a proof — see the governance rule).
    """
    if not event_name or not isinstance(event_name, str):
        raise ValueError("event_name must be a non-empty string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    event = {
        "schema_version": SCHEMA_VERSION,
        "event": event_name,
        "payload": copy.deepcopy(payload),
        "licence": licence,
        "provenance": provenance,
        "verified": bool(verified),
        "needs_human_decision": bool(needs_human_decision),
        "synthetic": bool(synthetic),
    }
    json.dumps(event)  # must be plain JSON-able, or raise here
    return event


def _handler_name(handler):
    """A stable, human-readable name for a handler callable."""
    name = getattr(handler, "__name__", None)
    if isinstance(name, str) and name:
        return name
    cls = getattr(handler, "__class__", None)
    if cls is not None and getattr(cls, "__name__", None):
        return cls.__name__
    return repr(handler)


class EventBus:
    """An in-memory monitoring event bus.

    Handlers are plain callables taking one argument (the event
    dict). They are observers only: their return values are
    never used as event data, and they can never change the
    verified flag of an event. The dispatch log is the audit
    trail — every handler invocation is recorded there.
    """

    def __init__(self):
        self._handlers = {}  # event name -> list of handlers
        self._log = []       # list of dispatch-log entry dicts

    # -- attach / detach ------------------------------------------------

    def attach(self, event_name, handler):
        """Attach ``handler`` to ``event_name``.

        Returns True if newly attached, False if this exact
        handler was already attached to this event (attach is
        idempotent — the same handler is never called twice per
        dispatch). Raises ValueError for a bad event name and
        TypeError for a non-callable handler.
        """
        if not event_name or not isinstance(event_name, str):
            raise ValueError("event_name must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        handlers = self._handlers.setdefault(event_name, [])
        if handler in handlers:
            return False
        handlers.append(handler)
        return True

    def detach(self, event_name, handler):
        """Detach ``handler`` from ``event_name``.

        Returns True if the handler was attached and is now
        removed, False if it was never attached — detaching a
        handler that was never attached is a safe no-op, never
        an error (chosen so teardown / re-registration code
        cannot fail on a handler that was already gone).
        """
        handlers = self._handlers.get(event_name)
        if not handlers or handler not in handlers:
            return False
        handlers.remove(handler)
        if not handlers:
            del self._handlers[event_name]
        return True

    def attached(self, event_name):
        """Handler names currently attached to ``event_name``."""
        return [_handler_name(h)
                for h in self._handlers.get(event_name, [])]

    # -- execute ---------------------------------------------------------

    def execute(self, event_name, event):
        """Dispatch ``event`` to all handlers of ``event_name``.

        Returns a dispatch record (plain JSON-able dict) with
        the event as dispatched and one result entry per
        handler. The bus stores a deep copy of the event; each
        handler receives its own deep copy. A handler raising
        an exception is recorded (outcome "error") and dispatch
        continues. A handler attempting to change the verified
        flag — by returning a dict with a different flag, or by
        mutating the flag of its copy — is recorded as
        "rejected" and its return is discarded; the stored and
        logged flag stays as dispatched.
        """
        if not isinstance(event, dict):
            raise ValueError("event must be a dict")
        for field in ("event", "payload", "licence", "provenance",
                      "verified", "needs_human_decision"):
            if field not in event:
                raise ValueError(f"event is missing field: {field!r}")
        if event["event"] != event_name:
            raise ValueError(
                f"event name mismatch: execute({event_name!r}) given "
                f"an event named {event['event']!r}")
        json.dumps(event)  # must be plain JSON-able, or raise here
        dispatched = copy.deepcopy(event)
        dispatched_flag = bool(dispatched["verified"])
        results = []
        for handler in list(self._handlers.get(event_name, [])):
            name = _handler_name(handler)
            handler_copy = copy.deepcopy(dispatched)
            outcome = "accepted"
            detail = None
            try:
                returned = handler(handler_copy)
            except Exception as exc:  # noqa: BLE001 — recorded, not lost
                outcome = "error"
                detail = f"{type(exc).__name__}: {exc}"
                returned = None
            else:
                # Promotion / demotion by return value: a returned
                # dict whose verified flag differs from the flag as
                # dispatched is rejected and discarded.
                if isinstance(returned, dict) and "verified" in returned:
                    if bool(returned["verified"]) != dispatched_flag:
                        outcome = "rejected"
                        detail = ("handler returned an event with "
                                  f"verified={returned['verified']!r} "
                                  "but the event was dispatched with "
                                  f"verified={dispatched_flag!r}; "
                                  "handlers never change the flag")
                # Promotion / demotion by mutation: the handler was
                # handed a copy, so mutating it cannot change the
                # bus's copy — but the attempt itself is rejected
                # and logged, never silently ignored.
                if outcome == "accepted" and (
                        bool(handler_copy.get("verified"))
                        != dispatched_flag):
                    outcome = "rejected"
                    detail = ("handler mutated the verified flag of "
                              "its copy from "
                              f"{dispatched_flag!r} to "
                              f"{handler_copy.get('verified')!r}; "
                              "handlers never change the flag")
            entry = {
                "schema_version": SCHEMA_VERSION,
                "event": event_name,
                "handler": name,
                "verified": dispatched_flag,
                "outcome": outcome,
                "detail": detail,
            }
            self._log.append(entry)
            results.append(dict(entry))
        return {
            "schema_version": SCHEMA_VERSION,
            "event": event_name,
            "verified": dispatched_flag,
            "needs_human_decision": bool(
                dispatched["needs_human_decision"]),
            "licence": dispatched["licence"],
            "provenance": dispatched["provenance"],
            "event_dispatched": dispatched,
            "handlers_run": len(results),
            "results": results,
            "status": "ok",
        }

    # -- dispatch log ----------------------------------------------------

    def log(self):
        """A deep copy of the in-memory dispatch log."""
        return copy.deepcopy(self._log)

    def log_to_json(self):
        """The dispatch log as a JSON string."""
        return json.dumps(self._log, sort_keys=True)

    def clear_log(self):
        """Empty the dispatch log (test / rotation helper only)."""
        self._log.clear()


def dispatch_record_to_json(record):
    """Serialise a dispatch record to a JSON string."""
    return json.dumps(record, sort_keys=True)


def dispatch_record_from_json(text):
    """Deserialise a dispatch record. Flags carried as stored."""
    return json.loads(text)


# Synthetic example bus (clearly synthetic, not real telemetry):
# a logging handler that records what it saw and a metrics
# handler that counts events per name. Both are observers only.
def synthetic_bus():
    """Build a bus with a logging and a metrics handler attached.

    Returns (bus, seen, counts): ``seen`` is the list of event
    dicts the logging handler received (deep copies), ``counts``
    maps event names to how many times the metrics handler ran.
    """
    bus = EventBus()
    seen = []
    counts = {}

    def logging_handler(event):
        seen.append(copy.deepcopy(event))

    def metrics_handler(event):
        counts[event["event"]] = counts.get(event["event"], 0) + 1

    bus.attach("plan.verified", logging_handler)
    bus.attach("plan.verified", metrics_handler)
    bus.attach("plan.candidate", logging_handler)
    bus.attach("plan.candidate", metrics_handler)
    return bus, seen, counts
