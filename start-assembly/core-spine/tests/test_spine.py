"""Core-spine adapter tests. Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Only tests for adapters actually built here are asserted; a missing
optional package skips its test (recorded as skipped, not passed).
Never claim a test passed unless it ran here.
"""

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.statuses import (  # noqa: E402
    CheckStatus, ConstraintResult, InternalStatus, PlanningResult,
    evaluate_ge, evaluate_le, project_to_verdict)
from adapters import optimisation as opt  # noqa: E402
from adapters import governance, orchestration, evaluation  # noqa: E402
from adapters import interop  # noqa: E402


def _has(mod):
    return importlib.util.find_spec(mod) is not None


class TestStatuses(unittest.TestCase):
    def test_empty_checks_never_pass(self):
        r = PlanningResult(scenario_id="x", checks=[])
        self.assertEqual(r.overall_status, InternalStatus.NOT_CHECKED)
        self.assertEqual(r.overall_verdict, CheckStatus.INDETERMINATE)
        self.assertFalse(r.passes)

    def test_unknown_only_is_indeterminate_not_pass(self):
        r = PlanningResult(scenario_id="x", checks=[
            ConstraintResult("n", InternalStatus.UNKNOWN, "no bound")])
        self.assertEqual(r.overall_status, InternalStatus.UNKNOWN)
        self.assertEqual(r.overall_verdict, CheckStatus.INDETERMINATE)
        self.assertFalse(r.passes)

    def test_fail_wins_over_pass_and_unknown(self):
        r = PlanningResult(scenario_id="x", checks=[
            ConstraintResult("a", InternalStatus.PASS, ""),
            ConstraintResult("b", InternalStatus.UNKNOWN, ""),
            ConstraintResult("c", InternalStatus.FAIL, "")])
        self.assertEqual(r.overall_status, InternalStatus.FAIL)
        self.assertEqual(r.overall_verdict, CheckStatus.FAIL)

    def test_all_pass_is_pass(self):
        r = PlanningResult(scenario_id="x", checks=[
            ConstraintResult("a", InternalStatus.PASS, "")])
        self.assertTrue(r.passes)

    def test_incomplete_projects_to_indeterminate(self):
        self.assertEqual(project_to_verdict(InternalStatus.INCOMPLETE),
                         CheckStatus.INDETERMINATE)

    def test_wire_result_shape(self):
        c = ConstraintResult("food", InternalStatus.PASS, "ok",
                             actual_value=2800, required_value=2500,
                             unit="kcal/capita/day")
        w = c.to_wire_result()
        self.assertEqual(w["schema_version"], "1.0.0")
        self.assertEqual(w["status"], "PASS")
        self.assertEqual(w["reason_code"], "OK")

    def test_evaluate_ge_food_flagship(self):
        # ISSUE-03 flagship: 2800 kcal/capita/day >= 2500 -> PASS
        c = evaluate_ge(2800, 2500, "food_energy_adequacy", "kcal/capita/day")
        self.assertEqual(c.status, InternalStatus.PASS)

    def test_evaluate_le_fail(self):
        c = evaluate_le(12, 10, "fail", "L")
        self.assertEqual(c.status, InternalStatus.FAIL)

    def test_non_finite_is_unknown_never_pass(self):
        c = evaluate_le(float("inf"), 10, "x", "kg")
        self.assertEqual(c.status, InternalStatus.UNKNOWN)

    def test_empty_constraint_id_is_unknown(self):
        c = evaluate_le(5, 10, "", "kg")
        self.assertEqual(c.status, InternalStatus.UNKNOWN)


