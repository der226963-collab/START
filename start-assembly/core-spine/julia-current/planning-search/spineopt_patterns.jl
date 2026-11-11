# ORIGINAL START code (2026-11-11) — SpineOpt planning patterns,
# rebuilt as original Julia. INSPIRATION-REBUILD of
# spine-tools/SpineOpt.jl (Module 18); NO SpineOpt code copied,
# no SpineOpt dependency, no SpineInterface, no Spine DB.
#
# Inspiration source (audit only — see
# source-audit/REPLACEMENTS_AUDIT.md §6 and
# source-audit/ALL_CANDIDATES_BORROWING_PLAN.md):
#   spine-tools/SpineOpt.jl — DROP as the Module 18 engine.
#   Energy-only JuMP application, redundant with the already
#   assembled JuMP 1.32.1 + HiGHS 1.26.1, heavier via the Spine
#   DB stack, copyleft with a GPL-3.0 LICENSE file vs
#   LGPL-3.0-or-later README/headers contradiction, and a
#   monolithic run_spineopt() build-solve-write call with no
#   separate verify step and no human gate. The audit worker read
#   temporal_structure.jl, stochastic_structure.jl, benders.jl,
#   constraint_nodal_balance.jl and run_spineopt_mga.jl in full
#   to understand the PATTERNS; nothing was copied from them.
#   What is rebuilt here, from the pattern descriptions only,
#   on the synthetic 1-site 2-crop domain already in
#   planning-search/ (never a real region):
#     (a) rolling-horizon / representative-period time slices
#     (b) stochastic scenario/path structure (normal vs low-yield)
#     (c) a Benders master/subproblem split with
#         objective-upperbound cuts
#     (d) the nodal balance equation, generalised to any
#         flow-conservation constraint
#     (e) Modelling-to-Generate-Alternatives (MGA) for HUMAN choice
#
# Load order (this file is deliberately NOT included by
# PlanningSearch.jl — it loads JuMP+HiGHS, so it lives apart,
# exactly like verify_lp.jl):
#   include("PlanningSearch.jl"); using .PlanningSearch
#   include("verify_lp.jl")        # solve_food_lp_from_spec,
#                                   # verify_candidate_with_lp
#   include("spineopt_patterns.jl")
# Runner: run_spineopt_patterns.jl; tests:
# test/spineopt_patterns.jl (standalone script, not included
# from test/runtests.jl, so the standalone tests stay JuMP-free).
#
# GOVERNANCE (non-negotiable, same as the rest of planning-search):
#  * Every plan a pattern produces is a CANDIDATE only
#    (`verified=false`, `status="CANDIDATE"`,
#    `needs_human_decision=true`). Nothing here verifies its own
#    output: candidates go through the separate verify step
#    (constraint verify + JuMP+HiGHS LP cross-check in
#    verify_lp.jl) and a plan still needs a human decision.
#  * The Benders split runs INSIDE that flow: it proposes a
#    candidate, and the test (and the runner) verify it with
#    verify_candidate_with_lp. There is no monolithic
#    run-solve-write call anywhere in this file.
#  * MGA surfaces alternatives for HUMAN choice and never
#    auto-selects: MGAResult.selected is always `nothing` at
#    creation, and choose_alternative requires
#    human_approved=true or throws.
#  * Wire format stays JSON: all results are plain structs of
#    numbers/strings/vectors, no Spine DB, no pickle.

using JuMP, HiGHS

if !isdefined(Main, :solve_food_lp_from_spec) ||
   !isdefined(Main, :verify_candidate_with_lp)
    error("spineopt_patterns.jl requires verify_lp.jl to be included " *
          "first (after PlanningSearch.jl): it reuses " *
          "solve_food_lp_from_spec / verify_candidate_with_lp.")
end

# ------------------------------------------------------------------
# Shared LP builder: the synthetic 1-site 2-crop model, solved
# from the spec alone. Same two stages as verify_lp.jl
# (minimise shortage, then minimise production at that shortage),
# but this helper also returns the areas, which the patterns need
# to build PlanningCandidates. Cross-checked against
# solve_food_lp_from_spec in the tests.
# ------------------------------------------------------------------

