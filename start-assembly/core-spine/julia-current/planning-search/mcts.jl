# MIT License — copied code, see PROVENANCE.md.
#
# Copyright (c) 2019 Jonathan Laurent
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# --- START adaptation (2026-11-11) ---
# Copied from AlphaZero.jl v0.5.6, src/mcts.jl (326 lines),
# git HEAD 177a6eb04aedeff7542bbaeeaf2c3c6da221aa96.
# Changes vs the original (full list in PROVENANCE.md):
#  * `using ..AlphaZero: GI, Util` -> `using ..PlanningSearch: GI, apply_temperature`
#    (standalone: no AlphaZero.jl import; apply_temperature is a small
#    START-written helper in PlanningSearch.jl, not copied from util.jl).
#  * Oracle value V is plan quality under constraints, NOT a win
#    probability for "white". There is no opponent and no player switch:
#    the planner always acts, so the q-sign flip in run_simulation!
#    never triggers in a planning domain (see mapping note there).
#  * Local names wp/wr renamed planner_acting/step_reward; the
#    GI.white_playing / GI.white_reward calls are the copied interface
#    names and are kept, with planning aliases in game.jl.
#  * Docstrings reworded from game/win language to planning language.
# The MCTS algorithm itself (UCT selection, Dirichlet-noise exploration,
# rollouts, policy from visit counts) is unchanged.
#
"""
A generic, standalone implementation of Monte Carlo Tree Search.
It can be used on any game that implements `GameInterface`
and with any external oracle.

## Oracle Interface

An oracle can be any function or callable object.
  
   oracle(state)

evaluates a single state from the planner's perspective and returns
a pair `(P, V)` where:

  - `P` is a probability vector on `GI.available_actions(GI.init(gspec, state))`
  - `V` is a scalar estimating the value of the state, i.e. the quality
    of the plan that can be reached from it (0..1 in a planning domain),
    NOT a win probability. There is no opponent and no "white" player:
    see the mapping note in `run_simulation!`.
"""
module MCTS

using Distributions: Categorical, Dirichlet

using ..PlanningSearch: GI, apply_temperature

#####
##### Standard Oracles
#####

"""
    MCTS.RolloutOracle(game_spec::AbstractGameSpec, γ=1.) <: Function

This oracle estimates the value of a position by simulating a random game
from it (a rollout). Moreover, it puts a uniform prior on available actions.
Therefore, it can be used to implement the "vanilla" MCTS algorithm.
"""
struct RolloutOracle{GameSpec} <: Function
  gspec :: GameSpec
  gamma :: Float64
  RolloutOracle(gspec, γ=1.) = new{typeof(gspec)}(gspec, γ)
end

function rollout!(game, γ=1.)
  action = rand(GI.available_actions(game))
  GI.play!(game, action)
  step_reward = GI.white_reward(game)  # planning: GI.plan_reward, see game.jl
  if GI.game_terminated(game)
    return step_reward
  else
    return step_reward + γ * rollout!(game, γ)
  end
end

function (r::RolloutOracle)(state)
  g = GI.init(r.gspec, state)
  planner_acting = GI.white_playing(g)  # planning: GI.planner_acting; always true
  n = length(GI.available_actions(g))
  P = ones(n) ./ n
  total_reward = rollout!(g, r.gamma)
  V = planner_acting ? total_reward : -total_reward
  return P, V
end

struct RandomOracle{GameSpec}
  gspec :: GameSpec
end

function (r::RandomOracle)(state)
  g = GI.init(r.gspec, state)
  n = length(GI.available_actions(g))
  P = ones(n) ./ n
  V = 0.
  return P, V
end

#####
##### State Statistics
#####

struct ActionStats
  P :: Float32 # Prior probability as given by the oracle
  W :: Float64 # Cumulated Q-value for the action (Q = W/N)
  N :: Int # Number of times the action has been visited
end

struct StateInfo
  stats :: Vector{ActionStats}
  Vest  :: Float32 # Value estimate given by the oracle
