# START core-spine — Assembly Report

Date: 2026-11-10. Location: `~/workspace/start-assembly/core-spine/`
(assembled locally; pushed to der226963-collab/START under
`start-assembly/core-spine/` on 2026-11-11, commit
674f6abc7478bbd497c8459ceec8e4a3d553ba2b; `~/workspace/ai-starter`,
the v0.3.2 review copy, and START guardrails/safety files untouched).

## Headline

- **Components: 20 total — 19 assembled, 1 stub-only, 0 blocked, 0 not run**
- **Tests: Python 136/136 passed, Rust 30/30 passed, Julia 513/513 checks passed — 679 passed, 0 failed**
- **Tests not run: 0**
- Runner `examples/run_spine.py`: ALL ASSEMBLED ADAPTERS PASS
- Julia spine: `julia-current/spine.jl` **16/16 checks PASS** (food 2800>=2500 PASS,
  LP delivered 600 t / shortage 50 t, ODE steady state 99.9952 t vs 100 t)

## Per-component status

| Component | Repo | Version installed | Status | Tests | Notes |
|---|---|---|---|---|---|
| HiGHS (via SciPy linprog) | ERGO-Code/HiGHS | SciPy 1.18.1 (venv) / system 1.11.4 | assembled | 5/5 Python (incl. PCAC-style) | Cross-solver totals 600/50 t; 5% loss totals 583.33/66.67 t |
| CPMpy | CPMpy/cpmpy | 1.1.1 | assembled | 1/1 | HiGHS backend (highspy 1.15.1); integer-scaled LP, same 600/50 t |
| CVXPY | cvxpy/cvxpy | 1.9.3 | assembled | 1/1 | HiGHS backend; same 600/50 t |
| JuMP.jl | jump-dev/JuMP.jl | 1.32.1 | assembled | 15/15 checks in spine_lp.jl (subset of combined 16/16) | JuMP + HiGHS LP reproduces 600/50 t; same version in pinned and current envs (MPL-2.0) |
| Agents.jl | JuliaDynamics/Agents.jl | 7.1.0 | assembled | smoke PASS (10 agents, wealth 50.0) | Pinned 6.2.10 fails to precompile (Distributions @check_args); current 7.1.0 passes. Smoke: `julia-current/smoke_agents.jl`, log `julia-current/logs/smoke-agents-current.log` |
| ModelingToolkit.jl | SciML/ModelingToolkit.jl | 11.46.1 | assembled | spine_ode PASS + combined 16/16 | Pinned 9.59.0 fails to precompile on Julia 1.13 and 1.11; current 11.46.1 passes (138.8 s precompile). ODE steady state 99.9952 t vs 100 t. Licence-metadata mismatch noted in LICENCES.md |
| Symbolics.jl | JuliaSymbolics/Symbolics.jl | 7.48.0 | assembled | smoke PASS (expand (x+1)², d/dx) | Pinned 6.58.0 passes on 1.13; current 7.48.0 passes too. Licence-detection mismatch noted |
| Turing.jl | TuringLang/Turing.jl | 0.49.0 | assembled | smoke PASS (posterior mean 0.6387 in [0.5, 0.8]) | Pinned 0.34.1 passes on 1.13 (mean 0.6265); current 0.49.0 passes too |
| DifferentialEquations.jl | SciML/DifferentialEquations.jl | 8.1.1 | assembled | smoke PASS (S(10)=36.78795 vs 36.78794) + spine_ode PASS | Pinned 7.17.0 fails to precompile on Julia 1.13 and 1.11 (SteadyStateDiffEq/DiffEqBase); current 8.1.1 passes. Licence NOASSERTION — confirm before adopting |
| NetworkDynamics.jl | JuliaDynamics/NetworkDynamics.jl | 1.3.0 | assembled | **31/31 Julia tests PASS** (see "NetworkDynamics.jl (Module 10)" below) | First networked domain model built first (synthetic 3-node resource network), then the dependency added — per the sweep's condition. Sweep said 1.4.0; the General registry latest is 1.3.0 (verified, see section). Dependency only, no code copied. Graphs.jl 1.15.0 added as a direct dependency for the network graph (already in the Manifest as transitive, resolved set otherwise unchanged). |
| AlphaZero.jl | jonathan-laurent/AlphaZero.jl | 0.5.6 | assembled | smoke 9/9 checks PASS | Git clone (not General registry); own env in `alphazero/` (Flux 0.16.12, CUDA 5.11.1, Plots 1.41.7, cuDNN 1.4.7). ConnectFour init + one move, CPU only, no training. Log `alphazero/logs/smoke-alphazero.log` |
| PlanningSearch (MCTS + game interface, copied from AlphaZero.jl) | jonathan-laurent/AlphaZero.jl (source) | 0.5.6, commit 177a6eb | assembled | **81/81 + 53/53 + 86/86 + 25/25 + 208/208 Julia tests PASS** | Standalone in `julia-current/planning-search/` (no AlphaZero.jl import; Distributions 0.25.134 only). MCTS + game interface copied with full MIT notice, re-expressed in planning terms (states = partial plans, reward = plan quality, not win probability). Original START code: `planning_domain.jl` (1-site 2-crop synthetic), `verify.jl`, `verify_lp.jl` (JuMP+HiGHS LP cross-check, separate file so `verify.jl` stays Distributions-only), `training_loop.jl` (original planning training loop — verified samples only, linear value model, held-out replacement rule; no network library), and `dynamics_search.jl` (original learned-dynamics search, INSPIRATION-REBUILD of MuZero.jl's design — no MuZero.jl code copied, no Flux/CUDA; see "Learned-dynamics search" below). Search finds the known optimum — delivered 600 t / shortage 50 t — candidate only, never verified by the search; the LP cross-check catches candidates that beat the optimum. See "Planning-search module" below |
| Borrowed helpers (Cognee chunk_by_word + chunk_id, Crawl4AI normalize_url) | topoteretes/cognee, unclecode/crawl4ai | Apache-2.0 | assembled | **24/24 Python tests PASS** | `helpers/borrowed_helpers.py`, stdlib-only, Apache-2.0 notices kept, provenance in `helpers/PROVENANCE.md`. Untrusted-input utilities only — not wired into any verify, governance, or decision path. Crawl4AI's own test file does not match the cloned function in 4 of 20 cases (recorded in PROVENANCE.md); tests assert actual behaviour. See "Borrowed helpers" below |
| LangGraph | langchain-ai/langgraph | 1.2.20 | assembled | 1/1 (+ pipeline tests) | Real StateGraph plan → verify → report; report refuses without verification |
| Cedar | cedar-policy/cedar | 4.14.1 (Rust) | assembled | 4/4 Rust | Real Cedar engine evaluates policies.cedar; Python adapter is a documented stub evaluator for the same two policies |
| egg | egraphs-good/egg | 0.10.0 | assembled | 2/2 Rust | `(+ x 0) -> x`, `(* y 1) -> y` |
| Tonic / gRPC | grpc/grpc-rust | tonic 0.14.9 (real server) | assembled | **14/14 Rust tests PASS** (4 Cedar, 2 egg, 3 stub evaluator, 4 wire + 1 server unit) + **4/4 new Python wire tests PASS** | Real Rust Tonic server (`rust/src/server.rs`, binary `start-tonic-server`) serves `proto/constraint_evaluation.proto` over a Unix socket; Python grpcio client calls it over the wire (PASS + FAIL cases). See "Real Tonic server (Module 21)" below |
| Apache Arrow | apache/arrow | pyarrow 26.0.1 | assembled | 1/1 | Arrow round-trip lossless on constraint-result table |
| DeepEval | confident-ai/deepeval | 4.3.3 | assembled | **11/11 Python tests PASS** (3 ExactMatch + 8 new) | Deterministic metrics only, no API key: ExactMatch scores [1,1,1,0], accuracy 0.75; PatternMatch (fullmatch) scores [1.0, 0.0, 0.0] on pattern `\d+ tonnes`; JsonCorrectness scores [1, 0, 0, 0, 0] against original schema PlanJsonSchema. Sweep correction: JsonCorrectness is key-free ONLY via eval_mode="system_one" — default construction builds an OpenAI model and raises without a key. LLM-as-a-judge metrics deferred, not run. See "DeepEval deterministic metrics (Module 22)" below |
| ODYM | IndEcol/ODYM | 0.1.0, git pin 9792c23 | assembled | **16/16 Python tests PASS** | Stock-flow resource accounting (Module 17). Dependency only, no code copied; never published to PyPI, installed from git pinned to the sweep's audited commit (see item 9). Thin original adapter `adapters/resource_accounting.py` over a synthetic 1-site 2-crop material flow (3 years, balance PASS, residual 0.0 t). Outputs are model results only — verified=false, needs_human_decision=true. See "ODYM (Module 17)" below |
| Pymrio | IndEcol/pymrio | 0.7.0 (PyPI) | assembled | **15/15 Python tests PASS** | Footprint / consumption-based accounting (Module 17). Dependency only, never copied, library unmodified and replaceable (LGPL-3.0; README badge wrongly says GPL v3 — LICENSE file authoritative). Thin original adapter `adapters/footprint_accounting.py` over a synthetic 2-region x 2-sector in-memory MRIO (footprint identity PASS, residual 2.2e-16 t). No downloads — no pymrio download/load/parse function is ever called. Outputs are model results only — verified=false, needs_human_decision=true. See "Pymrio (Module 17)" below |
| Graphiti (temporal schema only) | getzep/graphiti | Apache-2.0 (no version installed — nothing adopted) | assembled | **17/17 Python tests PASS** | Temporal knowledge fields only (Module 6): `adapters/temporal.py`, original Python, stdlib only — episodes with valid_from/valid_to, superseded_by, episode links. No Graphiti code copied; the system, LLM extraction, graph DB and telemetry were NOT adopted. See "Temporal knowledge (Graphiti rebuild, Module 6)" below |
| ash-flare | ashforge-rs/ash-flare | 3.0.0 (crates.io) | assembled | **6/6 new Rust tests PASS** (Rust suite now 20/20) | Local supervision of execution workers only (Module 24). Dependency only, no code copied, default features only (`python` OFF), distributed mode OFF by non-use. Supervisor core audited first. See "ash-flare (Module 24)" below |
| BehaviorTree.rs (node types + typed blackboard only) | ncrothers/behaviortree-rs | MIT (no version installed — nothing adopted) | assembled | **10/10 new Rust tests PASS** (Rust suite now 30/30) | Original Rust orchestration (Module 4): Sequence / Fallback / Inverter + Succeeder decorators / Action / Condition + typed blackboard, trees in JSON. No BehaviorTree.rs code copied; crate NOT a dependency. Verify is a hard gate — report refuses without a passed verify in the same run. See "Behavior-tree orchestration (BehaviorTree.rs rebuild, Module 4)" below |
| Beam-Telemetry (event bus only) | beam-telemetry/telemetry | Apache-2.0 (no version installed — nothing adopted) | assembled | **17/17 new Python tests PASS** (Python suite now 136/136) | Original Python monitoring bus (Module 8): `adapters/event_bus.py`, stdlib only — execute/attach/detach, events carrying licence/provenance + verified flag + needs_human_decision. No Beam-Telemetry code copied; Erlang library NOT a dependency. Handlers never mark a result verified — promotion attempts are rejected and logged. See "Monitoring event bus (Beam-Telemetry rebuild, Module 8)" below |

## Exact versions installed (venv `.venv`, Python 3.12.3)

numpy 2.5.4, scipy 1.18.1, pyarrow 26.0.1, grpcio 1.85.1,
grpcio-tools 1.85.1, langgraph 1.2.20, cpmpy 1.1.1, cvxpy 1.9.3,
highspy 1.15.1, deepeval 4.3.3, odym 0.1.0 (git pin 9792c23, not
PyPI — see item 9). Full list in `requirements.txt`.
Rust: rustc/cargo 1.99.1 (`~/.cargo/bin`, not on PATH);
cedar-policy 4.14.1, egg 0.10.0, tonic 0.14.9, tonic-prost 0.14.9,
tonic-prost-build 0.14.9, prost 0.14.5, prost-build 0.14.5,
tokio 1.54.1, tokio-stream 0.1.19, hyper-util 0.1.21, tower 0.5.3,
ash-flare 3.0.0 (default features only, `python` OFF — no pyo3 in the
resolved tree), async-trait 0.1.92
(see `rust/Cargo.lock`).
Julia: 1.13.3 (release channel) at `/home/hatch/.juliaup/bin/julia`
(juliaup, `~/.juliaup`); also 1.11.9 installed via `juliaup add 1.11`
(invoked as `julia +1.11`). Working env is `julia-current/` (current
versions, no per-package compat bounds): Agents 7.1.0,
DifferentialEquations 8.1.1, HiGHS 1.26.1, JuMP 1.32.1,
ModelingToolkit 11.46.1, Symbolics 7.48.0, Turing 0.49.0,
NetworkDynamics 1.3.0, Graphs 1.15.0 (both added 2026-11-11 for
the first networked domain model — see "NetworkDynamics.jl
(Module 10)" below; adding NetworkDynamics pulled in 26 new
Manifest packages, 299 → 325, and changed no existing package
version; Graphs was already in the Manifest as a transitive
dependency, so adding it as direct changed nothing),
Distributions 0.25.134 (added as a direct dependency 2026-11-11
for the planning-search module — it was previously only a
transitive dependency and could not be loaded by a standalone
module; the resolved set is otherwise unchanged).
The original pinned env `julia/` (Agents 6.2.10, DiffEq 7.17.0,
MTK 9.59.0, Symbolics 6.58.0, Turing 0.34.1) fails to precompile —
see "Julia install" below. AlphaZero 0.5.6 in `alphazero/` (Flux
0.16.12, CUDA 5.11.1, Plots 1.41.7, cuDNN 1.4.7, JSON3 1.14.4
deprecated). `~/.julia` is ~7.6 GB (three envs + caches).

## Julia install (added 2026-11-10/11)

- **Version:** Julia 1.13.3+0.x64.linux.gnu (release channel), installed
  2026-11-10 via the official juliaup installer
  (`curl -fsSL https://install.julialang.org`, script inspected first).
  Also Julia 1.11.9 (`juliaup add 1.11`) for a second-era check.
- **Install path:** `/home/hatch/.juliaup`, binary
  `/home/hatch/.juliaup/bin/julia`. Depot `~/.julia`.
- **Environments:**
  - `julia/` — the assembly's original pinned env (Project.toml with
    corrected UUIDs, see bug 7). `Pkg.instantiate()` exit 0 in ~20 min,
    but 5 direct dependencies failed to precompile (see bug 8).
    Log: `julia/logs/instantiate.log`. Its `spine_lp.jl` stage still
    PASSED 15/15 (JuMP+HiGHS only), and Symbolics/Turing smokes passed
    there; the MTK/DiffEq/Agents pieces did not.
  - `julia-1.11/` — same pinned env, fresh resolve on Julia 1.11.9.
    Instantiate completed (exit 0) but with the SAME 5 precompile
    failures (bug 8 is version skew, not a Julia-version problem).
    Log: `julia-1.11/logs/instantiate-1.11.log`. The run was
    interrupted once by a runtime restart mid-precompile and resumed
    from the surviving Manifest/caches with no data loss.
  - `julia-current/` — **the working env.** Copy of `julia/` with the
    Manifest removed and per-package compat bounds removed, so Pkg
    resolved the newest mutually-compatible set. Instantiate exit 0:
    284 dependencies precompiled in 2707 s, 206 already precompiled.
    Log: `julia-current/logs/instantiate-current.log`. All 7 Julia
    components pass here (see Test results).
  - `alphazero/` — git clone of jonathan-laurent/AlphaZero.jl @ 0.5.6
    with its own Project/Manifest. Instantiate exit 0: 201 deps
    precompiled in 740 s. Log: `alphazero/logs/instantiate-alphazero.log`.
- **Runs (all with `JULIA_NUM_THREADS=1`,
  `JULIA_NUM_PRECOMPILE_TASKS=1`, `--heap-size-hint=3G`):**
  combined `julia-current/spine.jl` 16/16 PASS
  (`julia-current/logs/spine-combined-current-run.log`);
  `spine_lp.jl` 15/15 PASS, `spine_ode.jl` PASS
  (`julia-current/logs/spine-lp-current-run.log`,
  `spine-ode-current-run.log`); smokes: Agents, DifferentialEquations,
  Symbolics, Turing PASS
  (`julia-current/logs/smoke-*-current.log`); AlphaZero 9/9 PASS
  (`alphazero/logs/smoke-alphazero.log`).