"""
    build_food_model(spec::FoodPlanSpec)

Build (but do not solve) the 2-crop LP for `spec`: areas,
production and shortage per crop, production == yield * area,
production + shortage == demand, land and water budgets.
Returns `(model, area, prod, short)`. The caller sets the
objective and solves.
"""
function build_food_model(spec::FoodPlanSpec)
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
    return (model=model, area=area, prod=prod, short=short)
end

"""
    solve_direct_lp(spec::FoodPlanSpec)

Solve the synthetic LP from the spec alone, in two stages
(minimise shortage, then minimise production at that shortage),
returning `(status, areas, delivered, shortage, production,
land, water)`. `status` is `:OPTIMAL` on success and the
solver's termination status otherwise (numeric fields `NaN`
then). Never throws for a solver failure — a failed solve is
data, and the caller turns it into UNKNOWN / an error, never
a PASS.
"""
function solve_direct_lp(spec::FoodPlanSpec)
    try
        built = build_food_model(spec)
        model, area, prod, short = built.model, built.area, built.prod, built.short
        @objective(model, Min, sum(short))
        optimize!(model)
        if termination_status(model) != MOI.OPTIMAL
            return (status=termination_status(model), areas=fill(NaN, length(spec.demand)),
                    delivered=NaN, shortage=NaN, production=NaN, land=NaN, water=NaN)
        end
        shortage_opt = objective_value(model)
        @constraint(model, sum(short) == shortage_opt)
        @objective(model, Min, sum(prod))
        optimize!(model)
        if termination_status(model) != MOI.OPTIMAL
            return (status=termination_status(model), areas=fill(NaN, length(spec.demand)),
                    delivered=NaN, shortage=NaN, production=NaN, land=NaN, water=NaN)
        end
        areas = value.(area)
        return (status=:OPTIMAL, areas=areas,
                delivered=sum(value.(prod)), shortage=sum(value.(short)),
                production=sum(value.(prod)), land=sum(areas),
                water=sum(spec.water_per_ha .* areas))
    catch err
        return (status=:ERROR, areas=fill(NaN, length(spec.demand)),
                delivered=NaN, shortage=NaN, production=NaN, land=NaN, water=NaN)
    end
end

"""Build a CANDIDATE-only PlanningCandidate from areas (wheat, potato)."""
function candidate_from_areas(spec::FoodPlanSpec, areas::AbstractVector)
    return PlanningSearch.candidate_from_state(spec, (areas[1], areas[2], 2))
end

# ------------------------------------------------------------------
# (a) Rolling-horizon / representative-period time slices.
#
# The annual problem is split into `nperiods` representative
# periods. The shared annual water budget is split equally
# across periods (water is the binding shared resource); land
# is reusable each period, so each slice keeps the full land
# budget; demand repeats each period (each period must feed
# the same demand). Each slice is solved by its own direct LP
# and is its own candidate — a slice is never verified by this
# code, only by the separate verify step.
# ------------------------------------------------------------------

"""
    TimeSlice

One representative period: an id, a human-readable label, a
weight in the horizon aggregate, and the period's own spec
(same crops, same demand, its share of the water budget).
"""
struct TimeSlice
    id::String
    label::String
    weight::Float64
    spec::FoodPlanSpec
end

"""
    representative_slices(spec=FoodPlanSpec(); nperiods=3)

Split the annual problem into `nperiods` representative
periods (see the section header for the split rule).
`nperiods < 1` throws ArgumentError.
"""
function representative_slices(spec::FoodPlanSpec=FoodPlanSpec(); nperiods::Int=3)
    nperiods >= 1 || throw(ArgumentError("nperiods must be >= 1"))
    return [TimeSlice("slice-$i", "period $i of $nperiods", 1.0,
                      FoodPlanSpec(spec.yields, spec.water_per_ha, spec.demand,
                                   spec.land_max, spec.water_max / nperiods,
                                   spec.wheat_options, spec.potato_options))
            for i in 1:nperiods]
end

"""
    TimeSlicedPlan

A rolling-horizon plan: one CANDIDATE-only candidate per slice
plus the weight-aggregated delivered/shortage totals.
`verified` is always false, `status` always "CANDIDATE".
"""
struct TimeSlicedPlan
    slices::Vector{TimeSlice}
    candidates::Vector{PlanningCandidate}
    delivered::Float64
    shortage::Float64
    total_weight::Float64
    verified::Bool
    needs_human_decision::Bool
    status::String
