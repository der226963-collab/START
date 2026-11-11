# Runner: the planning training loop with the LP cross-check.
#
# Run: julia --project=julia-current planning-search/run_training_loop.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# Loads PlanningSearch (Distributions only) plus JuMP+HiGHS via
# verify_lp.jl — the split-stage pattern: the loop itself stays
# JuMP-free, and the verify function it is given here is the
# combined verify (constraint + LP cross-check).
#
# Prints the per-iteration report and the final held-out
# numbers. TRAINING_LOOP RESULT is PASS when the loop ran to
# completion and kept verified samples; the held-out numbers
# are reported as measured, whether or not the learned oracle
# improved on the rollout oracle.

include(joinpath(@__DIR__, "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "verify_lp.jl"))

function main()
    println("START core-spine — planning training loop + LP cross-check")
    println("needs_human_decision=$NEEDS_HUMAN_DECISION for every result")
    println("Training is original START code: no opponent, no win/loss,")
    println("no network library. Only verify+LP PASS candidates become")
    println("training samples; a learned oracle replaces the current")
    println("one only on a held-out verified-PASS rate at least as high,")
    println("with a mean shortage no worse.")
    result = train_planning_loop!(
        iterations=3, train_seeds=[1, 2, 3, 4],
        heldout_seeds=[101, 102, 103, 104],
        nsims=200, seed=1234,
        verify_fn=(candidate, spec) ->
            verify_candidate_with_lp(candidate; spec=spec))
    total_generated = 0
    total_kept = 0
    total_rejected = 0
    for r in result.reports
        total_generated += r.generated
        total_kept += r.verified_kept
        total_rejected += r.rejected
        println("  iteration $(r.iteration): generated=$(r.generated) " *
                "verified_kept=$(r.verified_kept) " *
                "rejected=$(r.rejected) memory=$(r.memory_size) " *
                "heldout rollout PASS=$(r.rollout_pass_rate) " *
                "learned PASS=$(r.learned_pass_rate) " *
                "rollout mean shortage=$(r.rollout_mean_shortage) t " *
                "learned mean shortage=$(r.learned_mean_shortage) t " *
                "replaced=$(r.oracle_replaced)")
    end
    println("  total: generated=$total_generated " *
            "verified_kept=$total_kept rejected=$total_rejected " *
            "memory=$(memory_size(result.memory)) " *
            "oracle_is_learned=$(result.oracle_is_learned)")
    if result.model !== nothing
        println("  fitted value weights: ",
                round.(result.model.weights, digits=3))
    end
    if memory_size(result.memory) == 0
        println("TRAINING_LOOP RESULT: FAIL (no verified samples kept)")
        exit(1)
    end
    println("TRAINING_LOOP RESULT: PASS")
    return nothing
end

main()
