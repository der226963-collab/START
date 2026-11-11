# ORIGINAL START code (2026-11-11) — planning training loop.
#
# This REPLACES the AlphaZero.jl training loop (src/training.jl,
# 360 lines) with original START code. It is NOT a copy: the game
# loop's self-play, its opponent-based evaluation, and its network
# training were studied (training.jl, learning.jl, params.jl) only
# to understand the shape being replaced — no code from
# training.jl, learning.jl, simulations.jl, or networks/ is in
# this file, and there is no network library here at all. The only
# external package beyond the standard library is Distributions
# (already used by the copied MCTS code); the fitted model below
# is plain least squares from LinearAlgebra (stdlib).
#
# What this loop does, and what it does NOT do:
#  * Per iteration it generates candidate plans with the copied
#    MCTS search over a small set of varied specs (the 1-site
#    2-crop spec with demand / land / water limits perturbed
#    deterministically by seed — never a real region), verifies
#    each candidate with the verify function it is given, and
#    keeps ONLY candidates whose verdict is PASS as training
#    samples. Rejected candidates are counted and recorded, and
#    never enter the memory. There is no opponent, no win/loss,
#    and no game outcome anywhere in this loop.
#  * From the verified memory it fits a small transparent model:
#    a linear value model over spec-normalised plan features.
#    That model becomes a learned oracle the MCTS search can use
#    in place of the rollout oracle.
#  * A new oracle replaces the current one ONLY when, on a
#    held-out set of specs (never used in its training), its
#    MCTS candidates reach a verified-PASS rate at least as high
#    as the current oracle's, with a mean shortage no worse.
#    The decision and the held-out numbers are recorded in the
#    iteration report. Even after replacement the oracle is only
#    a candidate generator: it never verifies a plan, and a plan
#    still needs a PASS verdict plus a human approval.
#  * The verify step is passed in as a function, so this file
#    stays loadable on Distributions alone: the standalone tests
#    use the constraint verify, and the LP runner passes the
#    combined verify (constraint + JuMP+HiGHS cross-check).
#
# GUARDRAILS (non-negotiable):
#  * Training never marks a plan verified. A sample enters the
#    memory only if the candidate it came from passed verify;
#    `insert_verified!` refuses anything else.
#  * The loop never changes the verify rules. It only calls the
#    verify function it is given and records the verdict.

using LinearAlgebra

#####
##### Verified samples and memory
#####

"""
    VerifiedSample

One training sample, taken from a candidate that PASSED verify.
`state` is a partial plan, `policy` is the MCTS visit-count
policy at that state, `outcome` is the final plan quality
(delivered / total demand) of the candidate, `spec_id` names
the varied spec the candidate was generated from, and `spec`
is that spec itself (features are spec-normalised, so the
fitted model can generalise across specs). `verified` is
always true for a sample that is stored; a sample built with
`verified=false` can never be inserted (see insert_verified!).
"""
struct VerifiedSample
    state::PlanState
    policy::Vector{Float64}
    outcome::Float64
    spec_id::String
    spec::FoodPlanSpec
    verified::Bool
end

"""
    VerifiedMemory(capacity=200)

A bounded store of verified samples only, oldest first. When
full, inserting a new sample drops the oldest one. Nothing
unverified can be inserted: insert_verified! throws for a
sample with verified=false or a non-finite outcome.
"""
mutable struct VerifiedMemory
    samples::Vector{VerifiedSample}
    capacity::Int
    function VerifiedMemory(capacity::Int=200)
        capacity >= 1 ||
            throw(ArgumentError("capacity must be >= 1"))
        new(VerifiedSample[], capacity)
    end
end

memory_size(mem::VerifiedMemory) = length(mem.samples)
memory_samples(mem::VerifiedMemory) = copy(mem.samples)

