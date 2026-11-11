"""A2UI emitter + approval gate (Module 25) — original Python, stdlib only.

Design inspiration: a2ui-project/a2ui (the A2UI protocol,
Apache-2.0 — verified in the replacements audit
``source-audit/REPLACEMENTS_AUDIT.md`` §7 from its own root
``LICENSE`` file, full Apache-2.0 text; 17,055 stars, 1,897
commits, last commit ``24d1bf9`` 2026-11-11, a breaking
``@``-prefixed v1.0 component-envelope change). The audit's
verdict for it was DEFER, and the audit's unblock is NOT met:
Eric has NOT approved Module 25 UI work, has NOT picked a
renderer stack, and no published a2ui-core supporting v1.0
has been confirmed. So NOTHING is adopted here: no a2ui-core,
no a2ui-agent-sdk, no a2ui-adk, no dependency, no renderer,
no host app — and **no a2ui code was copied**. This module
was written from the design idea only: the A2UI protocol is
a JSON wire format (agent -> renderer messages
``createSurface`` / ``updateComponents`` / ``updateDataModel``
/ ``deleteSurface`` plus bidirectional typed RPC) that lets an
agent stream UI as validated JSON data to a native renderer,
so the agent composes interfaces without executing code.
What START rebuilds originally, per the audit's REWRITE
verdict, is only the emitter/adapter that turns verified
plans into surfaces, the human-approval gate for
consequential function calls, and the verification-status
stamp on every surface.

NO CONSUMER YET (recorded here and in ASSEMBLY_REPORT.md):
START has no user-facing UI surface and no renderer — the
renderers are TypeScript (React/Lit/Angular), Dart/Flutter,
SwiftUI and Kotlin/Jetpack Compose, none of which is in the
v0.3.2 allocation, which has no UI language at all. An
emitted surface is therefore a JSON document nobody renders:
``consumer_status()`` reports ``{"renderer": None,
"host_app": None, "status": "no consumer — emitter only"}``,
and every emitted surface carries ``"consumer": "none"``.
The renderer/host app remain DEFERRED until Eric approves
Module 25 UI work and picks a renderer stack.

Governance — the gap this module exists to close: A2UI's
own security model (UI as data not code, strict schema
validation, per-function execution boundaries
``rendererOnly`` / ``agentOnly`` / ``rendererOrAgent``,
``requiresUserActivation`` gating functions like ``openUrl``
behind a user gesture, forced ``rendererOnly`` so the agent
cannot invoke them remotely) has NO verification or
human-approval concept — in the v1.0 spec "verify" means
schema/tree-integrity validation only. There is no
``needs_human_decision``, no verified/unverified
distinction, no approval workflow. START adds all of it on
top, because a slick rendered surface can make an
unverified plan *look* verified — exactly how a planner
would certify its own output through the presentation
layer. So:

- ``emit_surface(plan)`` emits a ``createSurface`` JSON
  message ONLY for a plan whose ``verification_status`` is
  ``"PASS"`` AND whose ``human_approved`` is exactly
  ``True``. An UNVERIFIED plan (status ``"UNKNOWN"`` or
  anything else), a ``"FAIL"`` plan, and a ``"PASS"`` plan
  that is NOT human-approved are all REFUSED with
  ``EmissionRefused`` — never emitted, never downgraded to
  a "draft" surface. This module never verifies a plan
  itself and never sets ``verification_status``: it reads
  the status the caller hands in, verbatim.
- Every emitted surface stamps the verification status
  onto it, in two places: top-level ``"verification"``
  (``status``, ``human_approved``, ``needs_human_decision``
  always ``True``) and inside ``"dataModel"``. The surface
  is JSON data only — components are plain dicts
  (``{"type": "Text", ...}`` / ``{"type": "Card", ...}``),
  never code, never a callable.
- ``update_data_model(surface, data, plan)`` and
  ``delete_surface(surface, plan)`` apply the SAME gate:
  the plan must still be verified PASS and human-approved
  at the time of the update/delete, or the call is refused.
- ``gate_function_call(call, approval)`` is the
  human-approval gate for consequential function calls.
  The gate NEVER approves its own calls: ``approval`` must
  be an explicit record supplied by a human, with
  ``approved`` exactly ``True``, a non-empty
  ``approved_by`` (who), a non-empty ``approval_id``
  (which approval), and a ``scope`` that names the
  function being called. A consequential call with no
  approval, a ``False`` approval, or an approval whose
  scope does not cover the function is REFUSED with
  ``GateRefused``. When allowed, the approval record is
  copied into the result (``result["approval"]``) — the
  approval is recorded, never invented. A non-consequential
  call is allowed without approval and records
  ``approval: None``. The A2UI execution boundary is also
  enforced: a ``rendererOnly`` function can never be
  invoked by the agent, approval or not (it is the
  renderer's to run, and the agent invoking it remotely is
  exactly what the boundary forbids); an unknown boundary
  is refused, never defaulted to allowed.
- Wire format stays JSON: every surface and every gate
  result is JSON-serialisable (plain dicts/lists/strings/
  numbers/bools/None), with sorted keys and no timestamps
  or random ids, so emission is deterministic for a given
  plan. No pickle, no network, no downloads, no real data
  — synthetic test data only.
"""