end

"""
    rolling_horizon_plan(spec=FoodPlanSpec(); nperiods=3)

Solve each representative period's LP and return a
TimeSlicedPlan (candidates only). Throws if any slice LP does
not reach OPTIMAL — a failed slice is an error, never a
silent PASS.
"""
function rolling_horizon_plan(spec::FoodPlanSpec=FoodPlanSpec(); nperiods::Int=3)
    slices = representative_slices(spec; nperiods=nperiods)
    candidates = PlanningCandidate[]
    delivered = 0.0
    shortage = 0.0
    total_weight = 0.0
    for s in slices
        lp = solve_direct_lp(s.spec)
        lp.status == :OPTIMAL ||
            error("time slice $(s.id): LP did not reach OPTIMAL (status $(lp.status))")
        push!(candidates, candidate_from_areas(s.spec, lp.areas))
        delivered += s.weight * lp.delivered
        shortage += s.weight * lp.shortage
        total_weight += s.weight
    end
    return TimeSlicedPlan(slices, candidates, delivered, shortage, total_weight,
                          false, NEEDS_HUMAN_DECISION, "CANDIDATE")
end

# ------------------------------------------------------------------
# (b) Stochastic scenario / path structure.
#
# At least two scenarios over the same domain. The built-in pair
# is normal yield vs low yield (yields scaled by
# `low_yield_factor`, default 0.8x). Each scenario is solved by
# its own direct LP and is its own candidate; the plan reports
# the probability-weighted expected delivered/shortage. This is
# a scenario fan, not a here-and-now first-stage decision: no
# single "expected" plan is produced, because a plan that is
# optimal on average need not be feasible in any one scenario.
# ------------------------------------------------------------------

"""
    StochasticScenario

One scenario: an id, a label, a probability (0..1), and the
scenario's own spec (same domain, scenario yields).
"""
struct StochasticScenario
    id::String
    label::String
    probability::Float64
    spec::FoodPlanSpec
end

"""
    two_scenarios(spec=FoodPlanSpec(); low_yield_factor=0.8, p_normal=0.7)

The built-in scenario pair: normal yield (probability
`p_normal`) and low yield (yields scaled by
`low_yield_factor`, probability `1 - p_normal`).
"""
function two_scenarios(spec::FoodPlanSpec=FoodPlanSpec();
                       low_yield_factor::Float64=0.8, p_normal::Float64=0.7)
    (0.0 <= p_normal <= 1.0) ||
        throw(ArgumentError("p_normal must be in [0, 1]"))
    (0.0 < low_yield_factor <= 1.0) ||
        throw(ArgumentError("low_yield_factor must be in (0, 1]"))
    low_spec = FoodPlanSpec(spec.yields .* low_yield_factor, spec.water_per_ha,
                            spec.demand, spec.land_max, spec.water_max,
                            spec.wheat_options, spec.potato_options)
    return [StochasticScenario("normal", "normal yield", p_normal, spec),
            StochasticScenario("low-yield", "low yield ($(low_yield_factor)x)",
                               1.0 - p_normal, low_spec)]
end

"""
    StochasticPlan

A scenario-fan plan: one CANDIDATE-only candidate per scenario
plus the probability-weighted expected delivered/shortage.
`verified` is always false, `status` always "CANDIDATE".
"""
struct StochasticPlan
    scenarios::Vector{StochasticScenario}
    candidates::Vector{PlanningCandidate}
    expected_delivered::Float64
    expected_shortage::Float64
    verified::Bool
    needs_human_decision::Bool
    status::String
end

