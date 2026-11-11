# Runner: MCTS search, then the combined verify with the LP cross-check.
#
# Run: julia --project=julia-current planning-search/run_verify_lp.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# Loads PlanningSearch (Distributions only) plus JuMP+HiGHS via
# verify_lp.jl — the split-stage pattern: this runner is separate
# from test/runtests.jl, which must stay JuMP-free.

include(joinpath(@__DIR__, "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "verify_lp.jl"))

function main()
    println("START core-spine — planning-search + LP cross-check")
    println("needs_human_decision=$NEEDS_HUMAN_DECISION for every result")
    c = run_search()
    println("  MCTS candidate: wheat=$(c.wheat_ha) ha, potato=$(c.potato_ha) ha, " *
            "delivered=$(c.delivered) t, shortage=$(c.shortage) t, " *
            "production=$(c.production) t, land=$(c.land_ha) ha, " *
            "water=$(c.water_m3) m3, status=$(c.status)")
    v = verify_candidate_with_lp(c)
    lp = v.lp_optimum
    if lp !== nothing
        println("  LP optimum: delivered=$(lp.delivered) t, " *
                "shortage=$(lp.shortage) t, production=$(lp.production) t, " *
                "land=$(lp.land) ha, water=$(lp.water) m3")
    else
        println("  LP optimum: none (solver did not reach OPTIMAL)")
    end
    println("  constraint verify: $(v.constraint_status), " *
            "LP cross-check: $(v.lp_status), combined: $(v.status)")
    println("  verified (needs PASS + human approval): " *
            "$(verified_status(c, v.status, false)) without approval, " *
            "$(verified_status(c, v.status, true)) with approval")
    if v.status != "PASS"
        println("VERIFY_LP RESULT: FAIL")
        exit(1)
    end
    println("VERIFY_LP RESULT: PASS")
    return nothing
end

main()
