# Canonical Julia environment — adopted 2026-11-11 by Eric

This folder (`julia-current/`) is the canonical Julia environment for
the START core spine.

- Julia 1.13.3 (juliaup, `~/.juliaup/bin/julia`)
- Agents 7.1.0, ModelingToolkit 11.46.1, Symbolics 7.48.0,
  Turing 0.49.0, DifferentialEquations 8.1.1, JuMP 1.32.1, HiGHS 1.26.1,
  Distributions 0.25.134 (added 2026-11-11 as a direct dependency for
  the planning-search module; resolved set otherwise unchanged)
- AlphaZero 0.5.6 lives in the separate `alphazero/` env (git clone)
- Planning-search module in `planning-search/` (MCTS + game interface
  copied from AlphaZero.jl 0.5.6, MIT; original START planning domain
  + verify code) — see `planning-search/PROVENANCE.md`
- Verified 2026-11-11: spine.jl 16/16 PASS, Julia checks 104/104
  passed, 0 failed (29 spine/smokes/AlphaZero + 75 planning-search);
  JuMP+HiGHS LP delivered 600 t / shortage 50 t; food 2800 >= 2500
  kcal/capita/day PASS; MCTS (rollout oracle, nsims=1000) finds the
  same 600 t / 50 t optimum as a candidate only. LP regression
  re-run after the planning-search work: spine_lp.jl 15/15 PASS

Use this env for all new Julia work on the spine. The pinned envs in
`julia/` and `julia-1.11/` are evidence only and are not canonical.
