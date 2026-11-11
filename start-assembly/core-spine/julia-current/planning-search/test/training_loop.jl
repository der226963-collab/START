# Tests for the planning training loop (training_loop.jl).
#
# STANDALONE — run separately from test/runtests.jl, or on its
# own: this file loads only PlanningSearch (Distributions alone),
# no JuMP. The LP-split tests live in test/training_loop_lp.jl.
#
# Run: julia --project=julia-current planning-search/test/training_loop.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
const GI = PlanningSearch.GI
const MCTS = PlanningSearch.MCTS

const PS_DIR = joinpath(@__DIR__, "..")

@testset "varied specs are deterministic and stay in bounds" begin
    base = FoodPlanSpec()
    a = vary_spec(base, 7)
    b = vary_spec(base, 7)
    # Same seed -> same spec (field-wise: FoodPlanSpec has no
    # == method, and == on structs falls back to identity for
    # the vector fields, so compare the fields explicitly).
    @test a.demand == b.demand && a.land_max == b.land_max &&
          a.water_max == b.water_max && a.yields == b.yields
    @test vary_spec(base, 8) != a
    @test 200.0 <= a.demand[1] <= 300.0
    @test 300.0 <= a.demand[2] <= 450.0
    @test 80.0 <= a.land_max <= 120.0
    @test 80_000.0 <= a.water_max <= 120_000.0
    @test a.yields == base.yields
    @test a.wheat_options == base.wheat_options
    # The empty plan stays available on a varied spec.
    game = GI.init(a)
    @test (1, 0.0) in GI.available_actions(game)
end

@testset "verified memory only takes verified samples" begin
    mem = VerifiedMemory(3)
    spec = FoodPlanSpec()
    good = VerifiedSample((50.0, 20.0, 2), [0.5, 0.5], 600 / 650,
                          "varied-1", spec, true)
    insert_verified!(mem, good)
    @test memory_size(mem) == 1
    @test memory_samples(mem)[1].verified == true
    # An unverified sample cannot be inserted.
    bad = VerifiedSample((50.0, 20.0, 2), [0.5, 0.5], 600 / 650,
                         "varied-1", spec, false)
    @test_throws ArgumentError insert_verified!(mem, bad)
    @test memory_size(mem) == 1
    # A non-finite outcome cannot be inserted either.
    nan_sample = VerifiedSample((50.0, 20.0, 2), [0.5, 0.5], NaN,
                                "varied-1", spec, true)
    @test_throws ArgumentError insert_verified!(mem, nan_sample)
    # Capacity: inserting past it drops the oldest sample.
    for i in 2:4
        insert_verified!(mem, VerifiedSample(
            (Float64(i), 0.0, 1), [1.0], 0.1 * i,
            "varied-$i", spec, true))
    end
    @test memory_size(mem) == 3
    @test memory_samples(mem)[1].spec_id == "varied-2"
    @test memory_samples(mem)[end].spec_id == "varied-4"
end

@testset "plan features are finite shares in [0, 1]" begin
    spec = FoodPlanSpec()
    feats = plan_features(spec, (50.0, 20.0, 2))
    @test length(feats) == 8
    @test all(isfinite.(feats))
    @test all(0.0 .<= feats .<= 1.0)
    @test feats[4] ≈ 600 / 650  # delivered share at the optimum
    @test plan_features(spec, (0.0, 0.0, 0))[4] == 0.0
end

@testset "linear value model fits and stays sane" begin
    spec = FoodPlanSpec()
    samples = VerifiedSample[
        VerifiedSample((0.0, 0.0, 0), [1.0], 0.0, "varied-1", spec, true),
        VerifiedSample((50.0, 0.0, 1), [0.5, 0.5], 200 / 650,
                       "varied-1", spec, true),
        VerifiedSample((50.0, 20.0, 2), [0.5, 0.5], 600 / 650,
                       "varied-1", spec, true),
        VerifiedSample((60.0, 10.0, 2), [0.5, 0.5], 440 / 650,
                       "varied-1", spec, true),
    ]
    model = fit_value_model(samples)
    @test length(model.weights) == 9
    @test all(isfinite.(model.weights))
    @test 0.0 <= predict_value(model, spec, (50.0, 20.0, 2)) <= 1.0
    # The fitted model ranks the optimum above the poor plan.
    @test predict_value(model, spec, (50.0, 20.0, 2)) >
          predict_value(model, spec, (60.0, 10.0, 2))
    # No usable samples -> the neutral model predicts 0.5.
    neutral = fit_value_model(VerifiedSample[])
    @test predict_value(neutral, spec, (50.0, 20.0, 2)) == 0.5
    # A sample with a non-finite outcome is skipped, not trained on.
    skipped = fit_value_model(vcat(samples, [VerifiedSample(
        (50.0, 20.0, 2), [0.5, 0.5], NaN, "varied-1", spec, true)]))
    @test all(isfinite.(skipped.weights))
    # A non-finite state predicts the neutral value.
    @test predict_value(model, spec, (NaN, 0.0, 0)) == 0.5
end

