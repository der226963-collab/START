"""Common interface for domain-specific deterministic planning modules."""
from __future__ import annotations
from abc import ABC, abstractmethod
import math
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
    # ISSUE-34 (2026-11-13): companion allow-list for NON-numeric
    # scenario changes (str, or list[str] such as source_ids). Same
    # shape, same default: None means NO non-numeric changes are
    # permitted — a non-numeric change to a field the domain has not
    # explicitly allow-listed here is rejected, never silently
    # applied, exactly as ISSUE-33 requires for numeric changes.
    # Food declares nothing here (default None): its scenario changes
    # stay numeric-only. A domain that needs non-numeric changes
    # declares them, e.g. frozenset({"source_ids", "geography",
    # "period"}). There is still exactly one allow-list mechanism —
    # these two attributes on DomainModule, enforced by the shared
    # _check_scenario_changes below; no second mechanism is invented.
    scenario_non_numeric_change_fields: frozenset[str] | None = None

    def _check_scenario_changes(self, scenario: Scenario) -> None:
        """Reject scenario changes outside the domain's declared fields.

        One rule for the generic and the food paths (ISSUE-38): the
        generic path used to apply any float field, including injected
        keys such as "__injected__" (ISSUE-33), while food raised
        ValueError. Both now raise the same way. ISSUE-34 extends the
        rule by value shape: a numeric change requires its key in
        scenario_change_fields; a str / list[str] change requires its
        key in scenario_non_numeric_change_fields. Anything else
        (bool, None, dict, non-finite number — normally already
        rejected by Scenario.__post_init__) is invalid outright.
        """
        numeric_allowed = set(self.scenario_change_fields or ())
        non_numeric_allowed = set(self.scenario_non_numeric_change_fields or ())
        numeric_unknown: list[str] = []
        non_numeric_unknown: list[str] = []
        invalid: list[str] = []
        for key, value in scenario.proposed_changes.items():
            if isinstance(value, bool):
                invalid.append(key)
            elif isinstance(value, (int, float)):
                if not math.isfinite(value):
                    invalid.append(key)
                elif key not in numeric_allowed:
                    numeric_unknown.append(key)
            elif isinstance(value, (str, list)):
                if key not in non_numeric_allowed:
                    non_numeric_unknown.append(key)
            else:
                invalid.append(key)
        if numeric_unknown:
            raise ValueError(
                f"Unsupported scenario change fields for domain {self.domain_id!r}: "
                + ", ".join(sorted(numeric_unknown))
                + " (not in scenario_change_fields)")
        if non_numeric_unknown:
            raise ValueError(
                f"Unsupported non-numeric scenario change fields for domain {self.domain_id!r}: "
                + ", ".join(sorted(non_numeric_unknown))
                + " (not in scenario_non_numeric_change_fields)")
        if invalid:
            raise ValueError(
                f"Invalid scenario change values for domain {self.domain_id!r}: "
                + ", ".join(sorted(invalid))
                + " (must be a finite number, a non-empty string, or a list of non-empty strings)")

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