end

Ntot(b::StateInfo) = sum(s.N for s in b.stats)

#####
##### MCTS Environment
#####

"""
    MCTS.Env(game_spec::AbstractGameSpec, oracle; <keyword args>)

Create and initialize an MCTS environment with a given `oracle`.

## Keyword Arguments

  - `gamma=1.`: the reward discount factor
  - `cpuct=1.`: exploration constant in the UCT formula
  - `noise_ϵ=0., noise_α=1.`: parameters for the dirichlet exploration noise
     (see below)
  - `prior_temperature=1.`: temperature to apply to the oracle's output
     to get the prior probability vector used by MCTS.

## Dirichlet Noise

A naive way to ensure exploration during training is to adopt an ϵ-greedy
policy, playing a random move at every turn instead of using the policy
prescribed by [`MCTS.policy`](@ref) with probability ϵ.
The problem with this naive strategy is that it may lead the player to make
terrible moves at critical moments, thereby biasing the policy evaluation
mechanism.

A superior alternative is to add a random bias to the neural prior for the root
node during MCTS exploration: instead of considering the policy ``p`` output
by the neural network in the UCT formula, one uses ``(1-ϵ)p + ϵη`` where ``η``
is drawn once per call to [`MCTS.explore!`](@ref) from a Dirichlet distribution
of parameter ``α``.
"""
mutable struct Env{State, Oracle}
  # Store (nonterminal) state statistics assuming the planner is to act.
  # Single-planner: there is no opponent and no player switch.
  tree :: Dict{State, StateInfo}
  # External oracle to evaluate positions
  oracle :: Oracle
  # Parameters
  gamma :: Float64 # Discount factor
  cpuct :: Float64
  noise_ϵ :: Float64
  noise_α :: Float64
  prior_temperature :: Float64
  # Performance statistics
  total_simulations :: Int64
  total_nodes_traversed :: Int64
  # Game specification
  gspec :: GI.AbstractGameSpec

  function Env(gspec, oracle;
      gamma=1., cpuct=1., noise_ϵ=0., noise_α=1., prior_temperature=1.)
    S = GI.state_type(gspec)
    tree = Dict{S, StateInfo}()
    total_simulations = 0
    total_nodes_traversed = 0
    new{S, typeof(oracle)}(
      tree, oracle, gamma, cpuct, noise_ϵ, noise_α, prior_temperature,
      total_simulations, total_nodes_traversed, gspec)
  end
end

#####
##### Access and initialize state information
#####

function init_state_info(P, V, prior_temperature)
  P = apply_temperature(P, prior_temperature)
  stats = [ActionStats(p, 0, 0) for p in P]
  return StateInfo(stats, V)
end

# Returns statistics for the current player, along with a boolean indicating
# whether or not a new node has been created.
function state_info(env, state)
  if haskey(env.tree, state)
    return (env.tree[state], false)
  else
    (P, V) = env.oracle(state)
    info = init_state_info(P, V, env.prior_temperature)
    env.tree[state] = info
    return (info, true)
  end
end

#####
##### Main algorithm
#####

function uct_scores(info::StateInfo, cpuct, ϵ, η)
  @assert iszero(ϵ) || length(η) == length(info.stats)
  sqrtNtot = sqrt(Ntot(info))
  return map(enumerate(info.stats)) do (i, a)
    Q = a.W / max(a.N, 1)
    P = iszero(ϵ) ? a.P : (1-ϵ) * a.P + ϵ * η[i]
    Q + cpuct * P * sqrtNtot / (a.N + 1)
  end
end

function update_state_info!(env, state, action_id, q)
  stats = env.tree[state].stats
  astats = stats[action_id]
  stats[action_id] = ActionStats(astats.P, astats.W + q, astats.N + 1)
end

