# Smoke test: Agents.jl — a 10-agent grid model, 5 steps.
# Pass = 10 agents present after 5 steps, none lost, needs_human_decision=true.
# Run: julia --project=. --heap-size-hint=3G smoke_agents.jl
using Agents

@agent struct Person(GridAgent{2})
    wealth::Float64
end

function agent_step!(agent, model)
    agent.wealth += 1.0
    return nothing
end

model = StandardABM(Person, GridSpace((10, 10)); agent_step!)
for _ in 1:10
    add_agent!(model; wealth=0.0)
end
step!(model, 5)
n = nagents(model)
total_wealth = sum(a.wealth for a in allagents(model))
println("AGENTS SMOKE: nagents=$n total_wealth=$total_wealth (expected 10 / 50.0)")
println("AGENTS SMOKE: $(n == 10 && total_wealth == 50.0 ? "PASS" : "FAIL") needs_human_decision=true")
(n == 10 && total_wealth == 50.0) || exit(1)
