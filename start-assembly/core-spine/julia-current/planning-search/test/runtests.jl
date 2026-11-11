# Tests for the planning-search module.
# Run: julia --project=julia-current test/runtests.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# The module is standalone on Distributions alone — no JuMP,
# ModelingToolkit, or AlphaZero.jl is loaded here.

using Test
using JSON

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
                              value=1.0, bound=2.0,
                              value_unit="kg", bound_unit="kg")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=NaN, bound=2.0,
                              value_unit="kg", bound_unit="kg")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=1.0, bound=Inf,
                              value_unit="kg", bound_unit="kg")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<>",
                              value=1.0, bound=2.0,
                              value_unit="kg", bound_unit="kg")[1] == "UNKNOWN"
    @test overall_status(String[]) == "NOT_CHECKED"
    @test overall_status(["PASS", "FAIL"]) == "FAIL"
    @test overall_status(["PASS", "UNKNOWN"]) == "UNKNOWN"
    @test overall_status(["PASS", "PASS"]) == "PASS"
    # Aggregation follows Python's overall_from_checks exactly:
    # FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED > all-PASS.
    @test overall_status(["UNKNOWN"]) == "UNKNOWN"
    @test overall_status(["UNKNOWN", "INCOMPLETE"]) == "INCOMPLETE"
    @test overall_status(["PASS", "NOT_CHECKED"]) == "NOT_CHECKED"
    @test overall_status(["INCOMPLETE"]) == "INCOMPLETE"
end

