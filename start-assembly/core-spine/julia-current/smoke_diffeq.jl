# Smoke test: DifferentialEquations.jl — exponential decay dS/dt = -0.1 S.
# S(0)=100, t in [0,10] -> S(10) = 100*exp(-1) ≈ 36.7879.
# Pass = |S(10) - 36.7879| < 0.01. Checked, not trusted on its own.
# Run: julia --project=. --heap-size-hint=3G smoke_diffeq.jl
using DifferentialEquations

f(u, p, t) = -0.1 * u
prob = ODEProblem(f, 100.0, (0.0, 10.0))
sol = solve(prob, Tsit5())
final = sol[end]
expected = 100.0 * exp(-1.0)
println("DIFFEQ SMOKE: S(10) = $final (expected $expected)")
ok = abs(final - expected) < 0.01
println("DIFFEQ SMOKE: $(ok ? "PASS" : "FAIL") needs_human_decision=true")
ok || exit(1)
