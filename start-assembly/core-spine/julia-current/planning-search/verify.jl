# ORIGINAL START code (2026-11-11) — the separate verify step.
#
# The evaluator, unit registry, aggregation and schema-version
# check live in julia-current/units.jl — the one canonical
# implementation shared by all Julia evaluators, included by
# PlanningSearch.jl before this file. This file keeps only the
# verify step itself. The old unit-free evaluate_constraint /
# overall_status defined here are removed.
#
# Rules (spine.jl / v0.3.2 ISSUE-02, ISSUE-16, plus Eric's
# 2026-11-11 test-vector decisions):
#  * empty checks -> NOT_CHECKED, never PASS
#  * FAIL wins; then INCOMPLETE, then UNKNOWN, then
#    NOT_CHECKED (Python overall_from_checks order); otherwise PASS
#  * non-finite value/bound -> UNKNOWN, never PASS
#  * empty constraint_id -> UNKNOWN
#  * unknown / incompatible units -> UNKNOWN, never PASS
#    (value_unit / bound_unit are required keywords on
#    evaluate_constraint — there is no unit-free comparison)
#  * land/water use a 1e-6 tolerance (not zero): LP solutions
#    come back with floating-point noise — see below. This
#    tolerance is UNCHANGED by the unit-registry work.
#
# A search result is a CANDIDATE only. verify_candidate returns a
# verdict; it does NOT mark the candidate verified. A candidate
# counts as verified only when the verdict is PASS *and* a human
# has approved it (see verified_status). The search itself can
# never produce that.

"""
    verify_candidate(candidate; spec=FoodPlanSpec())

Check a candidate against the planning constraints (land, water,
delivered + shortage == total demand, no overproduction) using
evaluate_constraint, with explicit units (land ha, water m3,
tonnages t). Returns (status, checks, needs_human_decision,
verified_by_search=false). This is a verdict, not an approval:
even a PASS verdict still needs a human decision, and it does not
change candidate.verified.
"""
function verify_candidate(candidate::PlanningCandidate;
                          spec::FoodPlanSpec=FoodPlanSpec())
    checks = String[]
    function check_one(constraint_id, operator, value, bound;
                       value_unit, bound_unit, tolerance=0.0)
        status, _ = evaluate_constraint(constraint_id=constraint_id,
                                        operator=operator, value=value,
                                        bound=bound, tolerance=tolerance,
                                        value_unit=value_unit,
                                        bound_unit=bound_unit)
        push!(checks, status)
        return status
    end
    # Land/water use a 1e-6 tolerance (not zero): LP solutions come
    # back with floating-point noise — e.g. the low-yield scenario's
    # water total is 100,000.00000000001 m3 against a 100,000 m3
    # budget, a 1e-11 artefact that must not fail an otherwise exact
    # candidate. 1e-6 ha / m3 is physically meaningless, and an
    # over-budget candidate (e.g. 112,000 m3) still fails by far.
    check_one("land", "<=", candidate.land_ha, spec.land_max;
              value_unit="ha", bound_unit="ha", tolerance=1e-6)
    check_one("water", "<=", candidate.water_m3, spec.water_max;
              value_unit="m3", bound_unit="m3", tolerance=1e-6)
    check_one("delivered-plus-shortage", "==",
              candidate.delivered + candidate.shortage,
              sum(spec.demand);
              value_unit="t", bound_unit="t", tolerance=1e-6)
    check_one("production-equals-delivered", "==",
              candidate.production, candidate.delivered;
              value_unit="t", bound_unit="t", tolerance=1e-6)
    check_one("shortage-nonnegative", ">=", candidate.shortage, 0.0;
              value_unit="t", bound_unit="t")
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
