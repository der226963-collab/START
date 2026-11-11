# network_model.jl — Synthetic networked domain model (Module 10).
#
# A 3-node resource network, SYNTHETIC numbers only (not a real region):
#   node 1 "source"  — produces resource at constant rate P
#   node 2 "storage" — stores resource, no production / consumption
#   node 3 "sink"    — consumes resource at rate c * S3
#   edge 1->2 — flow f12 = k12 * S1   (algebraic / static edge constraint)
#   edge 2->3 — flow f23 = k23 * S2   (algebraic / static edge constraint)
#
# Node balances (differential equations), S_i = stock at node i:
#   dS1/dt = P   - k12*S1
#   dS2/dt = k12*S1 - k23*S2
#   dS3/dt = k23*S2 - c*S3
#
# Parameters (synthetic): P = 10.0, k12 = 0.5, k23 = 0.5, c = 0.5 (all 1/time).
# Initial stocks: S(0) = (0, 0, 0).
#
# Closed-form solution (hand-derived, verified term-by-term in the test file):
#   S1(t) = 20*(1 - e^{-t/2})
#   S2(t) = 20*(1 - e^{-t/2}*(1 + t/2))
#   S3(t) = 20 - e^{-t/2}*(20 + 10*t + 2.5*t^2)
# Steady state: S* = (20, 20, 20).
# Mass balance (exact): total stock + cumulative outflow = P*t, i.e.
#   S1+S2+S3 + (c/2)*int_0^t S3(s) ds = 10*t, with int_0^10 S3 = 86.8727059...
#
# This file uses ONLY DifferentialEquations.jl (already a spine dependency).
# It does NOT use NetworkDynamics.jl: it is the independent check that the
# NetworkDynamics run in network_dynamics.jl must agree with.
# Model outputs are model results, never verified plans:
# needs_human_decision = true; nothing here bypasses the verify step.

using DifferentialEquations

# --- synthetic parameters (not a real region) ---
const SRC_PRODUCTION = 10.0   # P, resource units / time
const K12 = 0.5               # edge 1->2 flow coefficient, 1/time
const K23 = 0.5               # edge 2->3 flow coefficient, 1/time
const SINK_CONSUMPTION = 0.5  # c, sink consumption coefficient, 1/time
const T_END = 10.0
const U0 = [0.0, 0.0, 0.0]

"""Right-hand side of the 3-node network ODEs (plain, no NetworkDynamics)."""
function network_ode!(du, u, p, t)
    P, k12, k23, c = p
    du[1] = P - k12 * u[1]
    du[2] = k12 * u[1] - k23 * u[2]
    du[3] = k23 * u[2] - c * u[3]
    return nothing
end

"""Closed-form (hand-derived) stocks at time t."""
function analytic_stock(t)
    e = exp(-0.5 * t)
    s1 = 20.0 * (1.0 - e)
    s2 = 20.0 * (1.0 - e * (1.0 + 0.5 * t))
    s3 = 20.0 - e * (20.0 + 10.0 * t + 2.5 * t * t)
    return (s1, s2, s3)
end

"""Solve the network ODEs with plain DifferentialEquations (no NetworkDynamics)."""
function solve_independent(; t_end = T_END, u0 = U0)
    p = (SRC_PRODUCTION, K12, K23, SINK_CONSUMPTION)
    prob = ODEProblem(network_ode!, u0, (0.0, t_end), p)
    sol = solve(prob, Tsit5(), reltol = 1e-10, abstol = 1e-10)
    return sol
end

function main()
    sol = solve_independent()
    println("independent ODE solve (DifferentialEquations, no NetworkDynamics):")
    for t in (2.0, 5.0, 10.0)
        got = sol(t)
        want = analytic_stock(t)
        err = maximum(abs.(got .- collect(want)))
        println("  t=$t  S=$(round.(got, digits=6))  analytic=$(round.(collect(want), digits=6))  maxerr=$err")
        @assert err < 1e-6 "independent solve disagrees with analytic solution at t=$t (err=$err)"
    end
    println("INDEPENDENT CHECK PASS: plain ODE matches closed form at t=2,5,10 (tol 1e-6)")
    return sol
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
