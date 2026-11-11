# START core-spine — Julia LP stage (RUNNABLE, verified 2026-11-10).
#
# Stage A of spine.jl, split out because loading JuMP + HiGHS +
# ModelingToolkit + DifferentialEquations together OOM-kills this
# 6 GB VM (spine.jl full run, exit 137, 2026-11-10). This script
# loads ONLY JuMP + HiGHS. Run spine_ode.jl separately for the
# ModelingToolkit / DifferentialEquations stage.
#
# Checks: evaluate_constraint (<=, >=, ==, range, non-finite -> UNKNOWN,
# empty id -> UNKNOWN, unsupported operator -> UNKNOWN, unknown /
# incompatible units -> UNKNOWN), overall_status (empty ->
# NOT_CHECKED, FAIL wins, INCOMPLETE > UNKNOWN > NOT_CHECKED),
# check_schema_version (same-major 1.x.y accepted, 2.0.0 rejected),
# food case 2800 >= 2500 kcal/capita/day -> PASS, the m3/L
# conversion pair (0.008 m3 <= 10 L PASS, 0.02 m3 vs 10 L FAIL),
# and the JuMP + HiGHS LP: delivered 600 t, shortage 50 t
# (loss-free; 614/57 t are the 5%-loss figures, NOT the expected
# result here). Every result carries needs_human_decision = true.
# The evaluator, registry and version check live in units.jl —
# the one canonical implementation shared by all Julia
# evaluators (see that file's header).
#
# Run: julia --project=. --heap-size-hint=3G spine_lp.jl

using JuMP, HiGHS

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
    @constraint(model, sum(short) == shortage_opt)
    @objective(model, Min, sum(prod))
    optimize!(model)
    @assert termination_status(model) == MOI.OPTIMAL
    return (delivered=sum(value.(prod)), shortage=sum(value.(short)),
            production=sum(value.(prod)), land=sum(value.(area)),
            water=sum(water .* value.(area)))
end

function main()
    results = Bool[]
    println("START core-spine — Julia spine_lp.jl (JuMP + HiGHS stage)")
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

    println("1b. unit registry: wire cases (shared test-vectors)")
    # m3/L conversion, both directions — the discriminating pair:
    # 0.008 m3 = 8 L passes, 0.02 m3 = 20 L fails.
    push!(results, check("vol-m3-to-L-pass",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=0.008, bound=10.0,
                            value_unit="m3", bound_unit="L")[1], "PASS"))
    push!(results, check("vol-m3-to-L-fail",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=0.02, bound=10.0,
                            value_unit="m3", bound_unit="L")[1], "FAIL"))
    push!(results, check("vol-L-to-m3-pass",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=8.0, bound=0.01,
                            value_unit="L", bound_unit="m3")[1], "PASS"))
    push!(results, check("vol-L-to-m3-fail",
        evaluate_constraint(constraint_id="vol", operator="<=",
                            value=12.0, bound=0.01,
                            value_unit="L", bound_unit="m3")[1], "FAIL"))
    push!(results, check("mass-tonne-pass",
        evaluate_constraint(constraint_id="mass", operator="<=",
                            value=8.0, bound=10.0,
                            value_unit="t", bound_unit="t")[1], "PASS"))
    push!(results, check("kcal-day-pass",
        evaluate_constraint(constraint_id="kday", operator=">=",
                            value=2800.0, bound=2500.0,
                            value_unit="kcal/day",
                            bound_unit="kcal/day")[1], "PASS"))
    # The fixed bug: 5 L <= 10 kg is UNKNOWN, never a PASS.
    push!(results, check("incompatible-unknown",
        evaluate_constraint(constraint_id="incomp", operator="<=",
                            value=5.0, bound=10.0,
                            value_unit="L", bound_unit="kg")[1], "UNKNOWN"))
    push!(results, check("unknown-unit-unknown",
        evaluate_constraint(constraint_id="x", operator="<=",
                            value=5.0, bound=10.0,
                            value_unit="furlongs", bound_unit="kg")[1],
        "UNKNOWN"))
    # Range: inclusive with tolerance, bounds in bound_unit.
    push!(results, check("range-pass",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=5.0, bound_low=2.0, bound_high=8.0,
                            value_unit="L", bound_unit="L")[1], "PASS"))
    push!(results, check("range-low-fail",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=1.0, bound_low=2.0, bound_high=8.0,
                            value_unit="L", bound_unit="L")[1], "FAIL"))
    push!(results, check("range-high-fail",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=9.0, bound_low=2.0, bound_high=8.0,
                            value_unit="L", bound_unit="L")[1], "FAIL"))
    push!(results, check("range-low-boundary-pass",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=2.0, bound_low=2.0, bound_high=8.0,
                            value_unit="L", bound_unit="L")[1], "PASS"))
    push!(results, check("range-high-boundary-pass",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=8.0, bound_low=2.0, bound_high=8.0,
                            value_unit="L", bound_unit="L")[1], "PASS"))
    push!(results, check("range-missing-bounds-unknown",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=5.0,
                            value_unit="L", bound_unit="L")[1], "UNKNOWN"))
    push!(results, check("range-inverted-unknown",
        evaluate_constraint(constraint_id="rng", operator="range",
                            value=5.0, bound_low=8.0, bound_high=2.0,
                            value_unit="L", bound_unit="L")[1], "UNKNOWN"))

    println("1c. schema versions")
    for (version, expected) in (("1.0.0", true), ("1.0.1", true),
                                ("1.1.0", true), ("2.0.0", false))
        accepted, _ = check_schema_version(version)
        push!(results, check("version-$version", accepted, expected))
    end
    push!(results, check("version-2.0.0-message",
        check_schema_version("2.0.0")[2],
        "unsupported major schema version: 2.0.0 " *
        "(supported major version 1)"))

    println("2. overall_status")
    push!(results, check("empty-not-checked",
        overall_status(String[]), "NOT_CHECKED"))
    push!(results, check("fail-wins",
        overall_status(["PASS", "FAIL", "UNKNOWN"]), "FAIL"))
    push!(results, check("unknown-indeterminate",
        overall_status(["PASS", "UNKNOWN"]), "UNKNOWN"))
    push!(results, check("unknown-only",
        overall_status(["UNKNOWN"]), "UNKNOWN"))
    push!(results, check("incomplete-beats-unknown",
        overall_status(["UNKNOWN", "INCOMPLETE"]), "INCOMPLETE"))
    push!(results, check("not-checked-stays",
        overall_status(["PASS", "NOT_CHECKED"]), "NOT_CHECKED"))
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

    n_pass = count(results)
    n_total = length(results)
    println("SPINE_LP RESULT: $n_pass/$n_total checks passed " *
            "needs_human_decision=$NEEDS_HUMAN_DECISION")
    if n_pass != n_total
        println("SPINE_LP RESULT: FAIL")
        exit(1)
    end
    println("SPINE_LP RESULT: PASS")
    return nothing
end

main()
