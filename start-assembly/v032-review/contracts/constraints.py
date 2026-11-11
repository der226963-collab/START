"""Constraint and community objective representations.

CONTRACT VALIDATION RULES (ISSUE-48, 2026-11-11) — see
docs/ARCHITECTURE.md for the full statement. In short: ids/names are
non-empty everywhere (Constraint already enforced this since
ISSUE-12); Constraint/Objective unit is OPTIONAL ("" = deliberately
unit-less, e.g. the plan_limits phosphorus/work-hours constraints),
while Resource/Stock/Flow/ProcessInput/ProcessOutput require a known
registry unit even when quantity is None.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import math
from .statuses import CheckStatus
from .units import unit_definition


@dataclass
class Constraint:
    """A checkable bound on a resource value.

    Tolerance (ISSUE-30/35, 2026-11-11) — one coherent rule, chosen
    over requiring ``tolerance > 0`` for ``==``:

    * The default tolerance stays 0.0 everywhere. Requiring a
      positive tolerance for ``==`` would have been a breaking change
      (every existing ``==`` construction uses the default) and would
      have hidden the real fact: at tolerance 0.0, ``==`` is EXACT
      float equality, so ``Constraint(operator="==", bound=0.3)
      .evaluate(0.1 + 0.2)`` is FAIL (0.30000000000000004 != 0.3).
      Callers comparing computed floats must pass an explicit
      tolerance (e.g. 1e-9) and say so; the exactness is documented
      here rather than papered over by a forced tolerance.
    * A non-zero tolerance CAN flip a verdict (6.5 vs bound 6.2:
      FAIL at 0.0, PASS at 0.5). That is why the tolerance is always
      surfaced, never silent: ``to_dict()`` includes it, and the food
      evaluation row includes it plus ``verdict_without_tolerance``
      and ``tolerance_changed_verdict``, with a warning when a flip
      occurs (see domains/food/evaluation.py). A result that passes
      only because of its tolerance says so on its face.
    """
    constraint_id: str
    name: str
    resource_id: Optional[str] = None
    operator: str = "<="
    bound: Optional[float] = None
    bound_low: Optional[float] = None
    bound_high: Optional[float] = None
    # ISSUE-12 (2026-11-11): a bound-less constraint is an explicit,
    # deliberate UNKNOWN, never an accidental omission. Only the two
    # intentional cases in this tree use it — the nitrogen constraint
    # in contracts/plan_limits.py (ISSUE-18: no stored boundary exists)
    # and default_food_constraints(None) in domains/food/production.py
    # (no requirement stated) — both pass boundless=True explicitly.
    # Ordinary construction with a missing bound raises.
    boundless: bool = False
    unit: str = ""
    geography: str = "unspecified"
    period: str = "unspecified"
    source_ids: list[str] = field(default_factory=list)
    notes: str = ""
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        # ISSUE-12 (2026-11-11): construction is fail-fast. An empty
        # id/name, or a missing bound for the declared operator, used
        # to construct fine and only surface later as a silent UNKNOWN
        # from evaluate(). Those are programmer errors, raised here.
        # Recorded rules (ISSUE-48 aligned the rest of the contracts
        # to these on 2026-11-11; see docs/ARCHITECTURE.md):
        #  * constraint_id and name must be non-empty strings
        #    (whitespace-only counts as empty).
        #  * "range" needs bound_low AND bound_high; "<="/">="/"=="
        #    need bound — unless boundless=True is passed explicitly,
        #    in which case bound must be None and evaluate() returns
        #    UNKNOWN by design (see the boundless field note above).
        #  * "range" can never be boundless.
        #  * An empty unit ("") is still allowed at construction:
        #    plan_limits' phosphorus/work-hours constraints are
        #    unit-less by design (their display unit lives in the
        #    check row, not the registry). The unit rule is enforced
        #    at evaluation instead — see evaluate().
        if not isinstance(self.constraint_id, str) or not self.constraint_id.strip():
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("constraint name must be a non-empty string")
        if not isinstance(self.boundless, bool):
            raise ValueError("boundless must be a bool")
        if self.operator not in {"<=", ">=", "==", "range"}:
            raise ValueError(f"unsupported constraint operator: {self.operator}")
        if self.operator == "range":
            if self.boundless:
                raise ValueError("a range constraint cannot be boundless: bound_low and bound_high are required")
            if self.bound_low is None or self.bound_high is None:
                raise ValueError("range constraint requires bound_low and bound_high")
        else:
            if self.boundless and self.bound is not None:
                raise ValueError("boundless constraint must have bound=None")
            if not self.boundless and self.bound is None:
                raise ValueError(
                    f"constraint {self.constraint_id!r} operator {self.operator!r} requires a bound; "
                    "pass boundless=True explicitly if the constraint is deliberately bound-less "
                    "(it will always evaluate UNKNOWN, never PASS)")
        if self.unit and unit_definition(self.unit) is None:
            raise ValueError(f"unknown constraint unit: {self.unit}")
        for name, value in (("bound", self.bound), ("bound_low", self.bound_low), ("bound_high", self.bound_high), ("tolerance", self.tolerance)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite numeric")
        if self.tolerance < 0:
            raise ValueError("tolerance cannot be negative")
        if self.operator == "range" and self.bound_low is not None and self.bound_high is not None and self.bound_low > self.bound_high:
            raise ValueError("range lower bound exceeds upper bound")

    def evaluate(self, value: Optional[float], value_unit: Optional[str] = None) -> CheckStatus:
        # ISSUE-07 mapping (2026-11-11): the evaluator is total — an
        # unperformed check returns UNKNOWN, never PASS, never raises.
        # An empty / non-string constraint_id identifies no check, so
        # there is nothing to pass (Rust and Julia already return
        # UNKNOWN here; Python used to PASS — fixed here). A supplied
        # value_unit must be a known registry unit even when this
        # constraint declares no unit: an unknown unit string is never
        # silently ignored into a raw-number PASS (Rust rejects any
        # unknown unit string; Julia mirrors this). A known value_unit
        # on a unit-less constraint is still ignored (raw comparison),
        # as before — there is no target unit to convert into.
        if not isinstance(self.constraint_id, str) or not self.constraint_id.strip():
            return CheckStatus.UNKNOWN
        if value is None:
            return CheckStatus.UNKNOWN
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return CheckStatus.UNKNOWN
        if value_unit is not None and (not isinstance(value_unit, str) or unit_definition(value_unit) is None):
            return CheckStatus.UNKNOWN
        # ISSUE-12 (2026-11-11) unit rule, superseding the ISSUE-07 pin
        # that a known unit supplied to a unit-less constraint was
        # silently ignored into a raw-number PASS: a constraint with
        # no unit (unit == "") may only be evaluated with NO value_unit
        # supplied at all (raw comparison, as the plan_limits
        # phosphorus/work-hours constraints rely on). A known
        # value_unit supplied to a unit-less constraint RAISES
        # ValueError — there is no target unit to convert into, so
        # comparing raw numbers would silently ignore the caller's
        # unit. An unknown / non-string / empty value_unit still
        # returns UNKNOWN (checked above), never PASS.
        if not self.unit and value_unit is not None:
            raise ValueError(
                f"unit-less constraint {self.constraint_id!r} cannot be evaluated "
                f"against supplied unit {value_unit!r}: no target unit to convert into")
        if self.unit and value_unit:
            from .units import convert
            try:
                value = convert(value, value_unit, self.unit)
            except ValueError:
                return CheckStatus.UNKNOWN
        elif self.unit and not value_unit:
            return CheckStatus.UNKNOWN
        if self.operator == "range":
            if self.bound_low is None or self.bound_high is None:
                return CheckStatus.UNKNOWN
            return CheckStatus.PASS if self.bound_low - self.tolerance <= value <= self.bound_high + self.tolerance else CheckStatus.FAIL
        if self.bound is None:
            return CheckStatus.UNKNOWN
        if self.operator == "<=":
            return CheckStatus.PASS if value <= self.bound + self.tolerance else CheckStatus.FAIL
        if self.operator == ">=":
            return CheckStatus.PASS if value >= self.bound - self.tolerance else CheckStatus.FAIL
        return CheckStatus.PASS if math.isclose(value, self.bound, rel_tol=0.0, abs_tol=self.tolerance) else CheckStatus.FAIL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Objective:
    objective_id: str
    name: str
    description: str = ""
    resource_id: Optional[str] = None
    direction: str = "maximize"
    target: Optional[float] = None
    unit: str = ""
    weight: Optional[float] = None
    source_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # ISSUE-48 (2026-11-11): ids/names are non-empty everywhere.
        # Objective joins Constraint here: objective_id and name must
        # be non-empty strings (whitespace-only counts as empty).
        # Unit rule: Objective's unit is OPTIONAL ("" = deliberately
        # unit-less), like Constraint's — unlike Resource/Stock/Flow/
        # ProcessInput/ProcessOutput, where the unit is required even
        # when quantity is None. An objective is a target/direction,
        # not a physical amount; when a unit is given it must be a
        # known registry unit. See docs/ARCHITECTURE.md.
        if not isinstance(self.objective_id, str) or not self.objective_id.strip():
            raise ValueError("objective_id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("objective name must be a non-empty string")
        if self.direction not in {"maximize", "minimize", "target"}:
            raise ValueError("direction must be maximize, minimize, or target")
        if self.direction == "target" and self.target is None:
            raise ValueError("target objective requires a target value")
        for name, value in (("target", self.target), ("weight", self.weight)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite numeric")
        if self.weight is not None and self.weight < 0:
            raise ValueError("objective weight cannot be negative")
        if self.unit and unit_definition(self.unit) is None:
            raise ValueError(f"unknown objective unit: {self.unit}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
