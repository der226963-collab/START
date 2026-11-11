# ORIGINAL START code (2026-11-11) — LP cross-check for the verify step.
#
# A SECOND, INDEPENDENT check of MCTS candidates, against a JuMP+HiGHS
# LP solved from the spec. This file is deliberately NOT part of the
# standalone PlanningSearch module (verify.jl stays loadable on
# Distributions alone) and is NOT included by PlanningSearch.jl.
# Load order for a script that uses it:
#   include("PlanningSearch.jl"); using .PlanningSearch
#   include("verify_lp.jl")        # defines the functions below in Main
#   # (this file itself does `using JuMP, HiGHS`)
#
# Why a separate file: loading JuMP+HiGHS together with
# ModelingToolkit+DifferentialEquations OOM-kills this 6 GB VM
# (see spine.jl / spine_lp.jl), and the planning-search module was
# designed to stay standalone. The LP wiring therefore lives here
# and in a separate runner (run_verify_lp.jl), following the split-
# stage pattern already used for spine_lp.jl / spine_ode.jl.
#
# What it does, and what it does NOT do:
#  * verify_candidate_with_lp(candidate; spec) runs the existing
#    constraint verify FIRST (verify_candidate), then independently
#    solves the JuMP+HiGHS LP for the same spec, then compares the
#    candidate against the LP optimum.
#  * The LP is solved FROM THE SPEC (yields, water per ha, demand,
#    land/water limits) in two stages, exactly as in spine_lp.jl:
#    Stage 1 minimise total shortage; Stage 2 hold shortage at its
#    optimum and minimise production (waste). The candidate and the
#    MCTS search do not influence the LP model in any way.
#  * The LP cross-check is a BOUND check, not an equality check:
#    a candidate must not claim better than the LP optimum
#    (delivered above the optimum, shortage below the optimum,
#    production above the optimum production), and must respect the
#    spec's land/water budgets (the LP's own constraints,
#    re-applied to the candidate's claimed land/water). A feasible
#    but suboptimal candidate (delivered below the optimum) passes
#    the LP cross-check — verification is feasibility, not
#    optimality, and the constraint verify already passes such
#    candidates.
#  * Combined verdict: PASS only if BOTH the constraint verify and
#    the LP cross-check pass; FAIL if either fails; UNKNOWN if the
#    LP does not reach OPTIMAL in either stage or any value is
#    non-finite. Solver failure is NEVER a PASS.
#  * The LP check does NOT certify a candidate on its own. A
#    candidate counts as verified only when the combined verdict is
#    PASS *and* a human approved it (see verified_status in
#    verify.jl, which takes the combined verdict string). The
#    search itself can never produce that.

using JuMP, HiGHS

const LP_TOLERANCE = 0.02  # t / ha / m3 tolerance on LP bound checks

"""
    solve_food_lp_from_spec(spec::FoodPlanSpec)

Solve the synthetic 1-site 2-crop LP from the spec alone, in two
stages (minimise shortage, then minimise production at that
shortage), exactly as in spine_lp.jl. Returns a NamedTuple
`(status, delivered, shortage, production, land, water)` where
`status` is `:OPTIMAL` on success and the solver's termination
status otherwise (e.g. `:INFEASIBLE`); on a non-optimal outcome
the numeric fields are `NaN`. Never throws for a solver failure —
a failed solve is data, not a crash, and the caller turns it into
UNKNOWN.
"""
function solve_food_lp_from_spec(spec::FoodPlanSpec)
    try
        model = Model(HiGHS.Optimizer)
        set_silent(model)
        n = length(spec.demand)
        @variable(model, area[1:n] >= 0)
        @variable(model, prod[1:n] >= 0)
        @variable(model, short[1:n] >= 0)
        @constraint(model, prod .== spec.yields .* area)
        @constraint(model, prod .+ short .== spec.demand)
        @constraint(model, sum(area) <= spec.land_max)
        @constraint(model, sum(spec.water_per_ha .* area) <= spec.water_max)
        @objective(model, Min, sum(short))
        optimize!(model)
        if termination_status(model) != MOI.OPTIMAL
            return (status=termination_status(model),
                    delivered=NaN, shortage=NaN, production=NaN,
                    land=NaN, water=NaN)
        end
        shortage_opt = objective_value(model)
        @constraint(model, sum(short) == shortage_opt)
        @objective(model, Min, sum(prod))
        optimize!(model)
        if termination_status(model) != MOI.OPTIMAL
            return (status=termination_status(model),
                    delivered=NaN, shortage=NaN, production=NaN,
                    land=NaN, water=NaN)
        end
        return (status=:OPTIMAL,
                delivered=sum(value.(prod)), shortage=sum(value.(short)),
                production=sum(value.(prod)), land=sum(value.(area)),
                water=sum(spec.water_per_ha .* value.(area)))
    catch err
        # Solver error (e.g. an invalid spec) is a non-optimal
        # outcome, not a crash: report it so the caller can
        # return UNKNOWN instead of PASS.
        return (status=:ERROR, delivered=NaN, shortage=NaN,
                production=NaN, land=NaN, water=NaN)
    end