"""
    insert_verified!(mem, sample)

Store a verified sample. Throws ArgumentError for an
unverified sample or a non-finite outcome. Drops the oldest
sample when the memory is at capacity.
"""
function insert_verified!(mem::VerifiedMemory, sample::VerifiedSample)
    sample.verified ||
        throw(ArgumentError(
            "cannot insert an unverified sample into VerifiedMemory"))
    isfinite(sample.outcome) ||
        throw(ArgumentError(
            "cannot insert a sample with a non-finite outcome"))
    push!(mem.samples, sample)
    while length(mem.samples) > mem.capacity
        popfirst!(mem.samples)
    end
    return mem
end

#####
##### Varied specs (synthetic only, deterministic by seed)
#####

"""
    vary_spec(base, seed) -> FoodPlanSpec

Return a deterministic perturbation of the base spec: wheat
demand 200..300 t, potato demand 300..450 t, land 80..120 ha,
water 80,000..120,000 m3. Yields, water per hectare, and the
action grids are unchanged, and the empty plan (0 ha, 0 ha)
stays available, so every varied spec has a feasible candidate.
Same seed -> same spec. These are synthetic variations for
training and held-out evaluation, never a real region.
"""
function vary_spec(base::FoodPlanSpec, seed::Int)
    rng = Random.MersenneTwister(seed)
    wheat_demand = 200.0 + 10.0 * rand(rng, 0:10)
    potato_demand = 300.0 + 10.0 * rand(rng, 0:15)
    land_max = 80.0 + 5.0 * rand(rng, 0:8)
    water_max = 80_000.0 + 5_000.0 * rand(rng, 0:8)
    return FoodPlanSpec(base.yields, base.water_per_ha,
                        [wheat_demand, potato_demand],
                        land_max, water_max,
                        base.wheat_options, base.potato_options)
end

spec_id_for_seed(seed::Int) = "varied-$(seed)"

#####
##### Plan features and the linear value model
#####

const N_FEATURES = 8

"""
    plan_features(spec, state) -> Vector{Float64}

Eight spec-normalised features of a (partial) plan, each in
[0, 1] for a feasible state: wheat and potato area as a share
of the land budget, decision step, delivered so far as a share
of total demand, water and land used as shares of their
budgets, and each crop's production as a share of its demand.
Because every feature is a share of its own spec's limits,
one fitted model can be used across varied specs.
"""
function plan_features(spec::FoodPlanSpec, state::PlanState)
    wheat_ha, potato_ha, step = state
    t = plan_totals(spec, wheat_ha, potato_ha)
    total_demand = sum(spec.demand)
    return Float64[
        wheat_ha / spec.land_max,
        potato_ha / spec.land_max,
        step / 2.0,
        t.delivered / total_demand,
        t.water / spec.water_max,
        t.land / spec.land_max,
        (spec.yields[1] * wheat_ha) / spec.demand[1],
        (spec.yields[2] * potato_ha) / spec.demand[2],
    ]
end

"""
    LinearValueModel

A transparent value model: a weight vector over the eight
plan features plus a bias term (length 9). predict_value is
the dot product, clamped to [0, 1]. No hidden layers, no
network library: the weights are printed in the iteration
report and can be read by a human.

Known limitation (measured 2026-11-11): the linear form
cannot express interactions — e.g. water committed to wheat
while potato still needs water — so it can rank two
intermediate plans the wrong way (it ranks wheat 60 ha above
wheat 50 ha as a first step, even though 50 ha is the better
plan). That is why the model is never trusted on its own:
whether the learned oracle actually helps is judged by the
held-out comparison in the loop, and a worse oracle is never
adopted.
"""
struct LinearValueModel
    weights::Vector{Float64}
end

