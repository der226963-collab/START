"""Common interface for domain-specific deterministic planning modules."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from contracts.scenarios import Scenario, ScenarioResult
from contracts.statuses import CalculationStatus, CheckStatus


class DomainModule(ABC):
    domain_id: str = "unspecified"
    display_name: str = "Unspecified domain"
    # ISSUE-33/38 (2026-11-11): the fields a scenario's proposed_changes
    # may touch, declared by the domain. Default None means NO changes
    # are permitted — an unknown field is rejected, never silently
    # applied. A domain sets this to the frozenset of its changeable
    # request fields (FoodDomain: the five REQUIRED_FOR_AVAILABILITY
    # fields, the same allow-list its validate_inputs enforces via
    # domains/food/schema.py ALLOWED_REQUEST_FIELDS — there is exactly
    # one allow-list mechanism, this attribute, driven by the schema
    # set Food already had). The base request itself is NOT allow-listed
    # here: it is a full domain request, checked later by the domain's
    # own validate_inputs (food rejects unknown request fields).
    scenario_change_fields: frozenset[str] | None = None

    def _check_scenario_changes(self, scenario: Scenario) -> None:
        """Reject scenario changes outside the domain's declared fields.

        One rule for the generic and the food paths (ISSUE-38): the
        generic path used to apply any float field, including injected
        keys such as "__injected__" (ISSUE-33), while food raised
        ValueError. Both now raise the same way.
        """
        allowed = set(self.scenario_change_fields or ())
        unknown = set(scenario.proposed_changes) - allowed
        if unknown:
            raise ValueError(
                f"Unsupported scenario change fields for domain {self.domain_id!r}: "
                + ", ".join(sorted(unknown)))

    @abstractmethod
    def validate_inputs(self, request: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def calculate(self, request: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def identify_constraints(self, request: dict[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def describe_uncertainty(self, result: dict[str, Any]) -> list[str]: ...

    def scenario_request(self, scenario: Scenario) -> dict[str, Any]:
        """Build a domain request from a scenario.

        Generic convention: metadata.base_request supplies the baseline request;
        proposed_changes override request fields by name. Domains may override.
        """
        base = scenario.metadata.get("base_request")
        if not isinstance(base, dict):
            raise ValueError("scenario.metadata.base_request must contain a baseline domain request")
        request = dict(base)
        self._check_scenario_changes(scenario)
        request.update(scenario.proposed_changes)
        request.setdefault("geography", scenario.geography)
        request.setdefault("period", scenario.period)
        request["scenario_id"] = scenario.scenario_id
        request["scenario_assumptions"] = list(scenario.assumptions)
        return request

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Unverified convenience calculation; prefer PlanningEngine.run_scenario.

        The engine is required for independent verification and structured
        exception handling. This direct helper is retained for compatibility
        but explicitly marks its output as not independently verified.
        """
        try:
            request = self.scenario_request(scenario)
            validation = self.validate_inputs(request)
            if not validation.get("ok", False):
                return ScenarioResult(
                    scenario_id=scenario.scenario_id, domain=self.domain_id,
                    metrics={"validation": validation},
                    warnings=["Scenario validation failed; no calculation was run."],
                    limitations=validation.get("problems", []),
                    calculation_status=CalculationStatus.INSUFFICIENT_INPUT.value,
                    verification={"verification_status": "NOT_VERIFIABLE", "verified": False},
                )
            calc = self.calculate(request)
            evaluation = self.evaluate(calc)
            uncertainty = self.describe_uncertainty(calc)
            return ScenarioResult(
                scenario_id=scenario.scenario_id, domain=self.domain_id,
                metrics={"calculation": calc, "evaluation": evaluation, "uncertainty": uncertainty},
                constraint_results=evaluation.get("constraint_results", []),
                warnings=evaluation.get("warnings", []) + ["Direct domain scenario execution is not independently verified; use PlanningEngine.run_scenario."],
                limitations=list(calc.get("limitations", [])) + uncertainty,
                calculation_status=calc.get("calculation_status", CalculationStatus.ERROR.value),
                verification={"verification_status": "NOT_VERIFIABLE", "verified": False},
            )
        except Exception as exc:
            return ScenarioResult(
                scenario_id=scenario.scenario_id, domain=self.domain_id,
                warnings=[f"Scenario execution failed: {type(exc).__name__}: {exc}"],
                calculation_status=CalculationStatus.ERROR.value,
                verification={"verification_status": "NOT_VERIFIABLE", "verified": False},
            )
