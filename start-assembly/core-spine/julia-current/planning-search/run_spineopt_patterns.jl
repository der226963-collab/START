# Runner: SpineOpt planning patterns, then the separate verify step.
#
# Run: julia --project=julia-current planning-search/run_spineopt_patterns.jl
# (from the core-spine folder; Julia 1.13.3, JULIA_NUM_THREADS=1,
#  JULIA_NUM_PRECOMPILE_TASKS=1, --heap-size-hint=3G).
# Loads PlanningSearch (Distributions only) plus JuMP+HiGHS via
# verify_lp.jl and spineopt_patterns.jl — the split-stage pattern:
# this runner is separate from test/runtests.jl, which must stay
# JuMP-free. Every pattern result is verified here with
# verify_candidate_with_lp (constraint verify + LP cross-check);
# nothing is marked verified by the pattern code, and the MGA
# alternatives are listed for human choice, never auto-selected.

include(joinpath(@__DIR__, "PlanningSearch.jl"))
using .PlanningSearch
include(joinpath(@__DIR__, "verify_lp.jl"))
include(joinpath(@__DIR__, "spineopt_patterns.jl"))

function main()
    println("START core-spine — SpineOpt planning patterns (original rebuild)")
    println("needs_human_decision=$NEEDS_HUMAN_DECISION for every result")
    ok = true

    # (a) Rolling horizon: 3 representative periods.
    plan = rolling_horizon_plan()
    println("  (a) time slices: $(length(plan.slices)) periods, " *
            "aggregate delivered=$(plan.delivered) t, " *
            "shortage=$(plan.shortage) t, status=$(plan.status)")
    for (c, s) in zip(plan.candidates, plan.slices)
        v = verify_candidate_with_lp(c; spec=s.spec)
        println("      $(s.id): wheat=$(c.wheat_ha) ha, potato=$(c.potato_ha) ha, " *
                "delivered=$(c.delivered) t, verify=$(v.status)")
        ok &= v.status == "PASS"
    end

    # (b) Stochastic: normal vs low yield.
    sp = stochastic_plan()
    println("  (b) scenarios: expected delivered=$(sp.expected_delivered) t, " *
            "expected shortage=$(sp.expected_shortage) t")
    for (c, s) in zip(sp.candidates, sp.scenarios)
        v = verify_candidate_with_lp(c; spec=s.spec)
        println("      $(s.id) (p=$(s.probability)): delivered=$(c.delivered) t, " *
                "shortage=$(c.shortage) t, verify=$(v.status)")
        ok &= v.status == "PASS"
    end

    # (c) Benders: must agree with the direct LP optimum (600/50 t).
    b = benders_solve()
    lp = solve_direct_lp(FoodPlanSpec())
    println("  (c) Benders: iterations=$(b.iterations), converged=$(b.converged), " *
            "lower=$(b.lower_bound) t, upper=$(b.upper_bound) t, " *
            "delivered=$(b.delivered) t, shortage=$(b.shortage) t; " *
            "direct LP delivered=$(lp.delivered) t, shortage=$(lp.shortage) t")
    ok &= b.converged && b.delivered ≈ lp.delivered && b.shortage ≈ lp.shortage
    vb = verify_candidate_with_lp(b.candidate)
    println("      Benders candidate verify: $(vb.status) " *
            "(constraint $(vb.constraint_status), LP $(vb.lp_status))")
    ok &= vb.status == "PASS"

    # (d) Nodal balance on the Benders candidate.
    nb = nodal_balance_for_candidate(b.candidate)
    println("  (d) nodal balance: $(nb.status) " *
            "(residuals $(join(nb.residuals, ", ")))")
    ok &= nb.status == "PASS"

    # (e) MGA: alternatives for human choice — none auto-selected.
    m = mga_alternatives()
    println("  (e) MGA: optimum delivered=$(m.optimum.delivered) t / " *
            "shortage=$(m.optimum_shortage) t, slack=$(m.slack) t, " *
            "$(length(m.alternatives)) alternatives, selected=$(m.selected)")
    for (a, o) in zip(m.alternatives, m.objectives)
        va = verify_candidate_with_lp(a)
        println("      [$o] wheat=$(a.wheat_ha) ha, potato=$(a.potato_ha) ha, " *
                "delivered=$(a.delivered) t, shortage=$(a.shortage) t, " *
                "verify=$(va.status)")
        ok &= va.status == "PASS"
    end

    if !ok
        println("SPINEOPT_PATTERNS RESULT: FAIL")
        exit(1)
    end
    println("SPINEOPT_PATTERNS RESULT: PASS")
    return nothing
end

main()