"""
    fit_value_model(samples; ridge=1.0) -> LinearValueModel

Fit the value model by ridge least squares on the verified
samples: features (plus bias) against the recorded outcome.
Samples with non-finite features or outcomes are skipped,
never trained on. With no usable samples, return a neutral
model (all weights zero, bias 0.5) that predicts 0.5 for
every state.
"""
function fit_value_model(samples::AbstractVector{VerifiedSample};
                         ridge::Float64=1.0)
    usable = VerifiedSample[]
    for s in samples
        feats = plan_features(s.spec, s.state)
        if all(isfinite.(feats)) && isfinite(s.outcome)
            push!(usable, s)
        end
    end
    if isempty(usable)
        return LinearValueModel(vcat(zeros(Float64, N_FEATURES), [0.5]))
    end
    n = length(usable)
    X = Matrix{Float64}(undef, n, N_FEATURES + 1)
    y = Vector{Float64}(undef, n)
    for i in 1:n
        X[i, 1:N_FEATURES] .= plan_features(usable[i].spec, usable[i].state)
        X[i, N_FEATURES + 1] = 1.0
        y[i] = usable[i].outcome
    end
    w = (X' * X + ridge * I) \ (X' * y)
    return LinearValueModel(Vector{Float64}(w))
end

"""
    predict_value(model, spec, state) -> Float64

Estimated plan quality (delivered / total demand) reachable
from a partial plan, clamped to [0, 1].
"""
function predict_value(model::LinearValueModel,
                       spec::FoodPlanSpec, state::PlanState)
    feats = plan_features(spec, state)
    if !all(isfinite.(feats))
        return 0.5
    end
    v = dot(model.weights, vcat(feats, 1.0))
    return clamp(v, 0.0, 1.0)
end

#####
##### The learned oracle
#####

"""
    LearnedOracle(model, spec; temperature=0.1)

An oracle the MCTS search can use in place of the rollout
oracle. Calling it on a state returns (P, V): V is the
fitted value of the state, and P scores each available
action by the fitted value of the plan reached by taking it
(softmax over successor values, so actions that lead to
better predicted plans get a higher prior). It is bound to
one spec at a time — the model itself is spec-independent,
so a fresh oracle is built per spec from the same model.
"""
struct LearnedOracle <: Function
    model::LinearValueModel
    spec::FoodPlanSpec
    temperature::Float64
    LearnedOracle(model, spec, temperature=0.1) =
        new(model, spec, temperature)
end

function (o::LearnedOracle)(state)
    game = GI.init(o.spec, state)
    actions = GI.available_actions(game)
    if isempty(actions)
        return (Float64[], predict_value(o.model, o.spec, state))
    end
    values = Float64[]
    for a in actions
        next_game = GI.clone(game)
        GI.play!(next_game, a)
        push!(values,
              predict_value(o.model, o.spec, GI.current_state(next_game)))
    end
    m = maximum(values)
    exps = exp.((values .- m) ./ o.temperature)
    P = exps ./ sum(exps)
    V = predict_value(o.model, o.spec, state)
    return (P, V)
end

#####
##### Search with a given oracle (records the decision trace)
#####

"""
    run_search_with_oracle(spec, oracle; nsims, cpuct, seed, selection)

Run MCTS with the given oracle over the planning domain, one
allocation decision at a time, exactly as run_search does with
the rollout oracle — but the oracle is a parameter, so the
rollout oracle and a learned oracle can be compared on the
same spec. Returns (candidate, trace): the candidate is a
CANDIDATE only (never verified), and the trace is the list of
(state, MCTS policy) pairs at each decision step, which is
what becomes training samples once the candidate passes
verify. Deterministic for a fixed seed.
"""
function run_search_with_oracle(spec::FoodPlanSpec, oracle;
                                nsims::Int=200, cpuct::Float64=1.0,
                                seed::Int=1234, selection::Symbol=:visits)
    selection in (:visits, :mean_q) ||
        throw(ArgumentError("selection must be :visits or :mean_q"))
    Random.seed!(seed)
    env = MCTS.Env(spec, oracle; cpuct=cpuct)
    game = GI.init(spec)
    trace = Tuple{PlanState, Vector{Float64}}[]
    while !GI.plan_terminated(game)
        MCTS.explore!(env, game, nsims)
        actions = GI.available_actions(game)
        _, π = MCTS.policy(env, game)
        push!(trace, (GI.current_state(game), copy(π)))
        if selection == :visits
            GI.play!(game, actions[argmax(π)])
        else
            info = env.tree[GI.current_state(game)]
            qs = [s.W / max(s.N, 1) for s in info.stats]
            GI.play!(game, actions[argmax(qs)])
        end
    end
    return (candidate=candidate_from_state(spec, GI.current_state(game)),
            trace=trace)
