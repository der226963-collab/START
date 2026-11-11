"""Typed planning models (REVIEW.md ISSUE-16) — review-copy adaptation.

Adapted from the draft ``test_planning_models.py`` (2026-11-06, 9 plain
functions) to the review-copy suite style (``unittest`` TestCase,
discovered by ``python3 -m unittest discover -s tests``) and to the
review-copy types: the five-state internal status is the existing
``contracts.statuses.CheckStatus`` (aliased ``InternalStatus``), the
consumer tri-state is ``Verdict`` (the draft's ``CheckStatus`` name
was already taken), and ``check_plan_limits_typed`` wraps the
review-copy ``contracts.plan_limits.check_plan_limits``.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import unittest

from contracts.models import (
    CheckStatus,
    ConstraintResult,
    InternalStatus,
    PlanningResult,
    Verdict,
    check_plan_limits_typed,
    project_to_verdict,
)
from contracts.plan_limits import check_plan_limits
from contracts.statuses import CheckStatus as ContractCheckStatus


def _result(status, constraint_id="c"):
    return ConstraintResult(
        constraint_id=constraint_id,
        status=status,
        explanation=f"{constraint_id}: {status.value}",
    )


class ProjectionTests(unittest.TestCase):
    def test_fail_wins_over_indeterminate_and_pass(self):
        r = PlanningResult("s", [_result(InternalStatus.PASS), _result(InternalStatus.UNKNOWN), _result(InternalStatus.FAIL)])
        self.assertIs(r.overall_status, InternalStatus.FAIL)
        self.assertIs(r.overall_verdict, Verdict.FAIL)
        self.assertIs(r.passes, False)
        self.assertEqual(r.failed_count, 1)

    def test_unknown_projects_to_indeterminate_not_pass(self):
        r = PlanningResult("s", [_result(InternalStatus.UNKNOWN, "nitrogen")])
        self.assertIs(r.overall_status, InternalStatus.UNKNOWN)
        self.assertIs(r.overall_verdict, Verdict.INDETERMINATE)
        self.assertIs(r.passes, False)

    def test_empty_checks_are_not_checked_never_pass(self):
        r = PlanningResult("s", [])
        self.assertIs(r.overall_status, InternalStatus.NOT_CHECKED)
        self.assertIs(r.overall_verdict, Verdict.INDETERMINATE)
        self.assertIs(r.passes, False)

    def test_all_pass_is_the_only_pass(self):
        r = PlanningResult("s", [_result(InternalStatus.PASS, "p"), _result(InternalStatus.PASS, "food")])
        self.assertIs(r.overall_status, InternalStatus.PASS)
        self.assertIs(r.overall_verdict, Verdict.PASS)
        self.assertIs(r.passes, True)

    def test_internal_precedence_incomplete_before_unknown(self):
        r = PlanningResult("s", [_result(InternalStatus.UNKNOWN), _result(InternalStatus.INCOMPLETE)])
        self.assertIs(r.overall_status, InternalStatus.INCOMPLETE)
        self.assertIs(r.overall_verdict, Verdict.INDETERMINATE)

    def test_every_internal_state_projects(self):
        self.assertIs(project_to_verdict(CheckStatus.PASS), Verdict.PASS)
        self.assertIs(project_to_verdict(CheckStatus.FAIL), Verdict.FAIL)
        for s in (CheckStatus.UNKNOWN, CheckStatus.NOT_CHECKED, CheckStatus.INCOMPLETE):
            self.assertIs(project_to_verdict(s), Verdict.INDETERMINATE)

    def test_internal_status_is_the_existing_contracts_status(self):
        # No second five-state enum: the draft's InternalStatus IS the
        # review copy's CheckStatus, same object.
        self.assertIs(InternalStatus, ContractCheckStatus)


class TypedWrapperTests(unittest.TestCase):
    def test_typed_wrapper_empty_plan_does_not_pass(self):
        # Dict path still says passes_checked_limits True (old behaviour,
        # kept for compat); the typed path applies the safer ISSUE-02 rule.
        legacy = check_plan_limits({})
        self.assertIs(legacy["passes_checked_limits"], True)
        self.assertEqual(legacy["overall_status"], "NOT_CHECKED")
        typed = check_plan_limits_typed({})
        self.assertIs(typed.overall_status, InternalStatus.NOT_CHECKED)
        self.assertIs(typed.passes, False)

    def test_typed_wrapper_nitrogen_only_is_unknown_with_evidence(self):
        typed = check_plan_limits_typed({"nitrogen_fixation_tg_per_year": 165})
        self.assertEqual(len(typed.checks), 1)
        self.assertIs(typed.checks[0].status, InternalStatus.UNKNOWN)
        self.assertEqual(typed.checks[0].actual_value, 165)
        self.assertIsNone(typed.checks[0].required_value)
        self.assertTrue(typed.checks[0].evidence, "nitrogen note must survive as evidence")
        self.assertIn("twice", typed.checks[0].evidence[0])
        self.assertEqual(typed.checks[0].source_ids, ["snapshot:nitrogen_fixation:2025"])
        self.assertIs(typed.passes, False)
        self.assertIs(typed.overall_verdict, Verdict.INDETERMINATE)

    def test_typed_wrapper_issue01_examples(self):
        passing = check_plan_limits_typed({
            "phosphorus_application_tg_per_year": 5.0,
            "food_kcal_per_capita_per_day": 2600,
            "planning_need_kcal_per_capita_per_day": 2500,
            "paid_work_hours_per_week": 40,
        })
        self.assertIs(passing.passes, True)
        self.assertIs(passing.overall_verdict, Verdict.PASS)
        failing = check_plan_limits_typed({
            "phosphorus_application_tg_per_year": 18.2,
            "paid_work_hours_per_week": 55,
        })
        self.assertIs(failing.passes, False)
        self.assertEqual(failing.failed_count, 2)
        self.assertIs(failing.overall_status, InternalStatus.FAIL)

    def test_typed_wrapper_passes_overrides_through(self):
        # A contradicting stored-bound override must still raise: the
        # typed path wraps the real engine, it does not bypass it.
        with self.assertRaises(ValueError):
            check_plan_limits_typed(
                {"phosphorus_application_tg_per_year": 5.0},
                overrides={"phosphorus_application_tg_per_year": 62},
            )
        ok = check_plan_limits_typed(
            {"phosphorus_application_tg_per_year": 5.0},
            overrides={"phosphorus_application_tg_per_year": 6.2},
        )
        self.assertIs(ok.passes, True)

    def test_every_typed_row_carries_evidence_and_source_ids_fields(self):
        typed = check_plan_limits_typed({
            "phosphorus_application_tg_per_year": 5.0,
            "food_kcal_per_capita_per_day": 2600,
            "paid_work_hours_per_week": 40,
            "nitrogen_fixation_tg_per_year": 165,
        })
        for row in typed.to_dict()["checks"]:
            self.assertIn("evidence", row)
            self.assertIsInstance(row["evidence"], list)
            self.assertIn("source_ids", row)
            self.assertIsInstance(row["source_ids"], list)
            self.assertTrue(row["source_ids"], "every row must carry its source ids")

    def test_to_dict_round_trip_keeps_both_statuses(self):
        r = PlanningResult("s", [_result(InternalStatus.UNKNOWN, "nitrogen")])
        d = r.to_dict()
        self.assertEqual(d["overall_status"], "UNKNOWN")
        self.assertEqual(d["overall_verdict"], "indeterminate")
        self.assertEqual(d["checks"][0]["status"], "UNKNOWN")
        self.assertEqual(d["checks"][0]["verdict"], "indeterminate")

    def test_to_dict_is_json_and_sets_no_verified_flag(self):
        typed = check_plan_limits_typed({
            "phosphorus_application_tg_per_year": 5.0,
            "food_kcal_per_capita_per_day": 2600,
            "paid_work_hours_per_week": 40,
        })
        d = typed.to_dict()
        json.dumps(d)  # must be JSON-serialisable (wire format stays JSON)
        self.assertNotIn("verified", d)
        for row in d["checks"]:
            self.assertNotIn("verified", row)


class LegacyRowConversionTests(unittest.TestCase):
    def test_from_legacy_dict_accepts_uppercase_review_copy_rows(self):
        row = check_plan_limits({"nitrogen_fixation_tg_per_year": 165})["checks"][0]
        result = ConstraintResult.from_legacy_dict(row)
        self.assertIs(result.status, InternalStatus.UNKNOWN)
        self.assertEqual(result.constraint_id, "nitrogen_fixation_tg_per_year")

    def test_from_legacy_dict_accepts_lowercase_draft_rows(self):
        result = ConstraintResult.from_legacy_dict({
            "limit": "nitrogen_fixation_tg_per_year",
            "proposed": 165,
            "boundary": None,
            "status": "unknown",
            "note": "more than twice its boundary",
        })
        self.assertIs(result.status, InternalStatus.UNKNOWN)
        self.assertEqual(result.evidence, ["more than twice its boundary"])


if __name__ == "__main__":
    unittest.main()
