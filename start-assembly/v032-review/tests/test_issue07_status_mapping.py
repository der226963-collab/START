"""ISSUE-07: one invalid/empty-input mapping, same status in every language.

Decided 2026-11-11, review copy only, local, never pushed. The full
mapping and its rationale live in docs/STATUS_MAPPING_ISSUE-07.md; this
file pins it in Python. The SAME matrix is pinned in Rust
(components/rust-kernels/src/lib.rs, tests module) and Julia
(components/julia-planning/test/runtests.jl), asserting the SAME status
for the SAME input at each layer — except where the mapping itself says
the layers differ, which is pinned per language instead (see below).

The mapping, in one paragraph: the evaluator is total — a check that
cannot be performed returns UNKNOWN, never PASS, never raises. The
wire/adapter boundary rejects a malformed request with a reason: in
Python that rejection is a raised ValueError (validate_constraint_request
/ evaluate_constraint_request validate first); in Rust and Julia the
wire entry returns an UNKNOWN result with reason_code INVALID_REQUEST
(or UNSUPPORTED_MAJOR_VERSION for a major mismatch). The mechanism
differs — Python's adapter is a validating function whose contract is
to raise, pinned by existing tests — but the rule is the same:
malformed is rejected with a reason, never evaluated, never PASS/FAIL.
Construction is fail-fast in Python and Julia (bad operator,
non-finite bound, negative tolerance, inverted range bounds raise;
Python additionally raises for an unknown constraint unit, Julia and
Rust defer unknown units to evaluation, where they return UNKNOWN).
An empty check list aggregates to NOT_CHECKED in all three languages.

Run: python -m unittest discover -s tests -v   (from start_v03_work/)
"""
from __future__ import annotations
import math
import unittest

from adapters.python.contracts import (
    evaluate_constraint_request,
    validate_constraint_request,
)
from contracts.constraints import Constraint
from contracts.statuses import CheckStatus, overall_from_checks

FIVE = {CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.UNKNOWN,
        CheckStatus.NOT_CHECKED, CheckStatus.INCOMPLETE}


def _le(bound=10.0, unit="L"):
    return Constraint("c", "cap", operator="<=", bound=bound, unit=unit)


def _wire(**overrides):
    payload = {
        "schema_version": "1.0.0", "constraint_id": "w", "operator": "<=",
        "value": 8.0, "value_unit": "L", "bound": 10.0, "bound_unit": "L",
        "tolerance": 0.0,
    }
    payload.update(overrides)
    return payload