- **Checkpoints:** `julia/CHECKPOINT.md`,
  `julia-1.11/CHECKPOINT-1.11.md`, `julia-current/CHECKPOINT.md`
  record each stage (install, instantiate, OOM, LP pass, ODE failure,
  smokes, 1.11 attempt, current-env resolve/pass).

## Planning-search module (added 2026-11-11)

In `julia-current/planning-search/` (standalone in the
canonical env; the `alphazero/` clone, `~/workspace/ai-starter`,
and the v0.3.2 review copy are untouched; the module itself was
pushed to der226963-collab/START under `start-assembly/core-spine/`
on 2026-11-11, commit 674f6abc). Source audit
(`source-audit/ALPHAZERO_LANGGRAPH_AUDIT.md`) verdicts followed:
COPY `mcts.jl` + `game.jl`, REWRITE training loop, DEPENDENCY ONLY
for the Flux/CUDA network.

- **Provenance:** AlphaZero.jl v0.5.6, jonathan-laurent/AlphaZero.jl,
  git HEAD 177a6eb04aedeff7542bbaeeaf2c3c6da221aa96, MIT Copyright
  (c) 2019 Jonathan Laurent. Full MIT notice at the top of EACH
  copied file; `PROVENANCE.md` in the folder lists every change,
  the term mapping, and what was NOT copied (training loop,
  networks/, memory buffer, ConnectFour code). Copied files:
  `mcts.jl` (377 lines with header) and `game.jl` (429 lines with
  header). Original START code: `PlanningSearch.jl`,
  `planning_domain.jl`, `verify.jl`, `test/runtests.jl`.
- **Re-expression (planning terms):** the MCTS algorithm is
  unchanged (UCT selection, Dirichlet-noise exploration, rollouts,
  policy from visit counts, oracle interface (P, V)), but the
  two-player zero-sum semantics are gone: states = partial plans,
  actions = allocations (hectares per crop), reward/value V = plan
  quality under constraints (shortage, water, land), NOT a win
  probability. Planning-facing API uses `plan_reward`,
  `planner_acting`, `plan_terminated`; the copied internals still
  call `white_reward` / `white_playing`, documented in the file
  headers and `PROVENANCE.md` (the q-sign flip in
  `run_simulation!` never triggers — the planner always acts).
  `apply_temperature` is a START-written helper, NOT copied from
  AlphaZero `util.jl`. No AlphaZero.jl import anywhere.
- **Dependency finding:** the copied MCTS needs only
  Distributions (Dirichlet/Categorical). It was already in the
  Manifest as a transitive dependency but could not be loaded by a
  standalone module, so Distributions 0.25.134 was added as a
  direct dependency to `julia-current/Project.toml`; the resolved
  set is otherwise unchanged. No DataStructures/StaticArrays
  import in either copied file. No heavy dependency was added.
- **Measured behaviour (not claimed):** at nsims=500 the
  visit-count policy lags the Q-values — seed 1234 chose wheat
  60 ha / potato 10 ha (delivered 440 t) even though wheat 50 ha
  had the higher mean Q (0.86 vs 0.65). At nsims=1000 the
  visit-count policy finds the optimum (600 t / 50 t) on all five
  seeds tested (1234, 7, 42, 99, 2024); the mean-Q selection also
  finds it at nsims=500 on all five seeds. Default is therefore
  nsims=1000, `:visits`, with `:mean_q` as a documented alternative.
- **Candidate-only rule (non-negotiable):** every search result is
  a `PlanningCandidate` with `status="CANDIDATE"`,
  `verified=false`, `needs_human_decision=true`. It must pass the
  separate `verify_candidate` step (land ≤ 100 ha, water ≤
  100,000 m³, delivered + shortage == 650, production ==
  delivered, shortage ≥ 0; empty → NOT_CHECKED, FAIL wins,
  UNKNOWN/INCOMPLETE → indeterminate) and a human approval before
  it can be called verified. Tests prove: `verified_status`
  is false for a PASS verdict without human approval, and for
  FAIL/UNKNOWN verdicts even with approval; the search's own
  `verified_by_search` flag is always false.
- **Tests:** `julia-current/planning-search/test/runtests.jl`,
  **75/75 PASS**, plus the LP cross-check tests
  `julia-current/planning-search/test/verify_lp.jl`, **53/53 PASS**,
  plus the training-loop tests `test/training_loop.jl`,
  **86/86 PASS**, and `test/training_loop_lp.jl`, **25/25 PASS**
  (see Test results). LP regression after the work:
  `spine_lp.jl` 15/15 PASS, combined `spine.jl` 16/16 PASS.

## LP cross-check (added 2026-11-11)

`verify_candidate_with_lp` in `julia-current/planning-search/
verify_lp.jl` (original START code) wires the verify step to a
second, independent JuMP+HiGHS LP check of MCTS candidates:

- The LP is solved FROM THE SPEC (yields, water per ha, demand,
  land/water limits) in two stages, exactly as in `spine_lp.jl`:
  Stage 1 minimise total shortage, Stage 2 hold shortage at its
  optimum and minimise production. The candidate and the MCTS
  search do not influence the LP model.
- Combined verdict: PASS only if BOTH the constraint verify and
  the LP cross-check pass; FAIL if either fails; UNKNOWN if the LP
  does not reach OPTIMAL in either stage or any value is
  non-finite. Solver failure is NEVER a PASS.
- The LP cross-check is a BOUND check, not an equality check: a
  candidate must not claim better than the LP optimum (delivered
  above 600 t, shortage below 50 t, production above 600 t) and
  must respect the spec land/water budgets. A feasible but
  suboptimal candidate (e.g. delivered 400 t, shortage 250 t)
  passes both checks — verification is feasibility, not
  optimality.
- It catches what the constraint verify alone misses: a candidate
  claiming delivered 650 t / shortage 0 t is arithmetically
  consistent (650 == total demand, production == delivered) so
  the constraint verify PASSES it, but the LP cross-check FAILS
  it (delivered above the optimum, shortage below the optimum).
  An over-water candidate (112,000 m³) fails both checks.
- Split-file rule (kept): `verify.jl` stays loadable on
  Distributions alone; the LP wiring lives in `verify_lp.jl`
  (loads JuMP+HiGHS) and in the separate runner
  `run_verify_lp.jl`, following the split-stage pattern from
  `spine_lp.jl` / `spine_ode.jl`. The LP test file
  `test/verify_lp.jl` is likewise a standalone script, NOT
  included from `test/runtests.jl`, so the standalone tests stay
  JuMP-free.
- The LP check does NOT certify a candidate on its own: verified
  still requires the combined verdict PASS *and* human approval
  (`verified_status` in `verify.jl`).

## Training loop, rewritten for planning (added 2026-11-11)

`training_loop.jl` (original START code, included by
`PlanningSearch.jl`) replaces the AlphaZero.jl training loop
(`src/training.jl`, 360 lines — studied, NOT copied, and neither
were `learning.jl`, `simulations.jl`, or `networks/`). There is
no self-play, no opponent, no win/loss, and no network library:
the fitted model is ridge least squares from LinearAlgebra
(stdlib) over eight spec-normalised plan features.

- **Loop:** per iteration, one candidate per training spec
  (the 1-site 2-crop spec with demand / land / water perturbed
  deterministically by seed — never a real region), generated
  with the current oracle (rollout oracle first, learned oracle
  after a replacement), verified with the verify function it is
  given, and kept as training samples ONLY if the verdict is
  PASS. Rejected candidates are counted and never enter the
  memory. The memory (`VerifiedMemory`, bounded, oldest-first)
  holds verified samples only — `insert_verified!` throws for
  an unverified sample or a non-finite outcome (tested).
- **Learned oracle:** the fitted linear value model becomes a
  `LearnedOracle` the MCTS search can use in place of the
  rollout oracle: V is the fitted value of a state, P scores
  each action by the fitted value of the successor plan
  (softmax). It is bound to one spec at a time; the model
  itself is spec-independent.
- **Replacement rule (replaces the arena pit):** a new oracle
  replaces the current one ONLY if, on held-out specs never
  used in its training, its MCTS candidates reach a
  verified-PASS rate at least as high as the rollout oracle's,
  with a mean shortage no worse. The decision and the held-out
  numbers are recorded in every iteration report. Even after
  replacement the oracle is only a candidate generator — it
  never verifies a plan.
- **Measured results (runner `run_training_loop.jl`, 3
  iterations, 4 training + 4 held-out specs, nsims=200,
  combined verify):** 12 generated, 12 verified-kept, 0
  rejected, 24 samples in memory. Final iteration held-out:
  rollout PASS rate 1.0, learned PASS rate 1.0, rollout mean
  shortage 167.5 t, learned mean shortage 117.5 t — the
  learned oracle improves mean shortage by 50 t with PASS
  rates tied, so it replaced the current oracle in all three
  iterations. TRAINING_LOOP RESULT: PASS. Fitted weights:
  [0.026, 0.0, 0.011, 0.018, -0.01, 0.026, 0.04, 0.0, 0.707]
  (bias dominates — the model is mostly a constant plus small
  feature adjustments, and it still helps on held-out specs).
- **Known limitation (measured, not hidden):** the linear
  model cannot express interactions — e.g. water committed to
  wheat while potato still needs water — so it ranks wheat
  60 ha above wheat 50 ha as a first step on the base spec,
  even though 50 ha is the better plan. That ranking is
  deliberately NOT asserted in the tests; whether the oracle
  helps is judged by the held-out comparison, and a worse
  oracle is never adopted. The fitted value can also be
  trusted only as a search prior, never as verification.
- **Split-file rule (kept):** `training_loop.jl` itself stays
  loadable on Distributions alone — it takes the verify
  function as a parameter. The standalone tests use the
  constraint verify; the LP tests (`test/training_loop_lp.jl`)
  and the runner pass the combined verify
  (`verify_candidate_with_lp`).

## Learned-dynamics search (MuZero.jl rebuild, added 2026-11-11)

`dynamics_search.jl` (original START code, included by
`PlanningSearch.jl`) is the sweep's INSPIRATION-REBUILD item 2
(Module 4): MuZero.jl's learned-dynamics search, rebuilt as
original Julia in `planning-search/`.

- **Inspiration source.** MuZero.jl, deveshjawla/MuZero.jl, MIT
  (verified from LICENSE, copyright (c) 2021 Devesh Jawla),
  2,163 lines as counted in the sweep (`wc -l` over all `*.jl`
  files in the depth-1 clone: `src/` 1,034, `games/` 825,
  `test/` 114, examples ~190; last commit 2026-01-24).
  See `source-audit/ALL_CANDIDATES_BORROWING_PLAN.md` (Module 4)
  and `source-audit/sweep/group-b.json`. **NO code was copied:**
  MuZero.jl was not read line-by-line to transcribe it, and the
  file contains no Flux/Zygote/BSON/JLD2 code — a dedicated
  testset asserts no MuZero.jl / Flux identifier appears in any
  code line (comments and docstrings excluded). Why a rebuild,
  not a copy or a dependency: MuZero.jl is game-shaped
  (TicTacToe / Connect4 board-state tensors, win/loss rewards),
  Flux/Zygote-bound, thinly tested (a single 114-line test
  file), single-author, with a commented-out entry point, and
  its BSON/JLD2 binary checkpointing would violate START's JSON
  wire format.
- **What was rebuilt.** (1) A dynamics model:
  `DynamicsModel`, a multi-output ridge regression (stdlib
  LinearAlgebra only, no Flux/CUDA, no new dependencies) from
  11 state-action features (the 8 spec-normalised plan features
  + crop one-hot + area share) to 8 next-state features plus
  reward, trained on transitions generated by the existing
  synthetic 1-site 2-crop domain (`generate_transitions` —
  every reachable transition under varied specs; 258
  transitions from seeds 1..8, 135 held out from seeds
  101..104). (2) MinMaxStats-style value normalisation
  (`MinMaxStats`, `update_minmax!`, `normalize_value`) —
  original implementation of the idea: running min/max, values
  normalised into [0, 1], a constant stream normalises to the
  neutral 0.5 with no NaN or division by zero. (3) A reanalyse
  step (`reanalyse`): stored verified samples are revisited and
  their search targets recomputed with the current dynamics
  model; the memory is never mutated and the `verified` flag on
  every target is copied unchanged from the stored sample.
  (4) A `DynamicsOracle` usable as the MCTS oracle in place of
  the rollout oracle (like the existing `LearnedOracle`), plus
  `run_search_with_dynamics` and `evaluate_dynamics_heldout`.
- **Reward semantics.** Reward is verified-PASS plan quality
  under the JuMP+HiGHS gate: 0 for an intermediate allocation
  step, delivered / total demand at the terminal step — NEVER a
  win probability. The learned search is a candidate generator
  only: every candidate still goes through the separate verify
  step, and a plan still needs a PASS verdict plus human
  approval (`needs_human_decision` is always true). A search
  result is a candidate, never a verified plan.
- **Replacement rule (unchanged).** The dynamics oracle
  replaces the current oracle only if `replacement_decision`
  holds on held-out specs: held-out verified-PASS rate at
  least as high as the rollout oracle's AND mean shortage no
  worse.
- **Measured results (2026-11-11, Julia 1.13.3, canonical
  env).** Held-out prediction error (seeds 101..104, 135
  transitions): mean absolute error **0.0719**, max **0.4122**
  (train error 0.0717 / 0.4503); test thresholds (mean < 0.10,
  max < 0.50) were set from these measurements, not guessed.
  The predicted reward for the optimum step is 0.604 vs the
  true 0.923 (error 0.319 — the reward is the hardest output to
  fit: 0 for intermediate steps, the full delivered share at
  the terminal step). MCTS with the dynamics oracle finds the
  known optimum (delivered 600 t / shortage 50 t) on **all
  five seeds (1234, 7, 42, 99, 2024)** at nsims=500 and
  nsims=1000, visit-count and mean-Q selection. Held-out
  (seeds 101..104, nsims=200, constraint verify): rollout PASS
  rate 1.0, dynamics PASS rate 1.0, rollout mean shortage
  147.5 t, dynamics mean shortage 117.5 t — replaced under the
  rule. Reanalyse: a neutral (unfitted) model targets every
  sample at 0.5; the fitted model changes at least one target,
  all targets stay in [0, 1], and every target's `verified`
  flag matches its stored sample.
- **Limitations / known gaps (measured, not hidden).** The
  dynamics model is linear in its features, so — like the
  linear value model — it cannot express interactions the
  features do not carry (e.g. water committed to wheat while
  potato still needs water). Its root prior puts its largest
  mass on wheat 60 ha (0.38 vs 0.22 for 50 ha); MCTS corrects
  this through simulation values, and the search test shows it
  still finds the optimum on all five seeds — but the prior
  ranking is deliberately NOT asserted in the tests. The model
  covers a single synthetic domain only (1-site 2-crop); there
  is no neural network, no Flux/CUDA, and no learned
  representation network — the "representation" is the
  hand-defined plan-features vector. The dynamics value of a
  state is a predicted final delivered share from a two-step
  lookahead, not a learned value network.
- **Governance.** No new dependencies, no downloads of real
  data, synthetic test data only. Wire format stays JSON.
  `runtests.jl`'s no-AlphaZero-import check now also covers
  `training_loop.jl` and `dynamics_search.jl` (21 checks, was
  15), so `runtests.jl` is 81/81 (was 75/75). Python and Rust
  suites were NOT re-run for this item — nothing they touch
  changed.

## Borrowed helpers (added 2026-11-11)

The three small stdlib-only helpers from borrowing-audit batch 2,
copied on Eric's direction into `helpers/borrowed_helpers.py` (the
ONLY vendored candidate code in this assembly — `adapters/` stays
"thin adapters, no vendored engine code"), each with its Apache-2.0
notice kept and provenance in `helpers/PROVENANCE.md`:

- Cognee `chunk_by_word.py` (87 lines, whole file) + `chunk_id.py`
  (22 lines, whole file), clone commit
  8853378eae5366addb064e758e560a456146ae1a (pyproject 1.6.7).
- Crawl4AI `normalize_url` (`crawl4ai/utils.py` lines 2259–2358,
  ~100 lines, that function only — not the 3,786-line file), clone
  commit cae74b203a33994f7e13b9052c3b0d5c93daa0e6 (version 0.9.5).
- Copied verbatim (checked by diff after writing); only extraction
  changed (imports hoisted to the module top). Stdlib-only verified
  two ways: `ast` import check (`re`, `collections`, `hashlib`,
  `urllib`, `uuid` — all in `sys.stdlib_module_names`) and importing
  the module under the system Python with no venv and no third-party
  packages on the path (no non-stdlib module pulled in). No
  dependency was added.
