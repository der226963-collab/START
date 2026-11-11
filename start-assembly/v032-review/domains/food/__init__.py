"""Food domain: deterministic aggregate food-energy balance prototype.

Food-energy formula (ISSUE-15, 2026-11-11) — v0.3.2, the formula this
domain implements::

    effective_supply = supply * (1 - losses_fraction)
    total_available  = effective_supply + imports_kcal_per_capita_per_day
    surplus          = total_available - requirement

v0.3.1 (``mini_ai/planning.py: food_balance()``) had no losses or
imports at all: ``surplus = supply - need``. The two formulas give
different answers on the same supply/requirement — verified live:
2800/2500 gives 300 under v0.3.1 but total 2676.0 / surplus 176.0
under v0.3.2 with imports 100 and losses 0.08 — and agree ONLY when
losses are 0 and imports are 0 (2985/2500/0/0 gives 485.0 in both).
Losses/imports are the better model (real food systems lose food
between supply and availability and trade across borders), so they
are kept — but they must be STATED, never silently zero: a request
that omits ``imports_kcal_per_capita_per_day`` or ``losses_fraction``,
or passes explicit ``None`` for either, fails validation and the
calculation returns INSUFFICIENT_INPUT. Stating 0.0 explicitly is
allowed; it is the caller asserting "no imports" / "no losses".
See docs/ARCHITECTURE.md for the full worked comparison.
"""
from __future__ import annotations
from typing import Any
import math
from domains.base import DomainModule
from domains.food.schema import REQUIRED_FOR_AVAILABILITY, ALLOWED_REQUEST_FIELDS
from domains.food.production import food_availability, default_food_constraints, data_status_for
from domains.food.evaluation import evaluate_food_result, describe_food_uncertainty
from contracts.statuses import CalculationStatus
from contracts.scenarios import Scenario, ScenarioResult


