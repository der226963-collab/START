# START core spine — first local assembly

Date: 2026-11-10. Assembled locally at `~/workspace/start-assembly/core-spine/`,
pushed to der226963-collab/START under `start-assembly/core-spine/` on 2026-11-11
(commit 674f6abc7478bbd497c8459ceec8e4a3d553ba2b).
Nothing here touches `~/workspace/ai-starter`, the v0.3.2 review copy,
or START guardrails / self-edit / safety files.

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
| NetworkDynamics.jl | 10 World Modelling | JuliaDynamics/NetworkDynamics.jl | MIT | Networked dynamics assembler (nodes/edges as DAE components, solved via DifferentialEquations.jl) | assembled 1.3.0 (Julia 1.13.3) — first networked domain model built first: synthetic 3-node resource network (source → storage → sink), 31/31 Julia tests PASS; Graphs.jl 1.15.0 added as a direct dependency for the network graph |
| ModelingToolkit.jl | 10 World Modelling | SciML/ModelingToolkit.jl | MIT | Equation-based structural physics | assembled 11.46.1 (Julia 1.13.3) |
| Symbolics.jl | 12 Math & Computing | JuliaSymbolics/Symbolics.jl | MIT | Symbolic algebra / e-graph rewriting | assembled 7.48.0 (Julia 1.13.3) |
| Turing.jl | 12 Math & Computing | TuringLang/Turing.jl | MIT | Bayesian inference | assembled 0.49.0 (Julia 1.13.3) |
| DifferentialEquations.jl | 12 Math & Computing | SciML/DifferentialEquations.jl | NOASSERTION — confirm before adopting | Continuous physical systems | assembled 8.1.1 (Julia 1.13.3) |
| AlphaZero.jl | 4 Reasoning & Planning | jonathan-laurent/AlphaZero.jl | MIT | MCTS + self-play search (board-game core) | assembled 0.5.6 (git clone, CPU only, no training) |
| PlanningSearch (MCTS + game interface copied from AlphaZero.jl) | 4 Reasoning & Planning | jonathan-laurent/AlphaZero.jl (source, MIT) | MIT (copied files) | Standalone planning search: MCTS over partial plans, rollout oracle + learned linear oracle + learned-dynamics oracle (original MuZero.jl-design rebuild, no MuZero.jl code copied, no Flux/CUDA), candidate only — never verified by the search; original training loop (verified samples only, held-out replacement rule); original SpineOpt planning patterns (time slices, stochastic scenarios, Benders split, nodal balance, MGA for human choice — no SpineOpt code copied, no SpineOpt dependency) | assembled 2026-11-11, 84/84 + 53/53 + 86/86 + 25/25 + 208/208 + 134/134 Julia tests PASS, finds the 600/50 t optimum |
| SpineOpt planning patterns (rebuild only) | 18 Systems Planning | spine-tools/SpineOpt.jl (inspiration only, NOT adopted) | n/a — nothing adopted | SpineOpt planning patterns rebuilt as original Julia: rolling-horizon / representative-period time slices, stochastic normal-vs-low-yield scenarios, Benders master/subproblem split with objective-upperbound cuts (2 iterations, agrees with the direct LP optimum 600/50 t), nodal balance generalised to any flow-conservation constraint, MGA surfacing distinct near-optimal alternatives for human choice, never auto-selecting | assembled 2026-11-11, 134/134 tests PASS; original Julia in `julia-current/planning-search/spineopt_patterns.jl`, JuMP+HiGHS; no SpineOpt code copied, no SpineOpt dependency, no Spine DB; SpineOpt itself is DROP (energy-only, GPL/LGPL contradiction, monolithic build-solve-write); every result CANDIDATE-only until the separate verify step + human approval (Julia 650/650) |

## Canonical Julia environment (adopted 2026-11-11 by Eric)

