"""ISSUE-09 / ISSUE-10 / ISSUE-11 / ISSUE-54 — boundary validators and
versioning. Review copy only, local, never pushed.

ISSUE-09: the Python boundary validators enforced only a subset of the
JSON Schemas. Every violation reproduced in REVIEW.md is fed here, plus
the further violations found while fixing (wrong types, bad enums,
negative tolerance, non-finite numbers, missing range bounds, unknown
result fields). The validators now validate against the actual schema
files; a test below pins that the validator loads those files rather
than a private copy of their rules.

ISSUE-10/54: one canonical version per schema, from the single source
of truth ``interop/SCHEMA_VERSION``; the Julia planning message half
of ISSUE-10 is moot (see ``TestIssue10JuliaPlanningMessageMoot``).

ISSUE-11: the package version, the changelog heading and the README
heading must agree, and the changelog's "no changes" line must say
which prior artefact it means.

Run: python -m pytest tests/test_issue09_10_11_54.py -q (from
start_v03_work/)
"""
from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

import adapters.python.contracts as contracts
from adapters.python.contracts import (
    evaluate_constraint_request,
    validate_constraint_request,
    validate_constraint_result,
)
from contracts.statuses import CheckStatus

ROOT = Path(__file__).resolve().parent.parent


def _request(**overrides):
    payload = {
        "schema_version": "1.0.0", "constraint_id": "water_limit",
        "operator": "<=", "value": 8.0, "value_unit": "L",
        "bound": 10.0, "bound_unit": "L", "tolerance": 0.0,
    }
    payload.update(overrides)
    return payload


def _range_request(**overrides):
    payload = {
        "schema_version": "1.0.0", "constraint_id": "rng",
        "operator": "range", "value": 5.0, "value_unit": "L",
        "bound_unit": "L", "bound_low": 2.0, "bound_high": 8.0,
        "tolerance": 0.0,
    }
    payload.update(overrides)
    return payload


def _result(**overrides):
    payload = {
        "schema_version": "1.0.0", "constraint_id": "water_limit",
        "status": "PASS", "normalized_value": 8.0,
        "normalized_unit": "L", "reason_code": "OK",
    }
    payload.update(overrides)
    return payload