class TestOptimisationScipy(unittest.TestCase):
    def test_scipy_highs_cross_solver_totals(self):
        r = opt.solve_scipy_highs(loss=0.0)
        self.assertEqual(r["status"], "optimal", r)
        self.assertAlmostEqual(r["delivered_t"], 600.0, places=1)
        self.assertAlmostEqual(r["shortage_t"], 50.0, places=1)
        self.assertAlmostEqual(r["production_t"], 600.0, places=1)
        self.assertAlmostEqual(r["water_m3"], 100_000.0, places=0)

    def test_scipy_highs_pcac_style_totals(self):
        r = opt.solve_scipy_highs(loss=0.05)
        self.assertEqual(r["status"], "optimal", r)
        self.assertAlmostEqual(r["delivered_t"], 583.33, places=1)
        self.assertAlmostEqual(r["shortage_t"], 66.67, places=1)
        self.assertAlmostEqual(r["production_t"], 614.04, places=1)
        self.assertLess(r["labour_h"], 10_000.0)

    def test_check_totals_passes_on_correct_result(self):
        r = opt.solve_scipy_highs(loss=0.0)
        pr = opt.check_totals(r, opt.EXPECTED_CROSS)
        self.assertTrue(pr.passes, pr.to_dict())

    def test_check_totals_fails_on_wrong_result(self):
        bad = dict(opt.solve_scipy_highs(loss=0.0), delivered_t=100.0)
        pr = opt.check_totals(bad, opt.EXPECTED_CROSS)
        self.assertFalse(pr.passes)
        self.assertEqual(pr.failed_count, 1)

    def test_check_totals_unknown_on_missing_value(self):
        pr = opt.check_totals({"solver": "none"}, opt.EXPECTED_CROSS)
        self.assertEqual(pr.overall_status, InternalStatus.UNKNOWN)
        self.assertFalse(pr.passes)


@unittest.skipUnless(_has("cvxpy"), "cvxpy not installed")
class TestOptimisationCvxpy(unittest.TestCase):
    def test_cvxpy_reproduces_cross_solver_totals(self):
        r = opt.solve_cvxpy()
        self.assertEqual(r["status"], "optimal", r)
        self.assertAlmostEqual(r["delivered_t"], 600.0, places=1)
        self.assertAlmostEqual(r["shortage_t"], 50.0, places=1)
        pr = opt.check_totals(r, opt.EXPECTED_CROSS)
        self.assertTrue(pr.passes, pr.to_dict())


@unittest.skipUnless(_has("cpmpy"), "cpmpy not installed")
class TestOptimisationCpmpy(unittest.TestCase):
    def test_cpmpy_reproduces_cross_solver_totals(self):
        r = opt.solve_cpmpy()
        self.assertEqual(r["status"], "optimal", r)
        self.assertAlmostEqual(r["delivered_t"], 600.0, places=1)
        self.assertAlmostEqual(r["shortage_t"], 50.0, places=1)
        pr = opt.check_totals(r, opt.EXPECTED_CROSS)
        self.assertTrue(pr.passes, pr.to_dict())


@unittest.skipUnless(_has("pyarrow"), "pyarrow not installed")
class TestInteropArrow(unittest.TestCase):
    def test_arrow_round_trip_lossless(self):
        rows = [
            ConstraintResult("food", InternalStatus.PASS, "ok",
                             actual_value=2800, required_value=2500,
                             unit="kcal/capita/day"),
            ConstraintResult("mass", InternalStatus.FAIL, "over",
                             actual_value=12, required_value=10, unit="L"),
        ]
        out = interop.arrow_round_trip(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["constraint_id"], "food")
        self.assertEqual(out[0]["status"], "PASS")
        self.assertEqual(out[0]["actual_value"], 2800)
        self.assertEqual(out[1]["status"], "FAIL")
        self.assertEqual(out[1]["required_value"], 10)


@unittest.skipUnless(_has("grpc"), "grpcio not installed")
class TestInteropGrpc(unittest.TestCase):
    def test_grpc_round_trip_pass(self):
        r = interop.evaluate_remote({
            "schema_version": "1.0.0", "constraint_id": "mass",
            "operator": "<=", "value": 8, "value_unit": "t",
            "bound": 10, "bound_unit": "t", "tolerance": 0})
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["reason_code"], "OK")

    def test_grpc_round_trip_fail_and_unknown(self):
        r = interop.evaluate_remote({
            "schema_version": "1.0.0", "constraint_id": "fail",
            "operator": "<=", "value": 12, "value_unit": "L",
            "bound": 10, "bound_unit": "L", "tolerance": 0})
        self.assertEqual(r["status"], "FAIL")
        r2 = interop.evaluate_remote({
            "schema_version": "1.0.0", "constraint_id": "incomp",
            "operator": "<=", "value": 5, "value_unit": "L",
            "bound": 10, "bound_unit": "kg", "tolerance": 0})
        self.assertEqual(r2["status"], "UNKNOWN")
        self.assertEqual(r2["reason_code"], "INCOMPATIBLE_UNIT")


