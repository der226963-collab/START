# test_network_dynamics.jl — Tests for the synthetic 3-node resource network (Module 10).
#
# 31 tests in 7 testsets:
#   1. analytic closed form matches hand-computed values (t=2, t=10) — 6
#   2. mass-balance identity of the closed form — 1
#   3. independent plain-ODE solve matches the closed form (t=2,5,10) — 9
#   4. NetworkDynamics.jl solve matches the closed form (t=5, t=10) — 6
#   5. NetworkDynamics.jl solve matches the independent solve (t=10) — 3
#   6. NetworkDynamics.jl steady state is (20, 20, 20) at t=100 — 3
#   7. solution structure (retcode, state length, flat parameter vector) — 3
#
# Run: julia --project=. test_network_dynamics.jl
# (needs --heap-size-hint=3G and JULIA_NUM_THREADS=1 on this 6 GB VM)
#
# Hand-computed reference values (Python, math.exp, independent of Julia):
#   t=2:  S = (12.642411176571153, 5.284822353142307, 1.6060279414278824)
#   t=10: S = (19.865241060018292, 19.191446360109744, 17.506959610338377)
#   steady state: (20, 20, 20); int_0^10 S3 dt = 86.87270593906717
#
# Model outputs are model results, never verified plans:
# needs_human_decision = true.

using Test

include(joinpath(@__DIR__, "network_dynamics.jl"))

const HAND_T2 = (12.642411176571153, 5.284822353142307, 1.6060279414278824)
const HAND_T10 = (19.865241060018292, 19.191446360109744, 17.506959610338377)
const HAND_INT_S3_10 = 86.87270593906717  # closed-form int_0^10 S3(t) dt

@testset "analytic closed form matches hand-computed values" begin
    for (i, t, hand) in ((1, 2.0, HAND_T2), (2, 10.0, HAND_T10))
        got = analytic_stock(t)
        for j in 1:3
            @test got[j] ≈ hand[j] atol = 1e-12
        end
    end
end

@testset "mass-balance identity of the closed form" begin
    # total stock at t=10 + cumulative sink outflow (c * int S3) = production * 10
    s = analytic_stock(10.0)
    @test sum(s) + SINK_CONSUMPTION * HAND_INT_S3_10 ≈ SRC_PRODUCTION * 10.0 atol = 1e-9
end

@testset "independent plain-ODE solve matches closed form" begin
    sol = solve_independent()
    for t in (2.0, 5.0, 10.0)
        got = sol(t)
        want = analytic_stock(t)
        for j in 1:3
            @test got[j] ≈ want[j] atol = 1e-6
        end
    end
end

@testset "NetworkDynamics solve matches closed form" begin
    sol = solve_network()
    for t in (5.0, 10.0)
        got = sol(t)
        want = analytic_stock(t)
        for j in 1:3
            @test got[j] ≈ want[j] atol = 1e-6
        end
    end
end

@testset "NetworkDynamics solve matches independent solve" begin
    sol_nd = solve_network()
    sol_ind = solve_independent()
    for j in 1:3
        @test sol_nd(10.0)[j] ≈ sol_ind(10.0)[j] atol = 1e-6
    end
end

@testset "NetworkDynamics steady state" begin
    sol = solve_network(; t_end = 100.0)
    for j in 1:3
        @test sol(100.0)[j] ≈ 20.0 atol = 1e-3
    end
end

@testset "solution structure" begin
    sol = solve_network()
    # retcode is a SciMLBase ReturnCode enum, not the Symbol :Success:
    # compare against the independent solve's retcode instead of naming it.
    @test sol.retcode == solve_independent().retcode
    @test length(sol.u[1]) == 3
    @test network_parameters() ≈ [10.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.5] atol = 1e-12
end
