# Tests for the learned-dynamics search (dynamics_search.jl).
#
# STANDALONE — run separately from test/runtests.jl, or on its
# own: this file loads only PlanningSearch (Distributions +
# LinearAlgebra stdlib), no JuMP, no Flux, no MuZero.jl. The
# LP-split pattern is the same as test/training_loop.jl.
#
# Run: julia --project=julia-current planning-search/test/dynamics_search.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
#
# MEASURED NUMBERS (2026-11-11, Julia 1.13.3, canonical env;
# model fitted on transitions from varied-spec seeds 1..8,
# 258 transitions; held out on seeds 101..104, 135 transitions):
#   held-out mean absolute prediction error 0.0719
#   held-out max absolute prediction error 0.4122
# The thresholds below are set from those measurements (mean
# < 0.10, max < 0.50), not from an unmeasured guess.

using Test

include(joinpath(@__DIR__, "..", "PlanningSearch.jl"))
using .PlanningSearch
const GI = PlanningSearch.GI
const MCTS = PlanningSearch.MCTS

const PS_DIR = joinpath(@__DIR__, "..")

# One fitted model shared by the testsets that need it, so the
# fit (and its measured error) is computed once.
const BASE_SPEC = FoodPlanSpec()
const TRAIN_TRANSITIONS =
    generate_transitions(BASE_SPEC, collect(1:8))
const HELDOUT_TRANSITIONS =
    generate_transitions(BASE_SPEC, collect(101:104))
const DYN_MODEL = fit_dynamics_model(TRAIN_TRANSITIONS)
const HELDOUT_MEAN_ERR, HELDOUT_MAX_ERR =
    dynamics_prediction_error(DYN_MODEL, HELDOUT_TRANSITIONS)

println("  dynamics model: train transitions=",
        length(TRAIN_TRANSITIONS),
        " held-out transitions=", length(HELDOUT_TRANSITIONS),
        " held-out mean abs error=", HELDOUT_MEAN_ERR,
        " max abs error=", HELDOUT_MAX_ERR)

@testset "transition generation is deterministic and complete" begin
    a = generate_transitions(BASE_SPEC, [1])
    b = generate_transitions(BASE_SPEC, [1])
    @test length(a) == length(b)
    @test length(a) > 0
    @test all(i -> a[i].state == b[i].state &&
              a[i].action == b[i].action &&
              a[i].next_state == b[i].next_state &&
              a[i].reward == b[i].reward, eachindex(a))
    # Every transition advances the plan by exactly one step,
    # and the reward is a plan-quality share in [0, 1].
    for t in a
        @test t.next_state[3] == t.state[3] + 1
        @test 0.0 <= t.reward <= 1.0
    end
    # The optimum transition on the BASE spec (not a varied one:
    # a varied spec's water budget may not admit potato 20 ha
    # after wheat 50 ha) carries the optimum reward.
    base_game = GI.init(BASE_SPEC)
    GI.play!(base_game, (1, 50.0))
    GI.play!(base_game, (2, 20.0))
    @test GI.current_state(base_game) == (50.0, 20.0, 2)
    @test GI.white_reward(base_game) ≈ 600 / 650
    # And some transition in the varied set reaches a terminal
    # state with a positive reward.
    @test any(t -> t.next_state[3] == 2 && t.reward > 0.0, a)
    # Different seeds give different (varied) specs.
    @test generate_transitions(BASE_SPEC, [2]) != a
end

@testset "dynamics features are finite shares in [0, 1]" begin
    spec = BASE_SPEC
    feats = dynamics_features(spec, (50.0, 0.0, 1), (2, 20.0))
    @test length(feats) == PlanningSearch.N_DYNAMICS_FEATURES
    @test all(isfinite.(feats))
    @test all(0.0 .<= feats .<= 1.0)
    # First eight are the plan features of the state.
    @test feats[1:8] == plan_features(spec, (50.0, 0.0, 1))
    # Crop one-hot + area share.
    @test feats[9] == 0.0 && feats[10] == 1.0
    @test feats[11] ≈ 20.0 / 100.0
    wheat_feats = dynamics_features(spec, (0.0, 0.0, 0), (1, 50.0))
    @test wheat_feats[9] == 1.0 && wheat_feats[10] == 0.0
    @test wheat_feats[11] ≈ 50.0 / 100.0
end

