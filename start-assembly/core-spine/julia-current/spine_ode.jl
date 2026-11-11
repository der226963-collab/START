# START core-spine — Julia ODE stage (RUNNABLE, 2026-11-10).
#
# Stage B of spine.jl, split out because loading JuMP + HiGHS +
# ModelingToolkit + DifferentialEquations together OOM-kills this
# 6 GB VM (spine.jl full run, exit 137, 2026-11-10). This script
# loads ONLY ModelingToolkit + DifferentialEquations. Run
# spine_lp.jl separately for the JuMP + HiGHS stage.
#
# Check: a ModelingToolkit / DifferentialEquations food-stock ODE
# dS/dt = inflow - rate*S (inflow 10 t/day, rate 0.1/day ->
# equilibrium S* = 100 t), whose steady state is checked by
# evaluate_constraint, not trusted on its own. Every result
# carries needs_human_decision = true.
#
# Run: julia --project=. --heap-size-hint=3G spine_ode.jl

using ModelingToolkit, DifferentialEquations

# The evaluator lives in units.jl — the one canonical
# implementation shared by all Julia evaluators (see that file's
# header). The old unit-free evaluate_constraint defined here
# is removed.
include(joinpath(@__DIR__, "units.jl"))

const NEEDS_HUMAN_DECISION = true

function food_stock_steady_state()
    @variables t S(t)
    @parameters inflow rate
    D = Differential(t)
    eqs = [D(S) ~ inflow - rate * S]
    @mtkbuild sys = ODESystem(eqs, t)
    prob = ODEProblem(sys, [S => 0.0], (0.0, 100.0),
                      [inflow => 10.0, rate => 0.1])
    sol = solve(prob, Tsit5())
    return sol[S][end]
end

function main()
    println("START core-spine — Julia spine_ode.jl (MTK / DiffEq stage)")
    println("needs_human_decision=$NEEDS_HUMAN_DECISION for every result")
    s_final = food_stock_steady_state()
    println("  stock at t=100: $(round(s_final, digits=4)) t (equilibrium 100 t)")
    status, _ = evaluate_constraint(constraint_id="stock-equilibrium",
                                    operator="==", value=s_final,
                                    bound=100.0, tolerance=1.0,
                                    value_unit="t", bound_unit="t")
    ok = status == "PASS"
    println("  [ode-steady-state] got=$status expected=PASS ",
            ok ? "PASS" : "FAIL",
            " needs_human_decision=$NEEDS_HUMAN_DECISION")
    println("SPINE_ODE RESULT: $(ok ? "PASS" : "FAIL")")
    ok || exit(1)
    return nothing
end

main()
