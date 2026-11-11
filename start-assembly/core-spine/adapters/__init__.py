"""START core-spine adapters (local assembly, 2026-11-10).

Thin adapters only — no vendored engine code. Each adapter maps an
external engine to the v0.3.2 constraint-evaluation wire contract
(schema_version "1.0.0", see ../interop-schemas/ copies in this folder
via the review copy) and to the planning-package status rules:

* five internal states: PASS / FAIL / UNKNOWN / NOT_CHECKED / INCOMPLETE
* consumer tri-state: pass / fail / indeterminate
  (INCOMPLETE, UNKNOWN, NOT_CHECKED -> indeterminate; FAIL wins)
* empty checks -> NOT_CHECKED, never PASS
* UNKNOWN / INCOMPLETE are never converted into PASS

Sources: ~/workspace/v032-review/REVIEW.md (ISSUE-02, ISSUE-16),
~/workspace/v032-review/blocker-work/planning-package/models.py,
~/workspace/v032-review/blocker-work/shared-test-vectors/test-vectors.json
"""

from .statuses import (
    CheckStatus,
    ConstraintResult,
    InternalStatus,
    PlanningResult,
    project_to_verdict,
)

__all__ = [
    "CheckStatus",
    "ConstraintResult",
    "InternalStatus",
    "PlanningResult",
    "project_to_verdict",
]
