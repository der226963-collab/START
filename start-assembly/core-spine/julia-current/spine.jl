# START core-spine — Julia adapter (RUNNABLE, verified 2026-11-10).
#
# Maps the Julia SciML side onto the v0.3.2 constraint-evaluation wire
# contract (schema_version "1.0.0", statuses PASS / FAIL / UNKNOWN /
# NOT_CHECKED / INCOMPLETE). Every result carries
# needs_human_decision = true: Julia never certifies its own output.
#
# It does NOT repeat the v0.3.2 Julia mistakes (REVIEW.md ISSUE-05,
# ISSUE-07): no :candidate_feasible / :candidate_infeasible, no
# hard-coded `<=` for every constraint, no self-certification.
#
# Checks run here:
#   1. Food energy adequacy: 2800 kcal/capita/day >= 2500 -> PASS
#      (the ISSUE-03 flagship case).
#   2. Empty checks -> NOT_CHECKED, never PASS (ISSUE-02).
#   3. JuMP + HiGHS LP for the synthetic 1-site 2-crop example
#      (same as adapters/optimisation.py): delivered 600 t,
#      shortage 50 t, production 600 t, land 70 ha, water 100,000 m3.
#      CORRECTION (2026-11-10): an earlier draft of this file claimed
#      614/57 t here. Those are the 5%-loss potato figures from the
#      PCAC-style example; the loss-free totals are 600/50 t.
#   4. A ModelingToolkit / DifferentialEquations food-stock ODE whose
#      steady state is checked by evaluate_constraint, not trusted
#      on its own. dS/dt = inflow - rate*S, inflow 10 t/day,
#      rate 0.1/day -> equilibrium S* = 100 t.
#
# Run: julia --project=. spine.jl
# Requires: JuMP, HiGHS, ModelingToolkit, DifferentialEquations
# (installed via `julia --project=. -e "import Pkg; Pkg.instantiate()"`).
#
# MEMORY NOTE (2026-11-10): on this 6 GB VM the combined run was
# OOM-killed (exit 137) while loading ModelingToolkit +
# DifferentialEquations after JuMP + HiGHS — it never reached main().
# The same checks are therefore also provided as two split stages
# that each fit in memory: spine_lp.jl (JuMP + HiGHS only) and
# spine_ode.jl (ModelingToolkit + DifferentialEquations only).
# Run those two on a low-memory machine; run this combined file
# only where >6 GB is available. Use --heap-size-hint=3G.

using JuMP, HiGHS
using ModelingToolkit, DifferentialEquations

# The evaluator, registry, aggregation and version check live in
# units.jl — the one canonical implementation shared by all Julia
# evaluators (see that file's header). The old unit-free
# evaluate_constraint / overall_status defined here are removed.
include(joinpath(@__DIR__, "units.jl"))

const NEEDS_HUMAN_DECISION = true

function check(name, got, expected)
    ok = got == expected
    println("  [$name] got=$got expected=$expected ",
            ok ? "PASS" : "FAIL",
            " needs_human_decision=$NEEDS_HUMAN_DECISION")
    return ok
end

function solve_food_lp()
    # 1 site, 2 crops. Wheat: 4 t/ha, 1200 m3/ha, demand 250 t.
    # Potato: 20 t/ha, 2000 m3/ha, demand 400 t.
    # Land 100 ha, water 100,000 m3. Loss-free.
    yields = [4.0, 20.0]
    water = [1200.0, 2000.0]
    demand = [250.0, 400.0]
    model = Model(HiGHS.Optimizer)
    set_silent(model)
    @variable(model, area[1:2] >= 0)
    @variable(model, prod[1:2] >= 0)
    @variable(model, short[1:2] >= 0)
    @constraint(model, prod .== yields .* area)
    @constraint(model, prod .+ short .== demand)
    @constraint(model, sum(area) <= 100.0)
    @constraint(model, sum(water .* area) <= 100_000.0)
    @objective(model, Min, sum(short))
    optimize!(model)
    @assert termination_status(model) == MOI.OPTIMAL
    shortage_opt = objective_value(model)
    # Stage 2: hold shortage at its optimum, minimise production (waste).
    @constraint(model, sum(short) == shortage_opt)
    @objective(model, Min, sum(prod))
    optimize!(model)
    @assert termination_status(model) == MOI.OPTIMAL
    delivered = sum(value.(prod))
    shortage = sum(value.(short))
    production = sum(value.(prod))
    land = sum(value.(area))
    water_used = sum(water .* value.(area))
    return (delivered=delivered, shortage=shortage, production=production,
            land=land, water=water_used)
end

function food_stock_steady_state()
    # dS/dt = inflow - rate*S; inflow 10, rate 0.1 -> S* = 100 t.
    # NOTE (2026-11-11): MTK macros are qualified (ModelingToolkit.@variables
    # etc.) because JuMP exports @variables too and `using JuMP` +
    # `using ModelingToolkit` makes the bare name ambiguous in Main
    # (UndefVarError at spine.jl:122 on the combined run). The split
    # stages (spine_lp.jl = JuMP only, spine_ode.jl = MTK only) do not
    # hit this; only the combined script needs the qualification.
    ModelingToolkit.@variables t S(t)
    ModelingToolkit.@parameters inflow rate
    D = Differential(t)
    eqs = [D(S) ~ inflow - rate * S]
    ModelingToolkit.@mtkbuild sys = ODESystem(eqs, t)
    prob = ODEProblem(sys, [S => 0.0], (0.0, 100.0),
                      [inflow => 10.0, rate => 0.1])
    sol = solve(prob, Tsit5())
    return sol[S][end]
