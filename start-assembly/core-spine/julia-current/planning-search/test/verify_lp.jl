# Tests for the LP cross-check (verify_lp.jl).
#
# STANDALONE test script — run separately from test/runtests.jl.
# runtests.jl must stay loadable on Distributions alone; this file
# loads JuMP+HiGHS, so it lives on its own (split-stage pattern,
# same as spine_lp.jl vs spine_ode.jl).
#
# Run: julia --project=julia-current planning-search/test/verify_lp.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# It loads PlanningSearch (Distributions only) plus JuMP+HiGHS.

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "..", "verify_lp.jl"))

@testset "LP optimum from the spec alone" begin
    lp = solve_food_lp_from_spec(FoodPlanSpec())
    @test lp.status == :OPTIMAL
    @test lp.delivered == 600.0
    @test lp.shortage == 50.0
    @test lp.production == 600.0
    @test lp.land == 70.0
    @test lp.water == 100_000.0
    # The LP is solved from the spec, not from any candidate:
    # re-solving with the default spec gives the same optimum.
    lp2 = solve_food_lp_from_spec(FoodPlanSpec())
    @test lp2.delivered == lp.delivered
    @test lp2.shortage == lp.shortage
end

@testset "good MCTS candidate passes both checks" begin
    c = run_search()  # wheat 50 ha / potato 20 ha, delivered 600, shortage 50
    v = verify_candidate_with_lp(c)
    @test v.constraint_status == "PASS"
    @test v.lp_status == "PASS"
    @test v.status == "PASS"
    @test v.lp_optimum.delivered == 600.0
    @test v.lp_optimum.shortage == 50.0
    @test v.needs_human_decision == true
    @test v.verified_by_search == false
    # A PASS verdict is still not verified without human approval.
    @test verified_status(c, v.status, false) == false
    @test verified_status(c, v.status, true) == true
    @test c.verified == false
end

@testset "feasible but suboptimal candidate passes both checks" begin
    # Wheat 50 ha / potato 10 ha: delivered 400, shortage 250.
    # Feasible, but worse than the LP optimum — verification is
    # feasibility, not optimality, so both checks pass.
    c = PlanningSearch.candidate_from_state(FoodPlanSpec(), (50.0, 10.0, 2))
    @test c.delivered == 400.0
    @test c.shortage == 250.0
    v = verify_candidate_with_lp(c)
    @test v.constraint_status == "PASS"
    @test v.lp_status == "PASS"
    @test v.status == "PASS"
end

@testset "over-water candidate fails both checks" begin
    # Wheat 60 ha / potato 20 ha: water 112,000 m3 > 100,000, and
    # delivered 640 t / shortage 10 t also beats the LP optimum.
    bad = PlanningSearch.candidate_from_state(FoodPlanSpec(), (60.0, 20.0, 2))
    @test bad.water_m3 == 112_000.0
    @test bad.delivered == 640.0
    @test bad.shortage == 10.0
    v = verify_candidate_with_lp(bad)
    @test v.constraint_status == "FAIL"
    @test v.lp_status == "FAIL"
    @test v.status == "FAIL"
    @test verified_status(bad, v.status, true) == false
end

@testset "candidate claiming better than the LP optimum fails the LP check" begin
    # A lying candidate: delivered 650, shortage 0, production 650.
    # Its own arithmetic is consistent (delivered+shortage == 650
    # demand, production == delivered, land/water within budget),
    # so the constraint verify alone PASSES it — the LP cross-check
    # must be the check that catches it.
    liar = PlanningCandidate(50.0, 20.0, 650.0, 0.0, 650.0,
                             70.0, 100_000.0, false, true, "CANDIDATE")
    @test verify_candidate(liar).status == "PASS"
    v = verify_candidate_with_lp(liar)
    @test v.constraint_status == "PASS"
    @test v.lp_status == "FAIL"
    @test v.status == "FAIL"
    @test "FAIL" in v.checks
    @test verified_status(liar, v.status, true) == false
    # A second liar, beating the optimum by less: delivered 610,
    # shortage 40. Its arithmetic is also consistent (610+40 == 650,
    # production == delivered), so the constraint verify passes it
    # too, and again only the LP cross-check catches it.
    liar2 = PlanningCandidate(50.0, 20.0, 610.0, 40.0, 610.0,
                              70.0, 100_000.0, false, true, "CANDIDATE")
    @test verify_candidate(liar2).status == "PASS"
    v2 = verify_candidate_with_lp(liar2)
    @test v2.lp_status == "FAIL"
    @test v2.status == "FAIL"
end

@testset "LP non-optimal / infeasible spec is UNKNOWN, never PASS" begin
    # A spec with a negative land budget makes the LP infeasible:
    # area >= 0 but sum(area) <= -1 has no solution.
    infeasible_spec = FoodPlanSpec(
        [4.0, 20.0], [1200.0, 2000.0], [250.0, 400.0],
        -1.0, 100_000.0,
        [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        [0.0, 5.0, 10.0, 15.0, 20.0, 25.0])
    lp = solve_food_lp_from_spec(infeasible_spec)
    @test lp.status != :OPTIMAL
    @test !isfinite(lp.delivered)
    # The cross-check against a non-optimal LP is UNKNOWN.
    c = run_search()
    cross = lp_cross_check(c, lp; spec=infeasible_spec)
    @test cross.status == "UNKNOWN"
    @test all(s == "UNKNOWN" for s in cross.checks)
    # The combined verdict for an infeasible spec is never PASS
    # (here it is FAIL, because the constraint verify also fails
    # the land budget — either way, not PASS, and the LP side is
    # UNKNOWN, not a silent pass).
    v = verify_candidate_with_lp(c; spec=infeasible_spec)
    @test v.lp_status == "UNKNOWN"
    @test v.status != "PASS"
    @test verified_status(c, v.status, true) == false
end

@testset "non-finite candidate is UNKNOWN, never PASS" begin
    nan_candidate = PlanningCandidate(50.0, 20.0, NaN, 50.0, NaN,
                                      70.0, 100_000.0, false, true, "CANDIDATE")
    v = verify_candidate_with_lp(nan_candidate)
    @test v.status == "UNKNOWN"
    @test v.lp_status == "UNKNOWN"
    @test verified_status(nan_candidate, v.status, true) == false
end

@testset "candidate alone, with no verify at all, is not verified" begin
    c = run_search()
    @test c.verified == false
    @test c.status == "CANDIDATE"
    # No verdict exists yet: verified_status with no PASS is false,
    # and the candidate's own flag is unchanged by the search.
    @test verified_status(c, "UNKNOWN", true) == false
    @test verified_status(c, "NOT_CHECKED", true) == false
end
