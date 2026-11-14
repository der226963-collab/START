"""General deterministic planning engine; never allocates or approves.

Result-flag semantics (REVIEW.md ISSUE-37): the engine result dict
carries three honest flags instead of one overloaded ``ok``.

* ``calculation_ok`` — True only when the calculation ran to
  ``COMPLETED``. It says nothing about verification.
* ``verified`` — True only when ``verification["verified"]`` is True,
  i.e. an independent verifier re-derived the result (food arithmetic)
  or the result is otherwise fully verified. Generic domains without
  an independent verifier get ``PARTIALLY_VERIFIED`` and ``verified:
  False`` even when the calculation is correct — that is a limit of
  verification coverage, not a failed calculation.
* ``verified_ok`` — ``calculation_ok and verified``: the calculation
  completed AND was independently verified. This is the strictest
  reading and the only one that licenses reliance on the result.

``ok`` is kept as a deprecated alias for ``verified_ok`` (identical
value) so existing consumers keep working unchanged; new callers
should read ``calculation_ok`` / ``verified`` / ``verified_ok``.
``ok: False`` therefore does NOT mean "fail": a completed calculation
in a domain with no independent verifier returns ``ok: False`` with
``calculation_ok: True``. ``needs_human_decision`` is always True on
every engine result path.
"""
from __future__ import annotations

import logging
from typing import Any

from domains.base import DomainModule
from engine.event_log import log_event
from engine.verification import verify_domain_result
from contracts.plan_limits import PlanLimits, check_plan_limits, load_plan_limits
from contracts.statuses import CalculationStatus, CheckStatus
from contracts.scenarios import ScenarioResult