class FoodDomain(DomainModule):
    domain_id = "food"
    display_name = "Food"
    # ISSUE-33/38 (2026-11-11): the fields a scenario may change, declared
    # on the domain so the generic base path enforces the same allow-list
    # the food path does. See DomainModule.scenario_change_fields.
    scenario_change_fields = frozenset(REQUIRED_FOR_AVAILABILITY)

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
        # ISSUE-12(e): rejection, not a warning. Grep of every caller
        # (engine.run callers, examples, scenario_request) before
        # enforcing showed no caller depends on extra fields — the
        # only fields ever passed are the allowed ones — so rejecting
        # unknown fields cannot break a real caller, and a warning
        # would leave a misspelled field (e.g. "suply_...") silently
        # computing with the intended value missing.
        unknown = sorted(set(request) - set(ALLOWED_REQUEST_FIELDS))
        if unknown:
            problems.append("unknown request field(s): " + ", ".join(unknown))
        for field in REQUIRED_FOR_AVAILABILITY:
            value = request.get(field)
            if value is None:
                # ISSUE-15: imports/losses are in REQUIRED_FOR_AVAILABILITY,
                # so a missing field OR an explicit None is a missing
                # required field — never silently assumed 0.0. The
                # low-level food_availability() already refuses None/
                # missing optionals with INSUFFICIENT_INPUT by design;
                # this layer now agrees with it instead of papering
                # over it with an "assumed 0.0" assumption.
                problems.append(f"missing required field: {field}")
            else:
                problem = self._number_problem(field, value, positive=(field == "population"))
                if problem: problems.append(problem)
                elif field == "losses_fraction" and not 0.0 <= request[field] <= 1.0:
                    problems.append("losses_fraction must be between 0 and 1 inclusive")
                # ISSUE-12(d): population counts people, so it must be
                # a whole number. Booleans are already rejected by
                # _number_problem; a fractional float (1000.5) is
                # rejected here. An integer-valued float (1000.0) is
                # accepted, and the check is tolerance-based, not
                # float.is_integer(): a snapshot-derived population
                # such as 8.2e9 arrives as 8199999999.999999 through
                # float multiplication, which is a whole number
                # within float error and must not be rejected.
                elif field == "population" and not math.isclose(
                        float(value), round(float(value)),
                        rel_tol=1e-9, abs_tol=1e-6):
                    problems.append("field population must be a whole number")
        if "source_ids" in request and (not isinstance(request["source_ids"], list) or any(not isinstance(x, str) or not x.strip() for x in request["source_ids"])):
            problems.append("source_ids must be a list of non-empty strings")
        # ISSUE-21 (2026-11-11): scenario_assumptions is a list of
        # strings. Unvalidated, a string was char-split by list()
        # in calculate() ("abc" -> ['a', 'b', 'c']) and a non-iterable
        # (42) raised TypeError there instead of failing validation.
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
                "assumptions": assumptions, "required_fields": list(REQUIRED_FOR_AVAILABILITY)}

    def calculate(self, request: dict[str, Any]) -> dict[str, Any]:
        # ISSUE-20 (2026-11-11): validate_inputs handles non-dicts, but
        # calculate then called request.get(...) on the failure path and
        # raised AttributeError for "x"/[...]/42/None. A non-dict input
        # is INSUFFICIENT_INPUT, never a crash — direct callers get the
        # same structured status the engine path gives.
        if not isinstance(request, dict):
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": ["request must be a dictionary"], "metrics": {}, "display_metrics": {},
                    "assumptions": [], "source_ids": [], "data_status": "unknown",
                    "limitations": ["Input validation failed; calculation was not performed."]}
        validation = self.validate_inputs(request)
        if not validation["ok"]:
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": validation["problems"], "metrics": {}, "display_metrics": {},
                    "assumptions": validation["assumptions"], "source_ids": request.get("source_ids", []),
                    "data_status": data_status_for(request.get("source_ids")),
                    "limitations": ["Input validation failed; calculation was not performed."]}
        assumptions = list(validation["assumptions"])
        assumptions.extend(request.get("scenario_assumptions", []))
        # ISSUE-15 (decision (b), 2026-11-11): the ISSUE-13 None -> 0.0
        # normalisation is REMOVED, in calculate() and in
        # engine/verification.py alike. It is unreachable through the
        # validated path — validate_inputs now fails a missing or
        # explicit-None imports/losses, so calculate() only runs when
        # both are stated numbers — and keeping it as a "defensive
        # backstop" for direct (unvalidated) callers would reintroduce
        # exactly the silent zero ISSUE-15 removes, one layer down:
        # a direct caller passing None would silently get the 0.0
        # answer instead of INSUFFICIENT_INPUT. Treating None as
        # missing everywhere is the consistent rule: the low-level
        # food_availability() already refuses None/missing optionals
        # with INSUFFICIENT_INPUT, and calculate() now agrees with it
        # instead of normalising around it. The ISSUE-13 tests that
        # pinned the normalisation are superseded (see
        # tests/test_issue12_13.py, Issue13NoneMismatchTest, and the
        # new tests/test_issue15_food_formula.py).
        return food_availability(
            population=request["population"],
            supply_kcal_per_capita_per_day=request["supply_kcal_per_capita_per_day"],
            requirement_kcal_per_capita_per_day=request["requirement_kcal_per_capita_per_day"],
            imports_kcal_per_capita_per_day=request["imports_kcal_per_capita_per_day"],
            losses_fraction=request["losses_fraction"],
            assumptions=assumptions,
            source_ids=request.get("source_ids", []),
        )

    def identify_constraints(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        req = request.get("requirement_kcal_per_capita_per_day") if isinstance(request, dict) else None
        return [c.to_dict() for c in default_food_constraints(req)]

    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]:
        return evaluate_food_result(result)

    def describe_uncertainty(self, result: dict[str, Any]) -> list[str]:
        return describe_food_uncertainty(result)

    def scenario_request(self, scenario: Scenario) -> dict[str, Any]:
        base = scenario.metadata.get("base_request")
        if not isinstance(base, dict):
            raise ValueError("Food scenario requires metadata.base_request with population, supply and requirement")
        request = dict(base)
        # ISSUE-33/38: the unknown-field check lives in the shared
        # DomainModule._check_scenario_changes, driven by this domain's
        # declared scenario_change_fields — one rule, not a second
        # food-only allow-list.
        self._check_scenario_changes(scenario)
        request.update(scenario.proposed_changes)
        # ISSUE-25 (2026-11-11): generic setdefault semantics — the base
        # request wins. Food used to overwrite geography/period with the
        # scenario's defaults ("unspecified") unconditionally, clobbering
        # a base request's real geography/period; the documented generic
        # convention (docs/ARCHITECTURE.md, "Scenario convention") says
        # proposed_changes override by name and says nothing about
        # geography/period being clobbered. With setdefault, a base
        # without them still gets the scenario's values.
        request.setdefault("geography", scenario.geography)
        request.setdefault("period", scenario.period)
        request.setdefault("scenario_id", scenario.scenario_id)
        request["scenario_assumptions"] = list(scenario.assumptions)
        return request

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        return super().run_scenario(scenario)


__all__ = ["FoodDomain"]
