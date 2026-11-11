"""RAP hibernation pattern (Module 1) — original Python, stdlib only.

Design inspiration: hydro-project/infinity (hydro-project/infinity,
Apache-2.0 — verified in the replacements audit from its own
``LICENSE.txt``, full Apache-2.0 text, Copyright 2026 Hydro
Contributors; 57,969 lines of Rust across 21 crates, last commit
``e1a3e4b`` 2026-11-06, 809 stars, 94 forks). The audit's verdict
for it was DEFER: the runtime is a 21-crate, AWS-bound
(Lambda + DynamoDB/SQS/Scheduler/DSQL), paid-LLM-default
(Bedrock Claude) autonomous agent loop with no governance hooks
— no ``needs_human_decision``, no verified/unverified
distinction, no approval gate — in the wrong language for the
v0.3.2 allocation (orchestration is Python; Rust is for
constraint/verification kernels). So the runtime is NOT
adopted: no dependency, no ``rap-protocol`` install, and **no
Infinity code was copied** — this module was written from the
design idea only (the RAP hibernation pattern: fire-and-forget
tool invocation, immediate ack, runtime persists state and
exits, result delivered later to a callback, subscriptions
persisting across hibernations). No new dependency was added
(stdlib only), no LLM, no paid API, no downloads, no real
data — synthetic test data only.

LOCAL-ONLY CHOICE (recorded here and in ASSEMBLY_REPORT.md):
this rebuild is LOCAL-ONLY by default — and in fact local-only
full stop. It implements NO callback URL, NO network listener
and NO HTTP delivery at all. The audit's reason for refusing
the smallest copyable unit (``crates/rap-protocol/src/lib.rs``,
392 lines, ``RapInvocation``/``RapCallback`` JSON types) was
precisely that RAP's callback URLs carry no auth/verification
field and its trust model is anyone-holding-a-callback-URL-
can-deliver-a-result (``ToolCallId`` semantics are
provider-controlled Bedrock ``tooluse_*`` IDs). Copying that
model would import an unauthenticated remote-result channel
into START, where a delivered result must never be trusted on
arrival. Adding an auth token to a callback would only paper
over the same channel: the token would still be a bearer
secret carried in the URL, and START has no callback-listener
infrastructure, no secret store for such tokens, and no
consumer for remote delivery. So the pattern is rebuilt with
the network half removed: a result is delivered by a LOCAL
function call (``deliver_result``) in the same process, and
``register_callback`` unconditionally raises ``ValueError``
— there is no callback to register, and no URL is ever
accepted, stored or fetched. If remote delivery is ever
wanted, it needs its own design (authenticated, verified
channel) and Eric's approval; this module is not that design.

Semantics (original, defined here, not copied):
- A ``session`` is the hibernatable unit: one fire-and-forget
  tool invocation. ``invoke_tool(session_id, tool_call_id,
  tool_name, tool_args, subscriptions=())`` creates it in
  state ``ACTIVE`` and returns ``(session, ack)``. The ack is
  immediate and carries ``acknowledged: True`` — the tool has
  NOT run and no result exists yet; invocation is
  fire-and-forget, execution happens elsewhere (or later) and
  is not this module's business. ``tool_call_id`` is an opaque
  caller-supplied string; unlike RAP it carries no provider
  semantics and is never interpreted — it is only an
  identifier the caller can match a later delivery against.
- States: ``ACTIVE`` -> ``HIBERNATING`` -> ``WOKEN`` ->
  ``HIBERNATING`` -> ``WOKEN`` ... A session hibernates with
  ``hibernate(session)``, which returns the persisted state
  as ONE canonical JSON string (sorted keys, compact
  separators) including a SHA-256 checksum over the payload;
  the runtime is then expected to exit. ``wake(json_string)``
  parses that string, verifies the checksum and the schema
  version, requires the stored state to be ``HIBERNATING``,
  and returns the session in state ``WOKEN``. Any other
  transition raises ``ValueError``: hibernating an already
  hibernating session, waking a string whose state is not
  ``HIBERNATING``, waking a tampered string (checksum
  mismatch), or waking a string with the wrong schema
  version. Hibernate -> wake -> hibernate is byte-identical:
  ``hibernate(wake(hibernate(session))) ==
  hibernate(session)`` — there are no timestamps, no random
  ids and no insertion-order dependence in the envelope, so
  the round trip is exact.
- Subscriptions: ``subscribe(session, subscriber_id)`` /
  ``unsubscribe(session, subscriber_id)`` maintain an ordered
  list of subscriber ids (plain strings, e.g. ``"planner"``,
  ``"verifier"``) naming the parties to be told when a result
  arrives. They are part of the persisted state, so they
  survive hibernation and wake unchanged, in order, with no
  duplicates (subscribing twice is a no-op). Subscribing to a
  hibernating session raises ``ValueError`` — persisted state
  is not mutated in place; wake it first.
- Delivery: ``deliver_result(session, payload, status)``
  records a result on an ``ACTIVE`` or ``WOKEN`` session.
  ``status`` must be ``"PASS"``, ``"FAIL"`` or ``"UNKNOWN"``;
  ``payload`` must be JSON-able. A second delivery to the
  same session raises ``ValueError`` (one invocation, one
  result — a re-delivery is a protocol error, not an update).
  A delivered result is ALWAYS held unverified:
  ``result["verified"]`` is ``False`` and
  ``result["needs_human_decision"]`` is ``True``, whatever
  the status — even a ``"PASS"`` result. Delivery is not
  verification.
- Verification is a SEPARATE step, never part of delivery or
  wake: ``verify_result(session, verdict, human_approved)``
  sets the session's (and the result's) verified flag only
  when the verdict is ``"PASS"`` AND ``human_approved`` is
  ``True``; any other combination leaves it ``False``. It
  requires a delivered result and a session that is not
  hibernating (wake it first). This module does not itself
  check the payload — the real verify step (constraint verify
  + JuMP/HiGHS LP cross-check) is the caller's job; this
  function only records that step's verdict plus the human
  decision. No code path in this module writes the verified
  flag to the affirmative except through that one expression.
- A hibernated state NEVER wakes as verified:
  ``hibernate`` forces ``verified`` to ``False`` on the
  session and on any delivered result before serialising,
  and ``wake`` forces it to ``False`` again on the way back
  in — even if the persisted JSON was hand-crafted with
  ``verified`` set true (and a valid checksum). A result
  delivered after hibernation still goes through the
  separate verify step: it is held unverified until verified
  there. Verification does not survive hibernation either:
  a session verified before hibernating wakes unverified
  and must be re-verified (by the caller's verify step)
  after waking.

Wire format stays JSON: sessions, acks, results and
verification records are plain JSON-able dicts (schema
version "1.0.0"). All data here is synthetic; no network, no
listener, no callback URL, no LLM, no paid API.
"""

