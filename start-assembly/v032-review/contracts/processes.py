"""Shared process and transformation representations.

CONTRACT VALIDATION RULES (ISSUE-48, 2026-11-11) — one rule per concept,
enforced in ``__post_init__``; see also docs/ARCHITECTURE.md:

* Ids are non-empty everywhere: ``Process.process_id`` and
  ``Process.name``, and ``ProcessInput``/``ProcessOutput.resource_id``
  (a reference id must identify the resource), must be non-empty
  strings (whitespace-only counts as empty).
* Unit is REQUIRED for quantity-bearing types (``ProcessInput``,
  ``ProcessOutput``): it must be a known registry unit even when
  ``quantity`` is None — same rule as ``Resource``/``Stock``/``Flow``.
  The unit is part of the quantity's identity; a unit-less amount
  cannot be compared or converted later. (Note the defaults
  ``quantity=None, unit=""`` still raise on construction: a caller
  must supply a unit. The defaults only mean "no value yet", not
  "no unit needed".)
* Quantities (ISSUE-31): a physical amount is non-negative when
  present (None = unknown, still allowed); zero is allowed. Direction
  is expressed by input vs output role, never by sign — a negative
  input quantity is not a meaningful "consumption" here, and no
  process type has a sign/direction field to disambiguate it.
  ``ProcessInput``/``ProcessOutput`` have no status field, so the
  ISSUE-31 VERIFIED-with-None rule does not apply to them.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import math
from .units import unit_definition


def _require_nonempty_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _check_quantity(quantity: Optional[float], unit: str, label: str = "process quantity") -> None:
    if not unit or unit_definition(unit) is None:
        raise ValueError(f"unknown or missing unit: {unit!r}")
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity)):
        raise ValueError("process quantity must be finite numeric or None")
    # ISSUE-31 (2026-11-11): same rule as Resource/Stock/Flow — a
    # physical amount cannot be negative; None (unknown) stays
    # allowed. Direction is input vs output, never sign.
    if quantity is not None and quantity < 0:
        raise ValueError(f"{label} cannot be negative: a physical amount must be non-negative (None means unknown)")


@dataclass
class ProcessInput:
    resource_id: str
    quantity: Optional[float] = None
    unit: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        _require_nonempty_id(self.resource_id, "resource_id")
        _check_quantity(self.quantity, self.unit, "ProcessInput quantity")


@dataclass
class ProcessOutput:
    resource_id: str
    quantity: Optional[float] = None
    unit: str = ""

    def __post_init__(self) -> None:
        _require_nonempty_id(self.resource_id, "resource_id")
        _check_quantity(self.quantity, self.unit, "ProcessOutput quantity")


@dataclass
class Process:
    process_id: str
    name: str
    inputs: list[ProcessInput] = field(default_factory=list)
    outputs: list[ProcessOutput] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    constraint_ids: list[str] = field(default_factory=list)
    geography: str = "unspecified"
    period: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_nonempty_id(self.process_id, "process_id")
        _require_nonempty_id(self.name, "process name")

    def to_dict(self) -> dict[str, Any]: return asdict(self)
