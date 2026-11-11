# Tests for the planning training loop with the LP cross-check.
#
# STANDALONE test script — run separately from test/runtests.jl.
# runtests.jl and test/training_loop.jl must stay loadable on
# Distributions alone; this file loads JuMP+HiGHS, so it lives
# on its own (split-stage pattern, same as test/verify_lp.jl).
#
# Run: julia --project=julia-current planning-search/test/training_loop_lp.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# It loads PlanningSearch (Distributions only) plus JuMP+HiGHS.

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "..", "verify_lp.jl"))

const LP_VERIFY = (candidate, spec) ->
    verify_candidate_with_lp(candidate; spec=spec)

@testset "full loop with the LP cross-check" begin
    result = train_planning_loop!(
        iterations=2, train_seeds=[1, 2], heldout_seeds=[101, 102],
        nsims=200, seed=1234, verify_fn=LP_VERIFY)
    @test length(result.reports) == 2
    @test memory_size(result.memory) > 0
    @test all(s -> s.verified, memory_samples(result.memory))
    total_generated = sum(r -> r.generated, result.reports)
    total_kept = sum(r -> r.verified_kept, result.reports)
    total_rejected = sum(r -> r.rejected, result.reports)
    @test total_generated == 4  # 2 iterations x 2 training specs
    @test total_kept == total_generated
    @test total_rejected == 0
    @test result.model !== nothing
    # Every kept sample came from a candidate that passed BOTH
    # the constraint verify and the LP cross-check (the loop
    # was run with the combined verify function).
    for r in result.reports
        @test 0.0 <= r.rollout_pass_rate <= 1.0
        @test 0.0 <= r.learned_pass_rate <= 1.0
        @test isfinite(r.rollout_mean_shortage)
        @test isfinite(r.learned_mean_shortage)
    end
    # The held-out numbers, printed so the run shows them.
    last = result.reports[end]
    println("  held-out (final iteration): rollout PASS rate=",
            last.rollout_pass_rate,
            " learned PASS rate=", last.learned_pass_rate,
            " rollout mean shortage=", last.rollout_mean_shortage,
            " t learned mean shortage=", last.learned_mean_shortage,
            " t replaced=", last.oracle_replaced)
end

@testset "learned oracle does not degrade the held-out PASS rate" begin
    result = train_planning_loop!(
        iterations=2, train_seeds=[1, 2], heldout_seeds=[101, 102],
        nsims=200, seed=1234, verify_fn=LP_VERIFY)
    last = result.reports[end]
    # The task's criterion: the learned oracle must not degrade
    # the held-out verified-PASS rate. (On this tiny domain both
    # oracles generate feasible candidates, so both rates are
    # 1.0; the mean shortage is the discriminating number and is
    # recorded, not asserted as an improvement.)
    @test last.learned_pass_rate >= last.rollout_pass_rate
    @test last.oracle_replaced ==
          (last.learned_pass_rate >= last.rollout_pass_rate &&
           last.learned_mean_shortage <= last.rollout_mean_shortage + 1e-9)
    println("  held-out PASS rates: rollout=", last.rollout_pass_rate,
            " learned=", last.learned_pass_rate,
            "; mean shortage: rollout=", last.rollout_mean_shortage,
            " t learned=", last.learned_mean_shortage, " t")
end

@testset "learned-oracle candidate still needs verify + approval" begin
    result = train_planning_loop!(
        iterations=1, train_seeds=[1], heldout_seeds=[101],
        nsims=200, seed=1234, verify_fn=LP_VERIFY)
    @test result.model !== nothing
    spec = FoodPlanSpec()
    oracle = LearnedOracle(result.model, spec)
    c = run_search_with_oracle(spec, oracle; nsims=200,
                               seed=1234).candidate
    @test c.status == "CANDIDATE"
    @test c.verified == false
    combined = verify_candidate_with_lp(c)
    @test combined.status == "PASS"
    @test combined.constraint_status == "PASS"
    @test combined.lp_status == "PASS"
    @test verified_status(c, combined.status, false) == false
    @test verified_status(c, combined.status, true) == true
end