`julia-current/` is the canonical Julia environment for this spine:
Julia 1.13.3, Agents 7.1.0, ModelingToolkit 11.46.1, Symbolics 7.48.0,
Turing 0.49.0, DifferentialEquations 8.1.1, JuMP 1.32.1, HiGHS 1.26.1,
NetworkDynamics 1.3.0, Graphs 1.15.0,
AlphaZero 0.5.6 (separate env in `alphazero/`). Spine 16/16 PASS,
Julia checks 650/650 passed, 0 failed (29 spine/smokes/AlphaZero +
84 planning-search + 53 LP cross-check + 86 training loop +
25 training loop LP-split + 208 learned-dynamics search +
134 SpineOpt planning patterns +
31 NetworkDynamics networked model). The original pinned envs
`julia/` and `julia-1.11/` are evidence only — they fail to precompile
5 dependencies and are NOT canonical; do not use them for new work.
| LangGraph | 5 Orchestration | langchain-ai/langgraph | MIT | Stateful plan → verify → report graph | assembled |
| Cedar | 2 Governance & Security | cedar-policy/cedar | Apache-2.0 | Formal authorisation policy engine | assembled (Rust) + Python stub evaluator |
| egg | 4 Reasoning & Planning | egraphs-good/egg | MIT | E-graph symbolic rewrites | assembled (Rust) |
| Tonic / gRPC | 21 Interoperability | grpc/grpc-rust | MIT | Contract-driven RPC | assembled — real Rust server (tonic 0.14.9) over a Unix socket, called over the wire by Rust + Python clients (PASS + FAIL cases); Python grpcio in-process server also runnable |
| Apache Arrow | 21 Interoperability | apache/arrow | Apache-2.0 | Zero-copy in-memory table sharing | assembled (pyarrow) |
| DeepEval | 22 Evaluation & Learning | confident-ai/deepeval | Apache-2.0 | Evaluation framework | local non-LLM metrics only (ExactMatch, PatternMatch, JsonCorrectness — 11/11 tests PASS); JsonCorrectness is key-free only via eval_mode="system_one" (default construction needs an OpenAI key); LLM-as-judge deferred |
| ash-flare | 24 Resilience & Continuity | ashforge-rs/ash-flare | Apache-2.0 | Local supervision of execution workers | assembled 3.0.0, default features only (`python` OFF — no pyo3), distributed mode OFF by non-use (no `distributed` feature flag exists in 3.0.0; `ash_flare::distributed` never imported); supervisor core audited first; `Transient` + `OneForOne` only; supervision is liveness, never verification — restarted output stays unverified, a crashed worker is reported failed (6/6 tests PASS, Rust 20/20) |
| ODYM | 17 Resource Accounting | IndEcol/ODYM | MIT | Stock-flow resource accounting | assembled 0.1.0, git pin 9792c23 (never published to PyPI); dependency only, no code copied; adapter `adapters/resource_accounting.py`, 16/16 tests PASS; outputs are model results only (verified=false, needs_human_decision=true) |
| Pymrio | 17 Resource Accounting | IndEcol/pymrio | LGPL-3.0 | Footprint / consumption-based accounting | assembled 0.7.0 (PyPI); dependency only, never copied, library unmodified and replaceable; adapter `adapters/footprint_accounting.py`, 15/15 tests PASS; outputs are model results only (verified=false, needs_human_decision=true); no downloads — synthetic in-memory MRIO only |
| Graphiti (temporal schema only) | 6 Knowledge & Memory | getzep/graphiti | Apache-2.0 | Temporal knowledge fields (valid-from/valid-to, superseded-by, episode links) | assembled 2026-11-11, 17/17 tests PASS; original Python in `adapters/temporal.py`, stdlib only; no Graphiti code copied, system/LLM-extraction/graph-DB/telemetry NOT adopted; verified flag carried unchanged, never set by this module |
| BehaviorTree.rs (node types + typed blackboard only) | 4 Reasoning & Planning | ncrothers/behaviortree-rs | MIT | Behaviour-tree orchestration of plan → verify → report | assembled 2026-11-11, 10/10 tests PASS; original Rust in `rust/src/behavior_tree.rs`, trees in JSON; no BehaviorTree.rs code copied, crate NOT a dependency; verify is a hard gate, report refuses without a passed verify in the same run (Rust 30/30) |
| Beam-Telemetry (event bus only) | 8 Observation & Monitoring | beam-telemetry/telemetry | Apache-2.0 | Monitoring event bus: execute/attach/detach, events carrying licence/provenance + verified flag | assembled 2026-11-11, 17/17 tests PASS; original Python in `adapters/event_bus.py`, stdlib only; no Beam-Telemetry code copied, Erlang library NOT a dependency; handlers never mark a result verified — promotion attempts are rejected and logged (Python 136/136) |
| Collective-Intelligence-Library (pure transforms only) | 19 Collective Intelligence | eq-network/Collective-Intelligence-Library | MIT | Mechanism simulation: effect-declared pure transforms over immutable graph state, pipeline compiled from the read/write DAG, plurality-vote mechanism | assembled 2026-11-11, 19/19 tests PASS; original Python in `adapters/mechanism_simulation.py`, stdlib only; no Collective-Intelligence-Library code copied, JAX NOT a dependency; every result verified=false, needs_human_decision=true (Python 155/155) |
| Tumult (experiment pattern only) | 24 Resilience & Continuity | mwigge/tumult | Apache-2.0 | Fault-injection test tooling: hypothesis → baseline → fault → recovery measurement → evidence journal; three fault kinds (worker_crash, delayed_response, corrupted_value) | assembled 2026-11-11, 18/18 Python + 10/10 Rust tests PASS; original Rust in `rust/src/fault_injection.rs` and original Python in `adapters/fault_injection.py`, stdlib only; no Tumult code copied, Tumult platform (daemon, UI, MCP server) NOT adopted; a fault run can never report PASS and never sets verified=true (Python 173/173, Rust 40/40) |
| SciAgents Discovery (role pattern + 7-key proposal schema only) | 9 Multidisciplinary Intelligence | lamm-mit/SciAgentsDiscovery | Apache-2.0 | Research roles: deterministic, rule-based Ontologist → Scientist → Critic over supplied text; proposal in exactly the 7-key schema (hypothesis, outcome, mechanisms, design_principles, unexpected_properties, comparison, novelty) | assembled 2026-11-11, 18/18 tests PASS; original Python in `adapters/research_roles.py`, stdlib only; no SciAgents code copied, prototype (paid OpenAI key, Semantic Scholar API, GraphReasoning package) NOT adopted, no LLM; a proposal that fails the Critic is marked FAILED, never passed; no stage sets verified=true (Python 191/191) |
| Trace (feedback propagation only) | 22 Evaluation & Learning | microsoft/Trace | MIT | Evaluation attribution: given an evaluation result (e.g. a DeepEval deterministic metric score), propagate the feedback back to the step that produced it — which task, which metric, which input — by exact match on all three; unknown, partial or ambiguous sources are reported UNATTRIBUTED, never guessed, and a cause is never invented | assembled 2026-11-11, 21/21 tests PASS; original Python in `adapters/feedback_attribution.py`, stdlib only; no Trace code copied, `trace-opt` tool (paid LLM API via LiteLLM, optimiser rewriting prompts/code) NOT adopted, no LLM; the verified flag is carried from the result handed in, verbatim, never set here; needs_human_decision always true (Python 212/212) |
| RAP hibernation pattern (local-only only) | 1 Core Framework | hydro-project/infinity | Apache-2.0 | Hibernation state machine: fire-and-forget tool invocation with immediate ack, hibernate/wake over one canonical JSON envelope with a SHA-256 checksum, subscriptions persisting across hibernations, results delivered locally and held unverified until the separate verify step + human approval | assembled 2026-11-11, 20/20 tests PASS; original Python in `adapters/hibernation.py`, stdlib only; no Infinity code copied, `rap-protocol` crate NOT adopted and NOT copied; NO callback URL, listener or network delivery — local-only, `register_callback` always raises (a callback with a bad/missing auth token is rejected along with every other callback); a hibernated state never wakes as verified (Python 232/232) |

