"""Nutrients domain: deterministic phosphorus and nitrogen balances.

One domain (``domain_id "nutrients"``) covering phosphorus AND
nitrogen — the two nutrients share one balance shape (inputs -
uptake - losses = soil change), one request shape, and one snapshot
source, so they are one module, not two; see
``domains/nutrients/schema.py`` for why the split was not taken.

Snapshot values (``data/real_planning_data.csv``, Planetary Health
Check 2025, PIK report): phosphorus application 18.2 Tg/yr,
phosphorus regional boundary 6.2 Tg/yr, nitrogen fixation 165 Tg/yr
("more than twice its boundary", high-risk zone, NO exact boundary
stored). Everything else is an explicit caller input.

Phosphorus is evaluated pass/fail against the stored 6.2 Tg/yr
boundary. Nitrogen is ALWAYS UNKNOWN — its constraint is
deliberately bound-less, and no value of nitrogen fixation can make
it PASS. The engine therefore reports PARTIALLY_VERIFIED for this
domain (no independent verifier exists for nutrients; that is
expected and honest, per docs/ARCHITECTURE.md "Adding a domain"
rule 5) — a completed calculation here is calculation_ok True with
verified False, not a failure.
"""
from __future__ import annotations
from typing import Any
import math
from domains.base import DomainModule
from domains.nutrients.schema import (
    ALLOWED_REQUEST_FIELDS,
    NITROGEN_FIELDS,
    NUMERIC_REQUEST_FIELDS,
    PHOSPHORUS_FIELDS,
)
from domains.nutrients.balance import (
    default_nutrient_constraints,
    nutrient_balance,
    phosphorus_excess_and_ratio,
    stored_phosphorus_boundary,
)
from domains.nutrients.evaluation import (
    evaluate_nutrients_result,
    describe_nutrients_uncertainty,
)
from domains.food.production import data_status_for
from contracts.statuses import CalculationStatus
from contracts.scenarios import Scenario, ScenarioResult