- Tests `tests/test_borrowed_helpers.py`: **24/24 PASS** — chunking
  join/labels/empty/long-input, chunk-id determinism/occurrence/
  position-independence/idempotence, normalize_url (16 upstream
  Crawl4AI cases verbatim, tracking-param stripping, host
  lowercasing, fragment handling, extra drop params, HTTPS
  preservation, invalid-base behaviour).
- **Finding (measured, not hidden): Crawl4AI's own test file does not
  match the function in the cloned version.** Of its 20 cases, 16 pass
  as written and 4 do not: empty href returns `None` (the test file
  expects the base URL back), fragments are dropped by default (the
  test file expects them kept), and the two invalid-base cases expect
  `ValueError("Invalid base URL format")` while the function never
  validates the base (`ftp://` base returns
  `ftp://example.com/page.html`; empty-netloc base returns
  `http:///path/page.html`). The tests assert the copied function's
  actual behaviour, and the mismatch is recorded in
  `helpers/PROVENANCE.md` rather than silently "fixing" the copied
  function to match the test file. `chunk_by_word`'s
  `is_real_paragraph_end` likewise returns True for any sentence
  ending regardless of position — copied verbatim, tested, not fixed.
- These are untrusted-input utilities only (text chunking, URL
  canonicalisation). They are NOT wired into any verify, governance,
  or decision path and cannot mark a plan verified, authorise
  anything, or change a verdict.

## ODYM (Module 17) (added 2026-11-11)

ODYM (Open Dynamic Material Systems Model, IndEcol/ODYM, MIT) as a
dependency only — **no ODYM code was copied into this assembly**.
Installed from git, pinned to the sweep's audited commit
9792c23b1faced9515b425033694328aa8301c0f (2025-09-26), version
0.1.0, because ODYM was never published to PyPI (item 9). The pin is
recorded in `requirements.txt` as a direct reference
(`odym @ git+https://github.com/IndEcol/ODYM@9792c23b...`) and was
verified to round-trip through pip (`pip install --dry-run -r
requirements.txt` resolves it). The commit was verified reachable
with `git ls-remote` before installing; HEAD is not tracked.

- Thin original adapter `adapters/resource_accounting.py`: builds a
  small synthetic MFAsystem for the material stock-flow embodied in
  the spine's 1-site 2-crop food system (fertiliser Environment ->
  Field, harvest Field -> Storage, dispatch Storage ->
  Environment, 3 years 2026–2028, unit t, one element "All"), with
  field and storage net stock changes as part of the balance.
  Synthetic numbers only, not a real region.
- Balance check uses ODYM's own `MassBalance()` (inflows - outflows
  - net stock change, per year/process/element) under the spine's
  status rules: synthetic case PASS with residual exactly 0.0 t
  (tolerance 1e-9 t); a deliberately unbalanced case (dispatch flow
  removed) FAILs with residual 10.0 t; a missing system, an empty
  system, and non-finite values are UNKNOWN, never PASS.
- Cautions honoured: in-memory only — no ODYM Excel read/write
  (xlwt/xlrd) is ever called; every collection is built fresh and
  passed explicitly at construction, never MFAsystem's mutable
  defaults (ProcessList=[], FlowDict={}) — a test proves two
  independently built systems share no mutable state and do not
  alias the constructor defaults.
- Governance: ODYM computes accounts; its outputs are model results,
  NOT verified plans. `accounts_to_dict()` returns plain JSON-able
  data with verified=false and needs_human_decision=true, and the
  accounts must still go through START's separate verify step.
- Tests `tests/test_resource_accounting.py`: **16/16 PASS** —
  dependency/version/pin, system build, balance PASS, ODYM
  MassBalance zero everywhere, stock changes matching flow
  differences, unbalanced FAIL (dispatch removed, 1 t stock error),
  tolerance boundary, missing/empty/non-finite UNKNOWN,
  governance flags, JSON-ability, explicit-arguments isolation.
- Rust and Julia suites were not re-run for this change: nothing
  they touch was modified. Python suite after this work: 75/75.

## Pymrio (Module 17) (added 2026-11-11)

pymrio (IndEcol/pymrio, LGPL-3.0) as a dependency only — **no
pymrio code was copied into this assembly, and the library is
unmodified and replaceable**. Installed from PyPI as pymrio==0.7.0
(verified on PyPI first — HTTP 200, version 0.7.0 — after the ODYM
surprise; the sweep's install claim is never trusted without
checking). Sweep clone HEAD c22b419 (2026-10-22), 11,254 lines,
227 stars.

