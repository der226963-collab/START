# Tests for the planning-search module.
# Run: julia --project=julia-current test/runtests.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# The module is standalone on Distributions alone — no JuMP,
# ModelingToolkit, or AlphaZero.jl is loaded here.

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
const GI = PlanningSearch.GI
const MCTS = PlanningSearch.MCTS

const PS_DIR = joinpath(@__DIR__, "..")

@testset "MIT notice present in both copied files" begin
    for f in ("mcts.jl", "game.jl")
        text = read(joinpath(PS_DIR, f), String)
        @test occursin("Copyright (c) 2019 Jonathan Laurent", text)
        @test occursin("Permission is hereby granted, free of charge", text)
        @test occursin("The above copyright notice and this permission notice shall be included", text)
    end
end

@testset "no AlphaZero.jl import (standalone module)" begin
    # Match real import statements only: the adaptation headers in
    # mcts.jl / game.jl quote the old import in a comment, so a plain
    # substring search would trip on the comment itself.
    for f in ("PlanningSearch.jl", "mcts.jl", "game.jl",
              "planning_domain.jl", "verify.jl", "training_loop.jl",
              "dynamics_search.jl", "spineopt_patterns.jl")
        lines = readlines(joinpath(PS_DIR, f))
        code = [l for l in lines if !startswith(strip(l), "#")]
        @test !any(l -> occursin(r"^\s*using\s+(\.\.)?AlphaZero\b", l), code)
        @test !any(l -> occursin(r"^\s*import\s+AlphaZero\b", l), code)
        @test !any(l -> occursin(r"^\s*using\s+\.\.AlphaZero", l), code)
    end
end

@testset "interface contract (planning domain)" begin
    spec = FoodPlanSpec()
    @test GI.two_players(spec) == false
    @test length(GI.actions(spec)) == 13  # 7 wheat + 6 potato options
    game = GI.init(spec)
    @test GI.current_state(game) == (0.0, 0.0, 0)
    @test GI.planner_acting(game) == true
    @test GI.plan_terminated(game) == false
    # At the start only wheat actions are available.
    @test GI.available_actions(game) == [(1, h) for h in spec.wheat_options]
    # Clone is independent.
    clone = GI.clone(game)
    GI.play!(clone, (1, 50.0))
    @test GI.current_state(game) == (0.0, 0.0, 0)
    @test GI.current_state(clone) == (50.0, 0.0, 1)
    # Wrong-crop action at a step is an error.
    @test_throws ErrorException GI.play!(game, (2, 10.0))
    # After wheat, only feasible potato actions remain (water-capped).
    GI.play!(game, (1, 50.0))
    @test GI.available_actions(game) == [(2, h) for h in [0.0, 5.0, 10.0, 15.0, 20.0]]
    @test length(GI.vectorize_state(spec, GI.current_state(game))) == 3
    @test GI.action_string(spec, (1, 50.0)) == "wheat 50.0 ha"
    @test GI.parse_action(spec, "potato 20.0") == (2, 20.0)
    @test GI.parse_action(spec, "nonsense") === nothing
end

@testset "reward is plan quality, not a win probability" begin
    spec = FoodPlanSpec()
    game = GI.init(spec)
    GI.play!(game, (1, 50.0))
    @test GI.plan_reward(game) == 0.0  # intermediate step: no reward yet
    GI.play!(game, (2, 20.0))
    @test GI.plan_terminated(game) == true
    @test GI.plan_reward(game) ≈ 600 / 650
    @test GI.white_reward(game) == GI.plan_reward(game)  # alias == original name
    # Empty plan: zero delivered, zero reward.
    empty_game = GI.init(spec)
    GI.play!(empty_game, (1, 0.0))
    GI.play!(empty_game, (2, 0.0))
    @test GI.plan_reward(empty_game) == 0.0
    # Heuristic value tracks delivered so far.
    @test GI.heuristic_value(game) ≈ 600 / 650
end

@testset "MCTS finds the known optimum (rollout oracle, no network)" begin
    # Default: 1000 sims, visit-count policy, seed 1234.
    c = run_search()
    @test c.wheat_ha == 50.0
    @test c.potato_ha == 20.0
    @test c.delivered == 600.0
    @test c.shortage == 50.0
    @test c.production == 600.0
    @test c.land_ha == 70.0
    @test c.water_m3 == 100_000.0
    # Candidate only: never verified by the search itself.
    @test c.status == "CANDIDATE"
    @test c.verified == false
    @test c.needs_human_decision == true
    # Mean-Q selection also finds it at 500 sims (other seeds).
    for seed in (7, 42)
        cq = run_search(nsims=500, seed=seed, selection=:mean_q)
        @test cq.delivered == 600.0
        @test cq.shortage == 50.0
    end
    # Visit-count policy at 1000 sims finds it on other seeds too.
    @test run_search(nsims=1000, seed=99).delivered == 600.0
end

@testset "MCTS.policy requires explore! first" begin
    spec = FoodPlanSpec()
    env = MCTS.Env(spec, MCTS.RolloutOracle(spec))
    game = GI.init(spec)
    @test_throws ErrorException MCTS.policy(env, game)
end

@testset "empty / non-finite inputs are UNKNOWN, never PASS" begin
    @test evaluate_constraint(constraint_id="", operator="<=",
                              value=1.0, bound=2.0)[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=NaN, bound=2.0)[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=1.0, bound=Inf)[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<>",
                              value=1.0, bound=2.0)[1] == "UNKNOWN"
    @test overall_status(String[]) == "NOT_CHECKED"
    @test overall_status(["PASS", "FAIL"]) == "FAIL"
    @test overall_status(["PASS", "UNKNOWN"]) == "UNKNOWN"
    @test overall_status(["PASS", "PASS"]) == "PASS"
end

@testset "a search result alone is NOT verified" begin
    c = run_search()
    # No verdict at all: not verified.
    @test verified_status(c, "UNKNOWN", true) == false
    @test verified_status(c, "FAIL", true) == false
    # Even a PASS verdict without human approval is not verified.
    @test verified_status(c, "PASS", false) == false
    # Only PASS + human approval counts as verified.
    @test verified_status(c, "PASS", true) == true
    # The verify step on the good candidate passes — but the
    # candidate itself is still not marked verified by the search.
    verdict = verify_candidate(c)
    @test verdict.status == "PASS"
    @test verdict.needs_human_decision == true
    @test verdict.verified_by_search == false
    @test c.verified == false
    # A bad candidate (over the water budget) fails verification.
    bad = PlanningSearch.candidate_from_state(
        FoodPlanSpec(), (60.0, 20.0, 2))
    @test bad.water_m3 == 112_000.0
    @test verify_candidate(bad).status == "FAIL"
end
