"""Typed result models for the planning calculation layer.

A plan check produces a :class:`PlanningResult`: one
:class:`ConstraintResult` per limit that was checked, plus an
overall status. The overall status is tri-state:

- ``PASS`` — every check passed.
- ``FAIL`` — at least one check failed. Fail wins over everything.
- ``INDETERMINATE`` — no check failed, but at least one check could
  not be decided, or no check ran at all.

The last point is deliberate and is the one place this file differs
from the design as first proposed: an empty check list returns
``INDETERMINATE``, never ``PASS``. A plan that was never checked
must not read as a plan that passed. This is the same rule the
project's v0.3.2 review called out as the safer one, and it fixes
the old behaviour where ``check_plan_limits({})`` reported a pass.

These models check a plan; they do not approve or decide it. A
``PASS`` still means only that the plan did not breach the stored
limits checked here.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


@dataclass
class ConstraintResult:
    constraint_id: str
    status: CheckStatus
    explanation: str

    actual_value: Optional[float] = None
    required_value: Optional[float] = None
    unit: Optional[str] = None

    evidence: list[str] = field(default_factory=list)

    def to_dict(self):
        """JSON-friendly dict; status as its string value."""
        return {
            "constraint_id": self.constraint_id,
            "status": self.status.value,
            "explanation": self.explanation,
            "actual_value": self.actual_value,
            "required_value": self.required_value,
            "unit": self.unit,
            "evidence": list(self.evidence),
        }


@dataclass
class PlanningResult:
    scenario_id: str
    checks: list[ConstraintResult]

    # Carried from the old dict result: passing these checks does not
    # mean a plan is good, fair, or decided. Kept on the result so
    # the warning survives serialisation instead of living only in
    # the checking function's docstring.
    note: str = ""

    @property
    def overall_status(self) -> CheckStatus:
        if not self.checks:
            # No check ran, so nothing was established. Never PASS.
            return CheckStatus.INDETERMINATE

        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return CheckStatus.FAIL

        if any(
            c.status == CheckStatus.INDETERMINATE
            for c in self.checks
        ):
            return CheckStatus.INDETERMINATE

        return CheckStatus.PASS

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)

    def to_dict(self):
        """JSON-friendly dict; statuses as their string values."""
        return {
            "scenario_id": self.scenario_id,
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": self.overall_status.value,
            "failed_count": self.failed_count,
            "note": self.note,
        }
