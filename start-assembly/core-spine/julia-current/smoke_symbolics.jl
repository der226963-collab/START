# Smoke test: Symbolics.jl — expand (x+1)^2 and differentiate.
# Pass = expansion equals x^2 + 2x + 1 and d/dx = 2x + 2.
# Run: julia --project=. --heap-size-hint=3G smoke_symbolics.jl
using Symbolics

@variables x
expr = expand((x + 1)^2)
expected = x^2 + 2x + 1
deriv = Symbolics.derivative(expr, x)
println("SYMBOLICS SMOKE: expand((x+1)^2) = $expr")
println("SYMBOLICS SMOKE: d/dx = $deriv")
ok = isequal(expr, expected) && isequal(deriv, 2x + 2)
println("SYMBOLICS SMOKE: $(ok ? "PASS" : "FAIL") needs_human_decision=true")
ok || exit(1)
