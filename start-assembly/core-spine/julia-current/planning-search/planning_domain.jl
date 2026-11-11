# ORIGINAL START code (2026-11-11) — planning domain for the copied
# AlphaZero.jl interface. Pattern learned from the ConnectFour example
# (how a domain implements the interface); no ConnectFour code copied.
#
# Domain: the synthetic 1-site, 2-crop example used across the spine.
#   Wheat:  4 t/ha, 1,200 m3/ha, demand 250 t
#   Potato: 20 t/ha, 2,000 m3/ha, demand 400 t
#   Land 100 ha, water 100,000 m3, loss-free.
#   Known optimum (JuMP+HiGHS / SciPy / CPMpy / CVXPY): delivered
#   600 t, shortage 50 t, production 600 t, land 70 ha, water 100,000 m3
#   (wheat 50 ha, potato 20 ha).
#
# How it is played: two sequential allocation decisions. Step 0 chooses
# the wheat area, step 1 chooses the potato area, step 2 is terminal.
# Actions are total areas per crop (not increments). An action is only
# available if, after it, land and water stay within budget AND the
# crop's production does not exceed its demand (no wasteful
# overproduction — the same rule as the LP's Stage 3).
#
# Reward: 0 for the intermediate (wheat) step; at the terminal step,
# delivered / 650, i.e. plan quality in [0, 1]. There is no opponent,
# no win/loss, and no "white" player: white_playing is always true
# (planning alias planner_acting), two_players is false.

"""
    FoodPlanSpec

Static description of the synthetic 1-site 2-crop planning problem.
"""
struct FoodPlanSpec <: GI.AbstractGameSpec
    yields::Vector{Float64}       # t/ha per crop: [wheat, potato]
    water_per_ha::Vector{Float64} # m3/ha per crop
    demand::Vector{Float64}       # t per crop
    land_max::Float64
    water_max::Float64
    wheat_options::Vector{Float64}  # ha choices for wheat
    potato_options::Vector{Float64} # ha choices for potato
end