class TestGovernance(unittest.TestCase):
    def test_planner_may_plan_synthetic(self):
        d = governance.authorise("Planner", "PlanAction", {"synthetic": True})
        self.assertTrue(d.authorised)

    def test_planner_may_not_plan_real(self):
        d = governance.authorise("Planner", "PlanAction", {"synthetic": False})
        self.assertFalse(d.authorised)

    def test_publish_denied_when_unverified(self):
        d = governance.authorise("Planner", "PublishAction",
                                 {"verified": False, "human_approved": True})
        self.assertFalse(d.authorised)

    def test_publish_denied_when_not_human_approved(self):
        d = governance.authorise("Human", "PublishAction",
                                 {"verified": True, "human_approved": False})
        self.assertFalse(d.authorised)

    def test_publish_allowed_when_verified_and_approved(self):
        d = governance.authorise("Human", "PublishAction",
                                 {"verified": True, "human_approved": True})
        self.assertTrue(d.authorised)

    def test_unknown_action_is_unknown_not_authorised(self):
        d = governance.authorise("Planner", "DeleteEverything", {})
        self.assertFalse(d.authorised)
        self.assertEqual(d.status, "UNKNOWN")

    def test_denied_action_stays_denied(self):
        # No override path: the same denied request, re-checked, is denied.
        ctx = {"verified": False, "human_approved": True}
        self.assertFalse(governance.authorise("Planner", "ExecuteAction", ctx).authorised)
        self.assertFalse(governance.authorise("Planner", "ExecuteAction", ctx).authorised)


class TestOrchestration(unittest.TestCase):
    def test_pipeline_passes_on_consistent_plan(self):
        out = orchestration.run_pipeline({"scenario_id": "s1"})
        self.assertTrue(out["report"]["passes"])
        self.assertTrue(out["report"]["needs_human_decision"])

    def test_pipeline_fails_on_inconsistent_plan(self):
        out = orchestration.run_pipeline(
            {"scenario_id": "s1", "delivered_t": 600.0, "shortage_t": 100.0})
        # 600 + 100 = 700 != 650 demand -> verification FAIL
        self.assertFalse(out["report"]["passes"])
        self.assertEqual(out["report"]["failed_count"], 1)

    def test_report_refuses_without_verification(self):
        with self.assertRaises(RuntimeError):
            orchestration.report_step({"plan": {"scenario_id": "s1"}})

    def test_verify_cannot_be_bypassed_by_planner(self):
        # Even if a caller forges a plan, report still needs verify output.
        state = orchestration.plan_step({"scenario_id": "s1"})
        self.assertNotIn("verification", state)
        with self.assertRaises(RuntimeError):
            orchestration.report_step(state)

    @unittest.skipUnless(_has("langgraph"), "langgraph not installed")
    def test_langgraph_graph_matches_pipeline(self):
        out = orchestration.run_graph({"scenario_id": "s1"})
        self.assertTrue(out["report"]["passes"])
        self.assertTrue(out["report"]["needs_human_decision"])


