# ORIGINAL START code (2026-11-11) — the separate verify step.
#
# This mirrors spine.jl's evaluate_constraint / overall_status
# (same rules, same vocabulary) in a light form that does not load
# JuMP / ModelingToolkit / DifferentialEquations, so the
# planning-search module stays standalone on Distributions alone.
# The LP cross-check is the separate verify_lp.jl (JuMP+HiGHS),
# not part of this module: it lives in its own file and runner so
# this file stays loadable on Distributions alone.
#
# Rules (spine.jl / v0.3.2 ISSUE-02, ISSUE-16):
#  * empty checks -> NOT_CHECKED, never PASS
#  * FAIL wins; INCOMPLETE / UNKNOWN / NOT_CHECKED -> UNKNOWN
#    (consumer verdict: indeterminate); otherwise PASS
#  * non-finite value/bound -> UNKNOWN, never PASS
#  * empty constraint_id -> UNKNOWN
#
# A search result is a CANDIDATE only. verify_candidate returns a
# verdict; it does NOT mark the candidate verified. A candidate
# counts as verified only when the verdict is PASS *and* a human
# has approved it (see verified_status). The search itself can
# never produce that.

"""Evaluate one constraint. Non-finite value/bound -> UNKNOWN, never PASS.
Empty constraint_id -> UNKNOWN. Unsupported operator -> UNKNOWN."""
function evaluate_constraint(; constraint_id, operator, value, bound,
                               tolerance=0.0)
    if isempty(constraint_id)
        return ("UNKNOWN", "empty constraint_id")
    end
    if !isfinite(value) || !isfinite(bound)
        return ("UNKNOWN", "non-finite value or bound")
    end
    ok = if operator == "<="
        value <= bound + tolerance
    elseif operator == ">="
        value >= bound - tolerance
    elseif operator == "=="
        abs(value - bound) <= tolerance
    else
        return ("UNKNOWN", "unsupported operator: $operator")
    end
    return (ok ? "PASS" : "FAIL", "OK")
end

"""Aggregate statuses. Empty -> NOT_CHECKED (never PASS). FAIL wins.
INCOMPLETE / UNKNOWN / NOT_CHECKED -> UNKNOWN (consumer verdict:
indeterminate). Otherwise PASS."""
function overall_status(statuses)
    isempty(statuses) && return "NOT_CHECKED"
    "FAIL" in statuses && return "FAIL"
    any(s in statuses for s in ("INCOMPLETE", "UNKNOWN", "NOT_CHECKED")) &&
        return "UNKNOWN"
    return "PASS"
end

"""
    verify_candidate(candidate; spec=FoodPlanSpec())

Check a candidate against the planning constraints (land, water,
delivered + shortage == total demand, no overproduction) using
evaluate_constraint. Returns (status, checks, needs_human_decision,
verified_by_search=false). This is a verdict, not an approval:
even a PASS verdict still needs a human decision, and it does not
change candidate.verified.
"""
function verify_candidate(candidate::PlanningCandidate;
                          spec::FoodPlanSpec=FoodPlanSpec())
    checks = String[]
    function check_one(constraint_id, operator, value, bound; tolerance=0.0)
        status, _ = evaluate_constraint(constraint_id=constraint_id,
                                        operator=operator, value=value,
                                        bound=bound, tolerance=tolerance)
        push!(checks, status)
        return status
    end
    # Land/water use a 1e-6 tolerance (not zero): LP solutions come
    # back with floating-point noise — e.g. the low-yield scenario's
    # water total is 100,000.00000000001 m3 against a 100,000 m3
    # budget, a 1e-11 artefact that must not fail an otherwise exact
    # candidate. 1e-6 ha / m3 is physically meaningless, and an
    # over-budget candidate (e.g. 112,000 m3) still fails by far.
    check_one("land", "<=", candidate.land_ha, spec.land_max; tolerance=1e-6)
    check_one("water", "<=", candidate.water_m3, spec.water_max; tolerance=1e-6)
    check_one("delivered-plus-shortage", "==",
              candidate.delivered + candidate.shortage,
              sum(spec.demand); tolerance=1e-6)
    check_one("production-equals-delivered", "==",
              candidate.production, candidate.delivered; tolerance=1e-6)
    check_one("shortage-nonnegative", ">=", candidate.shortage, 0.0)
    return (status=overall_status(checks), checks=checks,
            needs_human_decision=NEEDS_HUMAN_DECISION,
            verified_by_search=false)
end

"""
    verified_status(candidate, verdict, human_approved::Bool) :: Bool

A candidate counts as verified only when the separate verify step
returned PASS *and* a human approved it. A search result alone
(never verified by the search), a non-PASS verdict, or a PASS
verdict without human approval are all NOT verified.
"""
function verified_status(::PlanningCandidate, verdict::String,
                         human_approved::Bool)
    return verdict == "PASS" && human_approved
end
