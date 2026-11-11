"""Explicit statuses used throughout START.

Statuses are deliberately conservative: an empty set of checks is never a pass.
"""
from __future__ import annotations
from enum import Enum
from collections.abc import Iterable


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"
    INCOMPLETE = "INCOMPLETE"


class CalculationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    NOT_RUN = "NOT_RUN"
    ERROR = "ERROR"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"


class DataStatus(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    ASSUMED = "assumed"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"
    VERIFIED = "verified"  # Explicitly verified against a documented method/source.


def overall_from_checks(statuses: Iterable[CheckStatus]) -> CheckStatus:
    """Derive a conservative aggregate status; FAIL dominates all other states.

    ISSUE-46 (2026-11-11): the annotation promises
    ``Iterable[CheckStatus]``, but a raw string used to slip through
    via str-Enum equality (``overall_from_checks(["PASS"])`` returned
    PASS). Anything that is not a ``CheckStatus`` instance is now
    normalised to UNKNOWN before aggregation — never PASS, never
    FAIL — so untyped input can only make the aggregate more
    conservative. All production callers already pass real
    ``CheckStatus`` values, so the typed path is unchanged.
    """
    values = [s if isinstance(s, CheckStatus) else CheckStatus.UNKNOWN for s in statuses]
    if not values:
        return CheckStatus.NOT_CHECKED
    if any(s == CheckStatus.FAIL for s in values):
        return CheckStatus.FAIL
    if any(s == CheckStatus.INCOMPLETE for s in values):
        return CheckStatus.INCOMPLETE
    if any(s == CheckStatus.UNKNOWN for s in values):
        return CheckStatus.UNKNOWN
    if any(s == CheckStatus.NOT_CHECKED for s in values):
        return CheckStatus.NOT_CHECKED
    if all(s == CheckStatus.PASS for s in values):
        return CheckStatus.PASS
    return CheckStatus.UNKNOWN
