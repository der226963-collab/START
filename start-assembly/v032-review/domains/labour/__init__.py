"""Labour domain: deterministic paid-work check and unpaid-care split.

Paid work (ISSUE-34, 2026-11-13) — the caller's stated
``paid_work_hours_per_week`` is checked against the 48 h/week ILO
long-hours threshold stored in ``contracts.plan_limits`` (a v0.3.1
code constant, not a snapshot CSV row): ``<= 48`` PASS, ``> 48``
FAIL. No paid-work figure stated means the check is UNKNOWN,
never PASS.

Unpaid care — the stated total (billion hours/day) is split by the
stated women's share (percent): women = total * share / 100, men =
total * (1 - share / 100). With the snapshot values (ILO 2018:
16.4 billion hours/day, women's share 76.2%) that is 12.4968 /
3.9032 billion hours/day. The snapshot employed / all-adults paid-work
averages (2026, Gethin and Saez IMF dataset: 43 / 25 h/week) may be
supplied as snapshot CONTEXT and are reported as such — they are
never the caller's figure and never checked against the threshold.

Per-person care hours are computed ONLY when the caller explicitly
supplies a population; no population is ever assumed. Combining the
2018 care figures with a 2024 population is a year mismatch and is
stated as a limitation whenever both are combined.

There is no independent verifier for this domain, so engine results
are PARTIALLY_VERIFIED by design (docs/ARCHITECTURE.md, "Adding a
domain" rule 5) — that is a limit of verification coverage, not a
failed calculation.
"""
from __future__ import annotations
from typing import Any
import math
from domains.base import DomainModule
from domains.labour.schema import (
    REQUIRED_FOR_CARE,
    NUMERIC_REQUEST_FIELDS,
    ALLOWED_REQUEST_FIELDS,
)
from domains.labour.labour import (
    labour_balance,
    default_labour_constraints,
    paid_work_threshold_hours_per_week,
)
from domains.labour.evaluation import evaluate_labour_result, describe_labour_uncertainty
from domains.food.production import data_status_for
from contracts.statuses import CalculationStatus
from contracts.scenarios import Scenario, ScenarioResult


