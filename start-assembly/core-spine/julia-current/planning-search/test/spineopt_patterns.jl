# Tests for the SpineOpt planning patterns (spineopt_patterns.jl).
#
# STANDALONE test script — run separately from test/runtests.jl.
# runtests.jl must stay loadable on Distributions alone; this file
# loads JuMP+HiGHS, so it lives on its own (split-stage pattern,
# same as test/verify_lp.jl).
#
# Run: julia --project=julia-current planning-search/test/spineopt_patterns.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# It loads PlanningSearch (Distributions only) plus JuMP+HiGHS.
#
# The patterns are ORIGINAL START code, an INSPIRATION-REBUILD of
# spine-tools/SpineOpt.jl (Module 18, DROP in the replacements
# audit: energy-only JuMP application, GPL/LGPL contradiction,
# Spine-DB I/O, monolithic build-solve-write). No SpineOpt code
# copied, no SpineOpt dependency. Every result is a CANDIDATE
# only until the separate verify step (constraint verify +
# JuMP+HiGHS LP cross-check) passes AND a human approves.

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "..", "verify_lp.jl"))
include(joinpath(@__DIR__, "..", "spineopt_patterns.jl"))

const SP_DIR = joinpath(@__DIR__, "..")

@testset "direct LP agrees with the verify_lp LP" begin
    spec = FoodPlanSpec()
    lp = solve_direct_lp(spec)
    @test lp.status == :OPTIMAL
    @test lp.delivered == 600.0
    @test lp.shortage == 50.0
    @test lp.production == 600.0
    @test lp.land == 70.0
    @test lp.water == 100_000.0
    @test lp.areas[1] == 50.0
    @test lp.areas[2] == 20.0
    # Same optimum as the independent LP in verify_lp.jl.
    lp2 = solve_food_lp_from_spec(spec)
    @test lp2.delivered == lp.delivered
    @test lp2.shortage == lp.shortage
    # A failed solve is data, never a PASS: infeasible spec.
    bad_spec = FoodPlanSpec([4.0, 20.0], [1200.0, 2000.0], [250.0, 400.0],
                            -1.0, 100_000.0,
                            [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                            [0.0, 5.0, 10.0, 15.0, 20.0, 25.0])
    bad = solve_direct_lp(bad_spec)
    @test bad.status != :OPTIMAL
    @test !isfinite(bad.delivered)
end

@testset "time-sliced plan (rolling horizon / representative periods)" begin
    plan = rolling_horizon_plan()
    @test length(plan.slices) == 3
    @test length(plan.candidates) == 3
    @test plan.total_weight == 3.0
    # Each slice splits the annual water budget three ways, so each
    # slice can only water 16.667 ha of potato: delivered 1000/3 t.
    for c in plan.candidates
        @test c.water_m3 <= 100_000.0 / 3 + 0.02
        @test c.land_ha <= 100.0
        @test c.delivered ≈ 1000.0 / 3
    end
    @test plan.delivered ≈ 1000.0
    @test plan.shortage ≈ 950.0
    @test plan.verified == false
    @test plan.status == "CANDIDATE"
    @test plan.needs_human_decision == true
    # Every slice candidate passes the separate verify step (with
    # its own slice spec) — but the plan itself is still only a
    # candidate until a human approves.
    for (c, s) in zip(plan.candidates, plan.slices)
        @test verify_candidate_with_lp(c; spec=s.spec).status == "PASS"
    end
    # One period is the base problem again: 600/50 t.
    one = rolling_horizon_plan(nperiods=1)
    @test one.delivered ≈ 600.0
    @test one.shortage ≈ 50.0
    @test_throws ArgumentError representative_slices(nperiods=0)
end

@testset "two-scenario stochastic plan (normal vs low yield)" begin
    sp = stochastic_plan()
    @test length(sp.scenarios) == 2
    @test length(sp.candidates) == 2
    @test sum(s.probability for s in sp.scenarios) ≈ 1.0
    @test sp.scenarios[1].id == "normal"
    @test sp.scenarios[2].id == "low-yield"
    # Normal scenario: the known 600/50 t optimum.
    @test sp.candidates[1].delivered == 600.0
    @test sp.candidates[1].shortage == 50.0
    # Low yield (0.8x): potato 25 ha -> 400 t, wheat 41.667 ha ->
    # 133.333 t; delivered 1600/3 t, shortage 350/3 t.
    @test sp.candidates[2].delivered ≈ 1600.0 / 3
    @test sp.candidates[2].shortage ≈ 350.0 / 3
    # Expected totals: 0.7 * 600 + 0.3 * 533.333 = 580 t delivered,
    # 0.7 * 50 + 0.3 * 116.667 = 70 t shortage.
    @test sp.expected_delivered ≈ 580.0
    @test sp.expected_shortage ≈ 70.0
    @test sp.verified == false
    @test sp.status == "CANDIDATE"
    @test sp.needs_human_decision == true
    # Every scenario candidate passes the separate verify step
    # (with its own scenario spec).
    for (c, s) in zip(sp.candidates, sp.scenarios)
        @test verify_candidate_with_lp(c; spec=s.spec).status == "PASS"
    end
    # Bad probabilities are rejected, never silently normalised.
    spec = FoodPlanSpec()
    @test_throws ArgumentError stochastic_plan(
        [StochasticScenario("a", "a", 0.6, spec),
         StochasticScenario("b", "b", 0.6, spec)])
    @test_throws ArgumentError stochastic_plan(
        [StochasticScenario("a", "a", -0.1, spec),
         StochasticScenario("b", "b", 1.1, spec)])
    @test_throws ArgumentError stochastic_plan(StochasticScenario[])
    @test_throws ArgumentError two_scenarios(p_normal=1.1)
end

@testset "Benders split agrees with the direct LP optimum" begin
    # Subproblem first, on its own: no areas -> full 650 t shortage;
    # the optimum areas -> 50 t shortage, 600 t delivered.
    spec = FoodPlanSpec()
    @test subproblem_shortage(spec, [0.0, 0.0]).shortage == 650.0
    @test subproblem_shortage(spec, [50.0, 20.0]).shortage == 50.0
    @test subproblem_shortage(spec, [50.0, 20.0]).delivered == 600.0
    b = benders_solve()
    @test b.converged == true
    @test b.iterations == 2
    @test b.areas[1] ≈ 50.0
    @test b.areas[2] ≈ 20.0
    @test b.delivered == 600.0
    @test b.shortage == 50.0
    @test b.production == 600.0
    @test b.land == 70.0
    @test b.water == 100_000.0
    # Bounds met: master theta (lower) == best subproblem (upper).
    @test b.lower_bound ≈ 50.0
    @test b.upper_bound ≈ 50.0
    @test b.lower_bound ≈ b.upper_bound
    @test length(b.cuts) == 1
    # Agreement with the direct LP optimum, field by field.
    lp = solve_direct_lp(spec)
    @test b.delivered ≈ lp.delivered
    @test b.shortage ≈ lp.shortage
    @test b.production ≈ lp.production
    @test b.land ≈ lp.land
    @test b.water ≈ lp.water
    # CANDIDATE only: never verified by the Benders code itself.
    @test b.candidate.status == "CANDIDATE"
    @test b.candidate.verified == false
    @test b.needs_human_decision == true
    @test b.verified == false
    # The separate verify step passes it (constraint + LP cross-check).
    v = verify_candidate_with_lp(b.candidate)
    @test v.constraint_status == "PASS"
    @test v.lp_status == "PASS"
    @test v.status == "PASS"
    @test verified_status(b.candidate, v.status, false) == false
    @test verified_status(b.candidate, v.status, true) == true
end

@testset "nodal balance (generalised flow conservation)" begin
    # Generic node: inflows 100 + 50, outflows 120, net demand 30.
    ok = check_nodal_balance(node_id="n1", inflows=[100.0, 50.0],
                             outflows=[120.0], net_demand=30.0)
    @test ok.status == "PASS"
    @test ok.residual ≈ 0.0
    bad = check_nodal_balance(node_id="n1", inflows=[100.0, 50.0],
                              outflows=[100.0], net_demand=30.0)
    @test bad.status == "FAIL"
    @test bad.residual ≈ 20.0
    @test check_nodal_balance(node_id="", inflows=[1.0],
                              outflows=[1.0]).status == "UNKNOWN"
    @test check_nodal_balance(node_id="n1", inflows=[NaN],
                              outflows=[1.0]).status == "UNKNOWN"
    # The optimum candidate balances: 2 crops x (production,
    # demand) + 3 claimed-total checks = 7 checks, all residuals 0.
    good = PlanningSearch.candidate_from_state(FoodPlanSpec(), (50.0, 20.0, 2))
    nb = nodal_balance_for_candidate(good)
    @test nb.status == "PASS"
    @test all(abs.(nb.residuals) .<= 1e-6)
    @test length(nb.checks) == 7
    @test nb.needs_human_decision == true
    @test nb.verified_by_search == false
    # A liar (areas 50/20 but claimed delivered 650) fails the
    # claimed-delivered check.
    liar = PlanningCandidate(50.0, 20.0, 650.0, 0.0, 650.0,
                             70.0, 100_000.0, false, true, "CANDIDATE")
    @test nodal_balance_for_candidate(liar).status == "FAIL"
    @test "FAIL" in nodal_balance_for_candidate(liar).checks
    # Separation of concerns: an over-water candidate still
    # balances (its flows conserve) but FAILS the verify step.
    over = PlanningSearch.candidate_from_state(FoodPlanSpec(), (60.0, 20.0, 2))
    @test nodal_balance_for_candidate(over).status == "PASS"
    @test verify_candidate(over).status == "FAIL"
end

@testset "MGA returns distinct near-optimal alternatives, none auto-selected" begin
    m = mga_alternatives()
    @test m.optimum.delivered == 600.0
    @test m.optimum_shortage == 50.0
    @test m.slack == 50.0
    @test length(m.alternatives) >= 2
    # Near-optimal: shortage <= 100 t (optimum 50 + slack 50),
    # delivered >= 550 t.
    @test all(a.shortage <= 100.0 + 1e-6 for a in m.alternatives)
    @test all(a.delivered >= 550.0 - 1e-6 for a in m.alternatives)
    # Distinct from the optimum and from each other (by areas).
    opt_areas = [m.optimum.wheat_ha, m.optimum.potato_ha]
    @test all(maximum(abs.([a.wheat_ha, a.potato_ha] .- opt_areas)) > 1e-6
              for a in m.alternatives)
    for i in 1:length(m.alternatives), j in (i + 1):length(m.alternatives)
        @test maximum(abs.([m.alternatives[i].wheat_ha - m.alternatives[j].wheat_ha,
                            m.alternatives[i].potato_ha - m.alternatives[j].potato_ha])) > 1e-6
    end
    # Every alternative is a CANDIDATE only.
    @test all(a.status == "CANDIDATE" for a in m.alternatives)
    @test all(a.verified == false for a in m.alternatives)
    @test all(a.needs_human_decision == true for a in m.alternatives)
    # Nothing is auto-selected.
    @test m.selected === nothing
    @test m.verified == false
    @test m.status == "CANDIDATE"
    @test m.needs_human_decision == true
    # Choosing requires human approval, and choosing is not verifying.
    @test_throws ArgumentError choose_alternative(m, 1)
    @test_throws ArgumentError choose_alternative(m, 1; human_approved=false)
    chosen = choose_alternative(m, 1; human_approved=true)
    @test chosen === m.alternatives[1]
    @test chosen.verified == false
    @test chosen.status == "CANDIDATE"
    @test_throws BoundsError choose_alternative(m, 99; human_approved=true)
    # Every alternative passes the separate verify step.
    @test all(verify_candidate_with_lp(a).status == "PASS" for a in m.alternatives)
    # Objectives line up with the alternatives found.
    @test length(m.objectives) == length(m.alternatives)
    @test all(o in MGA_OBJECTIVE_NAMES for o in m.objectives)
    @test_throws ArgumentError mga_alternatives(slack=-1.0)
end

@testset "no SpineOpt code, dependency, or monolithic call" begin
    text = read(joinpath(SP_DIR, "spineopt_patterns.jl"), String)
    code = [l for l in split(text, "\n") if !startswith(strip(l), "#")]
    @test !any(l -> occursin(r"^\s*using\s+SpineOpt\b", l), code)
    @test !any(l -> occursin(r"^\s*import\s+SpineOpt\b", l), code)
    @test !any(l -> occursin("SpineInterface", l), code)
    @test !any(l -> occursin("sqlite", l), code)
    @test !any(l -> occursin("run_spineopt", l), code)
    @test !any(l -> occursin("SpineOpt", l), code)
    @test !any(l -> occursin("verified=true", l), code)
    @test occursin("ORIGINAL START code", text)
    @test occursin("NO SpineOpt code copied", text)
end
