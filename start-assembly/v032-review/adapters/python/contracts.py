"""Small standard-library guardrails for language-boundary payloads.

ISSUE-09 fix (2026-11-11): both validators now validate against the
actual schema files in ``interop/schemas/`` — the request schema and the
result schema — instead of enforcing a hand-picked subset of their rules.
``jsonschema`` (4.10.3) is importable in the system Python but is NOT
importable in the test environment used for this tree, and this package
declares no third-party dependencies, so the validation below is a
complete hand-rolled equivalent written against the standard library
only. It implements exactly the JSON Schema keywords these two schemas
use (``type``, ``required``, ``properties``, ``additionalProperties``,
``enum``, ``const``, ``pattern``, ``minLength``, ``minimum``,
``if``/``then``/``else``); the loader refuses to run if a schema ever
uses a keyword outside that set, so a future schema addition can never
be silently ignored. ``$id``/``$schema``/``title``/``$comment`` are
metadata and are not constraints.

What the schemas cannot express, and where it is enforced instead
(ISSUE-08's verification already noted the first two; this module does
not claim to enforce them via the schema):

* Unit-registry membership — the schemas only require ``value_unit`` /
  ``bound_unit`` to be non-empty strings. Membership in
  ``contracts/units.py`` is enforced here (a wire request with an
  unknown unit raises) and by the evaluators (``UNKNOWN`` /
  ``UNKNOWN_UNIT``, never ``PASS``).
* ``bound_low <= bound_high`` for ``range`` — the schema's ``if``/``then``
  can only require the two fields to be present, not order them. The
  ordering check lives here.
* Finiteness — JSON Schema ``type: number`` does not exclude ``NaN`` /
  ``±inf`` from a Python caller (those are not valid JSON, but a Python
  ``float`` can hold them). Every numeric field is checked finite here.

Schema version: the schemas carry ``schema_version`` as a ``pattern``
(``^1\\.[0-9]+\\.[0-9]+$``), not the old ``const "1.0.0"`` — the const
contradicted the same-major acceptance the code already implemented
(ISSUE-10, decided 2026-11-11). The canonical version is ``1.0.0``,
held in the single source of truth ``interop/SCHEMA_VERSION`` and read
from there at import time (see also ``interop/CONTRACT_VERSIONING.md``).
The version check still runs before the schema check so a major
mismatch raises the distinct ``unsupported major schema version``
message and a malformed version the distinct ``invalid schema version``
message, exactly as pinned by the existing tests.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_schema_version() -> str:
    try:
        version = (_ROOT / "interop" / "SCHEMA_VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            "cannot read the single source of truth for the schema version "
            "(interop/SCHEMA_VERSION)"
        ) from exc
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise RuntimeError(f"interop/SCHEMA_VERSION holds a malformed version: {version!r}")
    return version


SCHEMA_VERSION = _read_schema_version()
STATUSES = {"PASS", "FAIL", "UNKNOWN", "NOT_CHECKED", "INCOMPLETE"}
OPERATORS = {"<=", ">=", "==", "range"}
REASON_CODES = {"OK", "NON_FINITE", "UNKNOWN_UNIT", "INCOMPATIBLE_UNIT", "INVALID_REQUEST",
                # ISSUE-52/53 (2026-11-11): the two distinct codes Rust
                # and Julia emit — a major version mismatch and an
                # unsupported operator — added to the schema enum and
                # here, so validate_constraint_result accepts the
                # results the other languages actually emit. Python
                # itself raises ValueError for a bad operator at its
                # boundary instead of emitting UNSUPPORTED_OPERATOR.
                "UNSUPPORTED_MAJOR_VERSION", "UNSUPPORTED_OPERATOR"}

# Major version this adapter speaks. Same-major patch/minor versions are
# accepted per interop/CONTRACT_VERSIONING.md (patch: clarifications or
# stricter validation; minor: additive optional fields only). Only a major
# mismatch is rejected, with a distinct error message.
SUPPORTED_MAJOR = int(SCHEMA_VERSION.split(".")[0])


def _load_schema(filename: str) -> dict[str, Any]:
    with (_ROOT / "interop" / "schemas" / filename).open(encoding="utf-8") as f:
        return json.load(f)


_REQUEST_SCHEMA = _load_schema("constraint-evaluation.schema.json")
_RESULT_SCHEMA = _load_schema("constraint-evaluation-result.schema.json")

# The JSON Schema keywords this hand-rolled validator implements. Any
# keyword outside this set in a schema file is a loud failure at import
# time, never a silently ignored constraint.
_SCHEMA_KEYWORDS = {
    "$id", "$schema", "$comment", "title",
    "type", "required", "properties", "additionalProperties",
    "enum", "const", "pattern", "minLength", "minimum",
    "if", "then", "else",
}


def _check_schema_keywords(schema: Any, where: str) -> None:
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        if key not in _SCHEMA_KEYWORDS:
            raise RuntimeError(
                f"unsupported JSON Schema keyword {key!r} in {where}: "
                "adapters/python/contracts.py cannot validate it — extend "
                "the validator instead of silently ignoring the constraint"
            )
        if key == "properties" and isinstance(value, dict):
            for prop, subschema in value.items():
                _check_schema_keywords(subschema, f"{where}.properties.{prop}")
        elif key in ("if", "then", "else"):
            _check_schema_keywords(value, f"{where}.{key}")
        elif key == "additionalProperties" and isinstance(value, dict):
            _check_schema_keywords(value, f"{where}.additionalProperties")


_check_schema_keywords(_REQUEST_SCHEMA, "constraint-evaluation.schema.json")
_check_schema_keywords(_RESULT_SCHEMA, "constraint-evaluation-result.schema.json")


def _validate_schema_version(version: Any) -> None:
    """Accept SCHEMA_VERSION and any same-major patch/minor version.

    A major mismatch raises a distinct error; a malformed version string
    raises a different error again. Neither is silently accepted.
    """
    if not isinstance(version, str):
        raise ValueError("invalid schema version: schema_version must be a string")
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid schema version: {version!r}")
    if int(parts[0]) != SUPPORTED_MAJOR:
        raise ValueError(
            f"unsupported major schema version: {version} "
            f"(supported major version {SUPPORTED_MAJOR})"
        )


def _type_matches(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    raise RuntimeError(f"unsupported JSON Schema type {type_name!r}")


def _validate_against_schema(instance: Any, schema: dict[str, Any], path: str) -> None:
    """Validate ``instance`` against one (sub)schema, raising ValueError.

    Implements the keywords listed in ``_SCHEMA_KEYWORDS``. ``if`` /
    ``then`` / ``else`` are evaluated with the same checks: when the
    instance matches the ``if`` schema the ``then`` schema applies,
    otherwise the ``else`` schema applies.
    """
    if "type" in schema:
        expected = schema["type"]
        types = [expected] if isinstance(expected, str) else expected
        if not any(_type_matches(instance, t) for t in types):
            raise ValueError(
                f"schema violation: {path} must be of type "
                f"{' or '.join(types)}, got {type(instance).__name__}"
            )
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(
            f"schema violation: {path} must be one of "
            f"{sorted(schema['enum'], key=str)}, got {instance!r}"
        )
    if "const" in schema and instance != schema["const"]:
        raise ValueError(
            f"schema violation: {path} must be {schema['const']!r}, got {instance!r}"
        )
    if "pattern" in schema:
        if not isinstance(instance, str) or re.search(schema["pattern"], instance) is None:
            raise ValueError(
                f"schema violation: {path} must match pattern "
                f"{schema['pattern']!r}, got {instance!r}"
            )
    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            raise ValueError(
                f"schema violation: {path} must be at least "
                f"{schema['minLength']} characters long"
            )
    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            raise ValueError(
                f"schema violation: {path} must be >= {schema['minimum']}, got {instance!r}"
            )
    if isinstance(instance, dict):
        if "required" in schema:
            missing = sorted(set(schema["required"]) - instance.keys())
            if missing:
                raise ValueError(f"missing required fields: {missing}")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                _validate_against_schema(instance[key], subschema, f"{path}.{key}")
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extra = sorted(set(instance.keys()) - set(properties.keys()))
            if extra:
                raise ValueError(f"unexpected properties: {extra}")
        elif isinstance(additional, dict):
            for key in sorted(set(instance.keys()) - set(properties.keys())):
                _validate_against_schema(instance[key], additional, f"{path}.{key}")
    if "if" in schema:
        branch = "then" if _matches_schema(instance, schema["if"]) else "else"
        if branch in schema:
            _validate_against_schema(instance, schema[branch], path)


def _matches_schema(instance: Any, schema: dict[str, Any]) -> bool:
    """True when ``instance`` satisfies ``schema`` (same checks, no raise)."""
    try:
        _validate_against_schema(instance, schema, "$")
    except ValueError:
        return False
    return True


def _require_finite_number(payload: dict[str, Any], key: str) -> None:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")


def _check_unit_registry(payload: dict[str, Any], *keys: str) -> None:
    """Unit-registry membership: the schema cannot express it (see the
    module docstring), so it is enforced here. An unknown unit raises —
    it is never passed on to be compared as a raw number."""
    from contracts.units import unit_definition

    for key in keys:
        unit = payload[key]
        if unit_definition(unit) is None:
            raise ValueError(f"unknown unit: {unit}")


def validate_constraint_request(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise TypeError("constraint request must be an object")
    # Version first, so a major mismatch / malformed version keeps its
    # distinct message instead of a generic schema-pattern failure. A
    # missing schema_version is reported by the schema check below.
    if "schema_version" in payload:
        _validate_schema_version(payload["schema_version"])
    _validate_against_schema(payload, _REQUEST_SCHEMA, "$")
    if not isinstance(payload["constraint_id"], str) or not payload["constraint_id"].strip():
        raise ValueError("constraint_id must be a non-empty string")
    if payload["operator"] not in OPERATORS:
        raise ValueError("unsupported operator")
    _require_finite_number(payload, "value")
    _require_finite_number(payload, "tolerance")
    if payload["tolerance"] < 0:
        raise ValueError("tolerance cannot be negative")
    _check_unit_registry(payload, "value_unit", "bound_unit")
    if payload["operator"] == "range":
        _require_finite_number(payload, "bound_low")
        _require_finite_number(payload, "bound_high")
        if payload["bound_low"] > payload["bound_high"]:
            raise ValueError("range lower bound exceeds upper bound")
    else:
        _require_finite_number(payload, "bound")


def evaluate_constraint_request(payload: dict[str, Any]) -> "CheckStatus":
    """Validate a wire request, then evaluate it with the native Constraint.

    Returns a CheckStatus. Unknown units, incompatible units and missing
    range bounds surface as UNKNOWN from Constraint.evaluate, never PASS;
    a malformed request raises before any evaluation happens. Since the
    ISSUE-09 fix, an unknown ``value_unit`` / ``bound_unit`` is itself a
    malformed request at this boundary and raises ValueError from
    validation (the native evaluator still returns UNKNOWN for an
    unknown unit when called directly, as do Rust and Julia).
    """
    from contracts.constraints import Constraint

    validate_constraint_request(payload)
    if payload["operator"] == "range":
        constraint = Constraint(
            payload["constraint_id"], payload["constraint_id"],
            operator="range",
            bound_low=payload["bound_low"], bound_high=payload["bound_high"],
            unit=payload["bound_unit"], tolerance=payload["tolerance"],
        )
    else:
        constraint = Constraint(
            payload["constraint_id"], payload["constraint_id"],
            operator=payload["operator"],
            bound=payload["bound"],
            unit=payload["bound_unit"], tolerance=payload["tolerance"],
        )
    return constraint.evaluate(payload["value"], payload["value_unit"])


def validate_constraint_result(payload: dict[str, Any]) -> None:
    """Validate a wire result against the result schema, fully.

    ISSUE-09 fix: previously this checked only the version (exact
    equality, so even a compatible ``1.0.1`` was rejected), the status,
    and the finiteness of ``normalized_value`` — a result missing
    ``constraint_id`` / ``normalized_value`` / ``normalized_unit`` /
    ``reason_code``, carrying an unknown ``reason_code`` or an extra
    field was accepted. All of those are now rejected by the schema
    check below; the version follows the same same-major rule as a
    request. ``normalized_unit`` is ``string | null`` in the schema, so
    registry membership is deliberately NOT enforced for it here.
    """
    if not isinstance(payload, dict):
        raise TypeError("constraint result must be an object")
    if "schema_version" in payload:
        _validate_schema_version(payload["schema_version"])
    _validate_against_schema(payload, _RESULT_SCHEMA, "$")
    if not isinstance(payload["constraint_id"], str) or not payload["constraint_id"].strip():
        raise ValueError("constraint_id must be a non-empty string")
    if payload.get("status") not in STATUSES:
        raise ValueError("invalid result status")
    if payload.get("reason_code") not in REASON_CODES:
        raise ValueError("invalid result reason_code")
    value = payload.get("normalized_value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
        raise ValueError("normalized_value must be finite or null")