- Licence: the LICENSE file contains the full GNU Lesser General
  Public License v3 text, Copyright (c) 2014 Konstantin Stadler,
  and the PyPI classifier agrees ("GNU Lesser General Public
  License v3 (LGPLv3)") — verified in the installed wheel's
  dist-info. **Inconsistency recorded, LICENSE authoritative:**
  the README.rst badge says "License-GPL v3" and links to
  gpl-3.0. The LICENSE file is authoritative; the badge is wrong.
- Thin original adapter `adapters/footprint_accounting.py`: builds
  a small synthetic IOSystem entirely in memory — 2 regions
  (R1, R2) x 2 sectors (Agriculture, Manufacturing), one stressor
  (CO2, t), one Households final-demand column per region — and
  runs pymrio's calc_all(). Total output x = [53, 57, 59, 67] t.
  Synthetic numbers only, not a real region or a real database.
- No downloads, ever: the adapter never calls any pymrio
  download, load, or parse function (no load_exiobase, load_wiod,
  load_eora26, download_*, parse_*, load_all, load_test,
  get_repo_content). Any real EXIOBASE / WIOD / EORA database
  would go through START's data-fetch approval and provenance
  path, never as an unreviewed side effect. Enforced by tests:
  an AST check that no such call name appears in the adapter,
  and a build + check that still passes with the network socket
  blocked and every pymrio download function monkeypatched to
  raise.
- Footprint-consistency check under the spine's status rules:
  per-region identity D_pba[r] = D_cba[r] + D_exp[r] - D_imp[r]
  and global total D_pba = total D_cba (trade cancels). Synthetic
  case PASS with residual 2.2e-16 t (tolerance 1e-9 t):
  D_pba = [3.0, 0.7] t, D_cba = [2.44025416, 1.25974584] t,
  totals 3.7 t each. A deliberately tampered account (D_cba cell
  +1.0 t after calculation) FAILs; missing, empty, or non-finite
  inputs are UNKNOWN, never PASS.
- Governance: pymrio computes accounts; its outputs are model
  results, NOT verified plans. `accounts_to_dict()` returns plain
  JSON-able data with verified=false and
  needs_human_decision=true, and the accounts must still go
  through START's separate verify step.
- Tests `tests/test_footprint_accounting.py`: **15/15 PASS** —
  dependency/version/pin, LGPL classifier in installed metadata,
  system build, identity PASS, production = consumption total,
  per-region accounts, tampered FAIL, missing/empty/non-finite
  UNKNOWN, tolerance boundary, governance flags, JSON-ability,
  AST no-download check, network-blocked build.
- Rust and Julia suites were not re-run for this change: nothing
  they touch was modified. Python suite after this work: 90/90.

## Test results (verified by running them here)

- Python: `.venv/bin/python -m unittest discover -s tests -v`
  → **Ran 90 tests, OK** (6.8 s). Breakdown: statuses 10, SciPy
  optimisation 5, CVXPY 1, CPMpy 1, Arrow 1, gRPC 2, governance 7,
  orchestration 5, evaluation 3, borrowed helpers 24 (chunk_by_word 8,
  chunk_id 7, normalize_url 9 — including 16 upstream Crawl4AI cases
  as subTests), resource accounting 16, footprint accounting 15.
  Before the helpers were added the suite was 35 tests; before ODYM
  it was 59 tests; before Pymrio it was 75 tests.
- Rust: `cargo test` in `rust/` → **9 passed, 0 failed**
  (4 Cedar, 2 egg, 3 Tonic-stub). Binary `target/debug/start-spine`
  also prints PASS on all 5 checks, exit 0. (After the Module 21
  work below: **14 passed, 0 failed** — the 9 above plus 4 Tonic
  wire tests and 1 server unit test; binary
  `target/debug/start-tonic-server` added.)
- Runner: `.venv/bin/python examples/run_spine.py`
  → ALL ASSEMBLED ADAPTERS PASS (HiGHS/CVXPY/CPMpy all 600/50 t,
  Arrow round-trip, gRPC PASS, governance deny, orchestration PASS
  with needs_human_decision=True, exact-match 3/4).
- Julia (all on Julia 1.13.3, working env `julia-current/`, unless noted):
  - Combined `spine.jl`: **16/16 checks PASS, 72 s, exit 0**
    (`julia-current/logs/spine-combined-current-run.log`).
    Section 1 evaluate_constraint 6/6 (food 2800>=2500 PASS, le-fail
    FAIL, eq-pass PASS, empty-id UNKNOWN, non-finite UNKNOWN,
    unsupported-op UNKNOWN). Section 2 overall_status 4/4 (empty →
    NOT_CHECKED, FAIL wins, unknown → indeterminate, all-pass PASS).
    Section 3 JuMP+HiGHS LP 5/5: delivered 600.0 t, shortage 50.0 t,
    production 600.0 t, land 70.0 ha, water 100,000.0 m³ — matches
    the Python/CPMpy/CVXPY cross-solver totals exactly. Section 4
    MTK/DiffEq ODE 1/1: food-stock steady state 99.9952 t vs
    equilibrium 100 t. Every result carries needs_human_decision=true.
  - Split stages (same checks, run separately on the low-memory VM):
    `spine_lp.jl` 15/15 PASS (~10 s) on both the pinned env
    (`julia/logs/spine-lp-run.log`) and `julia-current`
    (`julia-current/logs/spine-lp-current-run.log`);
    `spine_ode.jl` PASS on `julia-current`
    (`julia-current/logs/spine-ode-current-run.log`).
  - Smokes on `julia-current` (each exit 0): Agents 7.1.0 — 10 agents
    on a 10×10 grid, total wealth 50.0; DifferentialEquations 8.1.1 —
    exponential decay S(10)=36.78795 vs expected 36.78794;
    Symbolics 7.48.0 — expand((x+1)²)=1+2x+x², d/dx=2+2x;
    Turing 0.49.0 — coin-flip posterior mean 0.6387 in [0.5, 0.8].
    Same smokes on the pinned env (Julia 1.13.3): Symbolics 6.58.0
    PASS, Turing 0.34.1 PASS (mean 0.6265), Agents 6.2.10 FAIL
    (precompile), DifferentialEquations 7.17.0 FAIL (precompile).
  - AlphaZero 0.5.6 smoke: **9/9 checks PASS, 17 s, exit 0**
    (`alphazero/logs/smoke-alphazero.log`). Loads AlphaZero + the
    bundled ConnectFour game, inits the env (7 actions, all available,
    white to play, not terminated), plays one move (turn flips to
    black, disc placed at column 4 row 1). CPU only, no training.
  - Planning-search module: `julia-current/planning-search/test/runtests.jl`
    → **81/81 tests PASS, exit 0** (Julia 1.13.3, canonical env,
    `JULIA_NUM_THREADS=1`, `JULIA_NUM_PRECOMPILE_TASKS=1`,
    `--heap-size-hint=3G`; loads Distributions only, no JuMP/MTK/
    AlphaZero). Breakdown: MIT notice 6, no-AlphaZero-import 21
    (was 15: the check now also covers `training_loop.jl` and
    `dynamics_search.jl`), interface contract 14, reward semantics 6,
    MCTS optimum 15, policy-before-explore 1, UNKNOWN/never-PASS 8,
    candidate-only 10.
    Default search (nsims=1000, visit-count policy, seed 1234)
    finds wheat 50 ha / potato 20 ha — delivered 600.0 t, shortage
    50.0 t, production 600.0 t, land 70.0 ha, water 100,000.0 m³ —
    the known optimum, on all five seeds tested (1234, 7, 42, 99,
    2024); the mean-Q selection finds it at nsims=500 on all five
    seeds. The verify step passes the good candidate (PASS) and
    fails an over-water candidate (60 ha wheat / 20 ha potato,
    112,000 m³ → FAIL). LP regression re-run after this work:
    `spine_lp.jl` **15/15 PASS** — no regression.
  - LP cross-check tests: `julia-current/planning-search/test/verify_lp.jl`
    → **53/53 tests PASS, exit 0** (Julia 1.13.3, canonical env,
    loads JuMP+HiGHS in addition to PlanningSearch). Breakdown:
    LP optimum from spec 8, good candidate passes both 10,
    suboptimal-but-feasible passes both 5, over-water fails both 7,
    better-than-optimum fails LP check 9, infeasible spec UNKNOWN 7,
    non-finite UNKNOWN 3, candidate-alone not verified 4. The LP
    optimum from the spec alone is delivered 600.0 t, shortage
    50.0 t, production 600.0 t, land 70.0 ha, water 100,000.0 m³.
    Runner `planning-search/run_verify_lp.jl` → VERIFY_LP RESULT:
    PASS (MCTS candidate 600/50, constraint PASS, LP PASS,
    combined PASS; verified false without approval, true with it).
  - Training-loop tests (standalone, Distributions only):
    `julia-current/planning-search/test/training_loop.jl`
    → **86/86 tests PASS, exit 0**. Breakdown: varied specs 9,
    verified memory 8, features 5, value model 7, learned
    oracle 6, search with oracle 13, loop keeps verified
    samples 18, rejected never enter memory 3, trained oracle
    still candidate-only 6, no game-loop code 11.
  - Training-loop tests (LP-split, JuMP+HiGHS):
    `julia-current/planning-search/test/training_loop_lp.jl`
    → **25/25 tests PASS, exit 0**. Breakdown: full loop with
    LP cross-check 15, learned oracle does not degrade the
    held-out PASS rate 2, learned-oracle candidate still needs
    verify + approval 8. Final-iteration held-out numbers in
    that run: rollout PASS 1.0, learned PASS 1.0, rollout mean
    shortage 270.0 t, learned mean shortage 170.0 t, replaced.
    Runner `planning-search/run_training_loop.jl` (3 iterations)
    → TRAINING_LOOP RESULT: PASS (12 generated, 12 kept,
    0 rejected, 24 verified samples; final held-out learned
    mean shortage 117.5 t vs rollout 167.5 t).
  - Learned-dynamics search tests (standalone, Distributions +
    LinearAlgebra stdlib only):
    `julia-current/planning-search/test/dynamics_search.jl`
    → **208/208 tests PASS, exit 0**. Breakdown: transition
    generation 79, dynamics features 8, model fit + held-out
    error 10, predict_transition 8, state_from_features 5,
    MinMaxStats 11, dynamics value ranking 5, dynamics oracle
    12, MCTS with dynamics oracle 20, reanalyse 30, dynamics
    held-out 3, candidate-only 6, no-MuZero/Flux code 11.
    See "Learned-dynamics search (MuZero.jl rebuild)" below.
  - NetworkDynamics.jl (Module 10): `julia-current/test_network_dynamics.jl`
    → **31/31 tests PASS, exit 0** (Julia 1.13.3, canonical env,
    `JULIA_NUM_THREADS=1`, `--heap-size-hint=3G`;
    `julia-current/logs/test-networkdynamics.log`). Breakdown:
    analytic closed form vs hand-computed values 6, mass-balance
    identity 1, independent plain-ODE solve vs closed form 9,
    NetworkDynamics solve vs closed form 6, NetworkDynamics vs
    independent solve 3, steady state 3, solution structure 3.
    The model is a synthetic 3-node resource network (source →
    storage → sink, static linear edge flows, DAE node balances;
    full numbers in "NetworkDynamics.jl (Module 10)" below).
    NetworkDynamics result at t=10: S = (19.865241, 19.191446,
    17.506960) vs closed form (19.865241060018292,
    19.191446360109744, 17.506959610338377) — agreement within the
    1e-6 test tolerance; steady state (20, 20, 20) at t=100.
    The independent check (`julia-current/network_model.jl`, plain
    DifferentialEquations, no NetworkDynamics) was built and run
    FIRST, before the dependency was added, and matches the closed
    form to max error 5.8e-11 at t=10.
  - Julia checks total: 16 (combined spine) + 9 (AlphaZero) + 4
    (one PASS each for Agents, DiffEq, Symbolics, Turing smokes)
    + 81 (planning-search) + 53 (LP cross-check)
    + 86 (training loop) + 25 (training loop, LP-split)
    + 208 (learned-dynamics search)
    + 31 (NetworkDynamics networked model) =
    **513 passed, 0 failed, 0 not run**.
    The split-stage runs (15+1) are subsets of the combined 16
    and are not double-counted.
- Python re-run after the Julia work (2026-11-11): **35/35 OK**
  (11.4 s) — no regression from the Julia install.
- Python re-run after the LP cross-check work (2026-11-11):
  **35/35 OK** (10.7 s) — no regression. Rust re-run the same day:
  **9/9 passed**.
- Python and Rust re-run after the training-loop work (2026-11-11):
  **35/35 OK** (10.1 s) and **9/9 passed** — no regression.
  Combined `spine.jl` re-run the same day: **16/16 PASS**;
  `spine_lp.jl`: **15/15 PASS**.

## What was verified vs what is still unverified

Verified here:
- All three optimisation solvers reproduce the same synthetic totals
  (delivered 600 t, shortage 50 t, production 600 t, land 70 ha,
  water 100,000 m³) — cross-solver agreement, not a single-solver claim.
- The 5% loss variant via SciPy/HiGHS (583.33 / 66.67 t).
- Status rules: empty checks → NOT_CHECKED (never PASS), FAIL wins,
  UNKNOWN/INCOMPLETE → indeterminate, non-finite → UNKNOWN.
- LP cross-check of MCTS candidates: the JuMP+HiGHS LP, solved
  from the spec alone, agrees with the constraint verify on the
  good candidate (both PASS, 600/50 t) and on the over-water
  candidate (both FAIL), and catches a candidate claiming better
  than the optimum (delivered 650 / shortage 0) that the
  constraint verify alone passes. An infeasible spec gives
  UNKNOWN, never PASS.
- Governance: Cedar (real engine) and the Python stub agree —
  planner may plan synthetic, may not plan real, publish denied
  when unverified or not human-approved, allowed when both hold.
- Orchestration: verification cannot be bypassed — report raises
  without a verification result; an inconsistent plan (600+100≠650)
  is reported failed, never passed.
- Interop: Arrow round-trip lossless; gRPC round-trip PASS/FAIL/
  UNKNOWN with correct reason codes.
- DeepEval ExactMatchMetric, PatternMatchMetric and JsonCorrectnessMetric
  run with no API key (ExactMatch 0.75 on the 4-case golden set,
  matching the local exact-match implementation; PatternMatch
  [1.0, 0.0, 0.0] on `\d+ tonnes`; JsonCorrectness [1, 0, 0, 0, 0]
  against PlanJsonSchema — see "DeepEval deterministic metrics
  (Module 22)" below).
- MCTS search (copied AlphaZero.jl, rollout oracle, no neural
  network) proposes a candidate allocation at the known optimum
  (delivered 600 t / shortage 50 t) on the 1-site 2-crop synthetic
  domain, and the separate verify step passes it — while the search
  result itself stays CANDIDATE / unverified (see below).
- Planning training loop (original START code, replaces the
  AlphaZero training loop): only verify+LP PASS candidates
  become training samples; a linear value model fitted on them
  becomes a learned oracle; a new oracle replaces the current
  one only on a held-out verified-PASS rate at least as high
  with a mean shortage no worse. Measured: 3 iterations, 12
  kept, 0 rejected, final held-out learned mean shortage
  117.5 t vs rollout 167.5 t at tied PASS rates of 1.0.
  Training never marks a plan verified.
- Source audit batch 2 (2026-11-11, audit only, no code copied —
  `source-audit/CEDAR_EGG_COGNEE_GRAPHITI_CRAWL4AI_AUDIT.md`):
  Cedar — dependency only (233,228 lines, nothing small enough to
  copy); egg — dependency only for the e-graph core (10,721 lines,
  weak fit for numeric planning); Cognee — defer the system, copy
  only two stdlib chunking helpers (248,631 lines); Graphiti —
  defer the system, rewrite only the temporal-edge schema
  (40,844 lines); Crawl4AI — dependency only for the crawler,
  copy only `normalize_url` (47,234 lines).

Still unverified / not run:
- **Canonical Julia env adopted 2026-11-11 by Eric:** `julia-current/`
  (Julia 1.13.3; MTK 11.46.1 / DiffEq 8.1.1 / Agents 7.1.0 /
  Symbolics 7.48.0 / Turing 0.49.0 / JuMP 1.32.1 / HiGHS 1.26.1;
  AlphaZero 0.5.6 in `alphazero/`) is canonical — see
  `julia-current/CANONICAL.md`, and the updated README. The original
  pinned envs (`julia/`, MTK 9.59.0 / DiffEq 7.17.0 / Agents 6.2.10 /
  Symbolics 6.58.0 / Turing 0.34.1, and `julia-1.11/`) do NOT
  precompile on Julia 1.13.3 or 1.11.9 (5 direct deps fail — see
  bug 8) and are kept untouched as evidence only — see their
  `EVIDENCE_ONLY.md` files. Do not use them for new work.
- The v0.3.2 Julia gaps (ISSUE-05, ISSUE-07: no constraint contract,
  invented statuses) are NOT fixed by this assembly — the spine
  script is written to avoid repeating them and its checks pass, but
  the review-copy Julia module itself was not rewritten here.
- Tonic (Rust) server: **done, see "Real Tonic server (Module 21)"
  below** — real server over a Unix socket, Rust and Python wire
  tests passing. The Python grpcio in-process server remains as the
  Python-side gRPC round-trip.
- DeepEval LLM-as-a-judge metrics (G-Eval, hallucination, answer
  relevancy): deferred, need an LLM API key, not run, not claimed.
- Real (non-synthetic) data, real planning limits (ISSUE-01),
  and the shared test-vectors decisions (m³/L, kcal/day, range,
  versions) — unchanged, still Eric's picks. This assembly uses
  the draft vectors' already-agreeing cases only.
- Licences: DifferentialEquations.jl NOASSERTION is unresolved;
  confirm before adopting. No licence was re-verified beyond the
  2026-11-10 triage.

## Bugs found by the tests and fixed (not papered over)

1. **SciPy LP formulation bug.** The first draft merged
   `deliv = (1-loss)*prod` with `deliv+short=demand` into one row,
   letting the solver set production to 0 while delivered stayed
   free (delivered 650, production 0). Fixed to 6 separate
   equalities; all three solvers now agree.
2. **Wrong analytic totals.** The cross-solver example first
   claimed 614/57 t — those are the 5%-loss potato figures.
   Correct loss-free totals are 600/50 t (potato: 20 ha, 40,000 m³).
   The tests caught it; the file now records the correction.
3. **Cedar policy bug.** `policies.cedar` had a `forbid` for
   Publish/Execute but no `permit`, so Cedar's default-deny
   blocked even verified+approved publishes. The Rust test
   caught the disagreement with the Python stub; a permit
   (verified AND human-approved) was added.
4. **gRPC TCP loopback failure in this VM.** The grpcio client
   failed with "Failed parsing HTTP/2 ... frame type 101" while
   a raw socket showed the server speaking correct HTTP/2 —
   the VM's egress proxy intercepts TCP loopback. Switched the
   adapter to a Unix-domain socket (private file under /tmp);
   both gRPC tests now pass.
5. **Stale solver string.** Results hardcoded "scipy 1.11.4";
   now recorded dynamically from the imported SciPy (venv: 1.18.1).
6. **Julia draft was entirely commented out with wrong totals.**
   `julia/spine.jl` as assembled was 100% comments claiming the
   cross-solver totals were "delivered 614 t, shortage 57 t" — those
   are the 5%-loss potato figures, not the loss-free totals. Rewritten
   as real runnable code with the correct 600/50 t expectations; the
   combined run now verifies them (16/16 PASS).
7. **Wrong/malformed UUIDs in `julia/Project.toml`.** 4 of 7 package
   UUIDs did not match upstream (Agents, ModelingToolkit — whose last
   group was 11 chars, malformed — Symbolics, HiGHS). Verified each
   against the package's own upstream Project.toml on GitHub and
   corrected before instantiate; the first instantiate attempt had
   failed fast on the malformed ModelingToolkit UUID.
8. **Pinned Julia stack fails to precompile (version skew, not a
   Julia-version problem).** The assembly's pinned bounds (MTK 9.59.0,
   DiffEq 7.17.0, Agents 6.2.10, Symbolics 6.58.0, Turing 0.34.1)
   resolved on **both** Julia 1.13.3 and 1.11.9 to transitive versions
   they were never tested with, and 5 direct dependencies failed to
   precompile: SteadyStateDiffEq / NonlinearSolve —
   `UndefVarError: AbstractNonlinearTerminationMode not defined`
   (DiffEqBase version skew); Agents — Distributions `@check_args`
   macro API changed ("requires each check to include an offending
   value"); ModelingToolkit — TriangularSolve precompile worker
   OOM-killed plus DynamicQuantitiesSciMLBaseExt
   `SciMLBase.value does not exist`. Fixed by a new env
   (`julia-current/`) with per-package compat bounds removed, letting
   Pkg resolve the newest mutually-compatible set (MTK 11.46.1,
   DiffEq 8.1.1, Agents 7.1.0, Symbolics 7.48.0, Turing 0.49.0):
   instantiate exit 0, all 7 components pass. The pinned envs are
   kept untouched as evidence; adopting the current versions as
   canonical is Eric's pick.
9. **Julia OOM on the 6 GB VM.** Loading JuMP+HiGHS+MTK+DiffEq
   together was OOM-killed (exit 137, 4 kills) before reaching
   main(); parallel precompile workers also OOM. Workaround: split
   the spine into `spine_lp.jl` (JuMP+HiGHS) and `spine_ode.jl`
   (MTK+DiffEq), run with `JULIA_NUM_THREADS=1`,
   `JULIA_NUM_PRECOMPILE_TASKS=1`, `--heap-size-hint=3G`. Once
   packages were precompiled, the combined `spine.jl` DID run on
   the same 6 GB VM (16/16 PASS, 72 s) — the OOM was a
   precompile-time memory problem, not a runtime one.
10. **`@variables` ambiguity in the combined Julia script.** `using
    JuMP` + `using ModelingToolkit` makes bare `@variables`
    ambiguous in Main (both export it; `UndefVarError` at
    spine.jl:122 on the first combined run). Fixed by qualifying the
    MTK macros (`ModelingToolkit.@variables`, `@parameters`,
    `@mtkbuild`) in `spine.jl`. The split stages never hit this
    (each loads only one of the two packages).
11. **NetworkDynamics.jl needs its parameters passed explicitly.**
    `ODEProblem(nw, u0, tspan)` without `p` leaves p as
    `NullParameters`, which the coreloop rejects for a network
    with pdim > 0 (`MethodError: no method matching
    keys(::SciMLBase.NullParameters)` on the first
    NetworkDynamics run). Fixed by passing the flat parameter
    vector from `NWParameter(nw)` (filled from the psym defaults)
    — see `network_dynamics.jl` (`network_parameters()`).
12. **`sol.retcode` is not the Symbol `:Success`.** The
    NetworkDynamics test compared `sol.retcode == :Success` and
    failed: the retcode is a `SciMLBase.ReturnCode` enum.
    Fixed by comparing against the independent solve's retcode
    instead of naming the enum or the Symbol.

## Environment quirks recorded

- System pip is PEP 668 externally-managed (OR-Tools install was
  blocked in the PCAC build); a venv is the expected route here.
- `rustc`/`cargo` are at `~/.cargo/bin`, not on PATH.
- Julia 1.13.3 is at `/home/hatch/.juliaup/bin/julia` (juliaup,
  `~/.juliaup`); Julia 1.11.9 via `julia +1.11`. Julia precompile on
  this 6 GB VM must run serially (`JULIA_NUM_PRECOMPILE_TASKS=1`,
  `JULIA_NUM_THREADS=1`) or workers get OOM-killed; serial precompile
  of the full SciML stack takes ~45 min. `~/.julia` is ~7.6 GB.
- TCP-loopback gRPC is intercepted by the egress proxy in this
  VM; Unix sockets work for local gRPC.

## Next three concrete steps

1. ~~Install Julia 1.9+...~~ **Done 2026-11-11:** Julia 1.13.3 (+1.11.9)
   installed, all 7 Julia components pass on `julia-current/`
   (spine 16/16, AlphaZero 9/9, 4 smokes). **Canonical adopted
   2026-11-11 by Eric:** the current versions in `julia-current/`
   (MTK 11 / DiffEq 8 / Agents 7 / Symbolics 7 / Turing 0.49) are
   the canonical spine env; the pinned envs are evidence only.
2. Get Eric's four test-vector decisions (m³/L, kcal/day, range,
   versions) and wire the shared test-vectors into the Python,
   Rust and Julia tests, so the three languages are checked against
   each other — the ISSUE-04 fix this spine is built to support.
   (Julia now has a toolchain, so the Julia consuming test is
   unblocked once the decisions are made.)
3. **Done 2026-11-11:** run a real Tonic server (Rust) against
   the Python grpcio client using `proto/constraint_evaluation.proto`
   over a Unix socket, upgrading tonic 0.12 → 0.14.9 — see
   "Real Tonic server (Module 21)" below. Full suite after this
   work: Python 102/102, Rust 14/14, Julia 268/268 — 384 passed,
   0 failed.
4. **Done 2026-11-11:** copy AlphaZero MCTS + game interface
   into `julia-current/planning-search/` (75/75 tests, optimum
   600/50 t found, candidate-only rule enforced, LP regression
   15/15).
5. **Done 2026-11-11:** wire the verify step to the JuMP+HiGHS LP
   (`verify_lp.jl`, 53/53 tests): combined verdict PASS only if
   both the constraint verify and the LP cross-check pass; the
   LP check catches candidates claiming better than the optimum
   (delivered 650 / shortage 0 passes the constraint verify
   alone, fails the LP check). Full suite after this work:
   Python 35/35, Rust 9/9, Julia 157/157 — 201 passed, 0 failed.
6. **Done 2026-11-11:** rewrite the training loop for planning
   (`training_loop.jl`, original START code, audit verdict
   REWRITE ORIGINAL — training.jl / learning.jl /
   simulations.jl NOT copied, no network library): verified
   samples only, linear value model as the learned oracle,
   held-out verified-PASS-rate replacement rule instead of an
   arena pit. Tests 86/86 standalone + 25/25 LP-split;
   runner 3 iterations, 12 kept, 0 rejected, final held-out
   learned mean shortage 117.5 t vs rollout 167.5 t at tied
   PASS rates of 1.0. Full suite after this work: Python
   35/35, Rust 9/9, Julia 268/268 — 312 passed, 0 failed.
   Next for that module, when directed: a neural-network
   oracle as a dependency — not started, and not needed for
   the rollout-oracle or the learned linear-oracle search
   to work.
7. **Done 2026-11-11:** copy the three small stdlib-only helpers
   from borrowing-audit batch 2 into `helpers/borrowed_helpers.py`
   (Cognee `chunk_by_word` + `chunk_id`, Crawl4AI `normalize_url`,
   Apache-2.0 notices kept, verbatim, stdlib-only verified,
   provenance in `helpers/PROVENANCE.md`): 24/24 helper tests PASS.
   Full suite after this work: Python 59/59, Rust 9/9, Julia
   268/268 — 336 passed, 0 failed. Next for the helpers, when
   directed: rewrite Graphiti's temporal-edge/episode schema as
   original code, or copy nothing further until the full
   70-candidate borrowing sweep reports.
8. **Done 2026-11-11:** full 70-candidate borrowing sweep
   (`source-audit/ALL_CANDIDATES_BORROWING_PLAN.md`): USE 19,
   ADJUST 3, INSPIRATION-REBUILD 8, DEFER 28, DROP 12. Top 5
   priority items from the sweep, one line each:
   - Add ODYM as a pip dependency for stock-flow resource accounting (M17, MIT, 3,672 lines, nothing to copy).
   - Extend DeepEval use to the deterministic PatternMatch and JsonCorrectness metrics only (M22, no API key).
   - Run a real Tonic server against the Python grpcio client over a Unix socket, upgrading tonic 0.12 → 0.14.x (M21).
   - Add Pymrio as a pip dependency only, never copy, keeping the LGPL-3.0 notice and the library unmodified (M17).
   - Add ash-flare as a dependency, default features only and local supervision only, after auditing its supervisor core (M24).
9. **Attempted 2026-11-11, BLOCKED — ODYM is not on PyPI:** the
   sweep's top USE item said "pip install ODYM", but there is no
   PyPI package named ODYM. `.venv/bin/pip install ODYM` (and
   `odym`, pip is case-insensitive) fails with "ERROR: Could not
   find a version that satisfies the requirement ODYM (from
   versions: none) / ERROR: No matching distribution found for
   ODYM", and https://pypi.org/pypi/ODYM/json returns HTTP 404.
   The repo (IndEcol/ODYM) was never published to PyPI; GitHub
   PR #9 added a setup.py to make it installable, and the
   successor library is flodym (`pip install flodym`, an
   adaptation of ODYM). No ODYM code was vendored or copied, no
   dependency was added, requirements.txt is unchanged, and no
   adapter or tests were written — the pip route is stopped, per
   the task's stop condition. **Update 2026-11-11 — Eric chose the
   git route:** ODYM 0.1.0 installed from git, pinned to the sweep's
   audited commit 9792c23b1faced9515b425033694328aa8301c0f
   (verified reachable with `git ls-remote` first; HEAD not
   tracked), pin recorded in `requirements.txt`, thin original
   adapter `adapters/resource_accounting.py` + 16/16 tests written,
   adoption noted in LICENCES.md and README.md. The PyPI-blocked
   finding above stands: there is still no PyPI package named ODYM.
   Full suite after this work: Python 75/75, Rust 9/9, Julia
   268/268 — 352 passed, 0 failed.
10. **Done 2026-11-11:** ODYM from git (item 9, above) — 0.1.0
    pinned to commit 9792c23, thin original adapter
    `adapters/resource_accounting.py`, 16/16 tests PASS, LICENCES.md
    and README.md updated. Next for Module 17, when directed:
    Pymrio as a pip dependency only (LGPL-3.0, never copy), per the
    sweep's ADJUST list; and DeepEval deterministic metrics
    (PatternMatch, JsonCorrectness — no API key).
11. **Done 2026-11-11:** Pymrio (item 10, above) — 0.7.0 from PyPI
    (verified on PyPI first), thin original adapter
    `adapters/footprint_accounting.py`, 15/15 tests PASS, LICENCES.md
    and README.md updated. Full suite after this work: Python 90/90,
    Rust 9/9, Julia 268/268 — 367 passed, 0 failed. Next in the
    sweep's order, when directed: DeepEval deterministic metrics
    (PatternMatch, JsonCorrectness — no API key), then the real
    Tonic server (tonic 0.12 → 0.14.x).
12. **Done 2026-11-11:** replacements audit for the six blueprint
    names that do not exist (`source-audit/REPLACEMENTS_AUDIT.md`,
    7 repos audited, audit only, no code copied, no dependencies
    added): USE 0, ADJUST 0, DEFER 3 (hydro-project/infinity,
    dorjeduck/llm.mojo, a2ui-project/a2ui), DROP 4
    (resitkurttr/mojo-llm, SciAgent/OpenDCAI — paper withdrawn,
    official repo has zero code files — NuMojo for the Module 15
    slot, spine-tools/SpineOpt.jl). Yield is inspiration only: the
    RAP hibernation pattern (Infinity), the MAX `linalg.matmul`
    variant (llm.mojo, claimed 7.44×), and the temporal/stochastic/
    Benders patterns (SpineOpt) — all to be rebuilt as original
    START code, none adopted now. Nearest adoption if ever unblocked:
    a2ui-core/a2ui-agent-sdk when Module 25 UI work is approved.
13. **Done 2026-11-11:** DeepEval deterministic metrics (Module 22,
    sweep top-10 item 2) — `adapters/evaluation.py` extended from
    ExactMatch to PatternMatchMetric and JsonCorrectnessMetric, 8
    new tests, all offline with no API key and no network. Full
    suite after this work: Python 98/98, Rust 9/9, Julia 268/268
    — 375 passed, 0 failed. Rust and Julia suites were NOT re-run:
    nothing they touch changed. Next in the sweep's order, when
    directed: the real Tonic server (tonic 0.12 → 0.14.x).
14. **Done 2026-11-11:** real Tonic server (Module 21, sweep
    top-10 item 3) — `rust/src/server.rs` + binary
    `start-tonic-server`, tonic 0.12.3 → 0.14.9, real protobuf
    codegen from `proto/constraint_evaluation.proto`, served over
    a Unix socket and called over the wire by both the Rust
    generated client (4 wire tests) and the Python grpcio client
    (4 wire tests, PASS + FAIL cases). Full suite after this work:
    Python 102/102, Rust 14/14, Julia 268/268 — 384 passed,
    0 failed. Julia suite was NOT re-run: nothing it touches
    changed. See "Real Tonic server (Module 21)" below. Next in
    the sweep's order, when directed: ash-flare as a dependency
    (audit the supervisor core first, default features only,
    local supervision only, distributed mode OFF).
15. **Done 2026-11-11:** ash-flare as a dependency (Module 24, sweep
    top-10 item 5) — ash-flare 3.0.0, default features only, local
    supervision only, distributed mode OFF, supervisor core audited
    first from the v3.0.0 source. Full suite after this work:
    Python 102/102, Rust 20/20 (was 14/14: +6 supervision tests),
    Julia 268/268 (NOT re-run — nothing Julia touches changed) —
    **390 passed, 0 failed**. See "ash-flare (Module 24)" below.
    Next in the sweep's order, when directed: NetworkDynamics.jl
    (Module 10) — only when the first networked domain model is
    built.
16. **Done 2026-11-11:** NetworkDynamics.jl (Module 10, sweep
    top-10 item 4) — first networked domain model built (synthetic
    3-node resource network with hand-derived closed form), then
    NetworkDynamics.jl 1.3.0 added to `julia-current/` (the sweep
    said 1.4.0; the registry latest is 1.3.0 — verified first).
    Full suite after this work: Python 102/102 (NOT re-run —
    nothing Python touches changed), Rust 20/20 (NOT re-run —
    nothing Rust touches changed), Julia 299/299 (was 268/268:
    +31 network tests) — **421 passed, 0 failed**. See
    "NetworkDynamics.jl (Module 10)" below. Next in the sweep's
    order, when directed: LM-Eval-Harness task/metric registry
    rebuilt as original Python in `mini_ai/eval` (Module 3,
    sweep item 5).
17. **Done 2026-11-11:** LM-Eval-Harness task/metric registry
    rebuilt as original Python in `mini_ai/eval` (Module 3, sweep
    item 5) — this item lives in the ai-starter working copy
    (`~/workspace/ai-starter/mini_ai/eval/`), NOT in this assembly:
    task registry with YAML-defined tasks (original YAML-subset
    parser, stdlib only, no PyYAML dependency), metric registry
    (accuracy, exact-match, perplexity), filter pipeline, and a
    runner returning JSON-able results with
    `needs_human_decision: true`, `verified: false`. 32 new tests
    in `tests/test_eval_registry.py`, all passing; ai-starter
    suite now 92 tests OK (was 60). No lm-eval code copied, no
    lm-eval dependency, no paid API. Spine totals unchanged by
    this item (Python 102/102, Rust 20/20, Julia 299/299 — 421
    passed, 0 failed); the item was pushed to repo-root paths
    (`mini_ai/eval/...`, `tests/test_eval_registry.py`,
    `README.md`) in the START repo, not under `start-assembly/`.
18. **Done 2026-11-11:** MuZero.jl learned-dynamics search
    rebuilt as original Julia in `planning-search/` (Module 4,
    sweep INSPIRATION-REBUILD item 2) — `dynamics_search.jl`:
    ridge dynamics model over state-action features, MinMaxStats
    value normalisation, reanalyse step, `DynamicsOracle` for
    MCTS; reward is verified-PASS plan quality under the
    JuMP+HiGHS gate, never a win probability. No MuZero.jl code
    copied, no Flux/CUDA, no new dependencies. 208 new tests in
    `julia-current/planning-search/test/dynamics_search.jl`,
    all passing; held-out mean prediction error 0.0719, max
    0.4122; MCTS with the dynamics oracle finds the 600/50 t
    optimum on all five seeds. Full suite after this work:
    Python 102/102 (NOT re-run — nothing Python touches
    changed), Rust 20/20 (NOT re-run — nothing Rust touches
    changed), Julia 513/513 (was 299/299: +6 runtests from the
    widened no-import check, +208 dynamics tests) — **635
    passed, 0 failed**. See "Learned-dynamics search
    (MuZero.jl rebuild)" above. Next in the sweep's order, when
    directed: Graphiti temporal-edge/episode schema as original
    Python (Module 6, sweep item 3).
19. **Done 2026-11-11:** Graphiti temporal-edge/episode schema
    rebuilt as original Python (Module 6, sweep
    INSPIRATION-REBUILD item 3) — `adapters/temporal.py`:
    episodes with valid_from / valid_to (None = still current),
    superseded_by links, episode links (previous / next /
    part_of) as plain JSON references; current at T means the
    window covers T AND the episode is not superseded; a
    superseded record is never returned as current, even inside
    its original window or with verified=true stored; the
    verified flag is carried unchanged and never set by this
    module. No Graphiti code copied, no graph DB, no LLM
    extraction, no telemetry, no new dependencies. 17 new tests
    in `tests/test_temporal.py`, all passing. Full suite after
    this work: Python 119/119 (was 102/102: +17 temporal
    tests), Rust 20/20 (NOT re-run — nothing Rust touches
    changed), Julia 513/513 (NOT re-run — nothing Julia touches
    changed) — **652 passed, 0 failed**. See "Temporal
    knowledge (Graphiti rebuild, Module 6)" below. Next in the
    sweep's order, when directed: Aider repo map as original
    Python in mini_ai/ alongside self-edit (Module 20, sweep
    item 4).

## DeepEval deterministic metrics (Module 22)

**Version and licence.** deepeval 4.3.3 (already a dependency,
`requirements.txt` unchanged — no new dependency added),
confident-ai/deepeval, Apache-2.0 (verified in the sweep from
LICENSE.md). Python 3.12.3, `.venv`, run offline with no API key
in the environment and no network use by the metrics.

**What each metric is used for.**
- ExactMatchMetric (already in use): stripped-string equality of
  an actual answer against the expected answer, on the 4-case
  synthetic golden set. Scores [1, 1, 1, 0], accuracy 0.75,
  matching the spine's own local exact-match implementation.
- PatternMatchMetric (new): checks whether a whole output matches
  a regex — used here for output-shape checks, e.g. that a
  reported quantity looks like `"<number> tonnes"`. Pattern
  `\d+ tonnes`, ignore_case off by default.
- JsonCorrectnessMetric (new): checks whether an output parses
  as JSON AND validates against an expected pydantic schema —
  used here for structured plan-result JSON against the original
  START schema `PlanJsonSchema` (`delivered: int`,
  `shortage: int`). Score is 1 or 0 only.

**What was checked (including what the sweep got wrong).**
- Verified first against the installed package, not the sweep:
  `from deepeval.metrics import PatternMatchMetric,
  JsonCorrectnessMetric` imports cleanly in 4.3.3; constructor
  signatures inspected with `inspect.signature` and the measure
  sources read before any use.
- PatternMatchMetric: the sweep was right — it exists, takes no
  model and no API key, and scores by `re.fullmatch` (1.0 full
  match, else 0.0), NOT `re.search`. A substring match therefore
  scores 0.0. An invalid regex raises `ValueError("Invalid regex
  pattern: ...")` at construction.
- JsonCorrectnessMetric: the sweep was WRONG as stated. It called
  the metric model-free, but in 4.3.3 its default construction
  calls `initialize_model(None)`, which builds a default
  OpenAIModel and raises `DeepEvalError: OpenAI API key is not
  configured` when no key is set (reproduced here with no key in
  the environment). The score itself IS deterministic — pure
  pydantic `model_validate_json` in `_validate` — but the metric
  is only key-free via `eval_mode="system_one"`, which makes
  `initialize_model` return `(None, True)` so no LLM is built
  (verified: `metric.model is None`), and the failure reason
  falls back to the pydantic validation error instead of an
  LLM-generated reason. That is the route used here, with
  `async_mode=False` (synchronous `_validate` path); both the
  async and sync paths were probed and give the same scores with
  model None. A test pins this correction:
  default construction without `system_one` raises an API-key
  error when no key is set.
- No LLM-as-judge metric is used anywhere: no G-Eval, no
  hallucination/faithfulness/answer-relevancy metric, no model
  argument passed to any metric. No code path in
  `adapters/evaluation.py` can call an LLM API (JsonCorrectness
  runs with model None).

**Exact test cases and scores** (8 new tests in
`tests/test_spine.py::TestEvaluation`, all passing; full suite
98/98).
- PatternMatch, pattern `\d+ tonnes`: `"614 tonnes"` → 1.0
  (match); `"614 tonnes extra"` → 0.0 (contains a match but is
  not a full match — fullmatch, not search); `"no tonnes here"`
  → 0.0 (no match). Accuracy 1/3 ≈ 0.333.
- PatternMatch, pattern `potato`, ignore_case=True:
  `"Potato"` → 1.0.
- PatternMatch, invalid regex `"[unclosed"`: construction
  raises ValueError; the adapter returns status "blocked" with
  the exact error, never a faked score.
- JsonCorrectness, schema PlanJsonSchema:
  `'{"delivered": 614, "shortage": 57}'` → 1 (valid JSON, valid
  schema); `'{"delivered": 614,'` → 0 (malformed JSON);
  `'{"delivered": 614}'` → 0 (valid JSON, missing `shortage`
  field); `'{"delivered": "abc", "shortage": 57}'` → 0 (valid
  JSON, uncoercible type); `'hello'` → 0 (not JSON). Scores
  [1, 0, 0, 0, 0], accuracy 0.2. Failure reasons are the
  pydantic validation errors (e.g. "1 validation error for
  PlanJsonSchema … Field required").

**Governance rule.** Metric scores are model results, never
verified plans: a score of 1.0 does not mark anything verified,
does not bypass the verify step (constraint verify + JuMP/HiGHS
LP cross-check), and every result still needs
`needs_human_decision=true` with human approval. No paid API is
used and no API key is required or stored; the LLM-as-judge
metrics stay deferred unless Eric approves a paid LLM API key,
and even then would be used only as measurements on
already-verified outputs.

**Limitations / known gaps.**
- PatternMatch is fullmatch only: it cannot assert "contains
  this pattern somewhere in a longer output" — a `.*`-wrapped
  pattern would be needed for that, and it is not used here.
- JsonCorrectness checks JSON validity + pydantic schema
  validity only. It does not check semantic correctness of the
  values (614 could be the wrong number and still score 1), and
  pydantic's default lax mode coerces: `'{"delivered": "614",
  "shortage": 57}'` scores 1 (string coerced to int), and unknown
  extra keys are ignored by default (`"extra": 1` still scores
  1). Both quirks are pinned by a test as documented behaviour;
  catching them would need a stricter schema (StrictInt,
  `extra="forbid"`), which is not used yet.
- JsonCorrectness's key-free route depends on deepeval 4.3.3's
  `eval_mode="system_one"` behaviour; if a future deepeval
  version changes it, construction will fail loudly (blocked
  status with the exact error) rather than silently calling an
  LLM — but the adapter should be re-verified on any deepeval
  upgrade.
- Scores are 0/1 only for both new metrics; there is no partial
  credit, and the threshold is forced to 1 in strict mode
  (JsonCorrectness default).

## Real Tonic server (Module 21)

**Version adopted and what was checked.** tonic **0.14.9** (the
highest 0.14.x at the time), prost **0.14.5**, tokio **1.54.1**,
tonic-prost **0.14.9**, tonic-prost-build **0.14.9**,
prost-build 0.14.5, h2 0.4.20, hyper 1.12.0, tokio-stream 0.1.19,
hyper-util 0.1.21, tower 0.5.3 — all from `rust/Cargo.lock`.
Checked before adopting: `cargo update` in a scratch crate
resolved tonic 0.14.9 as the highest 0.14.x, and a scratch
`cargo build` of tonic 0.14.9 + prost 0.14.5 + tokio 1.54.1
compiled cleanly (41.9 s); a web search corroborated 0.14.9 as
the latest 0.14.x (0.14.7 released 2026-10-27; 0.14.6, 2026-05-07;
0.14.5, 2026-02-19). No fallback was needed: 0.14.x built here
on the first attempt, so no 0.12.x fallback was taken. (Direct
`curl` to the crates.io API returned HTTP 403 through the VM
proxy, so the version was established by cargo's own registry
resolution plus the web search, not by the API.) Two 0.14
differences from the 0.12 setup were found by building, not by
assuming: (1) `tonic_build::configure()` no longer exists in
tonic-build 0.14 — codegen moved to the `tonic-prost-build`
crate (`tonic_prost_build::configure().build_server(true)
.build_client(true).compile_protos(...)`); (2) the generated
code references `tonic_prost::ProstCodec`, so `tonic-prost`
0.14.9 is a direct dependency, not just a transitive one.
`rustc`/`cargo` 1.99.1; tonic 0.14's MSRV (1.88) is met.

**What the server does.** `rust/src/server.rs` +
`rust/src/bin/tonic_server.rs` (binary `start-tonic-server`,
`start-tonic-server [SOCKET_PATH]`, default
`/tmp/start-spine-tonic-<pid>.sock`). The service is code-
generated by tonic-prost-build from START's own
`proto/constraint_evaluation.proto` (`build.rs`; no candidate
code copied, nothing vendored). For each `Evaluate` request the
server runs the same logic as the Python adapter
(`adapters/interop.py::_evaluate_local`): schema-version
("1.0.0") and constraint-id validation, non-finite and
incompatible-unit checks, then the `<=` / `>=` / `==`
comparison with tolerance — and returns a real PASS / FAIL /
UNKNOWN verdict with reason code (OK / NON_FINITE /
UNKNOWN_UNIT / INCOMPATIBLE_UNIT / INVALID_REQUEST). The pure
evaluator core is the pre-existing `tonic_stub::LocalEvaluator`
(3/3 stub tests kept as unit tests of that logic); the stub is
replaced as the server — the wire tests below hit the real
server, not the evaluator in-process. `proto/` header comment
updated: it no longer says the Tonic server is a stub.

**Build note — protoc.** tonic-prost-build needs a `protoc`
binary; none is installed on this machine and none was
installed for this work. `rust/build.rs` resolves one in this
order: `$PROTOC`, a `protoc` on `PATH`, else the `grpc_tools`
package already in the spine venv
(`../.venv/bin/python -m grpc_tools.protoc`, libprotoc 35.1)
via a wrapper script written into `OUT_DIR`. That third route
is the one used here (build prints a `cargo:warning` saying
so). No system install was attempted and no `protoc` binary
was vendored.

**Exact wire test cases and verdicts.** Two independent wire
paths, both over a Unix socket in a temp dir, both passing:
- Rust generated client → Rust server
  (`rust/tests/spine_tests.rs`, 4 tests, each starting the
  real server and calling it with the generated
  `ConstraintEvaluationClient` over the socket):
  - water feasible, 30,000 m3 `<=` 40,000 m3 → **PASS** / OK.
  - water over-limit, 50,000 m3 `<=` 40,000 m3 → **FAIL** / OK.
  - land over-allocation, 25 ha `<=` 20 ha → **FAIL** / OK;
    demand shortfall, 550 t `>=` 600 t → **FAIL** / OK;
    demand met, 600 t `>=` 600 t → **PASS** / OK.
  - incompatible units, 5 L `<=` 10 kg → **UNKNOWN** /
    INCOMPATIBLE_UNIT (never PASS).
  Plus 1 server unit test (no wire): schema version "2.0.0"
  → UNKNOWN / INVALID_REQUEST.
- Python grpcio client → Rust server
  (`tests/test_spine.py::TestTonicServer`, 4 tests; the class
  starts one `start-tonic-server` subprocess on a temp-dir
  socket and calls `adapters/interop.evaluate_remote_tonic()`,
  which generates real protobuf stubs from the .proto with
  grpcio-tools at runtime):
  - feasible plan, water 30,000 `<=` 40,000 m3 and land 18
    `<=` 20 ha → **PASS** / OK (both calls).
  - over-water plan, 50,000 `<=` 40,000 m3 → **FAIL** / OK.
  - over-land 25 `<=` 20 ha → **FAIL**; demand shortfall
    550 `>=` 600 t → **FAIL**; demand met 600 `>=` 600 t →
    **PASS**.
  - incompatible units, 5 L `<=` 10 kg → **UNKNOWN** /
    INCOMPATIBLE_UNIT (never PASS).
  Full suites after this work: Python **102/102**, Rust
  **14/14** (was 9/9: +4 wire +1 unit), Julia 268/268
  (NOT re-run — nothing Julia touches changed) — **384
  passed, 0 failed**. The `start-spine` binary still prints
  PASS on all 5 checks, exit 0.

**Unix-socket reason.** Unix domain socket only, never TCP
loopback: the VM's egress proxy intercepts TCP loopback and
breaks gRPC HTTP/2 there (verified 2026-11-10 — grpcio client
failed with "Failed parsing HTTP/2 ... frame type 101" while a
raw socket showed correct HTTP/2). A Unix socket bypasses
that. The Python in-process grpcio server in
`adapters/interop.py` is unchanged and still works the same
way; the new `evaluate_remote_tonic()` is the cross-language
path to the Rust server.

**The `:authority` interop catch (found by debugging, not
assumed).** The first Python→Rust calls failed with
`INTERNAL: Stream removed (RST_STREAM (Received RST_STREAM
with error code 1))` while the Rust client worked and the
server stayed alive with no panic. A Unix-socket tap proxy
that dumped the HTTP/2 frames showed the server answering the
complete, well-formed request with RST_STREAM PROTOCOL_ERROR
(err 1) before the handler ran. Cause: grpcio's default
`:authority` for a Unix-socket target is the percent-encoded
socket path (e.g. `tmp%2Fstart-spine-tonic-123.sock`), and the
Tonic/h2 server rejects that authority. Fix, verified:
`grpc.default_authority` set to a plain hostname
(`"localhost"` in `evaluate_remote_tonic()`). Pinned by
experiment: `localhost` → PASS, `tonic-server` → PASS,
`tmp%2Ftonic-smoke.sock` → same RST_STREAM error,
`tmp/tonic-smoke.sock` (raw path) → same error. The Rust
client is unaffected (it sends no such authority).

**Governance rule.** The server evaluates; it does not verify
a plan. A PASS from this server is one constraint check, not
a verified plan: verified still means PASS *and* the separate
verify step (constraint verify + JuMP/HiGHS LP cross-check)
*and* human approval (`needs_human_decision=true`). The
server never marks anything verified, never bypasses the
verify step, and its verdict cannot approve anything on its
own.

**Limitations / known gaps.**
- No TLS and no authentication on the Unix socket — local
  only. Anyone who can reach the socket file can call
  Evaluate, so the socket must live in a private directory
  (the binary defaults to `/tmp` with a per-run name; tests
  use a fresh temp dir). Do not expose the socket or put it
  on a shared path.
- Single unary RPC only (`Evaluate`); no streaming, no
  health check, no reflection, no graceful shutdown — the
  server runs until stopped (tests terminate the process).
- The server does not convert units (value_unit must equal
  bound_unit, same as the Python adapter); it does not
  validate the plan as a whole — one constraint per call.
- The Python test builds the Rust binary on demand if
  `rust/target/debug/start-tonic-server` is missing (one
  `cargo build --bin start-tonic-server`); if that build
  fails the tests skip with the exact build error, they do
  not fake a pass.
- Build environment quirk, recorded for the next worker:
  `/tmp` is a 512M tmpfs and was 100% full during this work
  (other workers' audit dirs plus a probe target dir); `cc`
  then fails with "No space left on device". Builds here
  need `TMPDIR` pointed at roomy disk (the Python test does
  this for its on-demand build). The probe target in /tmp was
  removed after use.

## ash-flare (Module 24)

**Version and licence.** ash-flare **3.0.0**, ashforge-rs/ash-flare,
Apache-2.0 — verified from the crate's own LICENSE file ("Copyright
2026 ashforge-rs Contributors", full Apache-2.0 text) and from its
`Cargo.toml` (`license = "Apache-2.0"`); crates.io metadata carries
no licence field, so the LICENSE file is authoritative (recorded in
LICENCES.md). Existence at 3.0.0 verified before trusting the sweep:
crates.io API `max_version`/`max_stable_version` 3.0.0 with versions
`[3.0.0, 2.3.3, 2.3.2, 2.2.0, 2.0.0, 1.1.0, 1.0.4, 1.0.3, 1.0.2,
1.0.1, 1.0.0]`; `cargo search ash-flare` returns `ash-flare =
"3.0.0"`; `cargo add 'ash-flare@3' --dry-run` resolves to v3; `cargo
info ash-flare` reports version 3.0.0, licence Apache-2.0,
rust-version 1.88, features `default = []` and `python`. No ODYM
repeat: nothing was assumed from the sweep's version claim.
Dependency only — no ash-flare code copied anywhere. Rust:
rustc/cargo 1.99.1. Resolved in `rust/Cargo.lock` as ash-flare
3.0.0 (checksum
`05c8cd625d9e39a40eec9ae8a4fa3ed74911e67511714da36c017b3c49449234`),
with `async-trait` 0.1.92 added as a direct dependency (needed to
implement the `Worker` trait, which is itself `#[async_trait]`).

**What it is used for.** Local supervision of execution workers
only: start a worker, restart it if it crashes, give up loudly if
it keeps crashing. Nothing else. Original START wrapper in
`rust/src/supervision.rs` (`WorkerLedger`, `ExecutionWorker`,
`execution_supervisor_spec`, `start_supervised_execution`,
`supervisor_is_stopped`); tests in
`rust/tests/supervision_tests.rs`.

**Supervisor-core audit** (done FIRST, before adopting, as the
sweep required; source: depth-1 clone of ashforge-rs/ash-flare at
tag `v3.0.0`, commit `11beb3d3018b260eaaae983688e0d90d95210e62`,
kept in `source-audit/sweep/scratch/ash-flare/` — audit clone, not
vendored code, not pushed).
- *What the supervisor does.* OTP-style supervision tree:
  `SupervisorSpec` builds a tree of workers/nested supervisors;
  `SupervisorHandle::start` spawns the runtime; children report
  termination over a command channel as `ChildExitReason`
  (Normal / Abnormal / Shutdown). Strategies: `OneForOne`
  (restart only the failed child — the default, and the only one
  START uses), `OneForAll`, `RestForOne`. A supervisor-initiated
  stop is reported as `Shutdown` and is explicitly NOT treated as
  a failure (it must not consume restart budget or trigger a
  restart round). On shutdown, workers are asked to stop
  cooperatively via a `ShutdownSignal` and get their `shutdown`
  hook run; a worker that ignores the signal is aborted after
  the shutdown timeout (default 5 s) and does NOT get the hook.
- *Restart policy.* Per child: `Permanent` (restart on ANY
  termination, including a clean normal exit), `Temporary`
  (never restart — the child is dropped from supervision),
  `Transient` (restart only on abnormal exit). The decision
  lives in one shared function, `decide_restart`
  (`supervisor_common.rs`), used by both the stateless and the
  stateful supervisor runtimes, so the two cannot drift apart.
  Nested supervisors have no policy of their own and are always
  treated as permanent.
- *Backoff.* Default exponential 100 ms doubling, capped at
  30 s (`RestartBackoff::default()`), tracked per child, and
  reset once a child has stayed up for at least the cap — an
  occasional failure does not inherit an old crash loop's delay.
  `RestartBackoff::none()` restores immediate restart; START
  never uses it.
- *Max restarts / permanent failure.* Restart intensity default
  3 restarts within 5 s, sliding window (`RestartTracker`).
  Exceeding it escalates: the runtime shuts down all children
  and stops the supervisor itself, returning an abnormal exit
  so a parent supervisor observes the failure (`Escalate` in
  `runtime.rs`). A permanently failing worker therefore ends in
  a STOPPED supervisor, observable because `which_children()`
  then errors (`ShuttingDown`) — never in a silent success.
- *Governance concerns and how they are handled.*
  (1) Can it restart a worker without a human decision? Yes —
  that is the point of supervision, and it is allowed ONLY for
  execution workers: restarts apply to execution liveness, never
  to a verification or planning step, and never to anything that
  could approve a result. (2) Can it mask a failure as success?
  No by construction here: every crash is counted in the
  `WorkerLedger` (failures, attempts), a crashed worker's
  `verified` field stays `false`, and budget exhaustion stops
  the supervisor visibly. (3) Can a restarted worker re-run
  something that should have stayed failed? A restart creates
  a FRESH worker instance from the factory and re-runs `run()`
  from scratch — so a worker must never be a verifier: a
  restarted worker must never re-emit, carry over, or inherit a
  verified verdict. Verification results live in the separate
  verify step and are re-derived there. START uses `Transient`
  (never `Permanent`) for execution workers, because `Permanent`
  restarts even a worker that completed successfully — a trap
  for run-once work, pinned by a test below.

**Feature set (default only, distributed OFF).** `ash-flare = "3"`
in `rust/Cargo.toml` with no features named. The crate's only
optional feature is `python` (pyo3 bindings) — OFF: `cargo tree
-i ash-flare` shows only feature `default`, and the resolved tree
contains no pyo3/pythonize. The sweep's "distributed mode OFF"
needs a correction, recorded honestly: there is NO `distributed`
feature flag in 3.0.0 — `pub mod distributed` is always compiled
(rkyv is a non-optional dependency) and its protocol has no
authentication, authorization or encryption (stated in
`src/distributed.rs`: any peer that can connect can enumerate
children, terminate a child, or shut the whole tree down).
"Distributed OFF" is therefore enforced by non-use: no START code
imports `ash_flare::distributed`, nothing listens for supervision
commands, and the wire format stays JSON. The resolved
ash-flare dependencies are async-trait, dashmap, rand, rkyv,
serde, serde_json, thiserror, time, tokio, tracing.

**Exact test cases and results** (6 new tests in
`rust/tests/supervision_tests.rs`, all passing; Rust suite 14/14
→ 20/20; test backoff is 10 ms doubling to a 1 s cap so the tests
stay fast while still exercising exponential growth — production
use must pick its own backoff, not inherit the test value).
- `transient_worker_restarts_then_completes_but_stays_unverified`:
  worker fails twice then succeeds (Transient, budget 5 in 60 s).
  Observed: attempts 3, failures 2, completed true,
  verified false; after completion attempts stay at 3 (no
  restart on normal exit) and the child leaves supervision
  (Drop removes it — the first version of this test wrongly
  asserted the child stays listed, and the failure taught the
  correct behaviour: Transient + Normal ⇒ Drop).
- `always_failing_worker_hits_intensity_limit_and_supervisor_stops`:
  worker always fails (budget 3 in 60 s). Observed: attempts 4
  (1 initial + 3 restarts), failures 4, completed false,
  verified false; then `which_children()` errors — the
  supervisor stopped on escalation. Permanent failure is
  visible, never silent success.
- `temporary_worker_is_never_restarted`: Temporary policy,
  always-failing worker. Observed: attempts 1, failures 1,
  children list empty after the Drop.
- `documented_backoff_and_intensity_defaults_match`: pins the
  library defaults so a future upgrade that changes them fails
  loudly — backoff delays 100/200/400 ms then capped at 30 s;
  `RestartBackoff::none()` is zero; default intensity is 3
  restarts in 5 s.
- `permanent_policy_restarts_even_on_normal_completion`:
  Permanent policy, worker that returns `Ok` immediately.
  Observed: attempts reach 3+ while completed is true — the
  trap is real, which is why START never uses Permanent for
  execution workers.
- `spec_builder_uses_transient_one_for_one`: the START spec
  builder is pinned — Transient policy, OneForOne strategy,
  one child listed.

**Governance rule.** Supervision is about process liveness, not
verification: a restarted worker's output is still unverified
until the separate verify step (constraint verify + JuMP/HiGHS LP
cross-check) passes AND a human approves
(`needs_human_decision=true`). A crashed worker is reported as
failed, never silently as success. Restarts apply to execution
workers only; no verification, planning, or governance step is
ever supervised into re-running, and no supervised worker can
mark anything verified — the `WorkerLedger.verified` field exists
precisely to assert it stays `false`.

**Limitations / known gaps.**
- `ChildInfo` from `which_children()` carries only id, child
  type and restart policy — no restart count, no last exit
  reason, no running/failed state. Restart history is NOT
  queryable from ash-flare; START tracks it itself in the
  `WorkerLedger`, and treats a stopped supervisor as the
  permanent-failure signal.
- A panic inside a worker's `run()` is NOT delivered to the
  supervisor as an abnormal exit: `run_worker` has no
  `catch_unwind`, so a panicking task unwinds without sending
  `WorkerTermination` (only the linked-init path detects a
  panic, via the closed init channel). The
  `ChildExitReason::Abnormal` doc says "error or panic", but
  the run path only delivers errors. START workers must
  therefore return `Err` on failure, never panic — the workers
  here do, and a panic would leave a dead child listed as
  supervised.
- Single author, very low adoption (2 stars at audit time).
  The supervisor core was audited first, as required, and the
  dependency is small and replaceable: only `supervision.rs`
  and its tests touch ash-flare.
- The `distributed` module ships in the crate (always compiled)
  with an unauthenticated, unencrypted rkyv protocol; it is
  inert only because nothing calls it. A future grep for
  `ash_flare::distributed` / `distributed::` in `rust/src`
  must stay empty; if distributed supervision is ever wanted,
  it needs its own audit and Eric's approval.
- `OneForAll` / `RestForOne` restart healthy siblings too;
  START uses `OneForOne` only.
- Build note: `/tmp` is a 512M tmpfs (see the Tonic section);
  `TMPDIR` was pointed at `~/workspace/.tmp` for the cargo
  builds here, as in item 2.

## NetworkDynamics.jl (Module 10)

**Version and licence — sweep correction.** The sweep said
"General registry 1.4.0". That is wrong: the General registry's
`Versions.toml` for NetworkDynamics ends at **1.3.0** (63 versions
total, latest 1.3.0), the upstream GitHub releases list v1.3.0
(2026-09-01) as the latest release, and the upstream `Project.toml`
at tag v1.3.0 declares `version = "1.3.0"`. No 1.4.0 exists in the
registry or as a release. **Resolved and installed: 1.3.0**
(`Pkg.add(name="NetworkDynamics", version="1.3.0")`, pinned as
`NetworkDynamics = "1.3.0"` in `julia-current/Project.toml`;
Manifest git-tree-sha1
`4223c5dc3e1c14d83afdd5e2149ebd4cdd0cd506`, UUID
`22e9dc34-2a0d-11e9-0de0-8588d035468b`, julia compat `1.10` —
compatible with the spine's Julia 1.13.3). Licence **MIT**,
verified from the repo's own LICENSE file (fetched from
`JuliaDynamics/NetworkDynamics.jl`, main branch: "MIT License,
Copyright (c) 2019-2026 Frank Hellmann, Michael Lindner, Hans
Würfel and contributors", full MIT grant, 1,124 bytes) — agrees
with the sweep's licence finding. Recorded in LICENCES.md.
Dependency only — no NetworkDynamics code copied anywhere.

**Dependency weight (the sweep's condition).** Adding
NetworkDynamics.jl pulled in **26 new Manifest packages**
(299 → 325, 0 removed, 0 existing version changes — diffed
against the pre-add Manifest pushed in commit 674f6abc): the
package itself plus Atomix, BFloat16s,
BitTwiddlingConvenienceFunctions, CEnum, CPUSummary,
CloseOpenIntervals, CpuId, Hungarian, IfElse, KernelAbstractions,
LLVM, LLVMExtra_jll, LayoutPointers, ManualMemory, Mixers, NNlib,
Polyester, PolyesterWeave, SIMDTypes, Static,
StaticArrayInterface, SteadyStateDiffEq, StrideArraysCore,
ThreadingUtilities, UnsafeAtomics. Most of the SciML stack it
needs (DiffEqBase, SciMLBase, ForwardDiff, StaticArrays,
OrdinaryDiffEq via DifferentialEquations) was already in the
env, which is why the count is 26 and not ~40. Graphs.jl 1.15.0
was added as a direct dependency in the same work for building
the network graph in `network_dynamics.jl`; it was already in
the Manifest as a transitive dependency, so it added 0 packages.
Precompile of the 26 new packages: 172 s, serial
(`JULIA_NUM_PRECOMPILE_TASKS=1`, `--heap-size-hint=3G`).

**The network model — built FIRST, before the dependency.**
`julia-current/network_model.jl` (plain DifferentialEquations.jl
only, no NetworkDynamics) defines a synthetic 3-node resource
network — synthetic numbers only, not a real region:
- Node 1 "source": produces resource at constant rate P = 10.0
  units/time. Node 2 "storage": stores, no production or
  consumption. Node 3 "sink": consumes at rate c*S3, c = 0.5/time.
- Edge 1→2: static (algebraic) flow f12 = k12*S1, k12 = 0.5/time.
  Edge 2→3: static flow f23 = k23*S2, k23 = 0.5/time.
- Node balances (differential equations), S_i = stock at node i:
  dS1/dt = P - k12*S1; dS2/dt = k12*S1 - k23*S2;
  dS3/dt = k23*S2 - c*S3. Initial stocks (0, 0, 0).
- Hand-derived closed form (verified term-by-term by
  differentiation, and by an independent Python check):
  S1(t) = 20*(1 - e^{-t/2});
  S2(t) = 20*(1 - e^{-t/2}*(1 + t/2));
  S3(t) = 20 - e^{-t/2}*(20 + 10t + 2.5t²).
  Steady state (20, 20, 20). Mass balance (exact):
  S1+S2+S3 + c*∫₀¹⁰S3 dt = 10*10 = 100, with ∫₀¹⁰S3 dt =
  86.87270593906717.

**Independent check (no NetworkDynamics).** The plain-ODE solve
in `network_model.jl` (Tsit5, reltol/abstol 1e-10) matches the
closed form at t = 2, 5, 10 with max error 5.8e-11 (t=10), and
was run and passing BEFORE NetworkDynamics.jl was added — so the
model stands on its own and the package is not load-bearing for
the result.

**The NetworkDynamics run.** `julia-current/network_dynamics.jl`
assembles the same network as NetworkDynamics components:
vertex model `f!(dv, v, esum, p, t)`: dv[1] =
prod - cons*v[1] + esum[1] (prod = 10 at the source, 0
elsewhere; cons = 0.5 at the sink, 0 elsewhere; `g = 1`, i.e.
the vertex output is its stock); edge model: static (dim 0),
`AntiSymmetric` single-sided output ydst[1] = k*vsrc[1] with
ysrc = -ydst, so the flow leaves the upstream node and enters
the downstream node — the edge flow is the algebraic constraint
coupling the node ODEs, exactly as in `network_ode!`. Graph:
`SimpleGraph(3)`, edges 1–2, 2–3. Solved with Tsit5 at the same
tolerances. Parameters are passed explicitly as the flat vector
from `NWParameter(nw)` (psym defaults): [10.0, 0.0, 0.0, 0.0,
0.0, 0.5, 0.5, 0.5] — vertex params in vertex order, then edge
params in edge order. This is required: `ODEProblem(nw, u0,
tspan)` without `p` leaves p as `NullParameters`, which the
coreloop rejects for a network with pdim > 0
(`MethodError: no method matching keys(::NullParameters)` —
hit on the first run, fixed by passing the parameter vector;
see "Bugs found" below).

**Results side by side (t = 10, stocks in resource units).**

| | S1 (source) | S2 (storage) | S3 (sink) |
|---|---|---|---|
| Closed form (hand-derived) | 19.865241060018292 | 19.191446360109744 | 17.506959610338377 |
| Independent plain-ODE solve | 19.865241 | 19.191446 | 17.506960 |
| NetworkDynamics.jl solve | 19.865241 | 19.191446 | 17.506960 |

All three agree to the 1e-6 test tolerance (independent solve
max error vs closed form 5.8e-11 at t=10; NetworkDynamics max
error vs closed form 3.3e-12 at t=2, 6.0e-11 at t=5, 5.8e-11
at t=10 — exact per-time errors printed by
`network_dynamics.jl` main(), log
`julia-current/logs/networkdynamics-main.log`).
At t=2: (12.642411, 5.284822, 1.606028) all three ways.
Steady state at t=100: (20, 20, 20) within 1e-3, all three ways.

**Tests.** `julia-current/test_network_dynamics.jl` —
**31/31 PASS, 0 failed** (Julia 1.13.3, canonical env; log
`julia-current/logs/test-networkdynamics.log`):
analytic closed form vs hand-computed values 6 (t=2 and t=10,
3 stocks each, atol 1e-12 against literals computed in Python
with `math.exp`, independent of Julia); mass-balance identity 1
(total stock + cumulative outflow = 100, atol 1e-9);
independent plain-ODE solve vs closed form 9 (t=2, 5, 10,
atol 1e-6); NetworkDynamics solve vs closed form 6 (t=5, 10,
atol 1e-6); NetworkDynamics vs independent solve 3 (t=10,
atol 1e-6); steady state 3 (t=100, atol 1e-3); solution
structure 3 (retcode matches the independent solve's retcode,
state vector length 3, flat parameter vector equals
[10.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.5]).

**Governance rule.** Network model outputs are model results,
never verified plans: needs_human_decision = true; no new paid
dependencies or services (NetworkDynamics.jl and Graphs.jl are
MIT, General registry, free); no candidate code copied; the
network output does not bypass the verify step — it is not
wired into any verify, governance, or decision path. The sweep's
condition is met: the dependency was added only because the
first networked domain model now exists and runs through it.

**Limitations / known gaps.**
- The model is deliberately tiny (3 nodes, 2 edges, linear
  flows, one stock per node) — it exercises the assembly
  (components + topology + solver + parameter plumbing), not
  any real domain. A real networked domain model (more nodes,
  nonlinear or capacity-limited flows, DAE mass-matrix
  constraints) is still to be built when a planning domain
  needs it.
- The blueprint's Module 10 claim ("dynamic world modelling
  engine") remains overstated as written: NetworkDynamics.jl is
  a general-purpose networked-dynamics assembler, not a
  domain-specific world model — it supplies no planning,
  resource, or commons domain content of its own. Confirmed by
  the sweep and by this work.
- Two API gotchas recorded for future work: (1) parameters
  must be passed explicitly via `NWParameter`/`pflat` —
  `ODEProblem(nw, u0, tspan)` fails on a parameterised network;
  (2) `sol.retcode` is a `SciMLBase.ReturnCode` enum, not the
  Symbol `:Success` — compare against another solve's retcode
  (or the enum), not `:Success`.
- The add itself was interrupted once by an exec-service restart
  mid-`Pkg.add`: `Project.toml` was already rewritten (comments
  stripped by Pkg, NetworkDynamics 1.3.0 present) and the
  Manifest updated, but the second `Pkg.add(Graphs)` and the
  precompile had not run and `/tmp` scratch was wiped. Recovery:
  re-ran `Pkg.add(Graphs)` + `Pkg.precompile()` detached
  (26 deps, 172 s, exit 0), restored the Project.toml header
  comments by hand from the pre-add text (verified against the
  pushed copy in commit 674f6abc), and diffed the Manifest
  against that pushed copy to get the exact 26-package list
  above. No evidence-only env (`julia/`, `julia-1.11/`) was
  touched; no other file changed.
- `/tmp` is a 512M tmpfs: `TMPDIR` was pointed at
  `~/workspace/.tmp` for the Julia work here, as in items 2–3.

## Temporal knowledge (Graphiti rebuild, Module 6)

**Inspiration source and licence.** Graphiti
(getzep/graphiti, Apache-2.0 — verified in the batch-2 audit
from the repo's own LICENSE file; `graphiti_core/` 40,844 lines
of Python, HEAD `ebef986a0b2360211b65751c111cacb4a7d790eb`).
The sweep's verdict for it was INSPIRATION-REBUILD: rewrite
only the temporal-edge/episode field schema as original Python.
**No Graphiti code was copied** — this module was written from
the schema design only (`EntityEdge` temporal fields
`fact`/`valid_at`/`invalid_at`/`expired_at`/`reference_time`/
`attributes`/`episodes` and `EpisodicNode.valid_at`, as
described in
`source-audit/CEDAR_EGG_COGNEE_GRAPHITI_CRAWL4AI_AUDIT.md`
§5/§7). The Graphiti system was NOT adopted: no Neo4j (or
FalkorDB/Kuzu/Neptune) graph database, no LLM extraction (in
Graphiti every temporal bound is LLM-extracted text processed
by regex heuristics, with invalidation also LLM-decided), no
PostHog telemetry (on by default in Graphiti). Nothing was
installed: no new dependency, `requirements.txt` unchanged.
The sweep entry names no file path for this rebuild; the module
was placed at `adapters/temporal.py` because the existing
adapter layout (`adapters/*.py`, thin Python adapters) is
where a Python-layer Module 6 knowledge/memory piece belongs,
and it is stdlib-only (`datetime`, `json`), like the other
self-contained adapters.

**What was rebuilt.** `adapters/temporal.py` (original code):
- `Episode`: one temporal knowledge episode — `id`, `fact`,
  `valid_from` / `valid_to` (valid_to None = still current /
  open-ended), `superseded_by` (id of the replacing episode or
  None), `links` (previous / next / part_of as plain string
  references), `verified` (carried, never set), plus
  `licence` / `provenance` / `synthetic` fields. Invalid
  windows (valid_from after valid_to) and self-supersession
  are rejected with ValueError at construction.
- `is_current(episode, at)`: the window covers T (inclusive on
  both ends) AND the episode is not superseded. Supersession
  closes the episode even when valid_to is still open.
- `TemporalStore`: in-memory dict of episodes (no database).
  `add` rejects duplicate ids; `supersede(old, new)` records
  the replacement (both must exist; the old one must not
  already be superseded); `current(at)` / `current_verified(at)`
  filter as above; `follow_chain(id)` follows superseded_by
  links to the current episode; `validate_links()` lists broken
  links; `to_dict` / `from_dict` / `store_to_json` /
  `store_from_json` round-trip plain JSON.
- `query_current(store, at, verified_only=False)`: JSON-able
  result (`schema_version` "1.0.0", `query_time`, `episodes`,
  `count`, `status` "ok", `verified` false,
  `needs_human_decision` true).
- Synthetic example store (`synthetic_store()`): a small
  food-system knowledge timeline — wheat yield revised
  4.0 → 4.2 t/ha mid-2026, potato yield revised 18 → 20 t/ha
  with the OLD record stored as verified (to prove a superseded
  verified record is still never current), water allocation
  100,000 m³ in 2026 and 120,000 m³ in 2027. Synthetic only.

**What was checked — exact test cases and results.**
17 new tests in `tests/test_temporal.py`, all passing; full
Python suite after this work **119/119, 0 failed** (was
102/102; breakdown: statuses 10, optimisation 5, CVXPY 1,
CPMpy 1, Arrow 1, gRPC 6 (2 + 4 wire), governance 7, orchestration 5,
evaluation 11, borrowed helpers 24, resource accounting 16,
footprint accounting 15, temporal 17). Rust and Julia suites
NOT re-run — nothing they touch changed.
- Supersession (4): superseded wheat episode never current
  when queried "now" (2026-11-11 — wheat-b current, wheat-a
  absent); never current when queried inside its original
  window (2026-03-01 — wheat-a absent, wheat-b not yet valid,
  so no wheat episode is current); `superseded_by` points at
  the replacing episode; a 3-episode chain (c1→c2→c3) followed
  to the current episode c3.
- Temporal filtering (5): query 2026-06-01 returns water-2026
  (not water-2027), query 2027-06-01 returns water-2027 (not
  water-2026); query before all windows (2025-06-01) and after
  all bounded windows (2028-06-01 on a bounded-only store)
  returns an empty list — not an error, not a stale record;
  empty store returns []; window boundaries inclusive
  (2026-01-01 and 2026-12-31 return water-2026, 2027-01-01
  does not); open-ended valid_to (None) is current at 2030.
- Verified (3): superseded potato-old (stored verified=true)
  is excluded from current results at 2026-06-01 while
  potato-new is returned; `current_verified` is empty at
  2026-06-01, 2026-11-11 and 2027-06-01 (the only
  stored-verified episode is superseded, the current potato
  episode is unverified); the temporal layer never sets
  verified — an unverified episode stays unverified through
  add, query, supersession and JSON round-trip, the query
  result carries verified=false with needs_human_decision=true,
  and a stored verified=true survives the round-trip unchanged
  (carried, never invented).
- Links and wire format (5): broken link (superseded_by to
  "ep-missing") returns status "unknown" with episode None and
  a reason naming the missing id, is listed by
  `validate_links()`, and never resolves to a current record
  (the broken episode is itself superseded, so current() is
  empty); unknown starting id returns "unknown"; a
  superseded_by cycle (x1→x2→x1) returns "unknown" with a
  cycle reason (no infinite loop); JSON round-trip preserves
  ids, windows, superseded_by, links and the verified flag,
  and episode dicts are plain JSON with schema_version "1.0.0",
  licence Apache-2.0 and provenance; invalid window,
  self-supersession and duplicate id all raise ValueError.
- One test failed on its first run and was fixed by correcting
  the TEST, not the module: the "outside all windows" case
  queried 2028-06-01 on the full synthetic store, but the
  wheat-b and potato-new episodes are open-ended (valid_to
  None) and are correctly current in 2028. The test now queries
  before all windows (2025-06-01) on the full store and after
  all bounded windows on a bounded-only store.

**Governance rule.** Temporal records are knowledge, never
verified plans: a current episode is not a verified fact, a
verified flag is only ever read here (never set), and a
superseded record can never be presented as verified-current —
even one stored with verified=true. Query results carry
verified=false and needs_human_decision=true and must still go
through START's separate verify step like any other model
output. The module has no function that sets verified, no
graph database, no LLM, no network, no new dependency, and it
does not touch self-edit or guardrail files. This matches the
audit's core finding about Graphiti: it has no verified flag
and no needs_human_decision anywhere in graphiti_core, so the
rebuild adds both instead of inheriting their absence.

**Limitations / known gaps.**
- Times are calendar dates only (ISO "YYYY-MM-DD"); there is
  no time-of-day, timezone, or interval-uncertainty handling —
  a bound is exact or absent. Graphiti's `reference_time` /
  future-tense normalisation idea (`temporal_edge_utils.py`)
  was not rebuilt: bounds here are stated explicitly by the
  caller, never inferred from fact text.
- `superseded_by` is a single link: an episode has at most one
  replacer, and branching histories (two competing replacers)
  are not modelled — `supersede()` rejects re-superseding an
  already-superseded episode.
- A dangling superseded_by link is allowed at add time (ingest
  order) and only reported by `follow_chain()` /
  `validate_links()`; the store does not refuse it. That is
  deliberate (episodes may arrive out of order), but callers
  must check `validate_links()` after ingest rather than assume
  all links resolve.
- The store is in-memory only: no persistence, no concurrency,
  no query language beyond "current at T" / "current verified
  at T". A real knowledge store would still need a persistence
  layer — but not a graph database by default, and not one
  chosen by this item.
- `verified` on an episode is a carried flag, not a proof: the
  temporal layer cannot tell whether a stored verified=true
  was set by the real verify step + human approval or written
  in by hand. The guarantee is only that this layer never sets
  it and never presents a superseded record as verified-current.

## Behavior-tree orchestration (BehaviorTree.rs rebuild, Module 4)

**Inspiration source and licence.** BehaviorTree.rs
(ncrothers/behaviortree-rs, MIT — verified in the sweep from the
repo's own LICENSE file, copyright (c) 2023 Nicholas Crothers,
Cargo.toml also declares `license = "MIT"`; 6,450 lines of Rust,
last commit 2024-02-05, v0.2.1, 14 stars, single author, inactive
2+ years). The sweep's verdict was INSPIRATION-REBUILD: the node
taxonomy is standard (it mirrors BehaviorTree.CPP) and small
enough to rebuild originally, but the crate itself is a stale,
unproven WIP and is NOT a dependency. **No BehaviorTree.rs code
was copied** — `rust/src/behavior_tree.rs` was written from
scratch from the node-type design only. The crate's XML tree
format and its `#[bt_node]` derive macro were not rebuilt:
trees here are defined in JSON (never XML from an untrusted
source, never pickle), and nodes are a plain Rust enum, not
macro-generated types.

**What was rebuilt.** `rust/src/behavior_tree.rs` (wired into
`rust/src/lib.rs` as `pub mod behavior_tree`), plus
`rust/tests/behavior_tree_tests.rs`:
- Node types: `Sequence`, `Fallback`, `Inverter` and `Succeeder`
  decorators, `Action`, `Condition`. Statuses `Success` /
  `Failure` / `Running`.
- Typed blackboard: one key holds one typed value (`Bool` /
  `Int` / `Float` / `Text`); reading with the wrong type is a
  `BlackboardError::WrongType` and a missing key is
  `BlackboardError::Missing` — never a silent coercion, never a
  default.
- JSON tree format (original): `{"type": "sequence" |
  "fallback", "children": [...]}`, `{"type": "inverter" |
  "succeeder", "child": {...}}`, `{"type": "action" |
  "condition", "step": "<name>"}`. Parsed with `serde_json`,
  which was ALREADY a direct dependency in `rust/Cargo.toml`
  (`serde_json = "1"`, via the ash-flare item) — no new
  dependency was added and `Cargo.toml` is unchanged.
- Action steps are stubs that record what they did on the
  blackboard: `plan` produces the synthetic candidate
  (delivered 600 t / shortage 50 t / demand 650 t, the same
  totals as the Python pipeline); `verify` re-derives the check
  through the existing `tonic_stub::LocalEvaluator` (delivered +
  shortage must equal demand within 0.01 t, checked in both
  directions, and delivered non-negative) and records
  `verify_ran` / `verify_passed`; `report` emits the report.
  `fail` / `succeed` are test steps; `defer_once` returns
  `Running` on its first tick and `Success` on the next.
  Conditions: `verify_passed`, `plan_produced` (missing or
  wrong-typed key = failed condition, never a default).

**What was checked — exact test cases and results.** 10 new
tests in `rust/tests/behavior_tree_tests.rs`, all passing; full
Rust suite after this work **30/30, 0 failed** (was 20/20:
14 spine + 6 supervision + 10 behaviour-tree). Python and
Julia suites NOT re-run — nothing they touch changed. Spine
totals now **662 passed, 0 failed** (Python 119/119, Rust
30/30, Julia 513/513).
- End-to-end (1): the JSON Sequence plan → verify → report
  runs all three steps in order (trace `["plan", "verify",
  "report"]`), report succeeds only after verify passed, and
  the blackboard records each step (`plan_produced`,
  `verify_ran`, `verify_passed`, `report_emitted`,
  `report_status = "PASS"`, `needs_human_decision = true`);
  there is no `verified` key anywhere in the module.
- Fallback (2): Fallback `[fail, succeed]` returns Success and
  runs the second child (trace `["fail", "succeed"]`); Fallback
  `[fail, fail]` returns Failure.
- Verify gate (2): a JSON tree with the verify node removed
  (Sequence plan → report) returns Failure, trace
  `["plan", "report_refused"]`, and the blackboard has NO
  `report_emitted` entry; a lone report Action also refuses.
  A plan whose numbers do not add up (delivered 500 t +
  shortage 50 t vs demand 650 t) fails verify
  (`verify_passed = false`) and the report is not emitted.
- Typed blackboard (1): all four types round-trip; reading a
  float key as bool and a bool key as float are `WrongType`
  errors; missing keys are `Missing` errors.
- Decorators (2): Inverter turns fail→Success, succeed→
  Failure, and an unset `verify_passed` condition→Success;
  Succeeder turns fail→Success and passes Success through.
  Decorators chosen: **Inverter (primary) and Succeeder** —
  both implemented and tested.
- Running (1): `defer_once` returns `Running` on its first
  tick and `Success` on the next; a Sequence containing it
  returns `Running` on the first tick without running the
  following child, and `Success` on the second tick.
- Errors (1): invalid JSON, an unknown node type
  (`"parallel"`), and an Action with no `step` are parse
  errors; an unknown step name parses but fails at run time
  (never a silent skip).
- Build note: `/tmp` is a 512M tmpfs (see the Tonic section);
  cargo was run with `TMPDIR=$HOME/workspace/.tmp` (roomy
  disk) for this item.

**Governance rule.** Trees orchestrate, never verify. The
verify Action calls the existing local evaluator and records
whether it passed; it writes no `verified` key and no tree can
produce one. The report Action is a hard gate mirroring
`adapters/orchestration.py`: it refuses (Failure, nothing
emitted, trace `report_refused`) unless `verify_ran = true`
AND `verify_passed = true` on the blackboard in the same run.
A tree that skips verification, or a JSON tree with the verify
node removed, fails explicitly at the report step — never a
silent success. Every emitted report records
`needs_human_decision = true`.

**Limitations / known gaps.**
- `Running` is genuinely exercised by `defer_once`, but there
  is no async tick loop and no background scheduler: `tick`
  is a single synchronous pass, and a caller wanting a later
  tick must call `tick` again. No node other than `defer_once`
  returns `Running`.
- The Action steps are stubs: `plan` always produces the same
  synthetic 600/50/650 t candidate and `verify` checks only
  that candidate's arithmetic via the local evaluator. There
  is no real planner, no LP cross-check, and no connection to
  the Julia planning-search or the LangGraph pipeline — this
  is the Rust-side orchestration shape only.
- The verify check uses the local evaluator's `<=` / `>=`
  operators with a 0.01 t tolerance in both directions to
  express equality; it is an arithmetic re-derivation, not a
  second solver.
- JSON trees are trusted input in this item: `parse_tree`
  validates structure and step names, but there is no schema
  version field, no size/depth limit on nesting, and no
  allow-listing of step names beyond the run-time failure for
  unknown steps. A tree from an untrusted source would need
  those before being accepted.
- No persistence: the blackboard and trace live only for the
  run; there is no checkpointing, no resume, and no
  supervision/restart of a tree (that is ash-flare's job, and
  a restarted worker must never re-emit a verified verdict —
  this module emits none).

## Monitoring event bus (Beam-Telemetry rebuild, Module 8)

**Inspiration source and licence.** Beam-Telemetry
(beam-telemetry/telemetry, Apache-2.0 — verified in the sweep
from the repo's own LICENSE file; `src/telemetry.erl` 482
lines, whole repo 1,445 lines of Erlang, per
`source-audit/sweep/group-a.json`). The sweep's verdict was
INSPIRATION-REBUILD: rebuild the execute/attach/detach event
bus as original Python, events carrying licence/provenance +
verified/unverified flags, handlers never marking a result
verified. **No Beam-Telemetry code was copied** — this module
was written from the event-bus design only (execute an event
by name, attach/detach handlers, handlers receive measurements
plus a metadata map). The Erlang library was NOT adopted:
START's v0.3.2 allocation has no BEAM runtime, so it cannot
be used as a dependency as-is; there is no BEAM/Elixir
component in the spine. Nothing was installed: no new
dependency, `requirements.txt` unchanged, no network, no real
telemetry backend. The module was placed at
`adapters/event_bus.py` because the existing adapter layout
(`adapters/*.py`, thin Python adapters) is where a
Python-layer Module 8 observation/monitoring piece belongs,
and it is stdlib-only (`copy`, `json`), like the other
self-contained adapters.

**What was rebuilt.** `adapters/event_bus.py` (original code):
- `make_event(event_name, payload, licence, provenance,
  verified=False, needs_human_decision=True, synthetic=True)`:
  builds a plain JSON-able event dict (`schema_version`
  "1.0.0", `"event"`, `"payload"`, `"licence"`,
  `"provenance"`, `"verified"`, `"needs_human_decision"`,
  `"synthetic"`); payload must be a dict and the event must
  be JSON-able (checked by `json.dumps` at construction).
- `EventBus.attach(event_name, handler)` /
  `detach(event_name, handler)` / `execute(event_name,
  event)`: handlers are plain callables taking one argument
  (the event dict). Attach is idempotent — attaching the same
  handler twice returns False and it is called once per
  dispatch. Detaching a handler that was never attached is a
  safe no-op returning False, never an error (chosen so
  teardown / re-registration code cannot fail on a handler
  that was already gone). `execute` dispatches to all handlers
  of that event name in attach order and returns a dispatch
  record (plain JSON-able dict: event name, verified flag,
  needs_human_decision, licence, provenance, the event as
  dispatched, `handlers_run`, per-handler `results`,
  `status` "ok").
- `execute` validates the event before dispatch: it must be a
  dict with the fields `event` / `payload` / `licence` /
  `provenance` / `verified` / `needs_human_decision`, must be
  JSON-able, and its `"event"` name must equal the event name
  it is executed under — a misrouted event raises ValueError
  and nothing is dispatched or logged.
- In-memory dispatch log (`log()` returns a deep copy,
  `log_to_json()` serialises it, `clear_log()` empties it):
  one entry per handler invocation with event name, handler
  name, the verified flag as dispatched, and the outcome
  (`"accepted"` / `"rejected"` / `"error"`) plus a detail
  string. Promotion attempts are never silent.
- Synthetic example bus (`synthetic_bus()`): a bus with a
  logging handler (records deep copies of the events it saw)
  and a metrics handler (counts events per name) attached to
  `plan.verified` and `plan.candidate`. Both are observers
  only.

**What was checked — exact test cases and results.** 17 new
tests in `tests/test_event_bus.py`, all passing; full Python
suite after this work **136/136, 0 failed** (was 119/119;
breakdown: statuses 10, optimisation 5, CVXPY 1, CPMpy 1,
Arrow 1, gRPC 6 (2 + 4 wire), governance 7, orchestration 5,
evaluation 11, borrowed helpers 24, resource accounting 16,
footprint accounting 15, temporal 17, event bus 17). Rust and
Julia suites NOT re-run — nothing they touch changed. Spine
totals now **679 passed, 0 failed** (Python 136/136, Rust
30/30, Julia 513/513).
- Attach/detach (5): an attached handler receives events; after
  detach it receives nothing and `attached()` is empty;
  detaching a handler that was never attached (unknown event,
  or a different handler on a known event) is a safe no-op
  returning False; attaching the same handler twice returns
  False the second time and it is called once per dispatch;
  three handlers run in attach order.
- Verified flag (2): an unverified event arrives with
  verified=false — the handler saw verified=false, the
  dispatch record and the log entry record verified=false,
  and the record carries needs_human_decision=true; a stored
  verified=true is carried unchanged through dispatch and the
  log (carried, never invented, never cleared).
- Promotion rejected (3): a handler returning a copy of the
  event with verified=true is recorded "rejected" with a
  detail naming the flag, its return is discarded, the dispatch
  record and the stored event stay verified=false, and a
  downstream handler attached after it still sees
  verified=false; a handler mutating the verified flag of the
  copy it was handed is likewise "rejected" (detail says
  "mutated"), later handlers are unaffected, and a second
  dispatch of the same event object still sees false (the
  bus's stored copy was never touched); demoting a verified
  event (returning verified=false) is rejected too — handlers
  never change the flag in either direction.
- Provenance and wire format (2): licence/provenance/payload
  on the event the handler saw, on the dispatch record, and
  on the event as dispatched are identical to the ones that
  went in, and the caller's own event object is not modified
  by dispatch; the dispatch record and the log serialise to
  plain JSON and round-trip with the flag, licence and outcome
  intact.
- Handler errors (1): a raising handler is logged with outcome
  "error" and a detail naming the exception type and message,
  the two later handlers still run, the dispatch record still
  carries the event (verified=false) with status "ok" — the
  event is not lost.
- Execute validation (3): executing an event under a different
  name raises ValueError and logs nothing; an event missing
  the licence field raises ValueError; executing with no
  handlers attached returns status "ok" with handlers_run 0
  and an empty log.
- Synthetic bus (1): the logging handler saw both dispatched
  events (unverified) and the metrics handler counted one of
  each event name.

**Governance rule.** Handlers are observers, never verifiers.
The bus enforces this by construction, in three layers: (1)
each handler receives a deep copy of the event, never the
bus's own copy, so mutating its input cannot change what the
bus stored or what later handlers see; (2) a handler's return
value is never used as event data — a returned dict whose
verified flag differs from the flag as dispatched is recorded
"rejected" and discarded; (3) a handler that mutates the
verified flag of its copy is recorded "rejected" with a
detail string, and the attempt is visible in the dispatch log
— promotion attempts are REJECTED, not silently ignored,
because a silent ignore would hide a governance violation
from audit. The choice of rejection over silent ignore is
deliberate: the log is the audit trail, and a handler that
tries to promote an event is a fact worth recording. The
stored/logged flag stays exactly as dispatched in every case,
so no downstream consumer can observe a verified=true version
of an event that was dispatched unverified. Dispatch results
carry verified=false and needs_human_decision=true and must
still go through START's separate verify step like any other
model output. The module has no function that sets verified,
no network, no telemetry backend, no new dependency, and it
does not touch self-edit or guardrail files.

**Limitations / known gaps.**
- The bus is in-memory only: no persistence, no concurrency
  (a single-threaded caller is assumed; concurrent attach /
  execute from two threads is not synchronised), no
  cross-process delivery, and no real telemetry backend —
  this is the dispatch shape only, not a monitoring system.
- The dispatch log grows without bound until `clear_log()` is
  called; there is no rotation, size cap, or persistence, so
  a long-running caller must rotate it.
- `verified` on an event is a carried flag, not a proof: the
  bus cannot tell whether a stored verified=true was set by
  the real verify step + human approval or written in by
  hand. The guarantee is only that this bus never sets it,
  never lets a handler change it, and records every attempt
  to do so.
- Mutations to fields other than `verified` in a handler's
  copy are harmless by construction (the copy is discarded)
  and do not change the outcome — only the verified flag is
  guarded and logged. A handler that silently drops or
  rewrites a payload field in its own copy has no effect on
  the bus, but is also not logged; callers that need payload
  integrity auditing should compare the handler's copy
  against the dispatch record themselves.
- Events are trusted input in this item: `execute` validates
  structure and the name match, but there is no schema
  version check on incoming events, no size limit on payloads,
  and no allow-listing of event names. An event from an
  untrusted source would need those before being accepted.