FoodPlanSpec() = FoodPlanSpec(
    [4.0, 20.0], [1200.0, 2000.0], [250.0, 400.0],
    100.0, 100_000.0,
    [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    [0.0, 5.0, 10.0, 15.0, 20.0, 25.0],
)

"""A partial plan: (wheat_ha, potato_ha, step). Step 0 = choose wheat,
step 1 = choose potato, step 2 = terminal (plan complete)."""
const PlanState = Tuple{Float64, Float64, Int}

mutable struct FoodPlanEnv <: GI.AbstractGameEnv
    spec::FoodPlanSpec
    state::PlanState
end

# --- Totals for a (partial or complete) plan ---
function plan_totals(spec::FoodPlanSpec, wheat_ha, potato_ha)
    areas = (wheat_ha, potato_ha)
    production_per_crop = spec.yields .* areas
    # Production beyond a crop's demand is waste, not delivered food.
    delivered_per_crop = min.(production_per_crop, spec.demand)
    delivered = sum(delivered_per_crop)
    production = sum(production_per_crop)
    shortage = sum(spec.demand) - delivered
    land = sum(areas)
    water = sum(spec.water_per_ha .* areas)
    return (delivered=delivered, shortage=shortage, production=production,
            land=land, water=water)
end

plan_totals(spec::FoodPlanSpec, state::PlanState) =
    plan_totals(spec, state[1], state[2])

# --- Interface implementation ---
GI.spec(env::FoodPlanEnv) = env.spec
GI.init(spec::FoodPlanSpec) = FoodPlanEnv(spec, (0.0, 0.0, 0))
GI.set_state!(env::FoodPlanEnv, state::PlanState) = (env.state = state; env)
GI.current_state(env::FoodPlanEnv) = env.state
GI.two_players(::FoodPlanSpec) = false
GI.actions(spec::FoodPlanSpec) =
    vcat([(1, h) for h in spec.wheat_options],
         [(2, h) for h in spec.potato_options])
GI.vectorize_state(::FoodPlanSpec, state::PlanState) =
    Float32[state[1] / 100.0, state[2] / 100.0, state[3] / 2.0]
GI.game_terminated(env::FoodPlanEnv) = env.state[3] >= 2
GI.white_playing(::FoodPlanEnv) = true  # single planner, no opponent

function GI.actions_mask(env::FoodPlanEnv)
    spec = env.spec
    wheat_ha, potato_ha, step = env.state
    mask = falses(length(GI.actions(spec)))
    step >= 2 && return mask
    crop = step + 1  # step 0 -> wheat (crop 1), step 1 -> potato (crop 2)
    for (i, (c, ha)) in enumerate(GI.actions(spec))
        c == crop || continue
        new_wheat = crop == 1 ? ha : wheat_ha
        new_potato = crop == 2 ? ha : potato_ha
        t = plan_totals(spec, new_wheat, new_potato)
        # Feasible only within land/water budgets and without
        # overproducing a crop beyond its demand.
        if t.land <= spec.land_max + 1e-9 &&
           t.water <= spec.water_max + 1e-9 &&
           spec.yields[crop] * ha <= spec.demand[crop] + 1e-9
            mask[i] = true
        end
    end
    return mask
end

function GI.play!(env::FoodPlanEnv, action)
    crop, ha = action
    step = env.state[3]
    step >= 2 && error("play! on a terminal plan")
    step + 1 == crop || error("play! action crop $crop does not match step $step")
    wheat_ha, potato_ha, _ = env.state
    if crop == 1
        env.state = (ha, potato_ha, 1)
    else
        env.state = (wheat_ha, ha, 2)
    end
    return env
end

"""Plan-quality reward after a transition: 0 for intermediate steps,
delivered / total demand at the terminal step. NOT a win/loss reward."""
function GI.white_reward(env::FoodPlanEnv)
    GI.game_terminated(env) || return 0.0
    t = plan_totals(env.spec, env.state)
    return t.delivered / sum(env.spec.demand)
end

"""Heuristic value of a (partial) plan: delivered so far / total demand."""
function GI.heuristic_value(env::FoodPlanEnv)
    t = plan_totals(env.spec, env.state)
    return t.delivered / sum(env.spec.demand)
end

GI.render(env::FoodPlanEnv) =
    println("plan: wheat=$(env.state[1]) ha, potato=$(env.state[2]) ha, step=$(env.state[3])")
GI.action_string(::FoodPlanSpec, action) =
    action[1] == 1 ? "wheat $(action[2]) ha" : "potato $(action[2]) ha"

function GI.parse_action(::FoodPlanSpec, str::String)
    parts = split(strip(str))
    length(parts) == 2 || return nothing
    crop = parts[1] == "wheat" ? 1 : parts[1] == "potato" ? 2 : nothing
    crop === nothing && return nothing
    ha = tryparse(Float64, parts[2])
    ha === nothing && return nothing
    return (crop, ha)
end

GI.read_state(::FoodPlanSpec) = nothing

# --- Candidate: what a search produces ---
"""
    PlanningCandidate

The result of a search. A CANDIDATE only: `verified` is always
`false` at creation and `status` is always `"CANDIDATE"`. The search
never verifies its own output; verification is a separate step
(see verify.jl) and a plan still needs a human decision
(`needs_human_decision` is always `true`).
"""
struct PlanningCandidate
    wheat_ha::Float64
    potato_ha::Float64
    delivered::Float64
    shortage::Float64
    production::Float64
    land_ha::Float64
    water_m3::Float64
    verified::Bool
    needs_human_decision::Bool
    status::String
end

function candidate_from_state(spec::FoodPlanSpec, state::PlanState)
    t = plan_totals(spec, state)
    return PlanningCandidate(state[1], state[2], t.delivered, t.shortage,
                             t.production, t.land, t.water,
                             false, NEEDS_HUMAN_DECISION, "CANDIDATE")
end

"""
    run_search(spec=FoodPlanSpec(); nsims=1000, cpuct=1.0, seed=1234,
               selection=:visits)

Run MCTS (copied search, rollout oracle — no neural network) over
the planning domain, one allocation decision at a time. Returns a
`PlanningCandidate` (CANDIDATE only, never verified). Deterministic
for a fixed seed.

`selection` is how the action is picked after explore!:
  * `:visits` (default) — the most-visited action, i.e. argmax of
    the visit-count policy from the copied `MCTS.policy`.
  * `:mean_q` — the action with the highest mean Q-value (W/N) in
    the root's statistics.

NOTE (2026-11-11, measured): at nsims=500 the visit-count policy
lags the Q-values — e.g. seed 1234 chose wheat 60 ha / potato 10 ha
(delivered 440 t) even though wheat 50 ha had the higher mean Q
(0.86 vs 0.65). At nsims=1000 the visit-count policy finds the
optimum (wheat 50 ha, potato 20 ha, delivered 600 t, shortage 50 t)
on all five seeds tested (1234, 7, 42, 99, 2024); the mean-Q
selection also finds it at nsims=500 on all five seeds. The default
is therefore nsims=1000 with :visits, so the search uses the copied
policy as intended.
"""
function run_search(spec::FoodPlanSpec=FoodPlanSpec();
                    nsims=1000, cpuct=1.0, seed=1234, selection=:visits)
    selection in (:visits, :mean_q) ||
        throw(ArgumentError("selection must be :visits or :mean_q"))
    Random.seed!(seed)
    oracle = MCTS.RolloutOracle(spec)
    env = MCTS.Env(spec, oracle; cpuct=cpuct)
    game = GI.init(spec)
    while !GI.plan_terminated(game)
        MCTS.explore!(env, game, nsims)
        actions = GI.available_actions(game)
        if selection == :visits
            _, π = MCTS.policy(env, game)
            GI.play!(game, actions[argmax(π)])
        else
            info = env.tree[GI.current_state(game)]
            qs = [s.W / max(s.N, 1) for s in info.stats]
            GI.play!(game, actions[argmax(qs)])
        end
    end
    return candidate_from_state(spec, GI.current_state(game))
end