## Layout

- `adapters/` — thin Python adapters, no vendored engine code:
  `statuses.py` (status model), `optimisation.py` (HiGHS/CPMpy/CVXPY),
  `interop.py` (Arrow + gRPC), `governance.py` (Cedar stub evaluator),
  `orchestration.py` (LangGraph plan → verify → report),
  `evaluation.py` (DeepEval non-LLM metrics only: ExactMatch,
  PatternMatch, JsonCorrectness — 11/11 tests PASS),
  `resource_accounting.py` (ODYM stock-flow accounting, Module 17 —
  dependency only, synthetic case, outputs are model results only),
  `footprint_accounting.py` (pymrio footprint accounting, Module 17 —
  dependency only, synthetic in-memory MRIO, no downloads, outputs
  are model results only),
  `temporal.py` (temporal knowledge, Module 6 — original Python,
  stdlib only, Graphiti temporal-edge/episode schema as design
  inspiration only, no code copied, no graph DB, no LLM; 17/17
  tests PASS),
  `event_bus.py` (monitoring event bus, Module 8 — original Python,
  stdlib only, Beam-Telemetry execute/attach/detach as design
  inspiration only, no code copied, no BEAM runtime; handlers
  never mark a result verified, promotion attempts rejected and
  logged; 17/17 tests PASS),
  `mechanism_simulation.py` (mechanism simulation, Module 19 —
  original Python, stdlib only, Collective-Intelligence-Library
  pure-transform / immutable-graph design as inspiration only,
  no code copied, no JAX; plurality vote over a synthetic
  5-node graph, pipeline compiled from the read/write DAG;
  every result verified=false, needs_human_decision=true;
  19/19 tests PASS),
  `fault_injection.py` (fault-injection test tooling, Module 24 —
  original Python, stdlib only, Tumult experiment pattern as
  design inspiration only, no code copied, no Tumult platform;
  hypothesis → baseline → fault → recovery measurement →
  evidence journal; fault kinds worker_crash / delayed_response /
  corrupted_value; outcome is always FAIL or UNKNOWN, verified
  always false; 18/18 tests PASS),
  `research_roles.py` (research roles, Module 9 — original
  Python, stdlib only, SciAgents Ontologist → Scientist →
  Critic role pattern and 7-key proposal schema as design
  inspiration only, no code copied, no LLM, no paid API;
  deterministic rule-based stages over supplied text; proposal
  has exactly the 7 keys hypothesis / outcome / mechanisms /
  design_principles / unexpected_properties / comparison /
  novelty; a proposal that fails the Critic is marked FAILED;
  verified always false, needs_human_decision always true;
  18/18 tests PASS),
  `feedback_attribution.py` (feedback attribution, Module 22 —
  original Python, stdlib only, Trace feedback-propagation
  idea as design inspiration only, no code copied, no
  `trace-opt`, no LLM, no optimiser; trace of steps with
  task / metric / input / component, exact-match attribution
  of an evaluation result to the step that produced it;
  unknown, partial or ambiguous sources reported
  UNATTRIBUTED, never guessed; cause never inferred
  (`cause` always None); verified flag carried from the
  result handed in, verbatim, never set here;
  needs_human_decision always true; 21/21 tests PASS),
  `hibernation.py` (RAP hibernation pattern, Module 1 —
  original Python, stdlib only, hydro-project/infinity
  hibernation pattern as design inspiration only, no code
  copied, `rap-protocol` NOT adopted; fire-and-forget tool
  invocation with immediate ack, hibernate/wake over one
  canonical JSON envelope with a SHA-256 checksum,
  subscriptions persisting across hibernations, results
  delivered locally by `deliver_result` and held unverified
  until the separate verify step + human approval; NO
  callback URL, listener or network delivery — local-only,
  `register_callback` always raises; a hibernated state
  never wakes as verified; 20/20 tests PASS).
