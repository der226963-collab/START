# START core-spine — Julia LP stage (RUNNABLE, verified 2026-11-10).
#
# Stage A of spine.jl, split out because loading JuMP + HiGHS +
# ModelingToolkit + DifferentialEquations together OOM-kills this
# 6 GB VM (spine.jl full run, exit 137, 2026-11-10). This script
# loads ONLY JuMP + HiGHS. Run spine_ode.jl separately for the
# ModelingToolkit / DifferentialEquations stage.
#
# Checks: evaluate_constraint (<=, >=, ==, non-finite -> UNKNOWN,
# empty id -> UNKNOWN, unsupported operator -> UNKNOWN),
# overall_status (empty -> NOT_CHECKED, FAIL wins, UNKNOWN ->
# indeterminate), food case 2800 >= 2500 -> PASS, and the JuMP +
# HiGHS LP: delivered 600 t, shortage 50 t (loss-free; 614/57 t
# are the 5%-loss figures, NOT the expected result here).
# Every result carries needs_human_decision = true.
#
# Run: julia --project=. --heap-size-hint=3G spine_lp.jl

using JuMP, HiGHS

const NEEDS_HUMAN_DECISION = true

function evaluate_constraint(; constraint_id, operator, value, bound,
                               tolerance=0.0)
    if isempty(constraint_id)
        return ("UNKNOWN", "empty constraint_id")
    end
    if !isfinite(value) || !isfinite(bound)
        return ("UNKNOWN", "non-finite value or bound")
    end
    ok = if operator == "<="
        value <= bound + tolerance
    elseif operator == ">="
        value >= bound - tolerance
    elseif operator == "=="
        abs(value - bound) <= tolerance
    else
        return ("UNKNOWN", "unsupported operator: $operator")
    end
    return (ok ? "PASS" : "FAIL", "OK")
end

function overall_status(statuses)
    isempty(statuses) && return "NOT_CHECKED"
    "FAIL" in statuses && return "FAIL"
    any(s in statuses for s in ("INCOMPLETE", "UNKNOWN", "NOT_CHECKED")) &&
        return "UNKNOWN"
    return "PASS"
end

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
                            value=2800.0, bound=2500.0)[1], "PASS"))
    push!(results, check("le-fail",
        evaluate_constraint(constraint_id="water", operator="<=",
                            value=12.0, bound=10.0)[1], "FAIL"))
    push!(results, check("eq-pass",
        evaluate_constraint(constraint_id="mass", operator="==",
                            value=10.0, bound=10.0, tolerance=1e-9)[1], "PASS"))
    push!(results, check("empty-id-unknown",
        evaluate_constraint(constraint_id="", operator="<=",
                            value=1.0, bound=2.0)[1], "UNKNOWN"))
    push!(results, check("nonfinite-unknown",
        evaluate_constraint(constraint_id="x", operator="<=",
                            value=NaN, bound=2.0)[1], "UNKNOWN"))
    push!(results, check("unsupported-op-unknown",
        evaluate_constraint(constraint_id="x", operator="<>",
                            value=1.0, bound=2.0)[1], "UNKNOWN"))

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
    for (key, got, expected) in
            [("delivered_t", lp.delivered, 600.0),
             ("shortage_t", lp.shortage, 50.0),
             ("production_t", lp.production, 600.0),
             ("land_ha", lp.land, 70.0),
             ("water_m3", lp.water, 100_000.0)]
        status, _ = evaluate_constraint(constraint_id="opt-$key",
                                        operator="==", value=got,
                                        bound=expected, tolerance=0.02)
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