class PlanningEngine:
    def __init__(self, snapshot_path=None) -> None:
        self._domains: dict[str, DomainModule] = {}
        # ISSUE-01: the versioned real-world constraint set is loaded by
        # default, so a plan check no longer depends entirely on
        # caller-supplied bounds. If the snapshot cannot be loaded the
        # engine still runs domains, but check_plan() refuses to run.
        try:
            self.plan_limits: PlanLimits | None = load_plan_limits(snapshot_path)
        except Exception:
            self.plan_limits = None

    def check_plan(self, plan: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check a plan against the default-loaded stored limits.

        Caller-supplied bounds in ``overrides`` that contradict a stored
        bound raise ValueError (see contracts.plan_limits); they are
        never silently applied.
        """
        log_event("engine", "engine.check_plan.started",
                  message="Plan check started")
        if self.plan_limits is None:
            log_event("engine", "engine.check_plan.failed", level=logging.ERROR,
                      message="Plan limits could not be loaded; refusing to check a plan",
                      reason="plan_limits_unavailable")
            raise RuntimeError("Default plan limits could not be loaded from the snapshot; refusing to check a plan against no limits.")
        result = check_plan_limits(plan, limits=self.plan_limits, overrides=overrides)
        log_event("engine", "engine.check_plan.completed",
                  message="Plan check completed",
                  overall_status=result["overall_status"],
                  failed_count=result["failed_count"])
        return result

    def register(self, domain: DomainModule) -> None:
        domain_id = getattr(domain, "domain_id", None)
        if not isinstance(domain_id, str) or not domain_id.strip() or domain_id == "unspecified":
            raise ValueError("Domain must declare a non-empty domain_id")
        if domain_id in self._domains:
            raise ValueError(f"Domain already registered: {domain_id}")
        self._domains[domain_id] = domain

    def available_domains(self) -> list[str]:
        return sorted(self._domains)

    @staticmethod
    def _result_flags(calculation_ok: bool, verified: bool) -> dict[str, Any]:
        """ISSUE-37 split flags. ``ok`` is a deprecated alias for
        ``verified_ok`` (identical value); it is kept so existing
        consumers keep working unchanged."""
        verified_ok = bool(calculation_ok and verified)
        return {"calculation_ok": bool(calculation_ok), "verified": bool(verified),
                "verified_ok": verified_ok, "ok": verified_ok}

    @staticmethod
    def _error_result(domain_id: str, message: str, validation: dict[str, Any] | None = None) -> dict[str, Any]:
        calculation = {"calculation_status": CalculationStatus.ERROR.value, "missing_fields": [],
                       "metrics": {}, "display_metrics": {}, "assumptions": [], "limitations": [message],
                       "error": message}
        evaluation = {"overall_status": CheckStatus.NOT_CHECKED.value,
                      "constraint_results": [], "warnings": ["Calculation failed; evaluation was not performed."]}
        verification = verify_domain_result(domain_id, calculation, evaluation)
        return {**PlanningEngine._result_flags(False, verification.get("verified", False)),
                "domain": domain_id, "validation": validation or {"ok": False, "problems": [message]},
                "calculation": calculation, "evaluation": evaluation, "uncertainty": [message],
                "verification": verification, "constraints_identified": [],
                "needs_human_decision": True, "limitations": [message],
                "note": "No allocation, approval or decision has been made."}

    @staticmethod
    def _as_str_list(value: Any, field: str) -> list[str]:
        """ISSUE-28: coerce a misbehaving domain's validation report into
        shape instead of crashing on it. A non-list problems/assumptions
        value (e.g. the string "oops-string") becomes a one-item list
        carrying it; non-string items are str()'d. A validation report
        is data from the domain, not a trusted structure."""
        if isinstance(value, list):
            return [item if isinstance(item, str) else str(item) for item in value]
        if value is None:
            return []
        return [value if isinstance(value, str) else str(value)]

    def run(self, domain_id: str, request: dict[str, Any]) -> dict[str, Any]:
        # ISSUE-27: metadata-only events (domain_id, statuses, counts).
        # Never a request or result payload at INFO or above.
        log_event("engine", "engine.run.started",
                  message="Engine run started", domain_id=domain_id)
        if domain_id not in self._domains:
            # ISSUE-23 (2026-11-11): the unknown-domain path used to
            # return a short shape (ok/error/available_domains/
            # needs_human_decision) with no domain/calculation/
            # evaluation/verification/limitations keys, so any caller
            # doing r["calculation"]["calculation_status"] got a
            # KeyError only on this path. It now returns the same
            # _error_result shape as every other failure, with
            # available_domains kept as an extra key.
            log_event("engine", "engine.run.unknown_domain", level=logging.WARNING,
                      message="Unknown domain", domain_id=domain_id)
            result = self._error_result(domain_id, f"Unknown domain: {domain_id}")
            result["available_domains"] = self.available_domains()
            return result
        if not isinstance(request, dict):
            log_event("engine", "engine.run.validation_failed", level=logging.WARNING,
                      message="Request failed validation", domain_id=domain_id,
                      reason="request_not_dict")
            return self._error_result(domain_id, "request must be a dictionary")
        domain = self._domains[domain_id]
        try:
            validation = domain.validate_inputs(request)
            if not isinstance(validation, dict) or not isinstance(validation.get("ok"), bool):
                log_event("engine", "engine.run.validation_failed", level=logging.WARNING,
                          message="Domain returned an invalid validation report",
                          domain_id=domain_id, reason="invalid_validation_report")
                return self._error_result(domain_id, "Domain returned an invalid validation report")
        except Exception as exc:
            log_event("engine", "engine.run.domain_error", level=logging.ERROR,
                      message="Input validation raised", domain_id=domain_id,
                      exception_type=type(exc).__name__)
            return self._error_result(domain_id, f"Input validation raised {type(exc).__name__}: {exc}")

        if not validation["ok"]:
            # ISSUE-28: this branch used to assume problems/assumptions
            # are lists and crashed (TypeError on list + str) on a
            # misbehaving domain. Coerce via _as_str_list so a malformed
            # report degrades to a structured validation failure.
            problems = self._as_str_list(validation.get("problems", []), "problems")
            assumptions = self._as_str_list(validation.get("assumptions", []), "assumptions")
            log_event("engine", "engine.run.validation_failed", level=logging.WARNING,
                      message="Input validation failed", domain_id=domain_id,
                      reason="validation_failed", problem_count=len(problems))
            calculation = {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                           "missing_fields": problems, "metrics": {},
                           "display_metrics": {}, "assumptions": assumptions,
                           "source_ids": request.get("source_ids", []),
                           "limitations": ["Validation failed; calculation was not run."]}
            evaluation = {"overall_status": CheckStatus.INCOMPLETE.value, "constraint_results": [],
                          "warnings": ["Validation failed; calculation not run."]}
            verification = verify_domain_result(domain_id, calculation, evaluation, request)
            return {**self._result_flags(False, verification.get("verified", False)),
                    "domain": domain_id, "validation": validation,
                    "calculation": calculation, "evaluation": evaluation,
                    "uncertainty": ["No calculation was performed because validation failed."],
                    "verification": verification, "constraints_identified": [],
                    "needs_human_decision": True,
                    "limitations": calculation["limitations"] + problems,
                    "note": "No allocation, approval or decision has been made."}

        try:
            calculation = domain.calculate(request)
            if not isinstance(calculation, dict):
                raise TypeError("domain.calculate must return a dictionary")
            evaluation = domain.evaluate(calculation)
            if not isinstance(evaluation, dict):
                raise TypeError("domain.evaluate must return a dictionary")
            uncertainty = domain.describe_uncertainty(calculation)
            constraints = domain.identify_constraints(request)
            if not isinstance(uncertainty, list) or not isinstance(constraints, list):
                raise TypeError("uncertainty and constraints must be lists")
        except Exception as exc:
            log_event("engine", "engine.run.domain_error", level=logging.ERROR,
                      message="Domain execution raised", domain_id=domain_id,
                      exception_type=type(exc).__name__)
            return self._error_result(domain_id, f"Domain execution raised {type(exc).__name__}: {exc}", validation)

        verification = verify_domain_result(domain_id, calculation, evaluation, request)
        completed = calculation.get("calculation_status") == CalculationStatus.COMPLETED.value
        verified = verification.get("verified", False)
        limitations = list(calculation.get("limitations", [])) + list(uncertainty)
        if not verified:
            limitations.append("Result is not fully verified; inspect verification status and issues before relying on it.")
        log_event("engine", "engine.run.completed",
                  message="Engine run completed", domain_id=domain_id,
                  calculation_status=calculation.get("calculation_status"),
                  overall_status=evaluation.get("overall_status"),
                  needs_human_decision=True)
        return {**self._result_flags(completed, verified),
                "domain": domain_id, "validation": validation,
                "calculation": calculation, "evaluation": evaluation,
                "uncertainty": uncertainty, "verification": verification,
                "constraints_identified": constraints, "needs_human_decision": True,
                "limitations": limitations,
                "note": "Deterministic planning result only. No allocation, approval or decision has been made."}

    def run_scenario(self, domain_id: str, scenario: Any) -> dict[str, Any]:
        """Same flag semantics as :meth:`run` (ISSUE-37): ``calculation_ok``
        reports the calculation, ``verified`` reports independent
        verification, ``verified_ok`` (and deprecated alias ``ok``) is
        both. A completed scenario in a domain with no independent
        verifier therefore returns ``calculation_ok: True`` with
        ``verified: False`` / ``ok: False`` — distinguishable from a
        failed calculation, where ``calculation_ok`` is False."""
        log_event("engine", "engine.run_scenario.started",
                  message="Scenario run started", domain_id=domain_id,
                  scenario_id=getattr(scenario, "scenario_id", "unknown"))
        if domain_id not in self._domains:
            # ISSUE-23: run_scenario's unknown-domain path used to return
            # a short flags+error dict while run()'s returned the full
            # _error_result shape — the two methods disagreed with each
            # other as well as with every other path. It now returns the
            # same ScenarioResult-shaped failure as the exception path
            # below (plus the W4 result flags and available_domains).
            log_event("engine", "engine.run_scenario.unknown_domain", level=logging.WARNING,
                      message="Unknown domain", domain_id=domain_id,
                      scenario_id=getattr(scenario, "scenario_id", "unknown"))
            failed = ScenarioResult(
                scenario_id=getattr(scenario, "scenario_id", "unknown"), domain=domain_id,
                warnings=[f"Unknown domain: {domain_id}"],
                calculation_status=CalculationStatus.ERROR.value, needs_human_decision=True,
            )
            return {**self._result_flags(False, False), "error": f"Unknown domain: {domain_id}",
                    "available_domains": self.available_domains(), **failed.to_dict()}
        try:
            request = self._domains[domain_id].scenario_request(scenario)
            run_result = self.run(domain_id, request)
            scenario_result = ScenarioResult(
                scenario_id=scenario.scenario_id, domain=domain_id,
                metrics={"calculation": run_result.get("calculation", {}),
                         "evaluation": run_result.get("evaluation", {}),
                         "uncertainty": run_result.get("uncertainty", [])},
                constraint_results=run_result.get("evaluation", {}).get("constraint_results", []),
                warnings=run_result.get("evaluation", {}).get("warnings", []),
                limitations=run_result.get("limitations", []),
                calculation_status=run_result.get("calculation", {}).get("calculation_status", CalculationStatus.ERROR.value),
                verification=run_result.get("verification", {}),
                needs_human_decision=True,
            )
            log_event("engine", "engine.run_scenario.completed",
                      message="Scenario run completed", domain_id=domain_id,
                      scenario_id=scenario.scenario_id,
                      calculation_status=scenario_result.calculation_status,
                      needs_human_decision=True)
            return {**self._result_flags(run_result.get("calculation_ok", False),
                                         run_result.get("verified", False)),
                    **scenario_result.to_dict()}
        except Exception as exc:
            log_event("engine", "engine.run_scenario.failed", level=logging.ERROR,
                      message="Scenario execution failed", domain_id=domain_id,
                      scenario_id=getattr(scenario, "scenario_id", "unknown"),
                      exception_type=type(exc).__name__)
            failed = ScenarioResult(
                scenario_id=getattr(scenario, "scenario_id", "unknown"), domain=domain_id,
                warnings=[f"Scenario execution failed: {type(exc).__name__}: {exc}"],
                calculation_status=CalculationStatus.ERROR.value, needs_human_decision=True,
            )
            return {**self._result_flags(False, False), **failed.to_dict()}

    def compare_scenarios(self, domain_id: str, scenarios: list[Any]) -> dict[str, Any]:
        """Calculate each supplied scenario; deliberately does not rank or select."""
        log_event("engine", "engine.compare_scenarios.started",
                  message="Scenario comparison started", domain_id=domain_id,
                  scenario_count=len(scenarios))
        if not scenarios:
            log_event("engine", "engine.compare_scenarios.completed",
                      message="Scenario comparison completed", domain_id=domain_id,
                      scenario_count=0, all_calculation_ok=False)
            return {**self._result_flags(False, False),
                    "domain": domain_id, "results": [],
                    "note": "No scenarios supplied; no selection was made.", "needs_human_decision": True}
        results = [self.run_scenario(domain_id, scenario) for scenario in scenarios]
        registered = domain_id in self._domains
        all_ok = registered and all(r.get("calculation_ok", False) for r in results)
        all_verified = registered and all(r.get("verified", False) for r in results)
        log_event("engine", "engine.compare_scenarios.completed",
                  message="Scenario comparison completed", domain_id=domain_id,
                  scenario_count=len(results), all_calculation_ok=all_ok,
                  all_verified=all_verified)
        return {**self._result_flags(all_ok, all_verified),
                "domain": domain_id, "results": results,
                "selection": None,
                "note": "Scenario consequences are reported without ranking, preference inference or automatic selection.",
                "needs_human_decision": True}