import json

PROTOCOL = "a2ui"
PROTOCOL_VERSION = "1.0"

# The execution boundaries from the A2UI v1.0 spec (design
# idea only — the strings, not any a2ui code).
BOUNDARY_RENDERER_ONLY = "rendererOnly"
BOUNDARY_AGENT_ONLY = "agentOnly"
BOUNDARY_RENDERER_OR_AGENT = "rendererOrAgent"
BOUNDARIES = (
    BOUNDARY_RENDERER_ONLY,
    BOUNDARY_AGENT_ONLY,
    BOUNDARY_RENDERER_OR_AGENT,
)

# No consumer exists: no renderer, no host app.
CONSUMER = "none"


class EmissionRefused(ValueError):
    """A plan was refused emission (not verified PASS + approved)."""


class GateRefused(ValueError):
    """A function call was refused by the approval gate."""


def consumer_status():
    """Report the (absent) consumer for emitted surfaces.

    The emitter has no consumer yet: no renderer, no host
    app. This is a fact about the assembly, not a value a
    caller can change — there is no setter for it.
    """
    return {
        "renderer": None,
        "host_app": None,
        "status": "no consumer — emitter only",
    }


def _require_gate(plan):
    """Enforce verified-PASS + human-approved, or raise.

    Returns the verification stamp dict. Reads the plan's
    status verbatim — never sets or upgrades it.
    """
    if not isinstance(plan, dict):
        raise EmissionRefused("plan is not an object")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise EmissionRefused("plan has no non-empty plan_id")
    status = plan.get("verification_status")
    if status != "PASS":
        raise EmissionRefused(
            f"plan {plan_id!r} refused: verification_status "
            f"is {status!r}, not 'PASS'"
        )
    if plan.get("human_approved") is not True:
        raise EmissionRefused(
            f"plan {plan_id!r} refused: verified PASS but not "
            "human-approved"
        )
    return {
        "status": "PASS",
        "human_approved": True,
        "needs_human_decision": True,
    }


def _surface_id(plan_id):
    return f"surface-{plan_id}"


def _components_for(plan):
    """Build the surface's components from the plan, as data only.

    One Card per plan, holding a Text title, a Text summary,
    and one Text row per item (``{"label": ..., "value": ...}``).
    Components are plain dicts — no code, no callables.
    """
    items = plan.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise EmissionRefused("plan items must be a list")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise EmissionRefused("plan item is not an object")
        label = item.get("label")
        value = item.get("value")
        if not isinstance(label, str) or not label:
            raise EmissionRefused("plan item has no non-empty label")
        rows.append({"type": "Text", "text": f"{label}: {value}"})
    title = plan.get("title")
    if not isinstance(title, str) or not title:
        raise EmissionRefused("plan has no non-empty title")
    summary = plan.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise EmissionRefused("plan summary must be a string")
    return [
        {
            "type": "Card",
            "title": title,
            "children": (
                [{"type": "Text", "text": summary}] if summary else []
            )
            + rows,
        }
    ]


def emit_surface(plan):
    """Turn a verified + human-approved plan into a surface.

    Returns a ``createSurface`` JSON message (a plain dict).
    Raises ``EmissionRefused`` for any plan that is not
    verified PASS *and* human-approved.
    """
    verification = _require_gate(plan)
    components = _components_for(plan)
    surface = {
        "protocol": PROTOCOL,
        "version": PROTOCOL_VERSION,
        "message": "createSurface",
        "surface_id": _surface_id(plan["plan_id"]),
        "plan_id": plan["plan_id"],
        "consumer": CONSUMER,
        "verification": dict(verification),
        "components": components,
        "dataModel": {
            "plan_id": plan["plan_id"],
            "title": plan["title"],
            "verification": dict(verification),
        },
    }
    # Deterministic JSON: sorted keys, no timestamps, no ids.
    json.dumps(surface, sort_keys=True)
    return surface


def update_data_model(surface, data, plan):
    """Emit an ``updateDataModel`` message for a surface.

    The same gate applies: the plan must still be verified
    PASS and human-approved, or the update is refused.
    ``surface`` must be a surface this module emitted for
    the same plan (same surface_id); ``data`` must be a
    JSON-serialisable dict.
    """
    verification = _require_gate(plan)
    if not isinstance(surface, dict):
        raise EmissionRefused("surface is not an object")
    if surface.get("surface_id") != _surface_id(plan["plan_id"]):
        raise EmissionRefused(
            "surface does not belong to this plan"
        )
    if not isinstance(data, dict):
        raise EmissionRefused("update data must be an object")
    json.dumps(data, sort_keys=True)
    return {
        "protocol": PROTOCOL,
        "version": PROTOCOL_VERSION,
        "message": "updateDataModel",
        "surface_id": surface["surface_id"],
        "plan_id": plan["plan_id"],
        "consumer": CONSUMER,
        "verification": dict(verification),
        "dataModel": dict(data),
    }


