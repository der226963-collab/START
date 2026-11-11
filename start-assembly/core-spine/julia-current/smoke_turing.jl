# Smoke test: Turing.jl — a coin-flip model, 200 MH samples, fixed seed.
# p ~ Beta(1,1); y ~ Bernoulli(p) for 10 flips with 7 heads.
# Pass = posterior mean of p is in [0.5, 0.8] (sanity range only;
# this is a smoke test, not a statistical validation).
# Run: julia --project=. --heap-size-hint=3G smoke_turing.jl
using Turing
using Statistics

@model function coinflip(y)
    p ~ Beta(1, 1)
    for i in eachindex(y)
        y[i] ~ Bernoulli(p)
    end
end

y = [1, 1, 0, 1, 1, 0, 1, 1, 0, 1]  # 7 heads in 10
chain = sample(coinflip(y), MH(), 200; progress=false)
m = mean(chain[:p])
println("TURING SMOKE: posterior mean of p = $m (expected in [0.5, 0.8])")
ok = 0.5 <= m <= 0.8
println("TURING SMOKE: $(ok ? "PASS" : "FAIL") needs_human_decision=true")
ok || exit(1)