@testset "unit registry: shared test-vectors (2026-11-11 decisions)" begin
    # The 8 wire cases from blocker-work/shared-test-vectors/
    # test-vectors.json, plus the discriminating cases that catch
    # the old right-status-for-the-wrong-reason behaviour.
    # 1. food-energy-adequacy: 2800 >= 2500 kcal/capita/day.
    @test evaluate_constraint(constraint_id="food_energy_adequacy",
                              operator=">=", value=2800.0, bound=2500.0,
                              value_unit="kcal/capita/day",
                              bound_unit="kcal/capita/day")[1] == "PASS"
    # 2. mass-tonne: 8 t <= 10 t.
    @test evaluate_constraint(constraint_id="mass", operator="<=",
                              value=8.0, bound=10.0,
                              value_unit="t", bound_unit="t")[1] == "PASS"
    # 3. volume-m3-vs-litre: 0.008 m3 = 8 L <= 10 L.
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=0.008, bound=10.0,
                              value_unit="m3", bound_unit="L")[1] == "PASS"
    # 3b. Discriminating pair: 0.02 m3 = 20 L > 10 L FAILs. The old
    # unit-free evaluator passed this (0.02 <= 10 numerically).
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=0.02, bound=10.0,
                              value_unit="m3", bound_unit="L")[1] == "FAIL"
    # 3c. Reverse direction: 8 L <= 0.01 m3 (10 L) PASS; 12 L FAIL.
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=8.0, bound=0.01,
                              value_unit="L", bound_unit="m3")[1] == "PASS"
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=12.0, bound=0.01,
                              value_unit="L", bound_unit="m3")[1] == "FAIL"
    # "m³" (superscript) is an alias for "m3".
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=0.008, bound=10.0,
                              value_unit="m³", bound_unit="L")[1] == "PASS"
    # 4. kcal/day is in the registry now (was Python-rejected,
    # Rust-invented; Eric's decision adds it): 2800 >= 2500 PASS.
    @test evaluate_constraint(constraint_id="kday", operator=">=",
                              value=2800.0, bound=2500.0,
                              value_unit="kcal/day",
                              bound_unit="kcal/day")[1] == "PASS"
    @test evaluate_constraint(constraint_id="kday", operator=">=",
                              value=2800.0, bound=2500.0,
                              value_unit="kcal/person/day",
                              bound_unit="kcal/person/day")[1] == "PASS"
    # 5. equality-kg: 10 kg == 10 kg.
    @test evaluate_constraint(constraint_id="eq", operator="==",
                              value=10.0, bound=10.0,
                              value_unit="kg", bound_unit="kg")[1] == "PASS"
    # 6. fail-litre: 12 L <= 10 L.
    @test evaluate_constraint(constraint_id="fail", operator="<=",
                              value=12.0, bound=10.0,
                              value_unit="L", bound_unit="L")[1] == "FAIL"
    # 7. incompatible-units: 5 L <= 10 kg is UNKNOWN, NEVER a
    # PASS. This is the bug the unit registry fixes: the old
    # unit-free evaluator silently PASSED this comparison.
    @test evaluate_constraint(constraint_id="incomp", operator="<=",
                              value=5.0, bound=10.0,
                              value_unit="L", bound_unit="kg")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="incomp", operator="<=",
                              value=5.0, bound=10.0,
                              value_unit="L", bound_unit="kg")[2] ==
          "incompatible units: L and kg"
    # Unknown units are UNKNOWN, never PASS — either side.
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=5.0, bound=10.0,
                              value_unit="furlongs",
                              bound_unit="kg")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=5.0, bound=10.0,
                              value_unit="kg",
                              bound_unit="furlongs")[1] == "UNKNOWN"
    # Cross-dimension conversions never happen: mass <-> volume.
    @test evaluate_constraint(constraint_id="x", operator="<=",
                              value=1000.0, bound=1.0,
                              value_unit="g", bound_unit="L")[1] == "UNKNOWN"
    # Same-dimension conversions: g -> kg, tonne -> kg.
    @test evaluate_constraint(constraint_id="mass", operator="<=",
                              value=8000.0, bound=10.0,
                              value_unit="g", bound_unit="kg")[1] == "PASS"
    @test evaluate_constraint(constraint_id="mass", operator="<=",
                              value=0.008, bound=10.0,
                              value_unit="t", bound_unit="kg")[1] == "PASS"
    # 8. range-operator: 5 L in [2, 8] — inclusive, with tolerance.
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=5.0, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L")[1] == "PASS"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=1.0, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L")[1] == "FAIL"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=9.0, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L")[1] == "FAIL"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=2.0, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L")[1] == "PASS"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=8.0, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L")[1] == "PASS"
    # Range with a tolerance: 8.05 L is inside [2, 8] + 0.1.
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=8.05, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L",
                              tolerance=0.1)[1] == "PASS"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=8.2, bound_low=2.0, bound_high=8.0,
                              value_unit="L", bound_unit="L",
                              tolerance=0.1)[1] == "FAIL"
    # Missing bounds -> UNKNOWN, never PASS; inverted -> UNKNOWN.
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=5.0,
                              value_unit="L", bound_unit="L")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=5.0, bound_low=2.0,
                              value_unit="L", bound_unit="L")[1] == "UNKNOWN"
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=5.0, bound_low=8.0, bound_high=2.0,
                              value_unit="L", bound_unit="L")[1] == "UNKNOWN"
    # Range converts units too: 0.005 m3 = 5 L in [2, 8] L.
    @test evaluate_constraint(constraint_id="rng", operator="range",
                              value=0.005, bound_low=2.0, bound_high=8.0,
                              value_unit="m3", bound_unit="L")[1] == "PASS"
end

@testset "schema versions: same-major accepted, major rejected" begin
    # Pure function check_schema_version, alongside the evaluator.
    @test check_schema_version("1.0.0") == (true, "OK")
    @test check_schema_version("1.0.1") == (true, "OK")
    @test check_schema_version("1.1.0") == (true, "OK")
    accepted, reason = check_schema_version("2.0.0")
    @test accepted == false
    # Exact message Python and Rust both use.
    @test reason == "unsupported major schema version: 2.0.0 " *
                    "(supported major version 1)"
    @test check_schema_version("3.2.1")[1] == false
    @test check_schema_version("3.2.1")[2] ==
          "unsupported major schema version: 3.2.1 " *
          "(supported major version 1)"
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

