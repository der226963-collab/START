# START core-spine — Assembly Report

Date: 2026-11-10. Location: `~/workspace/start-assembly/core-spine/`
(assembled locally; pushed to der226963-collab/START under
`start-assembly/core-spine/` on 2026-11-11, commit
674f6abc7478bbd497c8459ceec8e4a3d553ba2b; `~/workspace/ai-starter`,
the v0.3.2 review copy, and START guardrails/safety files untouched).

## Headline

- **Components: 17 total — 16 assembled, 1 stub-only, 0 blocked, 0 not run**
- **Tests: Python 35/35 passed, Rust 9/9 passed, Julia 268/268 checks passed — 312 passed, 0 failed**
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
| Tonic / gRPC | grpc/grpc-rust | tonic 0.12.3 (compiled, stub only) | stub_only | 3/3 Rust (stub evaluator) | No Tonic server run. Runnable gRPC here is Python grpcio 1.85.1 over a Unix socket (see below); 2/2 Python gRPC tests pass |
| Apache Arrow | apache/arrow | pyarrow 26.0.1 | assembled | 1/1 | Arrow round-trip lossless on constraint-result table |
| DeepEval | confident-ai/deepeval | 4.3.3 | assembled | 1/1 (+ local metric tests) | ExactMatchMetric only, no API key: scores [1,1,1,0], accuracy 0.75. LLM-as-a-judge metrics deferred, not run |

## Exact versions installed (venv `.venv`, Python 3.12.3)

numpy 2.5.4, scipy 1.18.1, pyarrow 26.0.1, grpcio 1.85.1,
grpcio-tools 1.85.1, langgraph 1.2.20, cpmpy 1.1.1, cvxpy 1.9.3,
highspy 1.15.1, deepeval 4.3.3. Full list in `requirements.txt`.
Rust: rustc/cargo 1.99.1 (`~/.cargo/bin`, not on PATH);
cedar-policy 4.14.1, egg 0.10.0, tonic 0.12.3 (see `rust/Cargo.lock`).
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

## Test results (verified by running them here)

- Python: `.venv/bin/python -m unittest discover -s tests -v`
  → **Ran 59 tests, OK** (11.6 s). Breakdown: statuses 10, SciPy
  optimisation 5, CVXPY 1, CPMpy 1, Arrow 1, gRPC 2, governance 7,
  orchestration 5, evaluation 3, borrowed helpers 24 (chunk_by_word 8,
  chunk_id 7, normalize_url 9 — including 16 upstream Crawl4AI cases
  as subTests). Before the helpers were added the suite was 35 tests.
- Rust: `cargo test` in `rust/` → **9 passed, 0 failed**
  (4 Cedar, 2 egg, 3 Tonic-stub). Binary `target/debug/start-spine`
  also prints PASS on all 5 checks, exit 0.
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
- DeepEval ExactMatchMetric runs with no API key (0.75 on the
  4-case golden set, matching the local exact-match implementation).
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
- Tonic (Rust) server: the crate compiles and the stub evaluator
  passes, but no Tonic server was started and no Tonic client call
  was made. The runnable gRPC here is Python grpcio.
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
3. Run a real Tonic server (Rust) against the Python grpcio
   client using `proto/constraint_evaluation.proto`, so the
   Rust side of Module 21 is exercised over the wire, not just
   as a stub evaluator — then re-run the full suite and update
   this report.
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