- `helpers/` — borrowed helpers, the ONLY vendored candidate code in
  this assembly: `borrowed_helpers.py` (Cognee `chunk_by_word` +
  `chunk_id`, Crawl4AI `normalize_url`, Apache-2.0 notices kept,
  stdlib-only, `PROVENANCE.md` in the same folder). Untrusted-input
  utilities only — NOT wired into any verify, governance, or decision
  path. Tests `tests/test_borrowed_helpers.py` — 24/24 PASS.
- `tests/test_spine.py` — the test suite. Run: `.venv/bin/python -m unittest discover -s tests -v`
- `rust/` — Cargo crate: real Cedar evaluation, egg rewrites, real
  Tonic server (`src/server.rs`, binary `start-tonic-server`,
  tonic 0.14.9, prost 0.14.5, tokio 1.54.1; codegen from
  `proto/constraint_evaluation.proto` via tonic-prost-build,
  protoc from grpc_tools — see `rust/build.rs`), and local
  supervision of execution workers (`src/supervision.rs`,
  ash-flare 3.0.0, default features only, distributed OFF,
  `Transient` + `OneForOne`; supervision is liveness, never
  verification), fault-injection test tooling
  (`src/fault_injection.rs` — original Rust rebuild of the
  Tumult experiment pattern, test-only, a fault run can never
  report PASS and never sets verified=true), and behaviour-tree orchestration
  (`src/behavior_tree.rs` — original Rust rebuild of the
  BehaviorTree.rs node types + typed blackboard, trees in JSON;
  verify is a hard gate, report refuses without a passed verify
  in the same run). Run:
  `export PATH="$HOME/.cargo/bin:$PATH" && cargo test` (rustc 1.99.1)
  — 40/40 PASS, including 4 wire tests against the real server
  over a Unix socket, 6 supervision tests, 10 behaviour-tree tests and 10 fault-injection tests. Run the server:
  `cargo run --bin start-tonic-server -- /tmp/tonic.sock` (Unix
  socket only, no TLS/auth — local only).
