"""Scenario representations for comparison, never automatic selection.

CONTRACT VALIDATION RULES (ISSUE-48, 2026-11-11) — one rule per concept,
enforced in ``__post_init__``; see also docs/ARCHITECTURE.md:

* Ids are non-empty everywhere: ``Scenario.scenario_id`` and
  ``Scenario.name``, and ``ScenarioResult.scenario_id``, must be
  non-empty strings (whitespace-only counts as empty). Scenario was
  the only contract already enforcing this; the check is now the
  same strict form (type + strip) used by ``Constraint``.
* ``Scenario`` has no quantity and no unit, so the ISSUE-48 unit rule
  and the ISSUE-31 quantity/status rules do not apply to it.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
import math

from .statuses import CalculationStatus


@dataclass
class Scenario:
    scenario_id: str
    name: str
    description: str = ""
    assumptions: list[str] = field(default_factory=list)
    proposed_changes: dict[str, float] = field(default_factory=dict)
    geography: str = "unspecified"
    period: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ISSUE-48 (2026-11-11): same strict form as Constraint —
        # non-string or whitespace-only ids/names raise, not just
        # falsy ones (the old `if not self.scenario_id` let "   "
        # through).
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ValueError("scenario_id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("scenario name must be a non-empty string")
        for key, value in self.proposed_changes.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"scenario change {key!r} must be finite numeric")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


# ISSUE-14: the headline safety invariant ``needs_human_decision=True``
# is enforced at the type level, not just by engine convention.
#
# Decision (recorded 2026-11-11): FREEZE, not an override reason.
# A grep of every construction site before this change showed no real
# caller needs False: domains/base.py (3 sites), engine/planning_engine.py
# (2 sites) all pass True or rely on the default, and no test constructs
# a False result. An override-reason field would have created a second,
# unaudited path to a result claiming no human decision is needed, which
# is exactly the hole being closed — so there is no override mechanism
# at all. Enforcement is twofold:
#   * ``__post_init__`` raises ValueError unless needs_human_decision
#     is exactly True (so ``False`` — or a truthy ``1`` — cannot be
#     constructed), and unless calculation_status is a CalculationStatus
#     member or one of its values (so "BOGUS" cannot be constructed).
#   * the dataclass is frozen, so the flag cannot be flipped by
#     attribute assignment after construction either.
# ``calculation_status`` is stored as the plain enum value string so
# the wire format stays JSON (``to_dict()`` returns plain dicts).
@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    domain: str
    metrics: dict[str, Any] = field(default_factory=dict)
    constraint_results: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    calculation_status: str = "NOT_RUN"
    verification: dict[str, Any] = field(default_factory=dict)
    needs_human_decision: bool = True

    def __post_init__(self) -> None:
        # ISSUE-48 (2026-11-11): a result must identify its scenario.
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ValueError("scenario_id must be a non-empty string")
        status = self.calculation_status
        if isinstance(status, CalculationStatus):
            # Frozen dataclass: coerce via object.__setattr__.
            object.__setattr__(self, "calculation_status", status.value)
        elif not isinstance(status, str) or status not in {s.value for s in CalculationStatus}:
            raise ValueError(
                f"calculation_status must be a CalculationStatus value "
                f"({sorted(s.value for s in CalculationStatus)}), got {status!r}"
            )
        if self.needs_human_decision is not True:
            raise ValueError(
                "needs_human_decision is frozen at True: every planning "
                "result requires a human decision; there is no override"
            )

    def to_dict(self) -> dict[str, Any]: return asdict(self)