class Issue09RequestSchemaViolationsTest(unittest.TestCase):
    """Each schema violation from ISSUE-09, plus the ones found while
    fixing. All must raise; the valid baseline must not."""

    def test_issue_reproduction_extra_context_and_bucket_rejected(self):
        # The exact reproduction from REVIEW.md ISSUE-09: extra key
        # (additionalProperties: false), non-object context, and
        # units outside the registry — previously accepted wholesale.
        with self.assertRaises(ValueError):
            validate_constraint_request(_request(
                value_unit="bucket", bound_unit="bucket",
                extra="x", context="not-an-object"))

    def test_unknown_extra_property_rejected(self):
        with self.assertRaises(ValueError):
            validate_constraint_request(_request(extra="x"))

    def test_context_must_be_an_object(self):
        for bad in ("not-an-object", 42, ["a"], None, True):
            with self.subTest(context=repr(bad)):
                with self.assertRaises(ValueError):
                    validate_constraint_request(_request(context=bad))
        validate_constraint_request(_request(context={"source": "gauge-1"}))
        validate_constraint_request(_request(context={}))

    def test_unknown_units_rejected_at_the_boundary(self):
        # Unit-registry membership: the schema cannot express it (it
        # only requires a non-empty string), so the validator enforces
        # it. The native evaluator still returns UNKNOWN for an
        # unknown unit when called directly — that layer is unchanged.
        for overrides in ({"value_unit": "bucket"},
                          {"bound_unit": "bucket"},
                          {"value_unit": "bucket", "bound_unit": "bucket"}):
            with self.subTest(case=overrides):
                with self.assertRaises(ValueError):
                    validate_constraint_request(_request(**overrides))
        from contracts.constraints import Constraint
        self.assertEqual(
            Constraint("c", "c", operator="<=", bound=10.0, unit="L")
            .evaluate(5.0, "bucket"), CheckStatus.UNKNOWN)

    def test_every_required_field_is_required(self):
        required = ("schema_version", "constraint_id", "operator", "value",
                    "value_unit", "bound_unit", "tolerance")
        for missing in required:
            payload = {k: v for k, v in _request().items() if k != missing}
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError):
                    validate_constraint_request(payload)
        # Non-range requests additionally require "bound"; range
        # requests require bound_low/bound_high instead (schema
        # if/then/else).
        with self.assertRaises(ValueError):
            validate_constraint_request(
                {k: v for k, v in _request().items() if k != "bound"})
        for missing in ("bound_low", "bound_high"):
            payload = {k: v for k, v in _range_request().items()
                       if k != missing}
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError):
                    validate_constraint_request(payload)

    def test_operator_must_be_in_the_schema_enum(self):
        for bad in ("!=", "<", "gt", "", None, 5):
            with self.subTest(operator=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_request(_request(operator=bad))

    def test_numbers_must_be_finite_and_not_bool(self):
        for key, bad in (("value", math.nan), ("value", math.inf),
                         ("value", -math.inf), ("value", True),
                         ("value", "8"), ("bound", math.nan),
                         ("tolerance", math.inf), ("tolerance", "0")):
            with self.subTest(case=(key, repr(bad))):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_request(_request(**{key: bad}))

    def test_tolerance_minimum_zero(self):
        with self.assertRaises(ValueError):
            validate_constraint_request(_request(tolerance=-0.5))

    def test_constraint_id_must_be_a_non_empty_string(self):
        for bad in ("", "   ", None, 7):
            with self.subTest(constraint_id=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_request(_request(constraint_id=bad))

    def test_units_must_be_non_empty_strings(self):
        for key in ("value_unit", "bound_unit"):
            for bad in ("", "   ", None, 5):
                with self.subTest(case=(key, repr(bad))):
                    with self.assertRaises((ValueError, TypeError)):
                        validate_constraint_request(_request(**{key: bad}))

    def test_range_bounds_must_not_be_inverted(self):
        # The schema's if/then cannot express low <= high; the
        # validator enforces it (ISSUE-08 boundary, recorded in the
        # module docstring and CONTRACT_VERSIONING.md).
        with self.assertRaises(ValueError):
            validate_constraint_request(
                _range_request(bound_low=8.0, bound_high=2.0))

    def test_non_object_payload_rejected(self):
        for bad in (None, "x", [1], 5):
            with self.subTest(payload=repr(bad)):
                with self.assertRaises(TypeError):
                    validate_constraint_request(bad)

    def test_valid_requests_still_accepted(self):
        validate_constraint_request(_request())
        validate_constraint_request(_range_request())
        # A range request carrying "bound" as well is allowed: the
        # schema lists "bound" as a property and only requires the
        # range bounds, it does not forbid "bound". Pinned so a
        # future tightening does not silently change the wire shape.
        validate_constraint_request(_range_request(bound=5.0))
        self.assertEqual(
            evaluate_constraint_request(_request()), CheckStatus.PASS)
        self.assertEqual(
            evaluate_constraint_request(_range_request()), CheckStatus.PASS)


class Issue09ResultSchemaViolationsTest(unittest.TestCase):
    """ISSUE-09 result side: every required field, the reason_code
    enum, additionalProperties, types — and same-major versions."""

    def test_issue_reproduction_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            validate_constraint_result(
                {"schema_version": "1.0.0", "status": "PASS"})

    def test_every_required_field_is_required(self):
        required = ("schema_version", "constraint_id", "status",
                    "normalized_value", "normalized_unit", "reason_code")
        for missing in required:
            payload = {k: v for k, v in _result().items() if k != missing}
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError):
                    validate_constraint_result(payload)

    def test_reason_code_must_be_in_the_schema_enum(self):
        # The exact reproduction from ISSUE-09, plus every other
        # plausible wrong value.
        for bad in ("BOGUS", "ok", "", None, 0):
            with self.subTest(reason_code=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_result(_result(reason_code=bad))
        for good in ("OK", "NON_FINITE", "UNKNOWN_UNIT",
                     "INCOMPATIBLE_UNIT", "INVALID_REQUEST",
                     # ISSUE-52 (2026-11-11): the distinct codes Rust
                     # and Julia emit for a major mismatch / bad
                     # operator; see REASON_CODES.
                     "UNSUPPORTED_MAJOR_VERSION", "UNSUPPORTED_OPERATOR"):
            validate_constraint_result(_result(reason_code=good))

    def test_status_must_be_in_the_schema_enum(self):
        for bad in ("APPROVED", "pass", "", None):
            with self.subTest(status=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_result(_result(status=bad))

    def test_unknown_extra_property_rejected(self):
        with self.assertRaises(ValueError):
            validate_constraint_result(_result(extra=1))

    def test_normalized_value_must_be_finite_or_null(self):
        for bad in (math.nan, math.inf, True, "8"):
            with self.subTest(value=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_result(_result(normalized_value=bad))
        validate_constraint_result(_result(normalized_value=None))
        validate_constraint_result(_result(normalized_value=0))

    def test_normalized_unit_must_be_string_or_null(self):
        for bad in (5, True, ["L"]):
            with self.subTest(unit=repr(bad)):
                with self.assertRaises((ValueError, TypeError)):
                    validate_constraint_result(_result(normalized_unit=bad))
        validate_constraint_result(_result(normalized_unit=None))

    def test_details_must_be_a_string_when_present(self):
        with self.assertRaises(ValueError):
            validate_constraint_result(_result(details=42))
        validate_constraint_result(_result(details="evaluated"))

    def test_result_version_follows_the_same_major_rule(self):
        # Previously exact equality: even a compatible 1.0.1 result
        # was rejected ("unsupported result schema version").
        validate_constraint_result(_result(schema_version="1.0.0"))
        validate_constraint_result(_result(schema_version="1.0.1"))
        validate_constraint_result(_result(schema_version="1.1.0"))
        with self.assertRaises(ValueError) as ctx:
            validate_constraint_result(_result(schema_version="2.0.0"))
        self.assertIn("unsupported major schema version", str(ctx.exception))
        with self.assertRaises(ValueError):
            validate_constraint_result(_result(schema_version="1.0"))

    def test_non_object_payload_rejected(self):
        for bad in (None, "x", [1]):
            with self.subTest(payload=repr(bad)):
                with self.assertRaises(TypeError):
                    validate_constraint_result(bad)

    def test_valid_results_still_accepted(self):
        validate_constraint_result(_result())
        validate_constraint_result(_result(
            status="UNKNOWN", normalized_value=None,
            normalized_unit=None, reason_code="UNKNOWN_UNIT"))


class Issue09ValidatorReadsTheSchemaFilesTest(unittest.TestCase):
    """The validator loads the schema files, it does not carry a
    private copy of their rules."""

    def test_loaded_schemas_match_the_files_on_disk(self):
        for filename, loaded in (
                ("constraint-evaluation.schema.json",
                 contracts._REQUEST_SCHEMA),
                ("constraint-evaluation-result.schema.json",
                 contracts._RESULT_SCHEMA)):
            on_disk = json.loads(
                (ROOT / "interop" / "schemas" / filename).read_text())
            self.assertEqual(loaded, on_disk, filename)

    def test_schema_alone_cannot_express_unit_membership(self):
        # Boundary record (ISSUE-08): the request schema requires
        # value_unit/bound_unit to be non-empty strings only — there
        # is no enum of registry units. Membership therefore has to
        # come from the validator code, which the unit tests above pin.
        schema = contracts._REQUEST_SCHEMA
        for key in ("value_unit", "bound_unit"):
            self.assertNotIn("enum", schema["properties"][key])
            self.assertEqual(
                schema["properties"][key], {"minLength": 1, "type": "string"})

    def test_schema_version_is_a_pattern_not_a_const(self):
        # Resolution of the const-vs-same-major contradiction: the
        # schema itself accepts any same-major 1.x.y version.
        for schema in (contracts._REQUEST_SCHEMA, contracts._RESULT_SCHEMA):
            prop = schema["properties"]["schema_version"]
            self.assertNotIn("const", prop)
            self.assertEqual(prop, {"pattern": r"^1\.[0-9]+\.[0-9]+$"})
            self.assertTrue(re.fullmatch(prop["pattern"], "1.0.0"))
            self.assertTrue(re.fullmatch(prop["pattern"], "1.0.1"))
            self.assertTrue(re.fullmatch(prop["pattern"], "1.1.0"))
            self.assertIsNone(re.fullmatch(prop["pattern"], "2.0.0"))
            self.assertIsNone(re.fullmatch(prop["pattern"], "1.0"))


class Issue10And54SingleSourceOfTruthTest(unittest.TestCase):
    """One canonical version per schema, from interop/SCHEMA_VERSION."""

    def test_canonical_version_file(self):
        text = (ROOT / "interop" / "SCHEMA_VERSION").read_text()
        self.assertEqual(text, "1.0.0")  # no trailing newline by design
        self.assertFalse(text.endswith("\n"))

    def test_python_reads_the_canonical_file(self):
        self.assertEqual(contracts.SCHEMA_VERSION, "1.0.0")
        self.assertEqual(
            contracts.SCHEMA_VERSION,
            (ROOT / "interop" / "SCHEMA_VERSION").read_text().strip())
        self.assertEqual(contracts.SUPPORTED_MAJOR, 1)

    def test_rust_reads_the_canonical_file(self):
        lib = (ROOT / "components" / "rust-kernels" / "src" / "lib.rs").read_text()
        self.assertIn(
            'include_str!("../../../interop/SCHEMA_VERSION")', lib)
        const_line = next(
            ln for ln in lib.splitlines()
            if ln.startswith("pub const SCHEMA_VERSION"))
        self.assertNotIn('"1.0.0"', const_line,
                         "Rust SCHEMA_VERSION must not be a hard-coded copy")

    def test_rust_binary_uses_the_constant_not_a_literal(self):
        binary = (ROOT / "components" / "rust-kernels" / "src" / "bin"
                  / "start-kernel.rs").read_text()
        self.assertNotIn('"1.0.0"', binary)
        self.assertIn("SCHEMA_VERSION", binary)

    def test_julia_reads_the_canonical_file(self):
        src = (ROOT / "components" / "julia-planning" / "src"
               / "STARTPlanning.jl").read_text()
        self.assertIn('joinpath(@__DIR__, "..", "..", "..", "interop", '
                      '"SCHEMA_VERSION")', src)
        self.assertNotIn('const SCHEMA_VERSION = "1.0.0"', src)
        self.assertIn("SUPPORTED_SCHEMA_MAJOR = parse(Int, "
                      'split(SCHEMA_VERSION, ".")[1])', src)

    def test_schema_patterns_agree_with_the_canonical_version(self):
        canonical = (ROOT / "interop" / "SCHEMA_VERSION").read_text().strip()
        major = canonical.split(".")[0]
        for filename in ("constraint-evaluation.schema.json",
                         "constraint-evaluation-result.schema.json"):
            schema = json.loads(
                (ROOT / "interop" / "schemas" / filename).read_text())
            pattern = schema["properties"]["schema_version"]["pattern"]
            self.assertTrue(re.fullmatch(pattern, canonical), filename)
            self.assertTrue(pattern.startswith(f"^{major}\\."), filename)

    def test_versioning_doc_names_the_single_source(self):
        doc = (ROOT / "interop" / "CONTRACT_VERSIONING.md").read_text()
        self.assertIn("interop/SCHEMA_VERSION", doc)
        self.assertIn("single source of truth", doc)


class TestIssue10JuliaPlanningMessageMoot(unittest.TestCase):
    """ISSUE-10's second half — give the Julia planning message its
    own schema/version — is moot: no Julia planning message exists any
    more. ISSUE-05 removed PlanningInput / evaluate_linear_balance
    from the review-copy Julia (the module docstring records the
    removal); the only remaining mentions are that historical record.
    There is no second payload to version."""

    def test_no_planning_message_definition_survives(self):
        src = (ROOT / "components" / "julia-planning" / "src"
               / "STARTPlanning.jl").read_text()
        self.assertNotIn("struct PlanningInput", src)
        self.assertNotIn("function evaluate_linear_balance", src)
        self.assertNotIn("evaluate_linear_balance(", src)

    def test_no_second_schema_version_in_julia(self):
        src = (ROOT / "components" / "julia-planning" / "src"
               / "STARTPlanning.jl").read_text()
        # Exactly one SCHEMA_VERSION definition, and it is the read
        # from the shared file — not a second version for another
        # payload.
        definitions = [ln for ln in src.splitlines()
                       if ln.startswith("const SCHEMA_VERSION")]
        self.assertEqual(len(definitions), 1)


class Issue11ReleaseVersionsAgreeTest(unittest.TestCase):
    """ISSUE-11: pyproject, changelog heading and README heading must
    name the same release. The fix chosen was to bump pyproject.toml
    to 0.3.2 (the changelog already announced 0.3.2 and its body
    describes 0.3.2 work); correcting the changelog down to 0.3.1
    would have mislabelled the release instead."""

    def _pyproject_version(self):
        match = re.search(
            r'^version\s*=\s*"([^"]+)"',
            (ROOT / "pyproject.toml").read_text(), re.MULTILINE)
        self.assertIsNotNone(match, "no version in pyproject.toml")
        return match.group(1)

    def _changelog_heading_version(self):
        text = (ROOT / "CHANGELOG.md").read_text()
        match = re.search(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\b",
                          text, re.MULTILINE)
        self.assertIsNotNone(match, "no version heading in CHANGELOG.md")
        return match.group(1)

    def test_package_version_matches_changelog_heading(self):
        self.assertEqual(self._pyproject_version(), "0.3.2")
        self.assertEqual(self._changelog_heading_version(), "0.3.2")
        self.assertEqual(self._pyproject_version(),
                         self._changelog_heading_version())

    def test_readme_heading_matches_too(self):
        first_line = (ROOT / "README.md").read_text().splitlines()[0]
        self.assertTrue(first_line.startswith("# START v0.3.2"),
                        first_line)

    def test_changelog_scopes_the_no_changes_line(self):
        text = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn("this zip package's own prior 0.3.1 release", text)
        self.assertIn("contains none of the START repository's v0.3.1 "
                      "`planning.py` functions or data", text)
        self.assertNotIn(
            "No changes to the existing v0.3.1 Python reference behavior",
            text)

    def test_issue02_correction_line_is_kept(self):
        # The dated ISSUE-02 correction added by the blockers job must
        # survive, immediately under the line it corrects.
        lines = (ROOT / "CHANGELOG.md").read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith("- No changes to the behaviour of this zip"):
                self.assertTrue(
                    lines[i + 1].startswith(
                        "- Correction 2026-11-11 (ISSUE-02):"),
                    "ISSUE-02 correction must follow the line it corrects")
                return
        self.fail("rewritten 'No changes' line not found in CHANGELOG.md")


if __name__ == "__main__":
    unittest.main()