class TestEvaluation(unittest.TestCase):
    def test_exact_match_accuracy_local(self):
        r = evaluation.exact_match_accuracy()
        self.assertEqual(r["matches"], 3)
        self.assertEqual(r["total"], 4)
        self.assertAlmostEqual(r["accuracy"], 0.75)

    def test_exact_match_empty_is_not_checked(self):
        r = evaluation.exact_match_accuracy(cases=[])
        self.assertEqual(r["status"], "NOT_CHECKED")
        self.assertIsNone(r["accuracy"])

    def test_deepeval_attempt_is_recorded_not_faked(self):
        r = evaluation.deepeval_exact_match()
        # Either it ran (assembled) or it is honestly blocked.
        self.assertIn(r["status"], ("assembled", "blocked"))
        if r["status"] == "assembled":
            self.assertAlmostEqual(r["accuracy"], 0.75, places=2)

    def test_deepeval_pattern_match_scores(self):
        r = evaluation.deepeval_pattern_match()
        self.assertEqual(r["status"], "assembled", r)
        # "614 tonnes" matches, "614 tonnes extra" and "no tonnes here" do not.
        self.assertEqual(r["scores"], [1.0, 0.0, 0.0])
        self.assertAlmostEqual(r["accuracy"], 1 / 3, places=2)

    def test_pattern_match_is_fullmatch_not_search(self):
        # A substring match is NOT enough: fullmatch requires the whole
        # output to match the pattern. This is the verified 4.3.3 behaviour.
        r = evaluation.deepeval_pattern_match(
            cases=[("614 tonnes extra", 0.0)])
        self.assertEqual(r["status"], "assembled", r)
        self.assertEqual(r["scores"], [0.0])

    def test_pattern_match_invalid_regex_is_blocked_not_faked(self):
        r = evaluation.deepeval_pattern_match(pattern="[unclosed")
        self.assertEqual(r["status"], "blocked")
        self.assertIn("ValueError", r["reason"])
        self.assertIn("Invalid regex pattern", r["reason"])

    def test_pattern_match_ignore_case(self):
        r = evaluation.deepeval_pattern_match(
            pattern=r"potato", cases=[("Potato", 1.0)], ignore_case=True)
        self.assertEqual(r["status"], "assembled", r)
        self.assertEqual(r["scores"], [1.0])

    def test_deepeval_json_correctness_scores(self):
        r = evaluation.deepeval_json_correctness()
        self.assertEqual(r["status"], "assembled", r)
        self.assertIsNone(r["model"])  # system_one: no LLM built, no key
        self.assertEqual(r["eval_mode"], "system_one")
        # valid 1; malformed 0; missing field 0; wrong type 0; not JSON 0.
        self.assertEqual(r["scores"], [1, 0, 0, 0, 0])
        self.assertAlmostEqual(r["accuracy"], 0.2, places=2)
        # The failure reason is the pydantic validation error, not LLM text.
        self.assertIn("validation error", r["reasons"][1].lower())

    def test_json_correctness_wrong_schema_cases(self):
        r = evaluation.deepeval_json_correctness(cases=[
            ('{"delivered": 614}', 0),                    # missing field
            ('{"delivered": "abc", "shortage": 57}', 0),  # uncoercible type
        ])
        self.assertEqual(r["status"], "assembled", r)
        self.assertEqual(r["scores"], [0, 0])

    def test_json_correctness_pydantic_quirks_documented(self):
        # Pydantic coerces the string "614" to int 614 and ignores
        # unknown extra keys by default, so both score 1. Recorded
        # here as a known limitation, not hidden: a stricter schema
        # (StrictInt, extra="forbid") would be needed to catch these.
        r = evaluation.deepeval_json_correctness(cases=[
            ('{"delivered": "614", "shortage": 57}', 1),
            ('{"delivered": 614, "shortage": 57, "extra": 1}', 1),
        ])
        self.assertEqual(r["status"], "assembled", r)
        self.assertEqual(r["scores"], [1, 1])

    def test_json_correctness_default_construction_needs_key(self):
        # Sweep correction, verified in deepeval 4.3.3: constructing
        # JsonCorrectnessMetric WITHOUT eval_mode="system_one" builds
        # a default OpenAI model and raises without an API key.
        import os
        from unittest import mock
        from deepeval.metrics import JsonCorrectnessMetric
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with self.assertRaises(Exception) as ctx:
                JsonCorrectnessMetric(
                    expected_schema=evaluation.PlanJsonSchema,
                    async_mode=False)
        self.assertIn("API key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