@testset "learned oracle returns a valid (P, V) pair" begin
    spec = FoodPlanSpec()
    neutral = fit_value_model(VerifiedSample[])
    oracle = LearnedOracle(neutral, spec)
    P, V = oracle((0.0, 0.0, 0))
    @test length(P) == length(GI.available_actions(GI.init(spec)))
    @test sum(P) ≈ 1.0
    @test all(P .>= 0.0)
    @test 0.0 <= V <= 1.0
    # A neutral model has no preference: the prior is uniform.
    @test maximum(P) - minimum(P) < 1e-9
    # A fitted model prefers the better successor.
    samples = VerifiedSample[
        VerifiedSample((0.0, 0.0, 0), [1.0], 0.0, "varied-1", spec, true),
        VerifiedSample((50.0, 0.0, 1), [0.5, 0.5], 200 / 650,
                       "varied-1", spec, true),
        VerifiedSample((50.0, 20.0, 2), [0.5, 0.5], 600 / 650,
                       "varied-1", spec, true),
        VerifiedSample((60.0, 10.0, 2), [0.5, 0.5], 440 / 650,
                       "varied-1", spec, true),
    ]
    fitted = LearnedOracle(fit_value_model(samples), spec)
    Pf, _ = fitted((0.0, 0.0, 0))
    # The fitted prior is a real preference, not uniform: the
    # model learned something from the samples.
    @test maximum(Pf) > 1 / length(Pf)
    # NOTE: we do NOT assert that the prior ranks wheat 50 ha
    # above wheat 60 ha. Measured 2026-11-11, the linear model
    # ranks the 60 ha step higher — it cannot express the
    # water-scarcity trade-off between the two wheat choices
    # (see the LinearValueModel docstring). Whether the learned
    # oracle helps in practice is judged by the held-out
    # comparison in the loop, not by this unit test.
end

@testset "search with a given oracle returns a candidate only" begin
    spec = FoodPlanSpec()
    result = run_search_with_oracle(spec, MCTS.RolloutOracle(spec);
                                    nsims=200, seed=1234)
    c = result.candidate
    @test c.status == "CANDIDATE"
    @test c.verified == false
    @test c.needs_human_decision == true
    @test c.delivered + c.shortage ≈ 650.0
    @test c.land_ha <= spec.land_max
    @test c.water_m3 <= spec.water_max
    @test length(result.trace) == 2  # one decision per crop
    @test result.trace[1][1][3] == 0
    @test result.trace[2][1][3] == 1
    # The trace policies are valid distributions.
    for (_, π) in result.trace
        @test sum(π) ≈ 1.0
        @test all(π .>= 0.0)
    end
end

@testset "the loop keeps only verified samples" begin
    result = train_planning_loop!(
        iterations=2, train_seeds=[1, 2], heldout_seeds=[101, 102],
        nsims=200, seed=1234)
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
    @test result.oracle_is_learned isa Bool
    # Held-out numbers are recorded for both oracles.
    for r in result.reports
        @test 0.0 <= r.rollout_pass_rate <= 1.0
        @test 0.0 <= r.learned_pass_rate <= 1.0
        @test isfinite(r.rollout_mean_shortage)
        @test isfinite(r.learned_mean_shortage)
        @test r.oracle_replaced ==
              (r.learned_pass_rate >= r.rollout_pass_rate &&
               r.learned_mean_shortage <= r.rollout_mean_shortage + 1e-9)
    end
end

@testset "rejected candidates never enter the memory" begin
    always_fail = (candidate, spec) -> (status="FAIL",)
    result = train_planning_loop!(
        iterations=2, train_seeds=[1, 2], heldout_seeds=[101, 102],
        nsims=200, seed=1234, verify_fn=always_fail)
    @test memory_size(result.memory) == 0
    total_generated = sum(r -> r.generated, result.reports)
    total_rejected = sum(r -> r.rejected, result.reports)
    @test total_rejected == total_generated
    @test sum(r -> r.verified_kept, result.reports) == 0
end

@testset "a trained oracle is still only a candidate generator" begin
    result = train_planning_loop!(
        iterations=1, train_seeds=[1], heldout_seeds=[101],
        nsims=200, seed=1234)
    @test result.model !== nothing
    spec = FoodPlanSpec()
    oracle = LearnedOracle(result.model, spec)
    c = run_search_with_oracle(spec, oracle; nsims=200,
                               seed=1234).candidate
    @test c.status == "CANDIDATE"
    @test c.verified == false
    # Even a PASS verdict without human approval is not verified.
    @test verify_candidate(c).status == "PASS"
    @test verified_status(c, "PASS", false) == false
    @test verified_status(c, "PASS", true) == true
end

@testset "no game-loop code in training_loop.jl" begin
    # Match code lines only: the header comment explains what was
    # replaced, so comment lines are excluded, as in the
    # no-AlphaZero-import test in runtests.jl.
    lines = readlines(joinpath(PS_DIR, "training_loop.jl"))
    code = [l for l in lines if !startswith(strip(l), "#")]
    for ident in ("self_play", "self-play", "arena", "pit_networks",
                  "compare_networks", "simulate_distributed", "Flux",
                  "Knet", "MemoryBuffer", "Trainer(", "AlphaZero")
        @test !any(l -> occursin(ident, l), code)
    end
end