@testset "dynamics model fits; held-out error below measured threshold" begin
    @test DYN_MODEL.fitted == true
    @test size(DYN_MODEL.weights) ==
          (PlanningSearch.N_DYNAMICS_FEATURES + 1,
           PlanningSearch.N_DYNAMICS_OUTPUTS)
    @test all(isfinite.(DYN_MODEL.weights))
    # Thresholds set from the measured held-out error above
    # (mean 0.0719, max 0.4122 on seeds 101..104): mean < 0.10,
    # max < 0.50. These are the numbers the model actually
    # achieves; they were not asserted before measuring.
    @test HELDOUT_MEAN_ERR < 0.10
    @test HELDOUT_MAX_ERR < 0.50
    @test isfinite(HELDOUT_MEAN_ERR) && isfinite(HELDOUT_MAX_ERR)
    # No usable transitions -> the neutral (unfitted) model.
    neutral = fit_dynamics_model(DynamicsTransition[])
    @test neutral.fitted == false
    # A transition with a non-finite reward is skipped, not trained on.
    bad = DynamicsTransition(BASE_SPEC, (0.0, 0.0, 0), (1, 50.0),
                             (50.0, 0.0, 1), NaN)
    skipped = fit_dynamics_model(vcat(TRAIN_TRANSITIONS, [bad]))
    @test skipped.fitted == true
    @test all(isfinite.(skipped.weights))
    # Empty transition list -> (NaN, NaN), not a crash
    # (NaN != NaN, so check with isnan).
    empty_err = dynamics_prediction_error(
        DYN_MODEL, DynamicsTransition[])
    @test isnan(empty_err[1]) && isnan(empty_err[2])
end

@testset "predict_transition is sane and bounded" begin
    spec = BASE_SPEC
    next_feats, reward = predict_transition(
        DYN_MODEL, spec, (50.0, 0.0, 1), (2, 20.0))
    @test length(next_feats) == 8
    @test all(0.0 .<= next_feats .<= 1.0)
    @test 0.0 <= reward <= 1.0
    # The optimum transition's predicted reward is close to the
    # true 600/650 (within 0.35 — measured 0.319 for this
    # transition on 2026-11-11; the reward is the hardest output
    # to fit, 0 for intermediate steps and the full delivered
    # share at the terminal step, and the held-out max error
    # overall is 0.4122, so a single-transition threshold is
    # set from this measurement, not from the 0.0719 mean).
    println("  predicted reward for the optimum step: ", reward,
            " (true ", 600 / 650, ")")
    @test abs(reward - 600 / 650) < 0.35
    # The predicted next features are close to the true ones
    # (mean error over this one transition below 0.20 —
    # measured 0.148 on 2026-11-11).
    truth = plan_features(spec, (50.0, 20.0, 2))
    @test sum(abs.(next_feats .- truth)) / 8 < 0.20
    # An unfitted model predicts the current features, zero reward.
    neutral = fit_dynamics_model(DynamicsTransition[])
    nf, nr = predict_transition(
        neutral, spec, (50.0, 0.0, 1), (2, 20.0))
    @test nf == plan_features(spec, (50.0, 0.0, 1))
    @test nr == 0.0
    # A non-finite state falls back to the neutral prediction.
    nf2, nr2 = predict_transition(
        DYN_MODEL, spec, (NaN, 0.0, 0), (1, 50.0))
    @test nr2 == 0.0
end