end

#####
##### Held-out evaluation and the replacement rule
#####

"""
    HeldoutResult

Outcome of one held-out evaluation: the verified-PASS rate
and the mean shortage of MCTS candidates generated with the
rollout oracle and with a learned oracle, over the same
held-out specs. PASS rate is the replacement criterion; mean
shortage is the quality tie-breaker (a candidate can pass
verify while still being far from the best plan).
"""
struct HeldoutResult
    rollout_pass_rate::Float64
    learned_pass_rate::Float64
    rollout_mean_shortage::Float64
    learned_mean_shortage::Float64
    n_specs::Int
end

"""
    evaluate_heldout(base_spec, heldout_seeds, model, verify_fn;
                     nsims, cpuct, seed)

Run MCTS on each held-out spec twice — once with the rollout
oracle, once with the learned oracle built from `model` —
verify each candidate with verify_fn, and return the
HeldoutResult. If model is nothing (no verified samples yet),
the learned side is the rollout oracle itself, so the two
sides agree and no replacement can follow from it.
"""
function evaluate_heldout(base_spec::FoodPlanSpec,
                          heldout_seeds::AbstractVector{Int},
                          model::Union{Nothing, LinearValueModel},
                          verify_fn;
                          nsims::Int=200, cpuct::Float64=1.0,
                          seed::Int=1234)
    rollout_pass = 0
    learned_pass = 0
    rollout_short = 0.0
    learned_short = 0.0
    n = length(heldout_seeds)
    for (i, s) in enumerate(heldout_seeds)
        spec = vary_spec(base_spec, s)
        c_roll = run_search_with_oracle(
            spec, MCTS.RolloutOracle(spec);
            nsims=nsims, cpuct=cpuct, seed=seed + i).candidate
        v_roll = verify_fn(c_roll, spec)
        v_roll.status == "PASS" && (rollout_pass += 1)
        rollout_short += c_roll.shortage
        if model === nothing
            learned_pass += (v_roll.status == "PASS" ? 1 : 0)
            learned_short += c_roll.shortage
        else
            c_learn = run_search_with_oracle(
                spec, LearnedOracle(model, spec);
                nsims=nsims, cpuct=cpuct, seed=seed + i).candidate
            v_learn = verify_fn(c_learn, spec)
            v_learn.status == "PASS" && (learned_pass += 1)
            learned_short += c_learn.shortage
        end
    end
    return HeldoutResult(rollout_pass / n, learned_pass / n,
                         rollout_short / n, learned_short / n, n)
end

"""
    replacement_decision(heldout) -> Bool

The replacement rule: the new oracle replaces the current
one only if its held-out verified-PASS rate is at least as
high as the rollout oracle's AND its mean shortage is no
worse. A worse oracle is never adopted, however the numbers
are sliced — and even an adopted oracle is only a candidate
generator, never a verifier.
"""
function replacement_decision(heldout::HeldoutResult)
    return heldout.learned_pass_rate >= heldout.rollout_pass_rate &&
           heldout.learned_mean_shortage <=
               heldout.rollout_mean_shortage + 1e-9
end

#####
##### The loop
#####

"""
    IterationReport

One iteration of the loop, as recorded for the report:
how many candidates were generated, how many passed verify
and were kept as samples, how many were rejected, the memory
size afterwards, the held-out numbers for both oracles, and
whether the learned oracle replaced the current one.
"""
struct IterationReport
    iteration::Int
    generated::Int
    verified_kept::Int
    rejected::Int
    memory_size::Int
    rollout_pass_rate::Float64
    learned_pass_rate::Float64
    rollout_mean_shortage::Float64
    learned_mean_shortage::Float64
    oracle_replaced::Bool