end

"""
    lp_cross_check(candidate::PlanningCandidate, lp;
                   spec::FoodPlanSpec=FoodPlanSpec(),
                   tolerance=LP_TOLERANCE)

Compare a candidate against an LP optimum (as returned by
solve_food_lp_from_spec) on delivered / shortage / production /
land / water. Bound checks only: the candidate must not claim
better than the optimum, and must respect the spec budgets.
Returns (status, checks) with status in "PASS" / "FAIL" /
"UNKNOWN". UNKNOWN when the LP did not reach OPTIMAL or any value
is non-finite — never PASS on solver failure.
"""
function lp_cross_check(candidate::PlanningCandidate, lp;
                        spec::FoodPlanSpec=FoodPlanSpec(),
                        tolerance::Float64=LP_TOLERANCE)
    if lp.status != :OPTIMAL
        # Solver did not reach an optimum: nothing can be compared.
        return (status="UNKNOWN",
                checks=["UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"])
    end
    values = [candidate.delivered, candidate.shortage,
              candidate.production, candidate.land_ha,
              candidate.water_m3, lp.delivered, lp.shortage,
              lp.production, lp.land, lp.water]
    if !all(isfinite.(values))
        return (status="UNKNOWN",
                checks=["UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"])
    end
    checks = String[]
    function check_one(constraint_id, operator, value, bound)
        status, _ = evaluate_constraint(constraint_id=constraint_id,
                                        operator=operator, value=value,
                                        bound=bound, tolerance=tolerance)
        push!(checks, status)
        return status
    end
    # Optimum bounds: the candidate must not claim better than the LP.
    check_one("lp-delivered-not-above-optimum", "<=",
              candidate.delivered, lp.delivered)
    check_one("lp-shortage-not-below-optimum", ">=",
              candidate.shortage, lp.shortage)
    check_one("lp-production-not-above-optimum", "<=",
              candidate.production, lp.production)
    # Resource budgets: the LP's own constraints, re-applied to the
    # candidate's claimed land/water.
    check_one("lp-land-within-budget", "<=", candidate.land_ha, spec.land_max)
    check_one("lp-water-within-budget", "<=", candidate.water_m3, spec.water_max)
    return (status=overall_status(checks), checks=checks)
end

"""
    verify_candidate_with_lp(candidate::PlanningCandidate;
                             spec::FoodPlanSpec=FoodPlanSpec())

Combined verify: (1) the existing constraint verify
(verify_candidate), then (2) an independent JuMP+HiGHS LP solved
from the spec, compared against the candidate by lp_cross_check.
Returns (status, constraint_status, lp_status, lp_optimum,
checks, needs_human_decision, verified_by_search=false).

status is PASS only if BOTH checks pass, FAIL if either fails,
UNKNOWN if the LP does not reach OPTIMAL or any value is
non-finite. This is a verdict, not an approval: even a PASS
verdict still needs a human decision (verified_status in
verify.jl: PASS + human approval).
"""
function verify_candidate_with_lp(candidate::PlanningCandidate;
                                  spec::FoodPlanSpec=FoodPlanSpec())
    # (1) Constraint verify first.
    constraint_verdict = verify_candidate(candidate; spec=spec)
    constraint_status = constraint_verdict.status

    # (2) Independent LP, solved from the spec alone.
    lp = solve_food_lp_from_spec(spec)
    lp_check = lp_cross_check(candidate, lp; spec=spec)
    lp_status = lp_check.status

    combined = overall_status([constraint_status, lp_status])
    return (status=combined, constraint_status=constraint_status,
            lp_status=lp_status,
            lp_optimum=(lp.status == :OPTIMAL ? lp : nothing),
            checks=vcat(constraint_verdict.checks, lp_check.checks),
            needs_human_decision=NEEDS_HUMAN_DECISION,
            verified_by_search=false)
end