def delete_surface(surface, plan):
    """Emit a ``deleteSurface`` message for a surface.

    The same gate applies: the plan must still be verified
    PASS and human-approved, or the delete is refused.
    """
    verification = _require_gate(plan)
    if not isinstance(surface, dict):
        raise EmissionRefused("surface is not an object")
    if surface.get("surface_id") != _surface_id(plan["plan_id"]):
        raise EmissionRefused(
            "surface does not belong to this plan"
        )
    return {
        "protocol": PROTOCOL,
        "version": PROTOCOL_VERSION,
        "message": "deleteSurface",
        "surface_id": surface["surface_id"],
        "plan_id": plan["plan_id"],
        "consumer": CONSUMER,
        "verification": dict(verification),
    }


def _check_approval(call, approval):
    """Validate an explicit human approval record for a call.

    Returns a recorded copy of the approval. Raises
    ``GateRefused`` for a missing, false, malformed, or
    out-of-scope approval. The gate never approves: it only
    checks the record a human supplied.
    """
    name = call["function_name"]
    if not isinstance(approval, dict):
        raise GateRefused(
            f"call {name!r} refused: no approval record supplied"
        )
    if approval.get("approved") is not True:
        raise GateRefused(
            f"call {name!r} refused: approval is not approved=True"
        )
    approved_by = approval.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by:
        raise GateRefused(
            f"call {name!r} refused: approval has no approved_by"
        )
    approval_id = approval.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        raise GateRefused(
            f"call {name!r} refused: approval has no approval_id"
        )
    scope = approval.get("scope")
    if isinstance(scope, str):
        covered = scope == name
    elif isinstance(scope, (list, tuple)):
        covered = name in scope
    else:
        covered = False
    if not covered:
        raise GateRefused(
            f"call {name!r} refused: approval scope {scope!r} "
            "does not cover this function"
        )
    return {
        "approved": True,
        "approved_by": approved_by,
        "approval_id": approval_id,
        "scope": scope if isinstance(scope, str) else list(scope),
    }


def gate_function_call(call, approval=None):
    """Gate one function call behind human approval.

    ``call`` is a dict: ``function_name`` (non-empty str),
    ``boundary`` (one of the three A2UI boundaries),
    ``consequential`` (bool), ``args`` (dict, optional).
    ``approval`` is the explicit human approval record (or
    None). Returns ``{"allowed": True, "function_name": ...,
    "boundary": ..., "consequential": ..., "approval": ...}``
    with the approval recorded (or None for a
    non-consequential call). Raises ``GateRefused`` when the
    call is refused. A refused call is never executed by
    this module — it returns no result and performs nothing.
    """
    if not isinstance(call, dict):
        raise GateRefused("call is not an object")
    name = call.get("function_name")
    if not isinstance(name, str) or not name:
        raise GateRefused("call has no non-empty function_name")
    boundary = call.get("boundary")
    if boundary not in BOUNDARIES:
        raise GateRefused(
            f"call {name!r} refused: unknown boundary {boundary!r}"
        )
    if boundary == BOUNDARY_RENDERER_ONLY:
        # The agent may never invoke a rendererOnly function
        # remotely, approval or not — that is what the
        # boundary forbids.
        raise GateRefused(
            f"call {name!r} refused: rendererOnly functions "
            "cannot be invoked by the agent"
        )
    consequential = call.get("consequential")
    if not isinstance(consequential, bool):
        raise GateRefused(
            f"call {name!r} refused: consequential must be a bool"
        )
    args = call.get("args", {})
    if not isinstance(args, dict):
        raise GateRefused(f"call {name!r} refused: args must be an object")
    json.dumps(args, sort_keys=True)
    if consequential:
        recorded = _check_approval(call, approval)
    else:
        recorded = None
    result = {
        "allowed": True,
        "function_name": name,
        "boundary": boundary,
        "consequential": consequential,
        "approval": recorded,
        "needs_human_decision": True,
    }
    json.dumps(result, sort_keys=True)
    return result


def synthetic_verified_plan():
    """A synthetic verified + human-approved plan (test data)."""
    return {
        "plan_id": "synthetic-food-plan-001",
        "title": "Synthetic food plan",
        "summary": "Delivered 600 t, shortage 50 t (synthetic 1-site 2-crop).",
        "verification_status": "PASS",
        "human_approved": True,
        "items": [
            {"label": "delivered_t", "value": 600},
            {"label": "shortage_t", "value": 50},
            {"label": "land_ha", "value": 70},
        ],
    }


def synthetic_unverified_plan():
    """A synthetic plan that has not been verified (test data)."""
    plan = synthetic_verified_plan()
    plan["plan_id"] = "synthetic-food-plan-002"
    plan["verification_status"] = "UNKNOWN"
    plan["human_approved"] = False
    return plan


def synthetic_approval(function_name="apply_plan"):
    """A synthetic explicit human approval record (test data)."""
    return {
        "approved": True,
        "approved_by": "human-reviewer",
        "approval_id": "approval-001",
        "scope": function_name,
    }
