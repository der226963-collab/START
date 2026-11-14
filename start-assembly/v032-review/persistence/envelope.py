"""Versioned JSON-envelope persistence for START planning (ISSUE-27).

Every persisted file is one JSON object with exactly these top-level
keys::

    {
      "schema_version": "<canonical version, e.g. 1.0.0>",
      "kind": "<one of KINDS>",
      "saved_at": "<UTC ISO-8601 with Z suffix>",
      "payload": { ... }
    }

Rules (see ``interop/CONTRACT_VERSIONING.md``):

* ``schema_version`` is mandatory. It is taken from the single source
  of truth — ``adapters.python.contracts.SCHEMA_VERSION``, itself read
  at import time from ``interop/SCHEMA_VERSION`` — never a second
  hard-coded copy in this package.
* On load, any same-major version (``1.x``) is accepted; a different
  major is rejected with a ``ValueError`` naming both versions. A file
  is never silently reinterpreted.
* Writes are atomic: the envelope is written to a temporary file in
  the *same directory* as the target and moved onto the target with
  ``os.replace``, so a crash can never leave a half-written file.
* Paths are always caller-chosen. There is no default store directory,
  no SQLite, no database — JSON files only, standard library only.
* Logging goes through ``engine.event_log.log_event("persistence",
  ...)`` and carries metadata only (kind, path, schema_version,
  reason) — never a payload, per the event-log privacy rule.

The persisted ``payload`` is stored verbatim: a result dict keeps its
statuses exactly as the engine produced them (``UNKNOWN`` stays
``UNKNOWN``; no status is ever upgraded, downgraded, or normalised on
the way in or out). Payloads are validated only for shape here — the
engine still validates plan keys at check time and the ``Scenario``
constructor validates the rest of a scenario downstream.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from adapters.python.contracts import SCHEMA_VERSION, SUPPORTED_MAJOR
from engine.event_log import log_event, utc_now_iso

__all__ = [
    "KINDS",
    "ENVELOPE_KEYS",
    "save_envelope",
    "load_envelope",
]

# The only kinds a persisted file may carry. Enumerated here, in this
# one place; the CLI uses exactly these names — do not rename them.
KINDS = frozenset({"plan_request", "scenario", "result", "plan_overrides"})

# The exact top-level keys every envelope carries, no more, no fewer.
ENVELOPE_KEYS = frozenset({"schema_version", "kind", "saved_at", "payload"})


def _fail(path: Path, reason: str) -> ValueError:
    """Build the load/save failure error: always names path + reason."""
    return ValueError(f"{path}: {reason}")


def _check_schema_version(version: Any, path: Path) -> None:
    """Accept the canonical version and any same-major ``X.Y.Z``.

    A malformed version and a major mismatch are distinct failures,
    both naming the path and the version involved — following
    ``interop/CONTRACT_VERSIONING.md`` exactly (patch/minor same-major
    accepted, major mismatch rejected, never silently reinterpreted).
    """
    if not isinstance(version, str):
        raise _fail(path, f"invalid schema version: {version!r} (must be a string)")
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise _fail(path, f"invalid schema version: {version!r}")
    if int(parts[0]) != SUPPORTED_MAJOR:
        raise _fail(
            path,
            f"unsupported major schema version: {version} "
            f"(supported {SCHEMA_VERSION}, major {SUPPORTED_MAJOR})",
        )


def _validate_payload(kind: str, payload: Any, path: Path) -> None:
    """Minimal kind-specific payload-shape checks for a loaded file.

    * ``plan_request`` / ``plan_overrides``: must be a dict; plan keys
      are validated by the engine at check time, not here.
    * ``scenario``: must contain non-empty string ``scenario_id`` and
      ``name`` (the ``Scenario`` constructor validates the rest
      downstream).
    * ``result``: must contain ``domain`` (str) and ``calculation``
      (dict); statuses inside are carried verbatim, never re-judged.
    """
    if not isinstance(payload, dict):
        raise _fail(path, f"payload for kind {kind!r} must be a JSON object")
    if kind == "scenario":
        for field in ("scenario_id", "name"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise _fail(
                    path,
                    f"scenario payload must contain a non-empty string {field!r}",
                )
    elif kind == "result":
        if not isinstance(payload.get("domain"), str):
            raise _fail(path, "result payload must contain \"domain\" (str)")
        if not isinstance(payload.get("calculation"), dict):
            raise _fail(path, "result payload must contain \"calculation\" (dict)")


def save_envelope(
    path: str | os.PathLike[str],
    kind: str,
    payload: dict[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    """Save ``payload`` as a versioned JSON envelope at ``path``.

    Returns the :class:`pathlib.Path` written. ``path`` is always
    caller-chosen; there is no default store directory.

    Raises ``ValueError`` for an unknown ``kind`` or a non-dict
    ``payload`` (and for a payload that is not JSON-serialisable), and
    ``FileExistsError`` (naming the path) when the target already
    exists and ``overwrite`` is False — the existing file is left
    untouched in that case. Other I/O errors (e.g. a missing parent
    directory — parents are never created for the caller) propagate
    unchanged.

    The write is atomic: the envelope is written to a temporary file
    in the same directory as the target, flushed and fsynced, then
    moved onto the target with ``os.replace``. If anything fails
    mid-write the temporary file is removed and no target file
    appears (or the previous target is left byte-identical).
    """
    target = Path(path)
    if kind not in KINDS:
        reason = f"unknown kind: {kind!r} (known kinds: {sorted(KINDS)})"
        log_event("persistence", "save_failed", logging.WARNING,
                  "save refused", path=str(target), reason=reason)
        raise ValueError(f"{target}: {reason}")
    if not isinstance(payload, dict):
        reason = "payload must be a dict"
        log_event("persistence", "save_failed", logging.WARNING,
                  "save refused", path=str(target), reason=reason)
        raise ValueError(f"{target}: {reason}")
    if target.exists() and not overwrite:
        reason = "file already exists (pass overwrite=True to replace it)"
        log_event("persistence", "save_failed", logging.WARNING,
                  "save refused", path=str(target), reason=reason)
        raise FileExistsError(f"{target}: {reason}")

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "saved_at": utc_now_iso(),
        "payload": payload,
    }
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(envelope, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except (TypeError, ValueError) as exc:
            # Payload is not JSON-serialisable (TypeError) or otherwise
            # unrepresentable: a caller-input problem, reported as one.
            reason = f"payload is not JSON-serialisable: {exc}"
            log_event("persistence", "save_failed", logging.WARNING,
                      "save failed", path=str(target), reason=reason)
            raise ValueError(f"{target}: {reason}") from exc
        os.replace(tmp_path, target)
        tmp_path = None  # moved onto the target; nothing left to clean up
    except Exception as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        if not isinstance(exc, ValueError):
            # I/O or replace failure: a system error, not bad input.
            # The target was never touched (replace is the only move
            # onto it), so no half-written file can exist.
            log_event("persistence", "save_failed", logging.ERROR,
                      "save failed", path=str(target), reason=str(exc))
        raise
    log_event("persistence", "save", logging.INFO, "envelope saved",
              kind=kind, path=str(target), schema_version=SCHEMA_VERSION)
    return target


def load_envelope(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and validate the versioned JSON envelope at ``path``.

    Returns the full envelope dict — ``schema_version``, ``kind``,
    ``saved_at`` and ``payload`` — with the payload verbatim as saved.
    Callers read the data from the returned ``["payload"]``.

    Any failure raises ``ValueError`` naming the file path and the
    reason, and never returns a half-loaded object: unreadable or
    corrupt JSON, a non-object top level, a missing envelope key, an
    unknown ``kind``, a malformed or different-major
    ``schema_version``, or a payload failing its kind-specific shape
    check. A missing file is likewise a ``ValueError`` (not
    ``FileNotFoundError``). A successful load logs an INFO event
    (kind, path, schema_version); a failed load logs a WARNING with
    path and reason only — never any payload content.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        reason = f"cannot read file: {exc}"
        log_event("persistence", "load_failed", logging.WARNING,
                  "load failed", path=str(target), reason=reason)
        raise _fail(target, reason) from exc
    try:
        envelope = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        reason = f"corrupt JSON: {exc}"
        log_event("persistence", "load_failed", logging.WARNING,
                  "load failed", path=str(target), reason=reason)
        raise _fail(target, reason) from exc

    try:
        if not isinstance(envelope, dict):
            raise _fail(target, "top-level value must be a JSON object")
        missing = sorted(ENVELOPE_KEYS - envelope.keys())
        if missing:
            raise _fail(target, f"missing required envelope keys: {missing}")
        # Extra top-level keys are tolerated: a same-major minor
        # version may add optional fields (see CONTRACT_VERSIONING.md).
        kind = envelope["kind"]
        if kind not in KINDS:
            raise _fail(
                target,
                f"unknown kind: {kind!r} (known kinds: {sorted(KINDS)})",
            )
        _check_schema_version(envelope["schema_version"], target)
        saved_at = envelope["saved_at"]
        if not isinstance(saved_at, str) or not saved_at.strip():
            raise _fail(target, "saved_at must be a non-empty string")
        _validate_payload(kind, envelope["payload"], target)
    except ValueError as exc:
        # _fail() already built a "path: reason" message; log it once.
        log_event("persistence", "load_failed", logging.WARNING,
                  "load failed", path=str(target), reason=str(exc))
        raise
    log_event("persistence", "load", logging.INFO, "envelope loaded",
              kind=kind, path=str(target),
              schema_version=envelope["schema_version"])
    return envelope
