# START core spine — first local assembly

Date: 2026-11-10. Local only: `~/workspace/start-assembly/core-spine/`.
Nothing here touches `~/workspace/ai-starter`, the v0.3.2 review copy,
any GitHub repo, or START guardrails / self-edit / safety files.
Nothing in this folder has been pushed anywhere.

## What this is

The first assembly of the core spine from Eric's Final Locked-In
START Architecture Blueprint, after the repo triage
(`~/workspace/v032-review/blueprint-triage/REPO_TRIAGE.md`:
64/70 candidates exist as named, 6 do not). Only the core spine
was assembled; the deferred modules (heavyweight LLM platforms,
Mojo inference, Modules 8, 16–19, 23–25, the 6 non-existent names)
were NOT assembled here.

Status rules, from the v0.3.2 review (REVIEW.md ISSUE-02, ISSUE-16)
and the planning-package draft (`blocker-work/planning-package/models.py`):
five internal states PASS / FAIL / UNKNOWN / NOT_CHECKED / INCOMPLETE;
consumer tri-state pass / fail / indeterminate (INCOMPLETE, UNKNOWN,
NOT_CHECKED → indeterminate; FAIL wins); empty checks → NOT_CHECKED,
never PASS; UNKNOWN / INCOMPLETE are never converted into PASS.

## Architecture map

| Component | Module | Repo (exact) | Licence | Role in START | Status |
|---|---|---|---|---|---|
| HiGHS (via SciPy `linprog`) | 14 Optimisation | ERGO-Code/HiGHS | MIT | LP solver for the food-planning LP | assembled |
| CPMpy | 14 Optimisation | CPMpy/cpmpy | Apache-2.0 | CP modelling layer; HiGHS backend here | assembled |
| CVXPY | 14 Optimisation | cvxpy/cvxpy | Apache-2.0 | Convex modelling layer; HiGHS backend here | assembled |
| JuMP.jl | 18 Systems Planning | jump-dev/JuMP.jl | MPL-2.0 | Julia modelling layer for planning LPs | assembled 1.32.1 (Julia 1.13.3) |
| Agents.jl | 10 World Modelling | JuliaDynamics/Agents.jl | MIT | Agent-based world modelling | assembled 7.1.0 (Julia 1.13.3) |
| ModelingToolkit.jl | 10 World Modelling | SciML/ModelingToolkit.jl | MIT | Equation-based structural physics | assembled 11.46.1 (Julia 1.13.3) |
| Symbolics.jl | 12 Math & Computing | JuliaSymbolics/Symbolics.jl | MIT | Symbolic algebra / e-graph rewriting | assembled 7.48.0 (Julia 1.13.3) |
| Turing.jl | 12 Math & Computing | TuringLang/Turing.jl | MIT | Bayesian inference | assembled 0.49.0 (Julia 1.13.3) |
| DifferentialEquations.jl | 12 Math & Computing | SciML/DifferentialEquations.jl | NOASSERTION — confirm before adopting | Continuous physical systems | assembled 8.1.1 (Julia 1.13.3) |
| AlphaZero.jl | 4 Reasoning & Planning | jonathan-laurent/AlphaZero.jl | MIT | MCTS + self-play search (board-game core) | assembled 0.5.6 (git clone, CPU only, no training) |
| PlanningSearch (MCTS + game interface copied from AlphaZero.jl) | 4 Reasoning & Planning | jonathan-laurent/AlphaZero.jl (source, MIT) | MIT (copied files) | Standalone planning search: MCTS over partial plans, rollout oracle + learned linear oracle, candidate only — never verified by the search; original training loop (verified samples only, held-out replacement rule) | assembled 2026-11-11, 75/75 + 53/53 + 86/86 + 25/25 Julia tests PASS, finds the 600/50 t optimum |

## Canonical Julia environment (adopted 2026-11-11 by Eric)

`julia-current/` is the canonical Julia environment for this spine:
Julia 1.13.3, Agents 7.1.0, ModelingToolkit 11.46.1, Symbolics 7.48.0,
Turing 0.49.0, DifferentialEquations 8.1.1, JuMP 1.32.1, HiGHS 1.26.1,
AlphaZero 0.5.6 (separate env in `alphazero/`). Spine 16/16 PASS,
Julia checks 268/268 passed, 0 failed (29 spine/smokes/AlphaZero +
75 planning-search + 53 LP cross-check + 86 training loop +
25 training loop LP-split). The original pinned envs
`julia/` and `julia-1.11/` are evidence only — they fail to precompile
5 dependencies and are NOT canonical; do not use them for new work.
| LangGraph | 5 Orchestration | langchain-ai/langgraph | MIT | Stateful plan → verify → report graph | assembled |
| Cedar | 2 Governance & Security | cedar-policy/cedar | Apache-2.0 | Formal authorisation policy engine | assembled (Rust) + Python stub evaluator |
| egg | 4 Reasoning & Planning | egraphs-good/egg | MIT | E-graph symbolic rewrites | assembled (Rust) |
| Tonic / gRPC | 21 Interoperability | grpc/grpc-rust | MIT | Contract-driven RPC | stub only (Rust); runnable gRPC is Python grpcio over a Unix socket |
| Apache Arrow | 21 Interoperability | apache/arrow | Apache-2.0 | Zero-copy in-memory table sharing | assembled (pyarrow) |
| DeepEval | 22 Evaluation & Learning | confident-ai/deepeval | Apache-2.0 | Evaluation framework | local non-LLM metrics only; LLM-as-judge deferred |