end

"""
    PlanningLoopResult

Everything the loop returns: the per-iteration reports, the
verified memory, the final fitted model (nothing if no
verified sample was ever kept), and whether the oracle in
use at the end is a learned one.
"""
struct PlanningLoopResult
    reports::Vector{IterationReport}
    memory::VerifiedMemory
    model::Union{Nothing, LinearValueModel}
    oracle_is_learned::Bool
end

"""
    train_planning_loop!(; base_spec, iterations, train_seeds,
                         heldout_seeds, nsims, cpuct, seed,
                         capacity, verify_fn)

Run the planning training loop. Per iteration:
  1. Generate one candidate per training spec with the
     current oracle (rollout oracle first, a learned oracle
     after a replacement), verify it with verify_fn, and
     keep its decision trace as verified samples ONLY if
     the verdict is PASS. Anything else is counted as
     rejected and never enters the memory.
  2. Refit the linear value model on the whole verified
     memory.
  3. Evaluate the refitted oracle against the rollout
     oracle on the held-out specs, and replace the current
     oracle only if the replacement rule is met.
`verify_fn` takes (candidate, spec) and returns something
with a `.status` field; the default is the constraint
verify, and the LP runner passes the combined verify.
Returns a PlanningLoopResult. Nothing in this loop marks a
plan verified: samples record that a candidate passed
verify, and a candidate still needs a PASS verdict plus a
human approval to count as verified (see verified_status).
"""
function train_planning_loop!(;
        base_spec::FoodPlanSpec=FoodPlanSpec(),
        iterations::Int=3,
        train_seeds::AbstractVector{Int}=[1, 2, 3, 4],
        heldout_seeds::AbstractVector{Int}=[101, 102, 103, 104],
        nsims::Int=200,
        cpuct::Float64=1.0,
        seed::Int=1234,
        capacity::Int=200,
        verify_fn=(candidate, spec) ->
            verify_candidate(candidate; spec=spec))
    iterations >= 1 ||
        throw(ArgumentError("iterations must be >= 1"))
    isempty(train_seeds) &&
        throw(ArgumentError("train_seeds must not be empty"))
    isempty(heldout_seeds) &&
        throw(ArgumentError("heldout_seeds must not be empty"))
    memory = VerifiedMemory(capacity)
    current_model::Union{Nothing, LinearValueModel} = nothing
    reports = IterationReport[]
    for it in 1:iterations
        generated = 0
        kept = 0
        rejected = 0
        for (j, s) in enumerate(train_seeds)
            spec = vary_spec(base_spec, s)
            oracle = current_model === nothing ?
                MCTS.RolloutOracle(spec) :
                LearnedOracle(current_model, spec)
            search_seed = seed + 1000 * it + j
            result = run_search_with_oracle(
                spec, oracle; nsims=nsims, cpuct=cpuct,
                seed=search_seed)
            generated += 1
            verdict = verify_fn(result.candidate, spec)
            if verdict.status == "PASS"
                outcome = result.candidate.delivered /
                          sum(spec.demand)
                for (state, π) in result.trace
                    insert_verified!(memory, VerifiedSample(
                        state, π, outcome, spec_id_for_seed(s),
                        spec, true))
                end
                kept += 1
            else
                rejected += 1
            end
        end
        new_model = fit_value_model(memory_samples(memory))
        heldout = evaluate_heldout(
            base_spec, heldout_seeds, new_model, verify_fn;
            nsims=nsims, cpuct=cpuct, seed=seed + 5000 * it)
        replaced = replacement_decision(heldout)
        if replaced
            current_model = new_model
        end
        push!(reports, IterationReport(
            it, generated, kept, rejected, memory_size(memory),
            heldout.rollout_pass_rate, heldout.learned_pass_rate,
            heldout.rollout_mean_shortage, heldout.learned_mean_shortage,
            replaced))
    end
    return PlanningLoopResult(reports, memory, current_model,
                              current_model !== nothing)
end