class EvaluatorInvalidInputTest(unittest.TestCase):
    """Evaluator level: Constraint.evaluate returns UNKNOWN, never PASS,
    never raises — same status as Rust evaluate_constraint and Julia
    evaluate_constraint for the same input."""

    def test_non_finite_and_missing_values_are_unknown(self):
        cases = [
            ("NaN", math.nan), ("+inf", math.inf), ("-inf", -math.inf),
            ("None", None), ("bool True", True), ("string '5'", "5"),
        ]
        for label, value in cases:
            with self.subTest(case=label):
                got = _le().evaluate(value, "L")
                self.assertEqual(got, CheckStatus.UNKNOWN, label)
                self.assertIn(got, FIVE)

    def test_unknown_or_incompatible_units_are_unknown(self):
        # An unknown bound_unit cannot reach evaluate natively in
        # Python: the constructor raises first (see
        # test_unknown_constraint_unit_raises). Rust and Julia
        # return UNKNOWN for it; the guarantee is the same — it can
        # never produce PASS or FAIL.
        cases = [
            ("unknown value_unit", _le(), 5.0, "bucket"),
            ("incompatible L vs kg",
             Constraint("i", "x", operator="<=", bound=10.0, unit="kg"),
             5.0, "L"),
        ]
        for label, constraint, value, unit in cases:
            with self.subTest(case=label):
                self.assertEqual(constraint.evaluate(value, unit),
                                 CheckStatus.UNKNOWN, label)

    def test_missing_value_unit_with_a_unit_is_unknown(self):
        self.assertEqual(_le().evaluate(5.0), CheckStatus.UNKNOWN)

    def test_missing_bounds_raise_at_construction(self):
        # ISSUE-12 (2026-11-11), superseding the ISSUE-07 pin that a
        # missing bound constructed fine and evaluated UNKNOWN: a
        # missing bound for the declared operator is now a
        # construction error. The deliberate exception is an
        # explicitly boundless constraint, which still evaluates
        # UNKNOWN by design (nitrogen / unstated food requirement).
        for kwargs in ({"operator": "<=", "unit": "L"},
                       {"operator": "range", "unit": "L"},
                       {"operator": "range", "bound_low": 2.0, "unit": "L"}):
            with self.subTest(case=kwargs):
                with self.assertRaises(ValueError):
                    Constraint("nb", "x", **kwargs)
        boundless = Constraint("nb", "x", operator="<=", unit="L",
                               boundless=True)
        self.assertEqual(boundless.evaluate(5.0, "L"), CheckStatus.UNKNOWN)
        with self.assertRaises(ValueError):
            Constraint("nb", "x", operator="range", unit="L", boundless=True)

    def test_empty_or_non_string_constraint_id_raises_at_construction(self):
        # ISSUE-12 (2026-11-11), superseding the ISSUE-07 pin that an
        # empty id constructed fine and evaluated UNKNOWN: empty /
        # whitespace / non-string ids (and empty names) now raise at
        # construction. evaluate()'s UNKNOWN guard for an empty id
        # remains only as defence for objects built without the
        # constructor; Rust/Julia still return UNKNOWN at evaluation.
        for constraint_id in ("", "   ", None):
            with self.subTest(constraint_id=repr(constraint_id)):
                with self.assertRaises(ValueError):
                    Constraint(constraint_id, "x", operator="<=",
                               bound=10.0, unit="kg")
        with self.assertRaises(ValueError):
            Constraint("c", "", operator="<=", bound=10.0, unit="kg")
        with self.assertRaises(ValueError):
            Constraint("c", "   ", operator="<=", bound=10.0, unit="kg")

    def test_unitless_constraint_with_unknown_value_unit_is_unknown(self):
        # Fixed 2026-11-11 (ISSUE-07): a supplied unit string must be a
        # known registry unit even when the constraint declares no unit.
        # Rust rejects any unknown unit string; Python used to ignore
        # the supplied unit and PASS on the raw numbers.
        unitless = Constraint("ul", "x", operator="<=", bound=10.0, unit="")
        self.assertEqual(unitless.evaluate(5.0, "bucket"), CheckStatus.UNKNOWN)
        self.assertEqual(unitless.evaluate(5.0, ""), CheckStatus.UNKNOWN)
        self.assertEqual(unitless.evaluate(5.0, 5), CheckStatus.UNKNOWN)

    def test_unitless_constraint_with_supplied_known_unit_raises(self):
        # ISSUE-12 (2026-11-11), superseding the ISSUE-07 pin that a
        # known unit supplied to a unit-less constraint was silently
        # ignored into a raw-number PASS: there is no target unit to
        # convert into, so evaluate() now RAISES instead of comparing
        # raw numbers while ignoring the caller's unit. No unit
        # supplied at all still compares raw, as before.
        unitless = Constraint("ul", "x", operator="<=", bound=10.0, unit="")
        self.assertEqual(unitless.evaluate(5.0), CheckStatus.PASS)
        self.assertEqual(unitless.evaluate(12.0), CheckStatus.FAIL)
        with self.assertRaises(ValueError):
            unitless.evaluate(5.0, "L")

    def test_valid_checks_still_pass_and_fail(self):
        self.assertEqual(_le().evaluate(8.0, "L"), CheckStatus.PASS)
        self.assertEqual(_le().evaluate(12.0, "L"), CheckStatus.FAIL)


class ConstructionFailFastTest(unittest.TestCase):
    """Construction level: programmer errors raise here, before any
    evaluation — Python ValueError, Julia ArgumentError, while Rust has
    no fallible constructor (plain struct) and reports the same inputs
    as UNKNOWN at evaluation. Same guarantee, different layer."""

    def test_bad_operator_raises(self):
        with self.assertRaises(ValueError):
            Constraint("x", "x", operator="!=", bound=1.0, unit="L")

    def test_non_finite_bound_raises(self):
        with self.assertRaises(ValueError):
            Constraint("x", "x", operator="<=", bound=math.nan, unit="L")

    def test_negative_tolerance_raises(self):
        with self.assertRaises(ValueError):
            Constraint("x", "x", operator="<=", bound=1.0, unit="L",
                       tolerance=-1.0)

    def test_inverted_range_raises(self):
        with self.assertRaises(ValueError):
            Constraint("x", "x", operator="range", bound_low=8.0,
                       bound_high=2.0, unit="L")

    def test_unknown_constraint_unit_raises(self):
        # Python-only fail-fast: Julia and Rust defer an unknown
        # constraint/bound unit to evaluation, where it is UNKNOWN.
        # Either way it can never produce PASS or FAIL.
        with self.assertRaises(ValueError):
            Constraint("x", "x", operator="<=", bound=1.0, unit="bucket")