# Run a single MCTS simulation, updating the statistics of all traversed states.
# Return the estimated Q-value for the current player.
# Modifies the state of the game environment.
function run_simulation!(env::Env, game; η, root=true)
  if GI.game_terminated(game)
    return 0.
  else
    state = GI.current_state(game)
    actions = GI.available_actions(game)
    info, new_node = state_info(env, state)
    if new_node
      return info.Vest
    else
      ϵ = root ? env.noise_ϵ : 0.
      scores = uct_scores(info, env.cpuct, ϵ, η)
      action_id = argmax(scores)
      action = actions[action_id]
      # MAPPING NOTE (planning): the original code tracks whether the
      # player to move changes ("white" vs "black") and flips the sign
      # of the value when it does. In a planning domain there is no
      # opponent: GI.white_playing (planning alias GI.planner_acting)
      # is always true, so pswitch is always false and q is never
      # flipped. GI.white_reward (planning alias GI.plan_reward) is
      # plan quality under constraints, not a win/loss reward.
      planner_acting = GI.white_playing(game)
      GI.play!(game, action)
      step_reward = GI.white_reward(game)
      r = planner_acting ? step_reward : -step_reward
      pswitch = planner_acting != GI.white_playing(game)
      qnext = run_simulation!(env, game, η=η, root=false)
      qnext = pswitch ? -qnext : qnext
      q = r + env.gamma * qnext
      update_state_info!(env, state, action_id, q)
      env.total_nodes_traversed += 1
      return q
    end
  end
end

function dirichlet_noise(game, α)
  actions = GI.available_actions(game)
  n = length(actions)
  return rand(Dirichlet(n, α))
end

"""
    MCTS.explore!(env, game, nsims)

Run `nsims` MCTS simulations from the current state.
"""
function explore!(env::Env, game, nsims)
  η = dirichlet_noise(game, env.noise_α)
  for i in 1:nsims
    env.total_simulations += 1
    run_simulation!(env, GI.clone(game), η=η)
  end
end

"""
    MCTS.policy(env, game)

Return the recommended stochastic policy on the current state.

A call to this function must always be preceded by
a call to [`MCTS.explore!`](@ref).
"""
function policy(env::Env, game)
  actions = GI.available_actions(game)
  state = GI.current_state(game)
  info =
    try env.tree[state]
    catch e
      if isa(e, KeyError)
        error("MCTS.explore! must be called before MCTS.policy")
      else
        rethrow(e)
      end
    end
  Ntot = sum(a.N for a in info.stats)
  π = [a.N / Ntot for a in info.stats]
  π ./= sum(π)
  return actions, π
end

"""
    MCTS.reset!(env)

Empty the MCTS tree.
"""
function reset!(env)
  empty!(env.tree)
  #GC.gc(true)
end

#####
##### Profiling Utilities
#####

"""
    MCTS.average_exploration_depth(env)

Return the average number of nodes that are traversed during an
MCTS simulation, not counting the root.
"""
function average_exploration_depth(env)
  env.total_simulations == 0 && (return 0)
  return env.total_nodes_traversed / env.total_simulations
end

"""
    MCTS.memory_footprint_per_node(gspec)

Return an estimate of the memory footprint of a single MCTS node
for the given game (in bytes).
"""
function memory_footprint_per_node(gspec)
  # The hashtable is at most twice the number of stored elements
  # For every element, a state and a pointer are stored
  size_key = 2 * (GI.state_memsize(gspec) + sizeof(Int))
  dummy_stats = StateInfo([
    ActionStats(0, 0, 0) for i in 1:GI.num_actions(gspec)], 0)
  size_stats = Base.summarysize(dummy_stats)
  return size_key + size_stats
end

"""
    MCTS.approximate_memory_footprint(env)

Return an estimate of the memory footprint of the MCTS tree (in bytes).
"""
function approximate_memory_footprint(env::Env)
  return memory_footprint_per_node(env.gspec) * length(env.tree)
end

# Possibly very slow for large trees
memory_footprint(env::Env) = Base.summarysize(env.tree)

end