class NutrientsDomain(DomainModule):
    domain_id = "nutrients"
    display_name = "Nutrients (phosphorus and nitrogen)"
    # ISSUE-33/38 (2026-11-11): the numeric fields a scenario may
    # change, declared on the domain so the generic base path
    # enforces the same allow-list the domain does. See
    # DomainModule.scenario_change_fields.
    scenario_change_fields = frozenset(NUMERIC_REQUEST_FIELDS)
    # ISSUE-34 (2026-11-13): the non-numeric fields a scenario may
    # change (str, or list[str] for source_ids). The base class
    # enforces this by value shape in _check_scenario_changes; a
    # non-listed non-numeric change raises ValueError, exactly as
    # for numeric changes.
    scenario_non_numeric_change_fields = frozenset({"source_ids", "geography", "period"})

    @staticmethod
    def _number_problem(field: str, value: Any) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"field {field} must be a number (booleans are not accepted)"
        if not math.isfinite(value):
            return f"field {field} must be finite"
        if value < 0:
            return f"field {field} must be non-negative"
        return None

    def validate_inputs(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "problems": ["request must be a dictionary"], "warnings": [], "assumptions": []}
        problems, warnings, assumptions = [], [], []
        # ISSUE-12(e): rejection, not a warning — a misspelled field
        # must surface as a problem, never be silently ignored while
        # the correctly-spelled value is missing.
        unknown = sorted(set(request) - set(ALLOWED_REQUEST_FIELDS))
        if unknown:
            problems.append("unknown request field(s): " + ", ".join(unknown))

        # Per-nutrient groups: a nutrient is stated iff its input
        # field (applied / fixation) is present and not None. A
        # stated nutrient requires its uptake AND losses, stated as
        # numbers — missing or explicit None is a missing required
        # field, never silently zero (ISSUE-15 rule, same as food
        # imports/losses). An uptake/losses without its input field
        # is a half-stated balance: a problem, not ignored. A request
        # stating neither nutrient states nothing to calculate.
        p_stated = request.get("phosphorus_applied_tg_per_year") is not None
        n_stated = request.get("nitrogen_fixation_tg_per_year") is not None
        if not p_stated and not n_stated:
            problems.append(
                "at least one nutrient must be stated: "
                "phosphorus_applied_tg_per_year or nitrogen_fixation_tg_per_year")
        for fields, stated in ((PHOSPHORUS_FIELDS, p_stated), (NITROGEN_FIELDS, n_stated)):
            input_field, uptake_field, losses_field = fields
            if stated:
                for field in (uptake_field, losses_field):
                    if request.get(field) is None:
                        problems.append(f"missing required field: {field}")
            else:
                for field in (uptake_field, losses_field):
                    if request.get(field) is not None:
                        problems.append(
                            f"field {field} supplied without {input_field}")
        for field in NUMERIC_REQUEST_FIELDS:
            value = request.get(field)
            if value is None:
                continue
            problem = self._number_problem(field, value)
            if problem:
                problems.append(problem)
        # Wrong-bound detection (ISSUE-01 rule): a caller-supplied
        # phosphorus boundary must equal the stored snapshot bound
        # exactly; a differing value is refused, never applied.
        if request.get("phosphorus_boundary_tg_per_year") is not None:
            try:
                stored = stored_phosphorus_boundary()
            except Exception as exc:
                problems.append(
                    f"stored phosphorus boundary could not be loaded, so a caller-supplied "
                    f"boundary cannot be checked: {type(exc).__name__}: {exc}")
            else:
                supplied = request["phosphorus_boundary_tg_per_year"]
                if isinstance(supplied, (int, float)) and not isinstance(supplied, bool) \
                        and math.isfinite(supplied) and float(supplied) != float(stored):
                    problems.append(
                        f"caller-supplied phosphorus boundary {supplied} conflicts with the "
                        f"stored limit {stored} (snapshot v0.3.1-2026-11-04). "
                        f"Refusing to check against a contradicted bound.")
        if "source_ids" in request and (not isinstance(request["source_ids"], list) or any(not isinstance(x, str) or not x.strip() for x in request["source_ids"])):
            problems.append("source_ids must be a list of non-empty strings")
        # ISSUE-21 (food): scenario_assumptions is a list of strings.
        if "scenario_assumptions" in request:
            value = request["scenario_assumptions"]
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                problems.append("scenario_assumptions must be a list of strings")
        for field in ("geography", "period"):
            if field in request and not isinstance(request[field], str):
                problems.append(f"{field} must be a string identifier")
        return {"ok": not problems, "problems": problems, "warnings": warnings,
                "assumptions": assumptions,
                "required_fields": list(NUMERIC_REQUEST_FIELDS)}

    def calculate(self, request: dict[str, Any]) -> dict[str, Any]:
        # ISSUE-20 (food): a non-dict input is INSUFFICIENT_INPUT,
        # never a crash.
        if not isinstance(request, dict):
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": ["request must be a dictionary"], "metrics": {}, "display_metrics": {},
                    "assumptions": [], "source_ids": [], "data_status": "unknown",
                    "limitations": ["Input validation failed; calculation was not performed."]}
        validation = self.validate_inputs(request)
        if not validation["ok"]:
            return {"calculation_status": CalculationStatus.INSUFFICIENT_INPUT.value,
                    "missing_fields": validation["problems"], "metrics": {}, "display_metrics": {},
                    "assumptions": validation["assumptions"],
                    "source_ids": request.get("source_ids", []) if isinstance(request.get("source_ids"), list) else [],
                    "data_status": "unknown",
                    "limitations": ["Input validation failed; calculation was not performed."]}
        assumptions = list(validation["assumptions"])
        assumptions.extend(request.get("scenario_assumptions", []))
        source_ids = request.get("source_ids", [])
        boundary = request.get("phosphorus_boundary_tg_per_year")
        if boundary is None:
            boundary = stored_phosphorus_boundary()
        metrics: dict[str, Any] = {}
        display: dict[str, Any] = {}
        limitations: list[str] = []
        missing: list[str] = []
        for nutrient, input_field in (
                ("phosphorus", "phosphorus_applied_tg_per_year"),
                ("nitrogen", "nitrogen_fixation_tg_per_year")):
            if request.get(input_field) is None:
                continue
            part = nutrient_balance(
                nutrient,
                applied_tg_per_year=request[input_field],
                uptake_tg_per_year=request[f"{nutrient}_uptake_tg_per_year"],
                losses_tg_per_year=request[f"{nutrient}_losses_tg_per_year"],
                assumptions=assumptions, source_ids=source_ids)
            if part["calculation_status"] != CalculationStatus.COMPLETED.value:
                # validate_inputs already passed, so this is
                # unreachable in practice; stay total anyway.
                return {**part, "assumptions": assumptions,
                        "source_ids": list(source_ids),
                        "limitations": part.get("limitations", [])}
            metrics.update(part["metrics"])
            display.update(part["display_metrics"])
            limitations.extend(part["limitations"])
            missing.extend(part.get("missing_fields", []))
        if "phosphorus_applied_tg_per_year" in metrics:
            excess, ratio = phosphorus_excess_and_ratio(
                metrics["phosphorus_applied_tg_per_year"], float(boundary))
            metrics["phosphorus_boundary_tg_per_year"] = float(boundary)
            metrics["phosphorus_excess_tg_per_year"] = excess
            metrics["phosphorus_ratio_to_boundary"] = ratio
            display["phosphorus_boundary_tg_per_year"] = round(float(boundary), 2)
            display["phosphorus_excess_tg_per_year"] = round(excess, 2)
            display["phosphorus_ratio_to_boundary"] = ratio
        if "nitrogen_fixation_tg_per_year" in metrics:
            metrics["nitrogen_boundary_tg_per_year"] = None
            display["nitrogen_boundary_tg_per_year"] = None
            assumptions.append(
                "Nitrogen has no stored boundary: the snapshot records fixation as "
                "more than twice its boundary but stores no exact value, so no "
                "nitrogen pass/fail is claimed.")
        # De-duplicate the shared limitations (each per-nutrient
        # balance repeats the aggregate warning).
        seen: set[str] = set()
        deduped = [x for x in limitations if not (x in seen or seen.add(x))]
        return {
            "calculation_status": CalculationStatus.COMPLETED.value,
            "missing_fields": missing, "metrics": metrics, "display_metrics": display,
            "assumptions": assumptions, "source_ids": list(source_ids),
            "data_status": data_status_for(source_ids),
            "limitations": deduped,
        }

    def identify_constraints(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        boundary = None
        if isinstance(request, dict):
            value = request.get("phosphorus_boundary_tg_per_year")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                boundary = float(value)
        geography = request.get("geography", "global") if isinstance(request, dict) else "global"
        period = request.get("period", "2025") if isinstance(request, dict) else "2025"
        return [c.to_dict() for c in default_nutrient_constraints(
            phosphorus_boundary=boundary, geography=geography, period=period)]

    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]:
        return evaluate_nutrients_result(result)

    def describe_uncertainty(self, result: dict[str, Any]) -> list[str]:
        return describe_nutrients_uncertainty(result)

    def scenario_request(self, scenario: Scenario) -> dict[str, Any]:
        base = scenario.metadata.get("base_request")
        if not isinstance(base, dict):
            raise ValueError("Nutrients scenario requires metadata.base_request with a nutrient input")
        request = dict(base)
        # ISSUE-33/38/34: the unknown-field checks live in the shared
        # DomainModule._check_scenario_changes, driven by this
        # domain's declared scenario_change_fields and
        # scenario_non_numeric_change_fields — one rule, not a second
        # domain-only allow-list. An explicit non-numeric change
        # (source_ids / geography / period) overrides the base
        # request via request.update below; a scenario's geography/
        # period DEFAULTS only fill a base that lacks them (ISSUE-25).
        self._check_scenario_changes(scenario)
        request.update(scenario.proposed_changes)
        request.setdefault("geography", scenario.geography)
        request.setdefault("period", scenario.period)
        if scenario.source_ids:
            request.setdefault("source_ids", list(scenario.source_ids))
        request.setdefault("scenario_id", scenario.scenario_id)
        request["scenario_assumptions"] = list(scenario.assumptions)
        return request

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        return super().run_scenario(scenario)


__all__ = ["NutrientsDomain"]
