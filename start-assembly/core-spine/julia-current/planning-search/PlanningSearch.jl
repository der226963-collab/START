# START core-spine — PlanningSearch module (2026-11-11).
#
# A START-native planning-search module built from two files copied
# from AlphaZero.jl v0.5.6 (MIT, Copyright (c) 2019 Jonathan Laurent)
# — mcts.jl and game.jl — re-expressed in planning terms. See
# PROVENANCE.md in this folder for the full provenance, the MIT
# notices, and the list of changes.
#
# Layout:
#   game.jl             copied interface, module PlanningGameInterface
#                       ("game" = planning domain, "state" = partial
#                       plan, "action" = allocation, reward = plan
#                       quality under constraints)
#   mcts.jl             copied MCTS search, module MCTS
#                       (UCT selection, Dirichlet-noise exploration,
#                       rollouts, policy from visit counts)
#   planning_domain.jl  ORIGINAL START code: the synthetic 1-site
#                       2-crop planning domain implementing the
#                       copied interface, plus run_search
#   verify.jl           ORIGINAL START code: the separate verify step
#                       (mirrors spine.jl's evaluate_constraint /
#                       overall_status); search results are candidates
#                       only and are never verified by the search
#   verify_lp.jl        ORIGINAL START code, NOT included here: the
#                       second, independent JuMP+HiGHS LP cross-check
#                       of candidates (see that file's header). It
#                       loads JuMP+HiGHS, so it lives apart — this
#                       module stays loadable on Distributions alone.
#                       Runner: run_verify_lp.jl; tests:
#                       test/verify_lp.jl (standalone script, not
#                       included from test/runtests.jl)
#   training_loop.jl    ORIGINAL START code: the planning training
#                       loop (replaces the game training loop — no
#                       opponent, no win/loss, no network library).
#                       Verified samples only, a linear value model
#                       as the learned oracle, and a held-out
#                       verified-PASS-rate replacement rule. Tests:
#                       test/training_loop.jl (standalone) and
#                       test/training_loop_lp.jl (LP-split script).
#
# GUARDRAILS (non-negotiable):
#  * A search result is a CANDIDATE only. It must go through the
#    separate verify step before it can be called a plan, it must
#    never be marked PASS/verified by the search itself, and every
#    result carries needs_human_decision = true.
#  * The training loop, network backend, and ConnectFour code from
#    AlphaZero.jl were NOT copied. No AlphaZero.jl import anywhere.
#  * Standalone in the canonical env: the only external package the
#    copied files need is Distributions (Dirichlet noise in MCTS).
#    Checked 2026-11-11: neither copied file imports
#    DataStructures or StaticArrays.
#
# Run the tests: julia --project=julia-current test/runtests.jl
# (from the core-spine folder, Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).

module PlanningSearch

using Distributions: Categorical, Dirichlet
using Random

export PlanningGameInterface, MCTS
export FoodPlanSpec, FoodPlanEnv, PlanningCandidate
export run_search, plan_totals, verify_candidate, verified_status
export evaluate_constraint, overall_status
export VerifiedSample, VerifiedMemory, insert_verified!
export memory_size, memory_samples, vary_spec, spec_id_for_seed
export plan_features, LinearValueModel, fit_value_model, predict_value
export LearnedOracle, run_search_with_oracle
export HeldoutResult, evaluate_heldout, replacement_decision
export IterationReport, PlanningLoopResult, train_planning_loop!
export NEEDS_HUMAN_DECISION

const NEEDS_HUMAN_DECISION = true

"""
    apply_temperature(π, τ)

Apply temperature `τ` to probability distribution `π`.
Handle the limit case where `τ=0` (one-hot on the argmax).

START-written helper: the same elementary mathematics the original
MCTS code used (π^(1/τ), normalised), written here from the
definition. It is NOT copied from AlphaZero.jl's util.jl.
"""
function apply_temperature(π, τ)
    if isone(τ)
        return π
    elseif iszero(τ)
        res = zeros(eltype(π), length(π))
        res[argmax(π)] = 1
        return res
    else
        res = π .^ inv(τ)
        res ./= sum(res)
        return res
    end
end

include("game.jl")   # module PlanningGameInterface
const GI = PlanningGameInterface
include("mcts.jl")   # module MCTS; uses ..PlanningSearch: GI, apply_temperature
include("planning_domain.jl")
include("verify.jl")
include("training_loop.jl")

end