class LabourDomain(DomainModule):
    domain_id = "labour"
    display_name = "Labour"
    # ISSUE-33/38 (2026-11-11): the fields a scenario may change, declared
    # on the domain so the generic base path enforces the same allow-list
    # the labour path does. See DomainModule.scenario_change_fields.
    scenario_change_fields = frozenset(NUMERIC_REQUEST_FIELDS)
    # ISSUE-34 (2026-11-13): companion allow-list for non-numeric
    # scenario changes, enforced by the shared
    # DomainModule._check_scenario_changes. See
    # DomainModule.scenario_non_numeric_change_fields.
    scenario_non_numeric_change_fields = frozenset({"source_ids", "geography", "period"})

    @staticmethod
    def _number_problem(field: str, value: Any, *, positive: bool = False) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"field {field} must be a number (booleans are not accepted)"
        if not math.isfinite(value):
            return f"field {field} must be finite"
        if positive and value <= 0:
            return f"field {field} must be greater than zero"
        if not positive and value < 0:
            return f"field {field} must be non-negative"
        return None

    def validate_inputs(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "problems": ["request must be a dictionary"], "warnings": [], "assumptions": []}
        problems, warnings, assumptions = [], [], []
        # ISSUE-12(e): rejection, not a warning — as in food. A
        # misspelled field must surface as a problem, never be
        # silently ignored while the intended value is missing.
        unknown = sorted(set(request) - set(ALLOWED_REQUEST_FIELDS))
        if unknown:
            problems.append("unknown request field(s): " + ", ".join(unknown))
        for field in REQUIRED_FOR_CARE:
            value = request.get(field)
            if value is None:
                # ISSUE-15 policy, carried over from food: the care
                # figures are REQUIRED stated inputs — a missing field
                # OR an explicit None is a missing required field,
                # never silently assumed.
                problems.append(f"missing required field: {field}")
            else:
                problem = self._number_problem(field, value)
                if problem:
                    problems.append(problem)
                elif field == "women_share_unpaid_care_percent" and not 0.0 <= request[field] <= 100.0:
                    problems.append("women_share_unpaid_care_percent must be between 0 and 100 inclusive")
        for field in ("paid_work_hours_per_week",
                      "snapshot_paid_work_hours_per_week_employed",
                      "snapshot_paid_work_hours_per_week_all_adults"):
            if field in request and request[field] is not None:
                problem = self._number_problem(field, request[field])
                if problem:
                    problems.append(problem)
        if "population" in request and request["population"] is not None:
            problem = self._number_problem("population", request["population"], positive=True)
            if problem:
                problems.append(problem)
            # ISSUE-12(d), as in food: population counts people, so
            # it must be a whole number (tolerance-based: a
            # snapshot-derived 8.2e9 arrives as 8199999999.999999
            # through float multiplication).
            elif not math.isclose(float(request["population"]), round(float(request["population"])),
                                  rel_tol=1e-9, abs_tol=1e-6):
                problems.append("field population must be a whole number")
        if "source_ids" in request and (not isinstance(request["source_ids"], list) or any(not isinstance(x, str) or not x.strip() for x in request["source_ids"])):
            problems.append("source_ids must be a list of non-empty strings")
        # ISSUE-21 (2026-11-11), as in food: scenario_assumptions is
        # a list of strings; unvalidated, a string was char-split by
        # list() in calculate() and a non-iterable raised TypeError.
        if "scenario_assumptions" in request:
            value = request["scenario_assumptions"]
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                problems.append("scenario_assumptions must be a list of strings")
        for field in ("geography", "period"):
            if field in request and not isinstance(request[field], str):
                problems.append(f"{field} must be a string identifier")
        if assumptions:
            warnings.append("Optional values were defaulted only as explicit assumptions; review their effect before relying on the result.")
        return {"ok": not problems, "problems": problems, "warnings": warnings,
                "assumptions": assumptions, "required_fields": list(REQUIRED_FOR_CARE)}

    def calculate(self, request: dict[str, Any]) -> dict[str, Any]:
        # ISSUE-20 (2026-11-11), as in food: a non-dict input is
        # INSUFFICIENT_INPUT, never a crash.
        if not isinstance(request, dict):
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": ["request must be a dictionary"], "metrics": {}, "display_metrics": {},
                    "metric_units": {}, "assumptions": [], "source_ids": [], "data_status": "unknown",
                    "limitations": ["Input validation failed; calculation was not performed."]}
        validation = self.validate_inputs(request)
        if not validation["ok"]:
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": validation["problems"], "metrics": {}, "display_metrics": {},
                    "metric_units": {}, "assumptions": validation["assumptions"],
                    "source_ids": request.get("source_ids", []),
                    "data_status": data_status_for(request.get("source_ids")),
                    "limitations": ["Input validation failed; calculation was not performed."]}
        assumptions = list(validation["assumptions"])
        assumptions.extend(request.get("scenario_assumptions", []))
        return labour_balance(
            unpaid_care_hours_per_day_billion=request["unpaid_care_hours_per_day_billion"],
            women_share_unpaid_care_percent=request["women_share_unpaid_care_percent"],
            paid_work_hours_per_week=request.get("paid_work_hours_per_week"),
            population=request.get("population"),
            snapshot_paid_work_hours_per_week_employed=request.get("snapshot_paid_work_hours_per_week_employed"),
            snapshot_paid_work_hours_per_week_all_adults=request.get("snapshot_paid_work_hours_per_week_all_adults"),
            assumptions=assumptions,
            source_ids=request.get("source_ids", []),
        )

    def identify_constraints(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        # The threshold is the stored bound from contracts.plan_limits,
        # read here — never re-derived in this domain.
        return [c.to_dict() for c in default_labour_constraints(
            bound=paid_work_threshold_hours_per_week())]

    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]:
        return evaluate_labour_result(result, bound=paid_work_threshold_hours_per_week())

    def describe_uncertainty(self, result: dict[str, Any]) -> list[str]:
        return describe_labour_uncertainty(result)

    def scenario_request(self, scenario: Scenario) -> dict[str, Any]:
        base = scenario.metadata.get("base_request")
        if not isinstance(base, dict):
            raise ValueError("Labour scenario requires metadata.base_request with unpaid care total and women's share")
        request = dict(base)
        # ISSUE-33/38/34: the unknown-field check lives in the shared
        # DomainModule._check_scenario_changes, driven by this domain's
        # declared scenario_change_fields and
        # scenario_non_numeric_change_fields — one rule, not a second
        # labour-only allow-list.
        self._check_scenario_changes(scenario)
        request.update(scenario.proposed_changes)
        # ISSUE-25 (2026-11-11), as in food: generic setdefault
        # semantics — the base request wins. An EXPLICIT proposed
        # change to geography/period (allow-listed above) wins over
        # the base because request.update ran first.
        request.setdefault("geography", scenario.geography)
        request.setdefault("period", scenario.period)
        request.setdefault("scenario_id", scenario.scenario_id)
        request["scenario_assumptions"] = list(scenario.assumptions)
        return request

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        return super().run_scenario(scenario)


__all__ = ["LabourDomain"]