- `julia-current/` — canonical Julia env (`Project.toml`, `Manifest.toml`, `spine.jl`, `spine_lp.jl`, `spine_ode.jl`, smokes, logs). Run it, not `julia/`. Networked domain model: `network_model.jl` (synthetic 3-node resource network + hand-derived closed form, plain DifferentialEquations — the independent check) and `network_dynamics.jl` (the same network run through NetworkDynamics.jl 1.3.0), tests `test_network_dynamics.jl` — 31/31 PASS.
- `julia-current/planning-search/` — standalone planning-search module
  (`PlanningSearch.jl`, copied `mcts.jl` + `game.jl` with MIT notices,
  original `planning_domain.jl` + `verify.jl`, `PROVENANCE.md`,
  `test/runtests.jl` — 84/84 PASS). MCTS finds the 600/50 t optimum
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
  `dynamics_search.jl` (original, INSPIRATION-REBUILD of MuZero.jl's
  learned-dynamics design — ridge dynamics model, MinMaxStats value
  normalisation, reanalyse step, `DynamicsOracle`; no MuZero.jl code
  copied, no Flux/CUDA; reward is verified-PASS plan quality, never a
  win probability). Tests `test/dynamics_search.jl` — 208/208 PASS
  (held-out mean prediction error 0.0719, max 0.4122; dynamics-oracle
  MCTS finds the 600/50 t optimum on all five seeds 1234, 7, 42, 99,
  2024; held-out dynamics PASS rate 1.0, mean shortage 117.5 t vs
  rollout 147.5 t).
  `spineopt_patterns.jl` (original, INSPIRATION-REBUILD of
  spine-tools/SpineOpt.jl's planning patterns, Module 18 — no SpineOpt
  code copied, no SpineOpt dependency, no Spine DB; SpineOpt itself is
  DROP). Rolling-horizon / representative-period time slices (3 periods,
  aggregate delivered 1,000 t), stochastic normal-vs-low-yield scenarios
  (expected delivered 580 t), Benders master/subproblem split with
  objective-upperbound cuts (2 iterations, agrees with the direct LP
  optimum 600/50 t), nodal balance generalised to any flow-conservation
  constraint, and MGA surfacing 2 distinct near-optimal alternatives
  (wheat 56.25 / potato 16.25 ha and wheat 37.5 / potato 20 ha, each
  delivered 550 t) for human choice — never auto-selected. Every result
  is a CANDIDATE only until the separate verify step + human approval.
  Runner `run_spineopt_patterns.jl` — SPINEOPT_PATTERNS RESULT: PASS.
  Tests `test/spineopt_patterns.jl` — 134/134 PASS (standalone script,
  not in `test/runtests.jl`, so the standalone tests stay JuMP-free).
  One fix the tests forced: `verify.jl` land/water checks now use a 1e-6
  tolerance (was zero), because an LP solution's water total of
  100,000.00000000001 m3 against a 100,000 m3 budget is floating-point
  noise, not an over-budget plan.
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