import hashlib
import json

SCHEMA_VERSION = "1.0.0"
LICENCE = "Apache-2.0"
PROVENANCE = ("START original — RAP hibernation pattern as design "
              "inspiration only (hydro-project/infinity, Apache-2.0), "
              "no code copied, local-only rebuild")

STATE_ACTIVE = "ACTIVE"
STATE_HIBERNATING = "HIBERNATING"
STATE_WOKEN = "WOKEN"

RESULT_STATUSES = ("PASS", "FAIL", "UNKNOWN")


def _canonical(payload):
    """Canonical JSON for checksumming: sorted keys, compact."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _checksum(payload):
    """SHA-256 hex digest of the canonical JSON of ``payload``."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _require_non_empty_string(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_jsonable(name, value):
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be JSON-able")


def invoke_tool(session_id, tool_call_id, tool_name, tool_args,
                subscriptions=()):
    """Fire-and-forget tool invocation: create a session, ack at once.

    Returns ``(session, ack)``. The session starts in state
    ``ACTIVE`` with no result; the ack carries
    ``acknowledged: True`` and the session/tool-call ids. The
    tool has NOT run — invocation is fire-and-forget, and no
    result exists yet. ``tool_args`` must be JSON-able;
    ``subscriptions`` is an iterable of subscriber-id strings
    (duplicates dropped, order kept). Every record carries
    ``verified`` False and ``needs_human_decision`` True.
    """
    _require_non_empty_string("session_id", session_id)
    _require_non_empty_string("tool_call_id", tool_call_id)
    _require_non_empty_string("tool_name", tool_name)
    _require_jsonable("tool_args", tool_args)
    if isinstance(subscriptions, (str, bytes)) or subscriptions is None:
        raise ValueError("subscriptions must be an iterable of strings")
    seen = []
    for subscriber in subscriptions:
        _require_non_empty_string("subscriber_id", subscriber)
        if subscriber not in seen:
            seen.append(subscriber)
    session = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "state": STATE_ACTIVE,
        "subscriptions": seen,
        "result": None,
        "verified": False,
        "needs_human_decision": True,
    }
    ack = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "state": STATE_ACTIVE,
        "acknowledged": True,
        "verified": False,
        "needs_human_decision": True,
    }
    json.dumps(session)
    json.dumps(ack)
    return session, ack