"""
    stochastic_plan(scenarios::Vector{StochasticScenario})
    stochastic_plan(spec=FoodPlanSpec(); low_yield_factor=0.8, p_normal=0.7)

Solve each scenario's LP and return a StochasticPlan
(candidates only, with expected totals). Probabilities must
each be in [0, 1] and sum to 1 (within 1e-9), or this throws
ArgumentError. Throws if any scenario LP does not reach
OPTIMAL.
"""
function stochastic_plan(scenarios::Vector{StochasticScenario})
    isempty(scenarios) && throw(ArgumentError("at least one scenario is required"))
    for s in scenarios
        (0.0 <= s.probability <= 1.0) ||
            throw(ArgumentError("scenario $(s.id): probability $(s.probability) not in [0, 1]"))
    end
    abs(sum(s.probability for s in scenarios) - 1.0) <= 1e-9 ||
        throw(ArgumentError("scenario probabilities must sum to 1"))
    candidates = PlanningCandidate[]
    expected_delivered = 0.0
    expected_shortage = 0.0
    for s in scenarios
        lp = solve_direct_lp(s.spec)
        lp.status == :OPTIMAL ||
            error("scenario $(s.id): LP did not reach OPTIMAL (status $(lp.status))")
        push!(candidates, candidate_from_areas(s.spec, lp.areas))
        expected_delivered += s.probability * lp.delivered
        expected_shortage += s.probability * lp.shortage
    end
    return StochasticPlan(scenarios, candidates, expected_delivered, expected_shortage,
                          false, NEEDS_HUMAN_DECISION, "CANDIDATE")
end

stochastic_plan(spec::FoodPlanSpec=FoodPlanSpec(); low_yield_factor::Float64=0.8,
                p_normal::Float64=0.7) =
    stochastic_plan(two_scenarios(spec; low_yield_factor=low_yield_factor,
                                  p_normal=p_normal))

# ------------------------------------------------------------------
# (c) Benders master/subproblem split with objective-upperbound cuts.
#
# Master (first stage): choose areas, with land/water budgets,
# per-crop no-overproduction caps (yield * area <= demand — the
# same rule as the planning domain), and a proxy variable theta
# for the subproblem cost (total shortage). Objective: minimise
# theta. Initially there are no cuts, so theta >= 0 only.
# Subproblem (second stage): given the master's areas, the
# shortage is delivered_i = min(yield_i * area_i, demand_i)
# per crop — this 2-crop subproblem has a closed form, so it is
# evaluated directly rather than as a second JuMP model, and
# the cut is derived from its subgradient (see below). In a
# larger model the subproblem would be its own LP and the cut
# would come from its duals; the shape — master proposes,
# subproblem evaluates, cut returns — is the same.
# Cut at areas a: shortage(a) = sum(max(demand_i -
# yield_i*a_i, 0)) is piecewise-linear convex in a, with
# subgradient g_i = -yield_i where the crop is under-delivered
# and 0 where it already meets demand. The cut added to the
# master is theta >= shortage(a) + g . (area - a).
# The loop stops when the best subproblem value found so far
# (upper bound) minus the master's theta (lower bound) is
# within tolerance. The result is a CANDIDATE only: the test
# and the runner verify it with verify_candidate_with_lp, and
# it must agree with the direct LP optimum.
# ------------------------------------------------------------------

"""
    subproblem_shortage(spec::FoodPlanSpec, areas)

The Benders subproblem, evaluated at `areas`: per-crop
delivered is min(yield * area, demand) and shortage is the
unmet demand. Returns `(shortage, delivered,
per_crop_shortage, per_crop_delivered)`.
"""
function subproblem_shortage(spec::FoodPlanSpec, areas::AbstractVector)
    delivered_i = min.(spec.yields .* areas, spec.demand)
    shortage_i = spec.demand .- delivered_i
    return (shortage=sum(shortage_i), delivered=sum(delivered_i),
            per_crop_shortage=shortage_i, per_crop_delivered=delivered_i)
end

"""
    BendersResult

The outcome of the Benders split: the best areas found, the
CANDIDATE-only candidate built from them, the iteration count,
the final lower bound (master theta) and upper bound (best
subproblem shortage), the cuts added, and whether the bounds
met. `verified` is always false, `status` always "CANDIDATE".
"""
struct BendersResult
    areas::Vector{Float64}
    candidate::PlanningCandidate
    delivered::Float64
    shortage::Float64
    production::Float64
    land::Float64
    water::Float64
    iterations::Int
    lower_bound::Float64
    upper_bound::Float64
    cuts::Vector{NamedTuple}
    converged::Bool
    verified::Bool
    needs_human_decision::Bool
    status::String