@testset "state_from_features round-trips on the action grid" begin
    spec = BASE_SPEC
    for state in [(0.0, 0.0, 0), (50.0, 0.0, 1), (50.0, 20.0, 2),
                  (60.0, 10.0, 2)]
        @test state_from_features(
            spec, plan_features(spec, state)) == state
    end
    # Small prediction error snaps to the nearest grid state.
    noisy = plan_features(spec, (50.0, 20.0, 2))
    noisy = noisy .+ [0.01, -0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    @test state_from_features(spec, noisy) == (50.0, 20.0, 2)
end

@testset "MinMaxStats normalisation stays in bounds, no NaN" begin
    stats = MinMaxStats()
    # No values yet: the neutral 0.5, never NaN.
    @test normalize_value(stats, 0.7) == 0.5
    @test normalize_value(stats, NaN) == 0.5
    # Two distinct values define the range.
    update_minmax!(stats, 0.2)
    update_minmax!(stats, 0.8)
    @test normalize_value(stats, 0.2) == 0.0
    @test normalize_value(stats, 0.8) == 1.0
    @test normalize_value(stats, 0.5) ≈ 0.5
    # Out-of-range values clamp into [0, 1].
    @test normalize_value(stats, -1.0) == 0.0
    @test normalize_value(stats, 2.0) == 1.0
    # A constant value stream normalises without NaN/div-by-zero.
    const_stats = MinMaxStats()
    for _ in 1:3
        update_minmax!(const_stats, 0.3)
    end
    @test normalize_value(const_stats, 0.3) == 0.5
    @test isfinite(normalize_value(const_stats, 0.3))
    # Non-finite values are ignored, never stored.
    update_minmax!(const_stats, NaN)
    @test const_stats.count == 3
    @test normalize_value(const_stats, Inf) == 0.5
end

@testset "dynamics value ranks the better plan above the worse one" begin
    spec = BASE_SPEC
    # An unfitted model is neutral.
    neutral = fit_dynamics_model(DynamicsTransition[])
    @test predict_dynamics_value(neutral, spec, (0.0, 0.0, 0)) == 0.5
    # The terminal optimum state has exactly its delivered share.
    @test predict_dynamics_value(DYN_MODEL, spec, (50.0, 20.0, 2)) ≈
          600 / 650
    # Unlike the linear value model (which ranks wheat 60 ha above
    # wheat 50 ha as a first step — see its docstring), the
    # dynamics model ranks the 50 ha first step above the 60 ha
    # one: 50 ha leaves the water for the potato that completes
    # the optimum, 60 ha does not.
    @test predict_dynamics_value(DYN_MODEL, spec, (50.0, 0.0, 1)) >
          predict_dynamics_value(DYN_MODEL, spec, (60.0, 0.0, 1))
    @test 0.0 <= predict_dynamics_value(
        DYN_MODEL, spec, (0.0, 0.0, 0)) <= 1.0
    # The root value is a real prediction, not the neutral 0.5.
    @test predict_dynamics_value(DYN_MODEL, spec, (0.0, 0.0, 0)) != 0.5
end

@testset "dynamics oracle returns a valid (P, V) pair" begin
    spec = BASE_SPEC
    neutral = fit_dynamics_model(DynamicsTransition[])
    oracle = DynamicsOracle(neutral, spec)
    P, V = oracle((0.0, 0.0, 0))
    @test length(P) == length(GI.available_actions(GI.init(spec)))
    @test sum(P) ≈ 1.0
    @test all(P .>= 0.0)
    @test 0.0 <= V <= 1.0
    # A neutral model has no preference: the prior is uniform.
    @test maximum(P) - minimum(P) < 1e-9
    # A fitted model has a real preference, not a uniform prior.
    fitted = DynamicsOracle(DYN_MODEL, spec)
    Pf, Vf = fitted((0.0, 0.0, 0))
    @test length(Pf) == 7
    @test sum(Pf) ≈ 1.0
    @test all(Pf .>= 0.0)
    @test 0.0 <= Vf <= 1.0
    @test maximum(Pf) > 1 / length(Pf)
    # NOTE: we do NOT assert the fitted prior ranks wheat 50 ha
    # above wheat 60 ha. Measured 2026-11-11, the dynamics prior
    # at the root puts its largest mass on wheat 60 ha (0.38 vs
    # 0.22 for 50 ha) — the one-step lookahead does not yet see
    # that 60 ha starves the potato step. MCTS corrects this
    # through simulation values, and the search test below shows
    # it still finds the optimum on all five seeds.
    # Terminal state: no actions, empty prior, bounded value.
    Pt, Vt = fitted((50.0, 20.0, 2))
    @test isempty(Pt)
    @test 0.0 <= Vt <= 1.0
end

@testset "MCTS with the dynamics oracle finds the known optimum" begin
    spec = BASE_SPEC
    # Default: 1000 sims, visit-count policy, seed 1234.
    c = run_search_with_dynamics(spec, DYN_MODEL).candidate
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
    # The other four seeds, at 500 sims (the search finds the
    # optimum at 500 sims on all five seeds — measured
    # 2026-11-11 — so the cheaper run is used here).
    for seed in (7, 42, 99, 2024)
        cs = run_search_with_dynamics(
            spec, DYN_MODEL; nsims=500, seed=seed).candidate
        @test cs.delivered == 600.0
        @test cs.shortage == 50.0
    end
    # Mean-Q selection also finds it at 500 sims.
    cq = run_search_with_dynamics(
        spec, DYN_MODEL; nsims=500, seed=1234,
        selection=:mean_q).candidate
    @test cq.delivered == 600.0
    @test cq.shortage == 50.0
end

@testset "reanalyse refreshes targets, never verified status" begin
    spec = BASE_SPEC
    mem = VerifiedMemory(200)
    for s in (1, 2)
        sspec = vary_spec(spec, s)
        insert_verified!(mem, VerifiedSample(
            (50.0, 20.0, 2), [0.5, 0.5], 600 / 650,
            "varied-$s", sspec, true))
        insert_verified!(mem, VerifiedSample(
            (0.0, 0.0, 0), [1.0], 0.0, "varied-$s", sspec, true))
    end
    neutral = fit_dynamics_model(DynamicsTransition[])
    tn = reanalyse(mem, neutral)
    tf = reanalyse(mem, DYN_MODEL)
    @test length(tn) == memory_size(mem) == 4
    @test length(tf) == 4
    # Every target stays in [0, 1] and keeps its sample's identity.
    for (i, t) in enumerate(tf)
        @test 0.0 <= t.new_target <= 1.0
        @test t.index == i
        @test t.spec_id == memory_samples(mem)[i].spec_id
        @test t.state == memory_samples(mem)[i].state
        @test t.old_outcome == memory_samples(mem)[i].outcome
    end
    # Verified status is copied unchanged, never recomputed:
    # every stored sample was verified, every target says so.
    @test all(t -> t.verified, tf)
    @test all(t -> t.verified, tn)
    @test all(t -> t.verified ==
              memory_samples(mem)[t.index].verified, tf)
    # The targets actually update when the model changes: the
    # neutral model targets everything at 0.5, the fitted model
    # does not (at least one target differs).
    @test all(t -> t.new_target == 0.5, tn)
    @test any(t -> t.new_target != 0.5, tf)
    # Re-running reanalyse is deterministic, and the memory is
    # not mutated by it.
    tf2 = reanalyse(mem, DYN_MODEL)
    @test [t.new_target for t in tf2] == [t.new_target for t in tf]
    @test memory_size(mem) == 4
    @test all(s -> s.verified, memory_samples(mem))
end

@testset "dynamics oracle held-out: no worse than the rollout oracle" begin
    heldout = evaluate_dynamics_heldout(
        BASE_SPEC, [101, 102, 103, 104], DYN_MODEL,
        (c, s) -> verify_candidate(c; spec=s);
        nsims=200, seed=1234)
    println("  dynamics held-out: rollout PASS rate=",
            heldout.rollout_pass_rate,
            " learned PASS rate=", heldout.learned_pass_rate,
            " rollout mean shortage=", heldout.rollout_mean_shortage,
            " t learned mean shortage=", heldout.learned_mean_shortage,
            " t replaced=", replacement_decision(heldout))
    # The existing replacement rule applies unchanged: the
    # dynamics oracle is adopted only if its held-out
    # verified-PASS rate is at least as high and its mean
    # shortage no worse. Measured 2026-11-11: both PASS rates
    # 1.0, learned mean shortage 117.5 t vs rollout 147.5 t —
    # replaced.
    @test heldout.learned_pass_rate >= heldout.rollout_pass_rate
    @test heldout.learned_mean_shortage <=
          heldout.rollout_mean_shortage + 1e-9
    @test replacement_decision(heldout) == true
end

@testset "a dynamics-search candidate is still only a candidate" begin
    spec = BASE_SPEC
    c = run_search_with_dynamics(spec, DYN_MODEL).candidate
    @test c.status == "CANDIDATE"
    @test c.verified == false
    # Even a PASS verdict without human approval is not verified.
    @test verify_candidate(c).status == "PASS"
    @test verified_status(c, "PASS", false) == false
    @test verified_status(c, "PASS", true) == true
    @test c.needs_human_decision == true
end

@testset "no MuZero.jl / Flux code in dynamics_search.jl" begin
    # Match code lines only: the header comment names MuZero.jl
    # as the design inspiration, and the docstrings name the
    # design ideas taken from it, so comment lines and
    # docstring lines are excluded, as in the no-AlphaZero-import
    # test in runtests.jl (which excludes comments). A line
    # inside a """...""" block is a docstring line.
    lines = readlines(joinpath(PS_DIR, "dynamics_search.jl"))
    code = String[]
    in_docstring = false
    for l in lines
        stripped = strip(l)
        if startswith(stripped, "#")
            continue
        end
        if count(c -> c == '"', l) >= 3 && occursin("\"\"\"", l)
            # A line opening (or closing) a docstring: toggle
            # once per """ pair on the line; the line itself is
            # not code.
            in_docstring = !in_docstring
            continue
        end
        in_docstring && continue
        push!(code, l)
    end
    for ident in ("MuZero", "Flux", "Zygote", "BSON", "JLD2",
                  "ReinforcementLearningBase", "TensorBoardLogger",
                  "using MuZero", "SelfPlay", "ReplayBuffer")
        @test !any(l -> occursin(ident, l), code)
    end
    # And the module loads no new dependency: only the stdlib
    # LinearAlgebra already used by training_loop.jl.
    @test !any(l -> occursin(r"^\s*using\s+(Flux|MuZero|CUDA)", l), code)
end
