"""Status model for the core spine.

Local copy of the rules in
~/workspace/v032-review/blocker-work/planning-package/models.py
(ISSUE-16 fix), adapted to the v0.3.2 wire vocabulary (UPPERCASE
status strings, per interop/schemas/constraint-evaluation-result.schema.json).

Rules, enforced here and in every adapter:
1. Five internal states, each with a different remedy:
   PASS, FAIL, UNKNOWN, NOT_CHECKED, INCOMPLETE.
2. Consumer tri-state: pass / fail / indeterminate.
   INCOMPLETE / UNKNOWN / NOT_CHECKED all project to indeterminate.
   FAIL wins over everything.
3. Empty check list -> NOT_CHECKED internally, indeterminate to
   consumers. It is NEVER a pass (ISSUE-02, intentional breaking
   change vs v0.3.1 check_plan_limits({}) -> True).
4. UNKNOWN / INCOMPLETE are never converted into PASS.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class InternalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"
    INCOMPLETE = "INCOMPLETE"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


_OVERALL_PRECEDENCE = (
    InternalStatus.FAIL,
    InternalStatus.INCOMPLETE,
    InternalStatus.UNKNOWN,
    InternalStatus.NOT_CHECKED,
)


def project_to_verdict(status: InternalStatus) -> CheckStatus:
    if status is InternalStatus.FAIL:
        return CheckStatus.FAIL
    if status is InternalStatus.PASS:
        return CheckStatus.PASS
    return CheckStatus.INDETERMINATE


@dataclass
class ConstraintResult:
    constraint_id: str
    status: InternalStatus
    explanation: str
    actual_value: Optional[float] = None
    required_value: Optional[float] = None
    unit: Optional[str] = None
    evidence: list = field(default_factory=list)
    source_ids: list = field(default_factory=list)

    @property
    def verdict(self) -> CheckStatus:
        return project_to_verdict(self.status)

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "constraint_id": self.constraint_id,
            "status": self.status.value,
            "verdict": self.verdict.value,
            "explanation": self.explanation,
            "actual_value": self.actual_value,
            "required_value": self.required_value,
            "unit": self.unit,
            "evidence": list(self.evidence),
            "source_ids": list(self.source_ids),
        }

    def to_wire_result(self, reason_code: str = "OK") -> dict:
        """Map to the v0.3.2 constraint-evaluation-result schema shape."""
        return {
            "schema_version": "1.0.0",
            "constraint_id": self.constraint_id,
            "status": self.status.value,
            "normalized_value": self.actual_value,
            "normalized_unit": self.unit,
            "reason_code": reason_code,
            "details": self.explanation,
        }


@dataclass
class PlanningResult:
    scenario_id: str
    checks: list

    @property
    def overall_status(self) -> InternalStatus:
        if not self.checks:
            return InternalStatus.NOT_CHECKED
        present = {c.status for c in self.checks}
        for status in _OVERALL_PRECEDENCE:
            if status in present:
                return status
        return InternalStatus.PASS

    @property
    def overall_verdict(self) -> CheckStatus:
        return project_to_verdict(self.overall_status)

    @property
    def passes(self) -> bool:
        return self.overall_status is InternalStatus.PASS

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if c.status is InternalStatus.FAIL)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "overall_status": self.overall_status.value,
            "overall_verdict": self.overall_verdict.value,
            "passes": self.passes,
            "failed_count": self.failed_count,
            "checks": [c.to_dict() for c in self.checks],
        }


def evaluate_le(value: float, bound: float, constraint_id: str, unit: str,
                tolerance: float = 0.0) -> ConstraintResult:
    """value <= bound, with the conservative status rules.

    Non-finite inputs -> UNKNOWN, never PASS. Missing bound (None) ->
    UNKNOWN. Empty constraint_id -> UNKNOWN (a check that was never
    really identified must not pass).
    """
    import math

    if not constraint_id:
        return ConstraintResult("", InternalStatus.UNKNOWN,
                                "empty constraint_id: check not identified")
    if bound is None or not math.isfinite(value) or not math.isfinite(bound):
        return ConstraintResult(constraint_id, InternalStatus.UNKNOWN,
                                "non-finite value or missing bound",
                                actual_value=value, required_value=bound,
                                unit=unit)
    status = InternalStatus.PASS if value <= bound + tolerance else InternalStatus.FAIL
    return ConstraintResult(constraint_id, status,
                            f"{value} <= {bound} {unit}: {status.value}",
                            actual_value=value, required_value=bound, unit=unit)


def evaluate_ge(value: float, bound: float, constraint_id: str, unit: str,
                tolerance: float = 0.0) -> ConstraintResult:
    import math

    if not constraint_id:
        return ConstraintResult("", InternalStatus.UNKNOWN,
                                "empty constraint_id: check not identified")
    if bound is None or not math.isfinite(value) or not math.isfinite(bound):
        return ConstraintResult(constraint_id, InternalStatus.UNKNOWN,
                                "non-finite value or missing bound",
                                actual_value=value, required_value=bound,
                                unit=unit)
    status = InternalStatus.PASS if value >= bound - tolerance else InternalStatus.FAIL
    return ConstraintResult(constraint_id, status,
                            f"{value} >= {bound} {unit}: {status.value}",
                            actual_value=value, required_value=bound, unit=unit)