end

"""
    benders_solve(spec=FoodPlanSpec(); tolerance=1e-6, max_iterations=20)

Run the Benders master/subproblem loop (see the section
header). Returns a BendersResult whose candidate is a
CANDIDATE only — it still needs the separate verify step
plus human approval, and the caller checks it against the
direct LP optimum. `converged` is false if the bounds did
not meet within `max_iterations`; the best candidate found
is still returned, unverified.
"""
function benders_solve(spec::FoodPlanSpec=FoodPlanSpec();
                       tolerance::Float64=1e-6, max_iterations::Int=20)
    max_iterations >= 1 || throw(ArgumentError("max_iterations must be >= 1"))
    n = length(spec.demand)
    cuts = NamedTuple[]
    best_ub = Inf
    best_areas = zeros(n)
    best_sub = subproblem_shortage(spec, best_areas)
    lower_bound = 0.0
    iterations = 0
    converged = false
    for iter in 1:max_iterations
        iterations = iter
        # --- Master: minimise theta over areas + cuts so far. ---
        model = Model(HiGHS.Optimizer)
        set_silent(model)
        @variable(model, area[1:n] >= 0)
        @variable(model, theta >= 0)
        @constraint(model, spec.yields .* area .<= spec.demand)  # no overproduction
        @constraint(model, sum(area) <= spec.land_max)
        @constraint(model, sum(spec.water_per_ha .* area) <= spec.water_max)
        for c in cuts
            @constraint(model, theta >= c.intercept + sum(c.gradient .* area))
        end
        @objective(model, Min, theta)
        optimize!(model)
        termination_status(model) == MOI.OPTIMAL ||
            error("Benders master (iteration $iter) did not reach OPTIMAL " *
                  "(status $(termination_status(model)))")
        lower_bound = objective_value(model)
        a = value.(area)
        # --- Subproblem: evaluate the master's areas. ---
        sub = subproblem_shortage(spec, a)
        if sub.shortage < best_ub
            best_ub = sub.shortage
            best_areas = copy(a)
            best_sub = sub
        end
        if best_ub - lower_bound <= tolerance
            converged = true
            break
        end
        # --- Cut at a, from the subproblem subgradient. ---
        gradient = [spec.yields[i] * a[i] < spec.demand[i] - 1e-9 ?
                    -spec.yields[i] : 0.0 for i in 1:n]
        intercept = sub.shortage - sum(gradient .* a)
        push!(cuts, (intercept=intercept, gradient=gradient, at_areas=copy(a)))
    end
    totals = plan_totals_for_areas(spec, best_areas)
    candidate = candidate_from_areas(spec, best_areas)
    return BendersResult(best_areas, candidate, totals.delivered, totals.shortage,
                         totals.production, totals.land, totals.water,
                         iterations, lower_bound, best_ub, cuts, converged,
                         false, NEEDS_HUMAN_DECISION, "CANDIDATE")
end

"""Totals (delivered/shortage/production/land/water) for areas, via plan_totals."""
function plan_totals_for_areas(spec::FoodPlanSpec, areas::AbstractVector)
    return PlanningSearch.plan_totals(spec, areas[1], areas[2])
end

# ------------------------------------------------------------------
# (d) Nodal balance, generalised to any flow-conservation constraint.
#
# The pattern from constraint_nodal_balance.jl, stripped of its
# energy ontology (unit_flow / node_state / gas / voltage): for
# any node, sum(inflows) - sum(outflows) - net_demand == 0
# within tolerance. A node balance is flow conservation only —
# it says nothing about resource feasibility, so a candidate
# can pass its nodal balances and still FAIL the verify step
# (e.g. over the water budget); the tests assert exactly that
# separation. Non-finite values and an empty node id are
# UNKNOWN, never PASS.
# ------------------------------------------------------------------

