# START core-spine — Assembly Report

Date: 2026-11-10. Location: `~/workspace/start-assembly/core-spine/`
(assembled locally; pushed to der226963-collab/START under
`start-assembly/core-spine/` on 2026-11-11, commit
674f6abc7478bbd497c8459ceec8e4a3d553ba2b; `~/workspace/ai-starter`,
the v0.3.2 review copy, and START guardrails/safety files untouched).

## Headline

- **Components: 19 total — 18 assembled, 1 stub-only, 0 blocked, 0 not run**
- **Tests: Python 102/102 passed, Rust 20/20 passed, Julia 268/268 checks passed — 390 passed, 0 failed**
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
| AlphaZero.jl | jonathan-laurent/AlphaZero.jl | 0.5.6 | assembled | smoke 9/9 checks PASS | Git clone (not General registry); own env in `alphazero/` (Flux 0.16.12, CUDA 5.11.1, Plots 1.41.7, cuDNN 1.4.7). ConnectFour init + one move, CPU only, no training. Log `alphazero/logs/smoke-alphazero.log` |
| PlanningSearch (MCTS + game interface, copied from AlphaZero.jl) | jonathan-laurent/AlphaZero.jl (source) | 0.5.6, commit 177a6eb | assembled | **75/75 + 53/53 + 86/86 + 25/25 Julia tests PASS** | Standalone in `julia-current/planning-search/` (no AlphaZero.jl import; Distributions 0.25.134 only). MCTS + game interface copied with full MIT notice, re-expressed in planning terms (states = partial plans, reward = plan quality, not win probability). Original START code: `planning_domain.jl` (1-site 2-crop synthetic), `verify.jl`, `verify_lp.jl` (JuMP+HiGHS LP cross-check, separate file so `verify.jl` stays Distributions-only), and `training_loop.jl` (original planning training loop — verified samples only, linear value model, held-out replacement rule; no network library). Search finds the known optimum — delivered 600 t / shortage 50 t — candidate only, never verified by the search; the LP cross-check catches candidates that beat the optimum. See "Planning-search module" below |
| Borrowed helpers (Cognee chunk_by_word + chunk_id, Crawl4AI normalize_url) | topoteretes/cognee, unclecode/crawl4ai | Apache-2.0 | assembled | **24/24 Python tests PASS** | `helpers/borrowed_helpers.py`, stdlib-only, Apache-2.0 notices kept, provenance in `helpers/PROVENANCE.md`. Untrusted-input utilities only — not wired into any verify, governance, or decision path. Crawl4AI's own test file does not match the cloned function in 4 of 20 cases (recorded in PROVENANCE.md); tests assert actual behaviour. See "Borrowed helpers" below |
| LangGraph | langchain-ai/langgraph | 1.2.20 | assembled | 1/1 (+ pipeline tests) | Real StateGraph plan → verify → report; report refuses without verification |
| Cedar | cedar-policy/cedar | 4.14.1 (Rust) | assembled | 4/4 Rust | Real Cedar engine evaluates policies.cedar; Python adapter is a documented stub evaluator for the same two policies |
| egg | egraphs-good/egg | 0.10.0 | assembled | 2/2 Rust | `(+ x 0) -> x`, `(* y 1) -> y` |
| Tonic / gRPC | grpc/grpc-rust | tonic 0.14.9 (real server) | assembled | **14/14 Rust tests PASS** (4 Cedar, 2 egg, 3 stub evaluator, 4 wire + 1 server unit) + **4/4 new Python wire tests PASS** | Real Rust Tonic server (`rust/src/server.rs`, binary `start-tonic-server`) serves `proto/constraint_evaluation.proto` over a Unix socket; Python grpcio client calls it over the wire (PASS + FAIL cases). See "Real Tonic server (Module 21)" below |
| Apache Arrow | apache/arrow | pyarrow 26.0.1 | assembled | 1/1 | Arrow round-trip lossless on constraint-result table |
| DeepEval | confident-ai/deepeval | 4.3.3 | assembled | **11/11 Python tests PASS** (3 ExactMatch + 8 new) | Deterministic metrics only, no API key: ExactMatch scores [1,1,1,0], accuracy 0.75; PatternMatch (fullmatch) scores [1.0, 0.0, 0.0] on pattern `\d+ tonnes`; JsonCorrectness scores [1, 0, 0, 0, 0] against original schema PlanJsonSchema. Sweep correction: JsonCorrectness is key-free ONLY via eval_mode="system_one" — default construction builds an OpenAI model and raises without a key. LLM-as-a-judge metrics deferred, not run. See "DeepEval deterministic metrics (Module 22)" below |
| ODYM | IndEcol/ODYM | 0.1.0, git pin 9792c23 | assembled | **16/16 Python tests PASS** | Stock-flow resource accounting (Module 17). Dependency only, no code copied; never published to PyPI, installed from git pinned to the sweep's audited commit (see item 9). Thin original adapter `adapters/resource_accounting.py` over a synthetic 1-site 2-crop material flow (3 years, balance PASS, residual 0.0 t). Outputs are model results only — verified=false, needs_human_decision=true. See "ODYM (Module 17)" below |
| Pymrio | IndEcol/pymrio | 0.7.0 (PyPI) | assembled | **15/15 Python tests PASS** | Footprint / consumption-based accounting (Module 17). Dependency only, never copied, library unmodified and replaceable (LGPL-3.0; README badge wrongly says GPL v3 — LICENSE file authoritative). Thin original adapter `adapters/footprint_accounting.py` over a synthetic 2-region x 2-sector in-memory MRIO (footprint identity PASS, residual 2.2e-16 t). No downloads — no pymrio download/load/parse function is ever called. Outputs are model results only — verified=false, needs_human_decision=true. See "Pymrio (Module 17)" below |
| ash-flare | ashforge-rs/ash-flare | 3.0.0 (crates.io) | assembled | **6/6 new Rust tests PASS** (Rust suite now 20/20) | Local supervision of execution workers only (Module 24). Dependency only, no code copied, default features only (`python` OFF), distributed mode OFF by non-use. Supervisor core audited first. See "ash-flare (Module 24)" below |

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
    → **75/75 tests PASS, exit 0** (Julia 1.13.3, canonical env,
    `JULIA_NUM_THREADS=1`, `JULIA_NUM_PRECOMPILE_TASKS=1`,
    `--heap-size-hint=3G`; loads Distributions only, no JuMP/MTK/
    AlphaZero). Breakdown: MIT notice 6, no-AlphaZero-import 15,
    interface contract 14, reward semantics 6, MCTS optimum 15,
    policy-before-explore 1, UNKNOWN/never-PASS 8, candidate-only 10.
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
  - Julia checks total: 16 (combined spine) + 9 (AlphaZero) + 4
    (one PASS each for Agents, DiffEq, Symbolics, Turing smokes)
    + 75 (planning-search) + 53 (LP cross-check)
    + 86 (training loop) + 25 (training loop, LP-split) =
    **268 passed, 0 failed, 0 not run**.
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
