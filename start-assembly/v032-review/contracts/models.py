"""Typed planning result models (REVIEW.md ISSUE-16) — review-copy adaptation.

Implements the ISSUE-16 verdict in the v0.3.2 review copy's ``contracts/``:

* Keep five states internally. The review copy already has them as
  :class:`contracts.statuses.CheckStatus` (PASS / FAIL / UNKNOWN /
  NOT_CHECKED / INCOMPLETE) with the conservative aggregation in
  :func:`contracts.statuses.overall_from_checks` (FAIL > INCOMPLETE >
  UNKNOWN > NOT_CHECKED > PASS; empty checks are NOT_CHECKED, never
  PASS). That type is reused here as-is — it is the draft's
  ``InternalStatus`` under its existing name, so no second five-state
  enum with different semantics is created. ``InternalStatus`` is kept
  only as an alias for draft compatibility.
* One consumer-facing tri-state verdict (:class:`Verdict`):
  pass / fail / indeterminate. INCOMPLETE, UNKNOWN and NOT_CHECKED all
  project to ``indeterminate``; FAIL wins, else PASS. The draft called
  this ``CheckStatus``; that name is already taken in this tree by the
  five-state enum, so the tri-state is named ``Verdict`` here to avoid
  a collision.
* ``evidence`` (and ``source_ids``) is carried on every
  :class:`ConstraintResult` row — the review copy's dict rows had no
  evidence field and did not copy the constraint's ``source_ids`` into
  the evaluation row (ISSUE-16, point 3). The typed wrapper copies
  both from the ``plan_limits`` dict rows.
* Empty-set rule explicit, per ISSUE-02: an empty check list is
  NOT_CHECKED internally and ``indeterminate`` to consumers. It is
  never a pass.

``check_plan_limits_typed`` wraps the review copy's plan-check entry
point, :func:`contracts.plan_limits.check_plan_limits` (the ISSUE-01
versioned snapshot / constraint-set engine). There is no legacy
``mini_ai`` ``check_plan_limits`` in this tree, so that is the only
candidate — and it fits: it returns plain dict rows with ``status``
(uppercase), ``limit`` / ``constraint_id``, ``proposed``, ``boundary``,
``unit``, ``note``, ``excess`` and ``source_ids``, all of which the
converter below consumes. The dict function is left untouched, so the
typed path is opt-in: callers that do not use it see exactly the
existing behaviour.

No ``verified`` flag exists anywhere here: a passing typed result
means only that the plan did not breach the stored limits checked
here; human approval is still required for any decision. Wire format
stays JSON: :meth:`PlanningResult.to_dict` returns plain dicts.

ISSUE-14 check (2026-11-11): ``PlanningResult`` carries neither a
``needs_human_decision`` flag nor a ``calculation_status`` — its
``overall_status`` / ``passes`` are derived properties over the
checks, never a claim that no human decision is needed — so there is
no second unguarded result path here to enforce the freeze on. The
freeze lives on :class:`contracts.scenarios.ScenarioResult` only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .statuses import CheckStatus, overall_from_checks


# The draft's InternalStatus is exactly the review copy's existing
# five-state CheckStatus. Reuse it; the alias exists only so code
# written against the draft's names keeps working.
InternalStatus = CheckStatus


class Verdict(str, Enum):
    """Consumer-facing verdict: pass / fail / indeterminate."""

    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


# Review-copy dict rows use uppercase statuses ("PASS"); the draft's
# legacy v0.3.1 rows used lowercase ("pass"). Accept both.
_STATUS_BY_NAME = {s.value: s for s in CheckStatus}
_STATUS_BY_NAME.update({s.value.lower(): s for s in CheckStatus})


def project_to_verdict(status: CheckStatus) -> Verdict:
    """Project one internal status onto the consumer tri-state."""
    if status is CheckStatus.FAIL:
        return Verdict.FAIL
    if status is CheckStatus.PASS:
        return Verdict.PASS
    return Verdict.INDETERMINATE


@dataclass
class ConstraintResult:
    constraint_id: str
    status: CheckStatus
    explanation: str

    actual_value: Optional[float] = None
    required_value: Optional[float] = None
    unit: Optional[str] = None

    evidence: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        return project_to_verdict(self.status)

    @classmethod
    def from_legacy_dict(cls, row: dict) -> "ConstraintResult":
        """Convert one ``check_plan_limits`` dict row to a typed result.

        Accepts both the review-copy rows (uppercase status, ``limit`` /
        ``constraint_id``, ``proposed``, ``boundary``, ``note``,
        ``excess``, ``source_ids``) and the draft's lowercase legacy
        rows. The ``note`` is preserved as evidence so the reason an
        unknown stays unknown is not lost in the conversion, and the
        row's ``source_ids`` are carried over.
        """
        status = _STATUS_BY_NAME[str(row["status"])]
        evidence: list[str] = []
        if row.get("note"):
            evidence.append(str(row["note"]))
        if row.get("excess"):
            evidence.append(f"excess over boundary: {row['excess']}")
        return cls(
            constraint_id=str(row.get("constraint_id", row.get("limit", ""))),
            status=status,
            explanation=row.get("note", "")
            or f"{row.get('limit', row.get('constraint_id', ''))}: {status.value}",
            actual_value=row.get("proposed", row.get("actual_value")),
            required_value=row.get("boundary", row.get("required_value")),
            unit=row.get("unit"),
            evidence=evidence,
            source_ids=list(row.get("source_ids", []) or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
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


@dataclass
class PlanningResult:
    scenario_id: str
    checks: list[ConstraintResult]

    @property
    def overall_status(self) -> CheckStatus:
        """Internal aggregate. Empty checks are NOT_CHECKED, never PASS."""
        return overall_from_checks([c.status for c in self.checks])

    @property
    def overall_verdict(self) -> Verdict:
        """Consumer aggregate: fail wins, then indeterminate, else pass."""
        return project_to_verdict(self.overall_status)

    @property
    def passes(self) -> bool:
        """True only when every check passed (and at least one ran)."""
        return self.overall_status is CheckStatus.PASS

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if c.status is CheckStatus.FAIL)

    @classmethod
    def from_legacy(cls, scenario_id: str, legacy: dict) -> "PlanningResult":
        """Convert a ``check_plan_limits`` dict return to a typed result."""
        return cls(
            scenario_id=scenario_id,
            checks=[ConstraintResult.from_legacy_dict(r) for r in legacy.get("checks", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "overall_status": self.overall_status.value,
            "overall_verdict": self.overall_verdict.value,
            "passes": self.passes,
            "failed_count": self.failed_count,
            "checks": [c.to_dict() for c in self.checks],
        }


def check_plan_limits_typed(
    plan: dict[str, Any],
    limits=None,
    overrides: dict[str, Any] | None = None,
    scenario_id: str = "plan",
) -> PlanningResult:
    """Typed wrapper around the review-copy ``check_plan_limits``.

    Wraps :func:`contracts.plan_limits.check_plan_limits` (ISSUE-01
    versioned snapshot / constraint set) and converts its dict rows,
    applying the ISSUE-16/02 rules: empty -> NOT_CHECKED /
    indeterminate, unknown-only -> UNKNOWN / indeterminate, never a
    pass. The dict function is unchanged, so its return keeps its old
    semantics; this wrapper is the opt-in typed path. ``limits`` and
    ``overrides`` are passed straight through, so the stored-bound
    override validation (a contradicting override raises ValueError)
    still applies.
    """
    from .plan_limits import check_plan_limits

    return PlanningResult.from_legacy(
        scenario_id, check_plan_limits(plan, limits=limits, overrides=overrides)
    )