"""
    check_nodal_balance(; node_id, inflows, outflows, net_demand=0.0, tolerance=1e-6)

Check one node's flow conservation: sum(inflows) -
sum(outflows) - net_demand == 0 within `tolerance`. Returns
`(status, residual, node_id, reason)` with status in
"PASS" / "FAIL" / "UNKNOWN". UNKNOWN for an empty node id or
any non-finite value — never PASS.
"""
function check_nodal_balance(; node_id::String, inflows, outflows,
                               net_demand::Float64=0.0, tolerance::Float64=1e-6)
    if isempty(node_id)
        return (status="UNKNOWN", residual=NaN, node_id=node_id,
                reason="empty node_id")
    end
    in_f = Float64.(collect(inflows))
    out_f = Float64.(collect(outflows))
    if !all(isfinite.(in_f)) || !all(isfinite.(out_f)) || !isfinite(net_demand)
        return (status="UNKNOWN", residual=NaN, node_id=node_id,
                reason="non-finite value")
    end
    residual = sum(in_f) - sum(out_f) - net_demand
    # Nodal flows on the synthetic domain are tonnages (t):
    # the residual is a difference of t-flows against a 0 t bound.
    status, _ = evaluate_constraint(constraint_id="nodal-balance:$node_id",
                                    operator="==", value=residual, bound=0.0,
                                    tolerance=tolerance,
                                    value_unit="t", bound_unit="t")
    return (status=status, residual=residual, node_id=node_id, reason="OK")
end

"""
    nodal_balance_for_candidate(candidate; spec=FoodPlanSpec())

Apply nodal balance to a candidate on the synthetic domain:
per crop, production == delivered + waste (waste is
production above demand) and delivered + shortage == demand,
with the flows derived from the candidate's AREAS via the
spec — plus checks that the candidate's CLAIMED production /
delivered / shortage totals match those derived flows. A
candidate whose claimed totals disagree with its own areas
fails here. Returns `(status, checks, residuals,
needs_human_decision, verified_by_search=false)`. Flow
conservation only: this does NOT check land/water budgets.
"""
function nodal_balance_for_candidate(candidate::PlanningCandidate;
                                     spec::FoodPlanSpec=FoodPlanSpec())
    n = length(spec.demand)
    areas = [candidate.wheat_ha, candidate.potato_ha]
    prod_i = spec.yields .* areas
    delivered_i = min.(prod_i, spec.demand)
    waste_i = max.(prod_i .- spec.demand, 0.0)
    shortage_i = max.(spec.demand .- prod_i, 0.0)
    checks = String[]
    residuals = Float64[]
    for i in 1:n
        b_prod = check_nodal_balance(node_id="crop-$i-production",
                                     inflows=[prod_i[i]],
                                     outflows=[delivered_i[i], waste_i[i]])
        push!(checks, b_prod.status)
        push!(residuals, b_prod.residual)
        b_dem = check_nodal_balance(node_id="crop-$i-demand",
                                    inflows=[delivered_i[i], shortage_i[i]],
                                    outflows=[spec.demand[i]])
        push!(checks, b_dem.status)
        push!(residuals, b_dem.residual)
    end
    for (label, claimed, derived) in
        (("production", candidate.production, sum(prod_i)),
         ("delivered", candidate.delivered, sum(delivered_i)),
         ("shortage", candidate.shortage, sum(shortage_i)))
        # Claimed vs derived totals are both tonnages (t).
        status, _ = evaluate_constraint(constraint_id="nodal-claimed-$label",
                                        operator="==", value=claimed, bound=derived,
                                        tolerance=1e-6,
                                        value_unit="t", bound_unit="t")
        push!(checks, status)
        push!(residuals, claimed - derived)
    end
    return (status=overall_status(checks), checks=checks, residuals=residuals,
            needs_human_decision=NEEDS_HUMAN_DECISION, verified_by_search=false)
end

# ------------------------------------------------------------------
# (e) Modelling-to-Generate-Alternatives (MGA).
#
# Surface near-optimal alternatives for HUMAN choice. The direct
# LP optimum is solved first; each alternative is then solved
# with the added constraint total shortage <= optimum shortage
# + slack, under a different diversity objective (maximise wheat
# area, maximise potato area, minimise water use, minimise wheat
# area). Alternatives that duplicate the optimum or an earlier
# alternative (areas within 1e-6) are dropped. NOTHING is
# auto-selected: MGAResult.selected is always `nothing` at
# creation, and choose_alternative requires human_approved=true
# or throws. A chosen alternative is still a CANDIDATE only —
# choosing is not verifying.
# ------------------------------------------------------------------