def subscribe(session, subscriber_id):
    """Add a subscriber to an ACTIVE or WOKEN session.

    Subscriptions persist across hibernations (they are part
    of the persisted state). Subscribing twice is a no-op —
    the list holds no duplicates. Subscribing to a
    hibernating session raises ``ValueError``: wake it first.
    Returns the session.
    """
    _check_session(session)
    _require_non_empty_string("subscriber_id", subscriber_id)
    if session["state"] == STATE_HIBERNATING:
        raise ValueError("cannot subscribe to a hibernating session: "
                         "wake it first")
    if subscriber_id not in session["subscriptions"]:
        session["subscriptions"].append(subscriber_id)
    return session


def unsubscribe(session, subscriber_id):
    """Remove a subscriber from an ACTIVE or WOKEN session.

    Removing a subscriber that is not listed is a no-op.
    Unsubscribing from a hibernating session raises
    ``ValueError``. Returns the session.
    """
    _check_session(session)
    _require_non_empty_string("subscriber_id", subscriber_id)
    if session["state"] == STATE_HIBERNATING:
        raise ValueError("cannot unsubscribe from a hibernating "
                         "session: wake it first")
    if subscriber_id in session["subscriptions"]:
        session["subscriptions"].remove(subscriber_id)
    return session


def _check_session(session):
    """Validate that ``session`` is a session dict from this module."""
    if not isinstance(session, dict):
        raise ValueError("session must be a dict from invoke_tool()")
    if session.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("session has the wrong schema_version")
    for name in ("session_id", "tool_call_id", "tool_name", "state"):
        if name not in session:
            raise ValueError(f"session is missing {name!r}")
    if not isinstance(session.get("subscriptions"), list):
        raise ValueError("session subscriptions must be a list")


def _force_unverified(session):
    """Force the session and any delivered result to unverified."""
    session["verified"] = False
    result = session.get("result")
    if isinstance(result, dict):
        result["verified"] = False


def hibernate(session):
    """Persist a session and return it as one canonical JSON string.

    Only an ``ACTIVE`` or ``WOKEN`` session can hibernate;
    anything else raises ``ValueError``. Before serialising,
    the session's verified flag — and any delivered result's
    — is forced to ``False``: a hibernated state never wakes
    as verified, and verification does not survive
    hibernation. The returned string is canonical JSON
    (sorted keys, compact separators) including a SHA-256
    ``checksum`` over the payload, so
    ``hibernate(wake(hibernate(session)))`` is byte-identical
    to ``hibernate(session)``. The session dict itself is
    moved to state ``HIBERNATING``.
    """
    _check_session(session)
    if session["state"] not in (STATE_ACTIVE, STATE_WOKEN):
        raise ValueError(
            f"cannot hibernate a session in state "
            f"{session['state']!r}: only ACTIVE or WOKEN can hibernate")
    _force_unverified(session)
    session["state"] = STATE_HIBERNATING
    payload = {key: value for key, value in session.items()
               if key != "checksum"}
    envelope = dict(payload)
    envelope["checksum"] = _checksum(payload)
    text = _canonical(envelope)
    session["checksum"] = envelope["checksum"]
    return text


def wake(text):
    """Wake a hibernated session from its persisted JSON string.

    Verifies the checksum (a tampered string raises
    ``ValueError``), the schema version, and that the stored
    state is ``HIBERNATING`` — waking anything else raises
    ``ValueError``. The returned session is in state
    ``WOKEN`` with ``verified`` forced to ``False`` on the
    session and on any delivered result, even if the
    persisted JSON claimed otherwise: a hibernated state
    never wakes as verified.
    """
    if not isinstance(text, str):
        raise ValueError("hibernated state must be a JSON string")
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("hibernated state is not valid JSON")
    if not isinstance(envelope, dict):
        raise ValueError("hibernated state must be a JSON object")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("hibernated state has the wrong schema_version")
    stored_checksum = envelope.get("checksum")
    if not isinstance(stored_checksum, str):
        raise ValueError("hibernated state is missing its checksum")
    payload = {key: value for key, value in envelope.items()
               if key != "checksum"}
    if _checksum(payload) != stored_checksum:
        raise ValueError("hibernated state checksum mismatch: the "
                         "persisted state was tampered with or corrupted")
    if payload.get("state") != STATE_HIBERNATING:
        raise ValueError(
            f"cannot wake a session in state "
            f"{payload.get('state')!r}: only HIBERNATING can wake")
    session = dict(payload)
    session["checksum"] = stored_checksum
    session["state"] = STATE_WOKEN
    _force_unverified(session)
    if not isinstance(session.get("subscriptions"), list):
        raise ValueError("hibernated state subscriptions must be a list")
    json.dumps(session)
    return session


