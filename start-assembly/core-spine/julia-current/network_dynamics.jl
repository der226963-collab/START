# network_dynamics.jl — The network_model.jl network run through NetworkDynamics.jl.
#
# Same synthetic 3-node resource network as network_model.jl (source ->
# storage -> sink, static linear edge flows, DAE/ODE node balances), now
# assembled as NetworkDynamics.jl components:
#   vertex: one stock S per node; f!(dv, v, esum, p, t) is
#           dv[1] = prod - cons*v[1] + esum[1]
#           (prod = 10 at the source, 0 elsewhere; cons = 0.5 at the sink,
#           0 elsewhere; esum = sum of incident edge outputs)
#   edge:   static (dim 0), AntiSymmetric single-sided output
#           ydst[1] = k * vsrc[1], ysrc[1] = -ydst[1]
#           so the flow leaves the upstream node and enters the downstream
#           node — the edge flow is the algebraic constraint coupling the
#           node ODEs, exactly as in network_ode! in network_model.jl.
#
# Dependency: NetworkDynamics.jl 1.3.0 (General registry, MIT), added
# 2026-11-11. No NetworkDynamics code copied — dependency only.
# Model outputs are model results, never verified plans:
# needs_human_decision = true; nothing here bypasses the verify step.

include(joinpath(@__DIR__, "network_model.jl"))

using NetworkDynamics
using Graphs
using DifferentialEquations

"""Vertex RHS: stock balance with production, proportional consumption, and net edge inflow."""
function stock_vertex!(dv, v, esum, p, t)
    prod, cons = p
    dv[1] = prod - cons * v[1] + esum[1]
    return nothing
end

"""Edge output (single-sided): flow into dst = k * (stock at src). AntiSymmetric makes src lose the same flow."""
function flow_edge!(ydst, vsrc, vdst, p, t)
    k, = p
    ydst[1] = k * vsrc[1]
    return nothing
end

"""Build the 3-node network: source (1) - storage (2) - sink (3)."""
function build_network()
    source = VertexModel(; f = stock_vertex!, dim = 1, g = 1, indim = 1,
        psym = [:prod => SRC_PRODUCTION, :cons => 0.0],
        sym = [:S], name = :source)
    storage = VertexModel(; f = stock_vertex!, dim = 1, g = 1, indim = 1,
        psym = [:prod => 0.0, :cons => 0.0],
        sym = [:S], name = :storage)
    sink = VertexModel(; f = stock_vertex!, dim = 1, g = 1, indim = 1,
        psym = [:prod => 0.0, :cons => SINK_CONSUMPTION],
        sym = [:S], name = :sink)
    edge12 = EdgeModel(; g = AntiSymmetric(flow_edge!), outdim = 1, indim = 1,
        psym = [:k => K12])
    edge23 = EdgeModel(; g = AntiSymmetric(flow_edge!), outdim = 1, indim = 1,
        psym = [:k => K23])
    g = SimpleGraph(3)
    add_edge!(g, 1, 2)
    add_edge!(g, 2, 3)
    nw = Network(g, [source, storage, sink], [edge12, edge23])
    return nw
end

"""Flat parameter vector for the network, filled from the psym defaults.

Layout (NetworkDynamics order): vertex params in vertex order
(source prod,cons; storage prod,cons; sink prod,cons), then edge params
in edge order (k12, k23) — 8 values total. Passing it explicitly is
required: ODEProblem(nw, u0, tspan) without p leaves p as
NullParameters, which the coreloop rejects for a network with pdim > 0.
"""
function network_parameters(nw = build_network())
    p = pflat(NWParameter(nw))
    @assert length(p) == 8 "expected 8 network parameters, got $(length(p))"
    return p
end

"""Solve the network through NetworkDynamics.jl (Tsit5, same tolerances as the independent check)."""
function solve_network(; t_end = T_END, u0 = U0)
    nw = build_network()
    p = network_parameters(nw)
    prob = ODEProblem(nw, u0, (0.0, t_end), p)
    sol = solve(prob, Tsit5(), reltol = 1e-10, abstol = 1e-10)
    return sol
end

function main()
    sol = solve_network()
    println("NetworkDynamics.jl solve:")
    for t in (2.0, 5.0, 10.0)
        got = sol(t)
        want = analytic_stock(t)
        err = maximum(abs.(got .- collect(want)))
        println("  t=$t  S=$(round.(got, digits=6))  analytic=$(round.(collect(want), digits=6))  maxerr=$err")
        @assert err < 1e-6 "NetworkDynamics solve disagrees with analytic solution at t=$t (err=$err)"
    end
    sol_long = solve_network(; t_end = 100.0)
    println("  t=100 S=$(round.(sol_long(100.0), digits=6)) (steady state 20, 20, 20)")
    @assert maximum(abs.(sol_long(100.0) .- 20.0)) < 1e-3 "steady state not reached"
    println("NETWORKDYNAMICS CHECK PASS: ND solve matches closed form at t=2,5,10 (tol 1e-6), steady state 20 at t=100")
    return sol
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