## Layout

- `adapters/` — thin Python adapters, no vendored engine code:
  `statuses.py` (status model), `optimisation.py` (HiGHS/CPMpy/CVXPY),
  `interop.py` (Arrow + gRPC), `governance.py` (Cedar stub evaluator),
  `orchestration.py` (LangGraph plan → verify → report),
  `evaluation.py` (DeepEval non-LLM metrics only).
- `helpers/` — borrowed helpers, the ONLY vendored candidate code in
  this assembly: `borrowed_helpers.py` (Cognee `chunk_by_word` +
  `chunk_id`, Crawl4AI `normalize_url`, Apache-2.0 notices kept,
  stdlib-only, `PROVENANCE.md` in the same folder). Untrusted-input
  utilities only — NOT wired into any verify, governance, or decision
  path. Tests `tests/test_borrowed_helpers.py` — 24/24 PASS.
- `tests/test_spine.py` — the test suite. Run: `.venv/bin/python -m unittest discover -s tests -v`
- `rust/` — Cargo crate: real Cedar evaluation, egg rewrites, Tonic stub.
  Run: `export PATH="$HOME/.cargo/bin:$PATH" && cargo test` (rustc 1.99.1).
- `julia-current/` — canonical Julia env (`Project.toml`, `Manifest.toml`, `spine.jl`, `spine_lp.jl`, `spine_ode.jl`, smokes, logs). Run it, not `julia/`.
- `julia-current/planning-search/` — standalone planning-search module
  (`PlanningSearch.jl`, copied `mcts.jl` + `game.jl` with MIT notices,
  original `planning_domain.jl` + `verify.jl`, `PROVENANCE.md`,
  `test/runtests.jl` — 75/75 PASS). MCTS finds the 600/50 t optimum
  on the synthetic domain; every result is a CANDIDATE only
  (`verified=false`, `needs_human_decision=true`) until the separate
  verify step passes AND a human approves. `verify_lp.jl` (original,
  JuMP+HiGHS) wires that verify step to a second, independent LP
  cross-check — combined verdict PASS only if both pass; a
  candidate claiming better than the optimum (delivered 650 /
  shortage 0) passes the constraint verify alone and fails the LP
  check. Runner `run_verify_lp.jl`; tests `test/verify_lp.jl` —
  53/53 PASS (standalone script, not in `test/runtests.jl`, so the
  standalone tests stay JuMP-free). `training_loop.jl` (original,
  replaces the AlphaZero training loop — no opponent, no win/loss,
  no network library) keeps only verify+LP PASS candidates as
  training samples, fits a linear value model as a learned oracle,
  and replaces the current oracle only on a held-out
  verified-PASS rate at least as high with a mean shortage no
  worse. Runner `run_training_loop.jl` — TRAINING_LOOP RESULT:
  PASS (3 iterations, 12 kept, 0 rejected; final held-out learned
  mean shortage 117.5 t vs rollout 167.5 t at tied PASS rates of
  1.0). Tests `test/training_loop.jl` — 86/86 PASS — and
  `test/training_loop_lp.jl` — 25/25 PASS.
- `julia/` and `julia-1.11/` — original pinned envs, kept untouched as evidence only (fail to precompile).
- `proto/constraint_evaluation.proto` — the gRPC wire contract (schema 1.0.0).
- `policies.cedar` — the authoritative Cedar policies.
- `examples/` — (reserved; the synthetic example lives in `adapters/optimisation.py`).
- `LICENCES.md`, `ASSEMBLY_REPORT.md`, `CHECKPOINT.md`.

## Synthetic example (all solvers must agree)

1 site, 2 crops, water binding. Wheat 4 t/ha, 1,200 m³/ha, demand 250 t;
Potato 20 t/ha, 2,000 m³/ha, demand 400 t; land 100 ha, water 100,000 m³.
Loss-free cross-solver totals: **delivered 600 t, shortage 50 t,
production 600 t, land 70 ha, water 100,000 m³**.
With a 5% distribution loss (SciPy/HiGHS only): delivered 583.33 t,
shortage 66.67 t, production 614.04 t. Synthetic only — not a real
region, diet, or advice.

## How to run

```bash
cd ~/workspace/start-assembly/core-spine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
export PATH="$HOME/.cargo/bin:$PATH"
cargo test --manifest-path rust/Cargo.toml
```

Julia (canonical env, Julia 1.13.3 at `~/.juliaup/bin/julia`):
```bash
export PATH="$HOME/.juliaup/bin:$PATH"
JULIA_NUM_THREADS=1 JULIA_NUM_PRECOMPILE_TASKS=1 julia --project=julia-current -e 'import Pkg; Pkg.instantiate()'
JULIA_NUM_THREADS=1 julia --project=julia-current --heap-size-hint=3G julia-current/spine.jl   # 16/16 PASS
```