def deliver_result(session, payload, status):
    """Deliver a tool result to an ACTIVE or WOKEN session.

    The result is ALWAYS held unverified: ``verified`` is
    ``False`` and ``needs_human_decision`` is ``True``,
    whatever the status — even ``"PASS"``. Delivery is not
    verification; the result must still go through the
    separate verify step. ``status`` must be ``"PASS"``,
    ``"FAIL"`` or ``"UNKNOWN"``; ``payload`` must be
    JSON-able. A second delivery to the same session raises
    ``ValueError``. Delivering to a hibernating session
    raises ``ValueError`` — wake it first. Returns the
    session.
    """
    _check_session(session)
    if status not in RESULT_STATUSES:
        raise ValueError(
            f"status must be one of {RESULT_STATUSES}, got {status!r}")
    _require_jsonable("payload", payload)
    if session["state"] == STATE_HIBERNATING:
        raise ValueError("cannot deliver a result to a hibernating "
                         "session: wake it first")
    if session.get("result") is not None:
        raise ValueError("a result has already been delivered to this "
                         "session: re-delivery is not allowed")
    session["result"] = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "tool_call_id": session["tool_call_id"],
        "status": status,
        "payload": payload,
        "verified": False,
        "needs_human_decision": True,
    }
    json.dumps(session)
    return session


def verify_result(session, verdict, human_approved):
    """Record the separate verify step's verdict on a delivered result.

    Returns a plain JSON-able verification record. The
    session's (and the result's) verified flag is set only
    when the verdict is ``"PASS"`` AND ``human_approved`` is
    ``True``; any other combination leaves it ``False``. A
    ``"PASS"`` verdict without human approval does NOT
    verify, and a ``"FAIL"``/``"UNKNOWN"`` verdict never
    verifies even with approval. Requires a delivered result
    and a session that is not hibernating (wake it first);
    otherwise raises ``ValueError``. This function does not
    itself check the payload — the real verify step
    (constraint verify + JuMP/HiGHS LP cross-check) is the
    caller's job; this records that step's verdict plus the
    human decision.
    """
    _check_session(session)
    if verdict not in RESULT_STATUSES:
        raise ValueError(
            f"verdict must be one of {RESULT_STATUSES}, got {verdict!r}")
    if session["state"] == STATE_HIBERNATING:
        raise ValueError("cannot verify a hibernating session: "
                         "wake it first")
    if session.get("result") is None:
        raise ValueError("cannot verify a session with no delivered "
                         "result")
    verified = (verdict == "PASS" and human_approved is True)
    session["verified"] = verified
    session["result"]["verified"] = verified
    record = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "session_id": session["session_id"],
        "tool_call_id": session["tool_call_id"],
        "verdict": verdict,
        "human_approved": bool(human_approved),
        "verified": verified,
        "needs_human_decision": True,
    }
    json.dumps(record)
    return record


def register_callback(url, **kwargs):
    """Refuse to register a callback — this module is local-only.

    There is no callback URL, no network listener and no HTTP
    delivery in this rebuild (see the module docstring): the
    audit refused RAP's unauthenticated callback-URL trust
    model, and no auth-token variant of it is implemented
    here. Any call raises ``ValueError``. A callback with a
    bad or missing auth token is therefore rejected — along
    with every other callback — because no callback is ever
    accepted.
    """
    raise ValueError(
        "local-only hibernation: no callback URLs are accepted; "
        "results are delivered by a local deliver_result() call, "
        "never over the network")


# Synthetic example (clearly synthetic, not a real tool run):
# the spine's food-planning LP (delivered 600 t, shortage 50 t)
# as a fire-and-forget tool invocation.
SYNTHETIC_SESSION_ID = "synthetic-food-lp-session"
SYNTHETIC_TOOL_CALL_ID = "call-food-lp-001"


def synthetic_session():
    """Build the synthetic session used by the tests.

    Tool ``solve_food_lp`` over the 1-site 2-crop food system
    (demand 650 t), subscribed by ``"planner"`` and
    ``"verifier"`` — the parties to be told when a result
    arrives. No tool has run; the session is ACTIVE with no
    result.
    """
    session, _ack = invoke_tool(
        SYNTHETIC_SESSION_ID, SYNTHETIC_TOOL_CALL_ID, "solve_food_lp",
        {"site": 1, "crops": ["wheat", "potato"], "demand_t": 650},
        subscriptions=("planner", "verifier"))
    return session


def synthetic_result_payload():
    """The synthetic delivered result: the known LP optimum."""
    return {"delivered_t": 600, "shortage_t": 50, "production_t": 600,
            "land_ha": 70, "water_m3": 100000}