class WireBoundaryRejectionTest(unittest.TestCase):
    """Wire/adapter level: a malformed request is rejected with a
    reason — in Python, a raised ValueError. Rust and Julia return an
    UNKNOWN result with reason_code INVALID_REQUEST (or
    UNSUPPORTED_MAJOR_VERSION for a major mismatch, or
    UNSUPPORTED_OPERATOR for a bad operator — ISSUE-52) for the same
    inputs; see docs/STATUS_MAPPING_ISSUE-07.md for why the mechanism
    differs."""

    def test_malformed_requests_raise(self):
        malformed = [
            ("missing fields", {"constraint_id": "w"}),
            ("non-finite value", _wire(value=math.nan)),
            ("non-finite bound", _wire(bound=math.inf)),
            ("non-finite tolerance", _wire(tolerance=math.nan)),
            ("negative tolerance", _wire(tolerance=-1.0)),
            ("bad operator", _wire(operator="!=")),
            ("empty constraint_id", _wire(constraint_id="")),
            ("whitespace constraint_id", _wire(constraint_id="   ")),
            ("non-string constraint_id", _wire(constraint_id=123)),
            ("missing bound",
             {k: v for k, v in _wire().items() if k != "bound"}),
        ]
        range_base = {"schema_version": "1.0.0", "constraint_id": "rng",
                      "operator": "range", "value": 5.0, "value_unit": "L",
                      "bound_unit": "L", "bound_low": 2.0, "bound_high": 8.0,
                      "tolerance": 0.0}
        malformed += [
            ("range missing bound_low",
             {k: v for k, v in range_base.items() if k != "bound_low"}),
            ("range missing bound_high",
             {k: v for k, v in range_base.items() if k != "bound_high"}),
            ("range inverted bounds",
             {**range_base, "bound_low": 8.0, "bound_high": 2.0}),
        ]
        for label, payload in malformed:
            with self.subTest(case=label):
                with self.assertRaises(ValueError, msg=label):
                    validate_constraint_request(payload)
                with self.assertRaises(ValueError, msg=label):
                    evaluate_constraint_request(payload)

    def test_unknown_bound_unit_raises_at_validation(self):
        # Unknown bound_unit: validate_constraint_request raises
        # ValueError — ISSUE-09 (2026-11-11) added unit-registry
        # membership to the boundary validator, superseding the
        # ISSUE-07 note that validation did not check it. (It also
        # raised before, at Constraint construction; validation now
        # rejects it first.) Rust and Julia return UNKNOWN /
        # UNKNOWN_UNIT for the same input; the guarantee is the same
        # — never PASS or FAIL.
        with self.assertRaises(ValueError):
            validate_constraint_request(_wire(bound_unit="bucket"))
        with self.assertRaises(ValueError):
            evaluate_constraint_request(_wire(bound_unit="bucket"))

    def test_major_version_rejected_with_distinct_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_constraint_request(_wire(schema_version="2.0.0"))
        self.assertEqual(
            str(ctx.exception),
            "unsupported major schema version: 2.0.0 "
            "(supported major version 1)")

    def test_malformed_version_rejected(self):
        with self.assertRaises(ValueError):
            validate_constraint_request(_wire(schema_version="1.0"))

    def test_unknown_value_unit_is_rejected_at_the_boundary(self):
        # ISSUE-09 fix (2026-11-11), superseding the ISSUE-07 pin
        # that validation passed an unknown unit and the evaluator
        # returned UNKNOWN: unit-registry membership is now checked
        # by the Python boundary validator, so the wire request
        # raises ValueError. The evaluator-level guarantee is
        # unchanged — Constraint.evaluate still returns UNKNOWN for
        # an unknown unit when called directly (pinned in
        # test_unknown_or_incompatible_units_are_unknown above), the
        # same status Rust and Julia return for this input.
        with self.assertRaises(ValueError):
            validate_constraint_request(_wire(value_unit="bucket"))
        with self.assertRaises(ValueError):
            evaluate_constraint_request(_wire(value_unit="bucket"))

    def test_valid_wire_requests_evaluate(self):
        self.assertEqual(evaluate_constraint_request(_wire()),
                         CheckStatus.PASS)
        self.assertEqual(evaluate_constraint_request(_wire(value=12.0)),
                         CheckStatus.FAIL)
        self.assertEqual(
            evaluate_constraint_request(_wire(value=5.0, bound_unit="kg")),
            CheckStatus.UNKNOWN)


class AggregationEmptyInputTest(unittest.TestCase):
    """Aggregation level: empty is NOT_CHECKED, never PASS; precedence
    FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED > PASS — identical in
    Python, Rust and Julia."""

    def test_empty_checks_are_not_checked(self):
        self.assertEqual(overall_from_checks([]), CheckStatus.NOT_CHECKED)

    def test_aggregation_precedence(self):
        cases = [
            ([CheckStatus.UNKNOWN], CheckStatus.UNKNOWN),
            ([CheckStatus.PASS], CheckStatus.PASS),
            ([CheckStatus.PASS, CheckStatus.PASS], CheckStatus.PASS),
            ([CheckStatus.PASS, CheckStatus.FAIL], CheckStatus.FAIL),
            ([CheckStatus.PASS, CheckStatus.UNKNOWN], CheckStatus.UNKNOWN),
            ([CheckStatus.UNKNOWN, CheckStatus.INCOMPLETE],
             CheckStatus.INCOMPLETE),
            ([CheckStatus.UNKNOWN, CheckStatus.NOT_CHECKED],
             CheckStatus.UNKNOWN),
            ([CheckStatus.NOT_CHECKED, CheckStatus.PASS],
             CheckStatus.NOT_CHECKED),
            ([CheckStatus.FAIL, CheckStatus.INCOMPLETE], CheckStatus.FAIL),
        ]
        for checks, expected in cases:
            with self.subTest(checks=[s.value for s in checks]):
                self.assertEqual(overall_from_checks(checks), expected)


if __name__ == "__main__":
    unittest.main()
