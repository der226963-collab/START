"""Shared resource, stock and flow representations.

Resource describes a resource type or a scoped observation. Stock is a quantity
held at an instant; Flow is a quantity transferred over an interval.

CONTRACT VALIDATION RULES (ISSUE-48, 2026-11-11) — one rule per concept,
enforced in ``__post_init__``; see also docs/ARCHITECTURE.md:

* Ids are non-empty everywhere: ``resource_id``, ``stock_id``,
  ``flow_id`` must be non-empty strings (whitespace-only counts as
  empty). A reference id (``Stock``/``Flow.resource_id``) must likewise
  be non-empty — it identifies the resource being observed.
* Unit is REQUIRED for quantity-bearing types (``Resource``, ``Stock``,
  ``Flow``): it must be a known registry unit even when ``quantity`` is
  None. The unit is part of the observation's identity — a unit-less
  amount cannot be compared or converted later. No existing caller
  needs a unit-less quantity type (verified by grep 2026-11-11: no
  production caller constructs these with quantity None and no unit).
  This is the deliberate asymmetry with ``Constraint``/``Objective``,
  whose unit is optional ("" = deliberately unit-less, e.g. the
  plan_limits phosphorus/work-hours constraints).
* Quantities (ISSUE-12/31): a physical amount is non-negative when
  present (None = unknown, still allowed); zero is allowed. Negative
  quantities are never meaningful here — a deficit/shortfall is a
  signed metric, not a Resource/Stock/Flow, and none of these types
  has a sign/direction field that could distinguish a deficit from an
  amount.
* Status (ISSUE-31): ``status=VERIFIED`` requires a quantity — a
  VERIFIED observation of nothing is a contradiction, so construction
  raises when ``quantity is None`` and ``status`` is VERIFIED.
  ``is_verified()`` already returned False for None quantities; the
  fix is at construction, not in ``is_verified()``.
* Dates (ISSUE-24): ``Flow.start``/``Flow.end`` are ISO-8601 dates
  (``YYYY-M-D``, month/day zero-padding optional) or ISO-8601
  datetimes; they are parsed to ``datetime.date`` and compared as
  dates, never as strings. Unparseable values raise with a clear
  error. ``Stock.as_of`` is NOT parsed — it is a period label and may
  be e.g. "2026".
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import math
import re
from datetime import date, datetime
from .statuses import DataStatus
from .units import unit_definition


def _require_nonempty_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _validate_quantity(quantity: Optional[float], unit: str, label: str = "quantity") -> None:
    if not unit or unit_definition(unit) is None:
        raise ValueError(f"unknown or missing unit: {unit!r}")
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity)):
        raise ValueError("quantity must be a finite number or None")
    # ISSUE-31 (2026-11-11): the ISSUE-12 Resource rule, extended to
    # Stock and Flow via this shared helper. A held/transferred
    # physical amount cannot be negative; None (unknown) stays
    # allowed. Zero is allowed.
    if quantity is not None and quantity < 0:
        raise ValueError(f"{label} cannot be negative: a physical amount must be non-negative (None means unknown)")


def _validate_status(quantity: Optional[float], status: DataStatus, label: str) -> None:
    # ISSUE-31 (2026-11-11): VERIFIED with no value serializes
    # misleadingly ("status": "verified", "quantity": null) even
    # though is_verified() correctly returns False. Verification is a
    # claim about a value; with no value there is nothing verified,
    # so construction raises instead of emitting the contradiction.
    if status == DataStatus.VERIFIED and quantity is None:
        raise ValueError(f"{label} cannot be VERIFIED without a quantity: quantity is None")


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def _parse_iso_date(value: Any, field_name: str) -> date:
    """Parse a Flow start/end value to a ``datetime.date``.

    ISSUE-24 (2026-11-11): the old check compared the raw strings,
    so "2026-9-1" > "2026-10-1" lexicographically and a valid
    September-to-October flow was rejected, while "2026-01-05" to
    "2026-1-4" (start after end) constructed fine. Strings are now
    parsed and compared as dates. Note: ``date.fromisoformat`` does
    NOT accept non-padded month/day (verified live on Python 3.12),
    so a regex normalises ``YYYY-M-D`` (padding optional) and
    ``date(...)`` validates ranges (month 1..12, real day, leap
    years); a full ISO-8601 datetime string is accepted via
    ``datetime.fromisoformat`` and reduced to its calendar date.
    Anything else raises with a clear error instead of constructing
    with an uncomparable label.
    """
    if not isinstance(value, str):
        raise ValueError(f"flow {field_name} must be an ISO-8601 date string, got {value!r}")
    m = _ISO_DATE_RE.match(value)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError as exc:
            raise ValueError(f"flow {field_name} is not a valid ISO-8601 date: {value!r} ({exc})") from exc
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        raise ValueError(
            f"flow {field_name} must be an ISO-8601 date (YYYY-MM-DD, month/day may be unpadded) "
            f"or ISO-8601 datetime, got {value!r}") from None



@dataclass
class Resource:
    resource_id: str
    category: str
    quantity: Optional[float]
    unit: str
    geography: str = "unspecified"
    period: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    uncertainty: Optional[str] = None
    status: DataStatus = DataStatus.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty_id(self.resource_id, "resource_id")
        _validate_quantity(self.quantity, self.unit, "Resource quantity")
        _validate_status(self.quantity, self.status, "Resource")
        # ISSUE-12 (2026-11-11): a Resource quantity is a physical
        # amount held/observed, so a negative quantity is meaningless
        # here and raises instead of constructing silently. None stays
        # allowed (quantity unknown, status UNKNOWN). Negative
        # quantities are never meaningful for Resource in this tree:
        # no caller represents a deficit/shortfall as a Resource —
        # signed balances (e.g. an annual gap/surplus) are metrics,
        # not Resources — and Resource has no sign/direction field
        # that could distinguish a deficit from an amount. If a
        # signed balance is ever needed it must be a distinct type
        # or field, not a negative Resource quantity.
        # The negativity check itself lives in the shared
        # _validate_quantity (ISSUE-31 extended the same rule to
        # Stock/Flow); the VERIFIED-with-None check is in
        # _validate_status above.

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self); d["status"] = self.status.value
        return d

    def has_value(self) -> bool:
        return self.quantity is not None

    def is_known(self) -> bool:
        return self.has_value() and self.status != DataStatus.UNKNOWN

    def is_verified(self) -> bool:
        return self.has_value() and self.status == DataStatus.VERIFIED


@dataclass
class Stock:
    stock_id: str
    resource_id: str
    quantity: Optional[float]
    unit: str
    as_of: str
    geography: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    status: DataStatus = DataStatus.UNKNOWN

    def __post_init__(self) -> None:
        _require_nonempty_id(self.stock_id, "stock_id")
        _require_nonempty_id(self.resource_id, "resource_id")
        _validate_quantity(self.quantity, self.unit, "Stock quantity")
        _validate_status(self.quantity, self.status, "Stock")
        if not self.as_of:
            raise ValueError("stock as_of must identify the observation time")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self); d["status"] = self.status.value
        return d


@dataclass
class Flow:
    flow_id: str
    resource_id: str
    quantity: Optional[float]
    unit: str
    period: str
    from_id: Optional[str] = None
    to_id: Optional[str] = None
    geography: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    status: DataStatus = DataStatus.UNKNOWN
    start: Optional[str] = None
    end: Optional[str] = None

    def __post_init__(self) -> None:
        _require_nonempty_id(self.flow_id, "flow_id")
        _require_nonempty_id(self.resource_id, "resource_id")
        _validate_quantity(self.quantity, self.unit, "Flow quantity")
        _validate_status(self.quantity, self.status, "Flow")
        if not self.period:
            raise ValueError("flow period must be specified")
        # ISSUE-24: parse and compare as dates, never as strings.
        # Each bound is validated even when the other is absent; the
        # ordering check applies only when both are present. An empty
        # string still means "absent", as before.
        start_date = _parse_iso_date(self.start, "start") if self.start else None
        end_date = _parse_iso_date(self.end, "end") if self.end else None
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"flow start must not be after end: {self.start!r} > {self.end!r}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self); d["status"] = self.status.value
        return d