@testset "shared test-vectors.json: agreed outcomes (2026-11-11 integration)" begin
    # Consuming test for interop/test-vectors.json (ISSUE-04). The file
    # records all four 2026-11-11 decisions; this testset PARSES the
    # real file with JSON.jl and drives every case through the fixed
    # evaluator in units.jl, so a disagreement between the file and
    # the evaluator is a FAILURE. JSON.jl became a direct dependency
    # of the canonical env on 2026-11-11 (v1.13.4 — already the
    # resolved transitive version, so the resolved set is unchanged).
    # The previous hand-transcribed table is gone: every request,
    # expected status and version case below comes from the parsed
    # file, so transcription drift is impossible now.
    vectors_path = joinpath(@__DIR__, "..", "..", "..", "..", "..",
                            "v032-review", "start_v03_work",
                            "interop", "test-vectors.json")
    @test isfile(vectors_path)
    vectors = JSON.parsefile(vectors_path)
    # The file's shape is pinned: 8 wire cases, 3 version cases,
    # 2 aggregation cases.
    @test length(vectors["cases"]) == 8
    @test length(vectors["version_cases"]) == 3
    @test length(vectors["aggregation_cases"]) == 2
    # No case carries "open_decision" as its conformance value —
    # checked on the PARSED data, not on raw text. The
    # conformance_kinds legend no longer lists open_decision at
    # all (cleaned up 2026-11-11, now that no case uses it).
    for case in vectors["cases"]
        @test case["conformance"] != "open_decision"
    end
    for case in vectors["version_cases"]
        @test case["conformance"] != "open_decision"
    end
    for case in vectors["aggregation_cases"]
        @test case["conformance"] != "open_decision"
    end
    @test !haskey(vectors["conformance_kinds"], "open_decision")

    # The 8 wire cases, driven from the parsed file: each request
    # goes through evaluate_constraint, and the status must match
    # BOTH the Julia expectation and the Python expectation recorded
    # in the file — the three languages must agree.
    for case in vectors["cases"]
        req = case["request"]
        bound = get(req, "bound", nothing)
        low = get(req, "bound_low", nothing)
        high = get(req, "bound_high", nothing)
        status, reason = evaluate_constraint(
            constraint_id=req["constraint_id"], operator=req["operator"],
            value=Float64(req["value"]),
            bound=bound === nothing ? nothing : Float64(bound),
            value_unit=req["value_unit"], bound_unit=req["bound_unit"],
            tolerance=Float64(get(req, "tolerance", 0)),
            bound_low=low === nothing ? nothing : Float64(low),
            bound_high=high === nothing ? nothing : Float64(high))
        @test status == case["julia_expected"]["status"]
        @test status == case["python_expected"]["status"]
        @test case["julia_expected"]["status"] ==
              case["python_expected"]["status"]
    end
    # The discriminating m3/L pair from the file's decision note:
    # 0.02 m3 = 20 L > 10 L FAILs (a no-conversion evaluator passes it).
    @test evaluate_constraint(constraint_id="vol", operator="<=",
                              value=0.02, bound=10.0,
                              value_unit="m3", bound_unit="L")[1] == "FAIL"
    # The 3 version cases, through check_schema_version. The file's
    # own expected outcome and the Julia expectation must agree,
    # and the evaluator must match both.
    for case in vectors["version_cases"]
        accepted, reason = check_schema_version(case["request_schema_version"])
        @test accepted == case["julia_expected"]["accepted"]
        @test accepted == case["expected"]["accepted"]
        if haskey(case["julia_expected"], "error")
            @test reason == case["julia_expected"]["error"]
            @test reason == case["expected"]["error"]
        end
    end
    # The 2 aggregation cases, through overall_status.
    for case in vectors["aggregation_cases"]
        checks = String.(case["input"]["checks"])
        @test overall_status(checks) == case["julia_expected"]["status"]
        @test overall_status(checks) == case["python_expected"]["status"]
    end
end