"""Diversity objectives tried in order. Each is applied to a built model."""
const MGA_OBJECTIVE_NAMES = ["maximise wheat area", "maximise potato area",
                             "minimise water use", "minimise wheat area"]

function apply_mga_objective!(built, spec::FoodPlanSpec, name::String)
    model, area = built.model, built.area
    if name == "maximise wheat area"
        @objective(model, Max, area[1])
    elseif name == "maximise potato area"
        @objective(model, Max, area[2])
    elseif name == "minimise water use"
        @objective(model, Min, sum(spec.water_per_ha .* area))
    elseif name == "minimise wheat area"
        @objective(model, Min, area[1])
    else
        throw(ArgumentError("unknown MGA objective: $name"))
    end
    return nothing
end

"""
    MGAResult

Near-optimal alternatives for human choice: the direct-LP
optimum (as a candidate), the slack used, the distinct
alternatives found and the diversity objective each came from.
`selected` is always `nothing` at creation — no alternative
is auto-selected. Every alternative is CANDIDATE-only
(`verified=false`, `needs_human_decision=true`).
"""
struct MGAResult
    optimum::PlanningCandidate
    optimum_shortage::Float64
    slack::Float64
    alternatives::Vector{PlanningCandidate}
    objectives::Vector{String}
    selected::Union{Nothing, Int}
    verified::Bool
    needs_human_decision::Bool
    status::String
end

"""
    mga_alternatives(spec=FoodPlanSpec(); slack=50.0, max_alternatives=3)

Find up to `max_alternatives` DISTINCT near-optimal
alternatives (total shortage <= optimum shortage + `slack`),
one per diversity objective in MGA_OBJECTIVE_NAMES order,
dropping duplicates of the optimum or of earlier
alternatives. Returns an MGAResult with `selected === nothing`.
An objective whose LP does not reach OPTIMAL is skipped, not
treated as an alternative. Throws if the direct LP itself
does not reach OPTIMAL.
"""
function mga_alternatives(spec::FoodPlanSpec=FoodPlanSpec();
                          slack::Float64=50.0, max_alternatives::Int=3)
    slack >= 0.0 || throw(ArgumentError("slack must be >= 0"))
    max_alternatives >= 1 || throw(ArgumentError("max_alternatives must be >= 1"))
    opt = solve_direct_lp(spec)
    opt.status == :OPTIMAL ||
        error("MGA: direct LP did not reach OPTIMAL (status $(opt.status))")
    optimum = candidate_from_areas(spec, opt.areas)
    alternatives = PlanningCandidate[]
    objectives = String[]
    seen = [copy(opt.areas)]
    for name in MGA_OBJECTIVE_NAMES
        length(alternatives) >= max_alternatives && break
        built = build_food_model(spec)
        model, area, short = built.model, built.area, built.short
        @constraint(model, sum(short) <= opt.shortage + slack)
        apply_mga_objective!(built, spec, name)
        optimize!(model)
        termination_status(model) == MOI.OPTIMAL || continue
        areas = value.(area)
        # Distinct from the optimum and from earlier alternatives?
        any(maximum(abs.(areas .- s)) <= 1e-6 for s in seen) && continue
        push!(seen, copy(areas))
        push!(alternatives, candidate_from_areas(spec, areas))
        push!(objectives, name)
    end
    return MGAResult(optimum, opt.shortage, slack, alternatives, objectives,
                     nothing, false, NEEDS_HUMAN_DECISION, "CANDIDATE")
end

"""
    choose_alternative(result::MGAResult, i::Int; human_approved::Bool=false)

Return alternative `i` — ONLY when `human_approved=true`.
Without human approval this throws ArgumentError: nothing is
ever auto-selected. The returned candidate is still a
CANDIDATE only (`verified=false`); choosing is not verifying,
and the chosen plan still needs the separate verify step.
"""
function choose_alternative(result::MGAResult, i::Int; human_approved::Bool=false)
    human_approved ||
        throw(ArgumentError("choosing an MGA alternative requires human approval " *
                            "(human_approved=true); nothing is auto-selected"))
    (1 <= i <= length(result.alternatives)) ||
        throw(BoundsError(result.alternatives, i))
    return result.alternatives[i]
end