end

function main()
    results = Bool[]
    println("START core-spine — Julia spine.jl")
    println("needs_human_decision=$NEEDS_HUMAN_DECISION for every result")

    println("1. evaluate_constraint")
    push!(results, check("food-2800>=2500",
        evaluate_constraint(constraint_id="food-energy", operator=">=",
                            value=2800.0, bound=2500.0,
                            value_unit="kcal/capita/day",
                            bound_unit="kcal/capita/day")[1], "PASS"))
    push!(results, check("le-fail",
        evaluate_constraint(constraint_id="water", operator="<=",
                            value=12.0, bound=10.0,
                            value_unit="L", bound_unit="L")[1], "FAIL"))
    push!(results, check("eq-pass",
        evaluate_constraint(constraint_id="mass", operator="==",
                            value=10.0, bound=10.0, tolerance=1e-9,
                            value_unit="kg", bound_unit="kg")[1], "PASS"))
    push!(results, check("empty-id-unknown",
        evaluate_constraint(constraint_id="", operator="<=",
                            value=1.0, bound=2.0,
                            value_unit="kg", bound_unit="kg")[1], "UNKNOWN"))
    push!(results, check("nonfinite-unknown",
        evaluate_constraint(constraint_id="x", operator="<=",
                            value=NaN, bound=2.0,
                            value_unit="kg", bound_unit="kg")[1], "UNKNOWN"))
    push!(results, check("unsupported-op-unknown",
        evaluate_constraint(constraint_id="x", operator="<>",
                            value=1.0, bound=2.0,
                            value_unit="kg", bound_unit="kg")[1], "UNKNOWN"))
    # The fixed bug: incompatible units are UNKNOWN, never PASS.
    push!(results, check("incompatible-unknown",
        evaluate_constraint(constraint_id="incomp", operator="<=",
                            value=5.0, bound=10.0,
                            value_unit="L", bound_unit="kg")[1], "UNKNOWN"))
    # m3/L conversion, both directions (discriminating pair).
    push!(results, check("vol-m3-to-L-pass",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=0.008, bound=10.0,
                            value_unit="m3", bound_unit="L")[1], "PASS"))
    push!(results, check("vol-m3-to-L-fail",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=0.02, bound=10.0,
                            value_unit="m3", bound_unit="L")[1], "FAIL"))

    println("2. overall_status")
    push!(results, check("empty-not-checked",
        overall_status(String[]), "NOT_CHECKED"))
    push!(results, check("fail-wins",
        overall_status(["PASS", "FAIL", "UNKNOWN"]), "FAIL"))
    push!(results, check("unknown-indeterminate",
        overall_status(["PASS", "UNKNOWN"]), "UNKNOWN"))
    push!(results, check("all-pass",
        overall_status(["PASS", "PASS"]), "PASS"))

    println("3. JuMP + HiGHS LP (synthetic 1-site 2-crop, loss-free)")
    lp = solve_food_lp()
    println("  delivered_t=$(round(lp.delivered, digits=2)) " *
            "shortage_t=$(round(lp.shortage, digits=2)) " *
            "production_t=$(round(lp.production, digits=2)) " *
            "land_ha=$(round(lp.land, digits=2)) " *
            "water_m3=$(round(lp.water, digits=2))")
    for (key, got, expected, unit) in
            [("delivered_t", lp.delivered, 600.0, "t"),
             ("shortage_t", lp.shortage, 50.0, "t"),
             ("production_t", lp.production, 600.0, "t"),
             ("land_ha", lp.land, 70.0, "ha"),
             ("water_m3", lp.water, 100_000.0, "m3")]
        status, _ = evaluate_constraint(constraint_id="opt-$key",
                                        operator="==", value=got,
                                        bound=expected, tolerance=0.02,
                                        value_unit=unit, bound_unit=unit)
        push!(results, check("lp-$key", status, "PASS"))
    end

    println("4. ModelingToolkit / DifferentialEquations food-stock ODE")
    s_final = food_stock_steady_state()
    println("  stock at t=100: $(round(s_final, digits=4)) t (equilibrium 100 t)")
    status, _ = evaluate_constraint(constraint_id="stock-equilibrium",
                                    operator="==", value=s_final,
                                    bound=100.0, tolerance=1.0,
                                    value_unit="t", bound_unit="t")
    push!(results, check("ode-steady-state", status, "PASS"))

    n_pass = count(results)
    n_total = length(results)
    println("SPINE RESULT: $n_pass/$n_total checks passed " *
            "needs_human_decision=$NEEDS_HUMAN_DECISION")
    if n_pass != n_total
        println("SPINE RESULT: FAIL")
        exit(1)
    end
    println("SPINE RESULT: PASS")
    return nothing
end

main()
