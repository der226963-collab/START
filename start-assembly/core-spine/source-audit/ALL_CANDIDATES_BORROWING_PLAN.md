# All 70 Candidates — Borrowing Plan

**Date:** 2026-11-11. **Status:** audit only — no code copied in this sweep, no dependencies added, nothing pushed by this sweep.

**Question Eric asked:** "let's look through all of them and find out what we need from them, what we have to make adjustments to or what we use as inspiration and rebuild on our own."

**Answer in one paragraph:** of the 70 named candidates, 19 are USE (17 of them already adopted as dependencies or copied — the spine already runs on HiGHS, JuMP, the Julia SciML stack, LangGraph, Cedar and the copied AlphaZero MCTS; only 2 USE items are still to do, ODYM and NetworkDynamics.jl, and the smallest is ODYM), 3 are ADJUST (DeepEval's deterministic metrics, Pymrio as a dependency only under LGPL-3.0, ash-flare with its distributed mode off), 8 are INSPIRATION-REBUILD (the best ideas are LM-Eval-Harness's task/metric registry, MuZero.jl's learned-dynamics search, and Graphiti's temporal-edge schema), 28 are DEFER (the dominant reason is a paid LLM API, GPU, or heavyweight cloud platform that a local project does not need yet), and 12 are DROP (6 do not exist as named, 3 are models not engines, 3 have no relevance). The recurring finding across all three audit batches is the same: **coupling is the barrier, not licence.** Apache-2.0 and MIT permit copying almost everywhere, but the code is too interdependent to lift in pieces — so the copyable units are tiny (a 109-line chunker, a ~100-line URL canonicaliser) and everything else is a dependency, a rewrite of the idea, or a defer.

## Method

- **Starting point:** the repo triage (`~/workspace/v032-review/blueprint-triage/REPO_TRIAGE.md`) — all 70 candidates checked for existence, exact owner/repo, licence, stars, relevance (40 high, 19 medium, 5 low, 6 none). This sweep goes one level deeper into the source; it does not redo the triage.
- **Workers:** six subagents, one per module group, each reading the real source (shallow git clone or the GitHub connector) — README, top-level structure, core module(s) for the claimed role, and the LICENSE file. Their per-group findings are in `source-audit/sweep/group-a.json` … `group-f.json` (with `group-*.md` reasoning notes). The coordinator verified a sample of each worker's claims (file existence and JSON validity for all six groups; licence and line-count spot checks, including the DifferentialEquations.jl 34-line figure, which is real — that repo is a re-export umbrella over OrdinaryDiffEq/SciMLBase).
- **Already decided, not re-audited:** batch 1 (AlphaZero.jl, LangGraph — `ALPHAZERO_LANGGRAPH_AUDIT.md`) and batch 2 (Cedar, egg, Cognee, Graphiti, Crawl4AI — `CEDAR_EGG_COGNEE_GRAPHITI_CRAWL4AI_AUDIT.md`, completed 2026-11-11). Their verdicts are folded into the table below. Work already done from them: AlphaZero MCTS + game interface copied, LP cross-check wired, training loop rewritten, and the three small helpers copied (`helpers/borrowed_helpers.py`, 24/24 tests).
- **Line counts are approximate and the counting basis varies** (repo-wide vs `src/`-only vs package-only — see each group JSON's `lines_how_counted`). They are good enough to judge size and coupling; they are not a precise census. No worker marked any candidate "shallow — README only", but three DROP verdicts rest on there being no code to read at all (SciAgent/OpenDCAI, Mojo-LLM, and the model repos DeepSeek-R1/OSeMOSYS, whose line counts of 0 mean "no engine code in the repo").
- **Classification counts:** USE 19, ADJUST 3, INSPIRATION-REBUILD 8, DEFER 28, DROP 12. Total 70.

## Governance filter (applied to every candidate)

- **v0.3.2 allocation:** Python — orchestration, memory, governance, self-edit; Julia — planning contracts and domain logic; Rust — constraint and verification kernels; PyTorch/Python — neural work; Mojo only on demonstrated need.
- **Trust boundaries:** Planning / Evaluation / Verification / Governance / Execution must not collapse. A borrowed piece must not let a planner certify its own output, or turn unverified data into verified.
- **Wire format stays JSON** — never pickle from an untrusted source.
- **Every result needs_human_decision=true.** Verified still means PASS *and* human approval.
- **No new paid dependencies/services without Eric's approval.**
- **Licence verified per source.** Flags that stand: AI-Scientist custom restrictive licence (do not copy); Pymrio LGPL-3.0 (dependency only, never copy, copyleft consequence flagged); DifferentialEquations.jl GitHub NOASSERTION vs MIT text in its LICENSE.md (dependency use is fine on the verified file text; keep the flag); Delibera and Agent-O1 state no licence (nothing copyable or usable); MAX portions under the MAX License, not OSI open source; polars-ts and OxiDiviner claim MIT with no LICENSE file (fails the verification rule); collective-intelligence AGPL-3.0 (copyleft).

## Summary table — one line per candidate

| # | Candidate | Mod | Licence (verified) | Lines | Class | What START needs / does with it |
|---|---|---|---|---|---|---|
| 1 | AWS Infinity Primitives | 1 | n/a — does not exist | 0 | DROP | Drop as named. Replacement hydro-project/infinity worth a later audit only with Eric's approval. |
| 2 | wasmCloud | 1 | Apache-2.0 | 275,187 | DEFER | Defer the platform; keep the deny-by-default capability model as an idea. No Wasm workload yet. |
| 3 | Wasmtime | 1 | Apache-2.0 | 533,096 | DEFER | Defer; adoption route when needed is the `wasmtime` crate, WASI denied by default. |
| 4 | MetaCall Core | 1 | Apache-2.0 | 148,624 | DEFER | Defer. In-process polyglot FFI would collapse the trust boundaries; keep JSON between processes. |
| 5 | Cedar Policy Engine | 2 | Apache-2.0 | 233,228 | USE | Dependency, already in use (cedar-policy 4.14.1). Nothing small enough to copy. |
| 6 | Agent Governance Toolkit | 2 | MIT | 225,237 | DEFER | Defer the platform; carry forward only the deterministic pre-wire intent-check idea. |
| 7 | LLaMA-Factory | 3 | Apache-2.0 | 65,888 | DEFER | Defer the platform (GPU-scale). Its dataset-template pattern is already in START in simpler form. |
| 8 | LM-Eval-Harness | 3 | MIT | 107,463 | INSPIRATION-REBUILD | Rebuild its task/metric registry + filter pipeline as original Python in `mini_ai/eval`. |
| 9 | Mojo-LLM | 3 | n/a — does not exist | 0 | DROP | Drop the name. Replacements (resitkurttr/mojo-llm, dorjeduck/llm.mojo) only if Mojo LLM training becomes a demonstrated need. |
| 10 | Llama3.mojo | 3 | MIT | 1,659 | DEFER | Defer. START's own Mojo samples already cover single-file inference; needs porting to current Mojo. |
| 11 | MAX Engine / Modular | 3, 15 | Apache-2.0 w/ LLVM Exceptions; MAX portions under MAX License | 461,149 | DEFER | Defer both halves. Mojo stays a toolchain dependency (pixi); MAX not adopted at all. |
| 12 | DeepSeek-R1 | 4 | MIT | 0 (model repo) | DROP | Drop as an engine. Only artefact: the GRPO/cold-start training recipe in its paper, as design reference. |
| 13 | QwQ Series | 4 | Apache-2.0 | 6,117 | DROP | Drop as an engine. Its eval harness is GPU-bound with an unsandboxed executor; not worth borrowing. |
| 14 | MuZero.jl | 4 | MIT | 2,163 | INSPIRATION-REBUILD | Rebuild learned-dynamics search as original Julia in planning-search/, with reward = verified-PASS plan quality and the JuMP+HiGHS gate. |
| 15 | AlphaZero.jl | 4 | MIT | 9,370 | USE | Copy done: MCTS + game interface in planning-search/ (75/75 tests). Training loop rewritten as original (111/111). Network dependency-only. |
| 16 | egg | 4 | MIT | 10,721 | USE | Dependency for the e-graph core. UnionFind/EClass are trivial structs, cheaper to rewrite originally if ever needed. |
| 17 | BehaviorTree.rs | 4 | MIT | 6,450 | INSPIRATION-REBUILD | Rebuild Sequence/Fallback/Decorator/Action/Condition + typed blackboard as original Rust, trees in JSON. |
| 18 | LangGraph | 5 | MIT | 38,801 | USE | Dependency, already in use (1.2.20). Do not copy the Pregel engine. |
| 19 | Cognee | 6 | Apache-2.0 | 248,631 | USE | Copy done: chunk_by_word + chunk_id (109 lines, stdlib-only) in helpers/. The system itself is deferred (paid-LLM default, no verified/unverified distinction). |
| 20 | Graphiti | 6 | Apache-2.0 | 40,844 | INSPIRATION-REBUILD | Rewrite only the temporal-edge/episode field schema as original Python. System deferred (Neo4j + OpenAI default, PostHog telemetry on by default). |
| 21 | Crawl4AI | 7 | Apache-2.0 | 47,234 | USE | Copy done: normalize_url (~100 lines) in helpers/. Crawler itself dependency-only. |
| 22 | Elixir Circuits | 8 | Apache-2.0 | 6,063 | DROP | Drop. GPIO hardware control is not observation of plans, data, or models. |
| 23 | Beam-Telemetry | 8 | Apache-2.0 | 1,445 | INSPIRATION-REBUILD | Rebuild the execute/attach/detach event bus as original Python, events carrying licence/provenance + verified/unverified flags; handlers never mark a result verified. |
| 24 | RaRegistry | 8 | Apache-2.0 | 2,371 | DEFER | Defer. Consensus-backed registry concept is sound, but the implementation is inactive/unproven and there is no BEAM allocation. |
| 25 | SciAgent / OpenDCAI | 9 | none — no code released | 0 | DROP | Drop. Withdrawn paper, no code. |
| 26 | SciAgents Discovery | 9 | Apache-2.0 | 1,036 | DEFER | Defer. Ontologist → Scientist → Critic roles + 7-key JSON proposal schema are a design note for original Python. |
| 27 | Agents.jl | 10 | MIT | 8,729 | USE | Dependency, already in use (7.1.0, canonical). No code copied. |
| 28 | ModelingToolkit.jl | 10 | MIT | 53,446 | USE | Dependency, already in use (11.46.1, canonical). No code copied. |
| 29 | NetworkDynamics.jl | 10 | MIT | 16,223 | USE | Dependency (General registry 1.4.0) — add to julia-current/ only when the first networked domain model is built. |
| 30 | AI-Scientist | 11 | Custom restrictive (AI Scientist Source Code License v1.0) | 2,037 | DEFER | Defer. Idea → experiment → writeup → review loop shape is a design note only; no code copied under this licence. |
| 31 | Robin | 11 | Apache-2.0 | 3,472 | DEFER | Defer. Multi-trajectory runner pattern is a design note for original Python. |
| 32 | InternAgent | 11 | Apache-2.0 | 114,456 | DEFER | Defer. Memory-module and workflow structure are design notes only; autonomous experiment execution is barred without verify + human approval. |
| 33 | Symbolics.jl | 12 | MIT | 15,632 | USE | Dependency, already in use (7.48.0, canonical). No code copied. |
| 34 | Turing.jl | 12 | MIT | 6,492 | USE | Dependency, already in use (0.49.0, canonical). No code copied. |
| 35 | DifferentialEquations.jl | 12 | MIT (file text; GitHub NOASSERTION) | 34 | USE | Dependency, already in use (8.1.1, canonical). The repo is a 34-line re-export umbrella; there is nothing to copy. Keep the licence flag. |
| 36 | Jutul.jl | 13 | MIT | 50,414 | DEFER | Defer. No START domain needs implicit finite-volume multiphysics simulation. |
| 37 | Trixi.jl | 13 | MIT | 125,665 | DEFER | Defer. No START domain needs conservation-law simulation. |
| 38 | AgentBasedModeling.jl | 13 | MIT | 2,239 | DEFER | Defer. Inactive, redundant with Agents.jl, and drags in a heavy stack for a niche START does not need. |
| 39 | HiGHS | 14 | MIT | 157,580 | USE | Dependency, already assembled (highspy 1.15.1 / HiGHS.jl 1.26.1). Nothing small enough to copy. |
| 40 | CPMpy | 14 | Apache-2.0 | 34,474 | USE | Dependency, already assembled (1.1.1, HiGHS backend). Nothing small enough to copy. |
| 41 | CVXPY | 14 | Apache-2.0 | 119,312 | USE | Dependency, already assembled (1.9.3, HiGHS backend). Nothing small enough to copy. |
| 42 | polars-ts | 15 | MIT claimed, no LICENSE file | 32,641 | DEFER | Defer. Licence not verifiable; later, dependency `polars-timeseries[forecast]` for classical forecasting only. |
| 43 | OxiDiviner | 15 | MIT claimed, no LICENSE file | 55,011 | DEFER | Defer. Licence not verifiable; inactive since 2025-07-06. Later, dependency `oxidiviner` if a Rust forecasting consumer exists. |
| 44 | Potts.jl | 15 | MIT | 96,341 | DROP | Drop as forecasting. No replacement needed in Module 15. |
| 45 | NumMojo | 15 | n/a — does not exist | 0 | DROP | Drop the name. Closest real project NuMojo is a NumPy-like library, not a forecasting engine — not worth auditing. |
| 46 | SolidCraft | 16 | MIT OR Apache-2.0 | 1,125,101 | DEFER | Defer. Application-scale CAD (1.1M lines); its parametric sketch constraint solver is too coupled to lift. |
| 47 | GridapTopOpt.jl | 16 | MIT | 12,084 | DEFER | Defer. Later, dependency if a physical-design use case appears. |
| 48 | JuliaFEM.jl | 16 | MIT | 30,795 | DEFER | Defer. API unstable mid-reset toward 1.0; no FEA consumer in the allocation. |
| 49 | ODYM | 17 | MIT | 3,672 | USE | Dependency (pip `ODYM`) for stock-flow resource accounting in the Python layer. Nothing needs copying. Not yet added — the smallest new USE item. |
| 50 | OSeMOSYS | 17 | Apache-2.0 | 0 (model) | DROP | Drop as an engine. If an energy-system model is ever needed, audit the Pyomo implementation later. |
| 51 | Pymrio | 17 | LGPL-3.0 | 11,254 | ADJUST | Dependency ONLY (pip `pymrio`) — never copy. Keep the LGPL-3.0 notice, keep the library unmodified and replaceable; add provenance/licence fields and a verify step around its outputs. |
| 52 | SpineModel | 18 | n/a — does not exist | 0 | DROP | Drop the name. Replacement spine-tools/SpineOpt.jl worth auditing later; Module 18 is covered meanwhile by JuMP.jl. |
| 53 | JuMP.jl | 18 | MPL-2.0 | 27,782 | USE | Dependency, already assembled (1.32.1, canonical). MPL-2.0 is file-level copyleft; dependency use imposes no licence on START. |
| 54 | Delibera | 19 | none stated | 8,295 | DEFER | Defer (effectively unusable). Deliberation mechanics (proposals, comments, votes) are at most a design note for an original Python M19 module. |
| 55 | collective-intelligence | 19 | AGPL-3.0-or-later | 966,782 | DEFER | Defer. Its Decision Layer idea (independent reasoning + verification + auditable provenance) is a design note, not a copy. |
| 56 | Collective-Intelligence-Library | 19 | MIT | 21,348 | INSPIRATION-REBUILD | Rebuild effect-declared pure transforms over immutable graph state as original Python (JAX-free), results unverified until the verify step. |
| 57 | OpenHands | 20 | MIT | 193,378 | DEFER | Defer the platform. Nothing small and self-contained exists to lift. |
| 58 | Aider | 20 | Apache-2.0 | 20,285 | INSPIRATION-REBUILD | Rebuild the repo map (tree-sitter tag extraction + ranked, token-budgeted context) as original Python alongside the self-edit/propose-and-approve machinery. |
| 59 | gRPC / Tonic | 21 | MIT | 149,163 | USE | Dependency, already in use (tonic 0.12; upgrade to 0.14.x when the real server is built). Next step is the real server, already assembly-report step 3. |
| 60 | Apache Arrow | 21 | Apache-2.0 | 705,715 | USE | Dependency, already in use (pyarrow 26.0.1; IPC round-trip tested). Wire format stays JSON for inter-component messages. |
| 61 | Agent-O1 | 22 | none stated | 4,168 | DEFER | Defer. No licence means no right to copy or use. Its HITL-gate design (explicit approval for mutating actions) is an idea only. |
| 62 | Trace / Microsoft | 22 | MIT | 10,917 | DEFER | Defer. Trace-based feedback propagation (attributing a failed verify to a step) is an idea for original Python code; the tool needs a paid LLM API. |
| 63 | DeepEval | 22 | Apache-2.0 | 126,512 | ADJUST | Dependency, already adopted (4.3.3). Extend use ONLY to deterministic, model-free metrics (ExactMatch, PatternMatch, JsonCorrectness). Do NOT adopt the LLM-as-judge metrics without Eric approving a paid API key. |
| 64 | Cronoq | 23 | MIT OR Apache-2.0 | 56,631 | DEFER | Defer the system. Only plausible slice later is the cronoq-core crate (6,202 lines, SQLite-backed) as a library, never the server/operator deployment. |
| 65 | Spur / AMD ROCm | 23 | Apache-2.0 | 309,491 | DEFER | Defer. Do not run a Slurm-compatible cluster scheduler for a local single-machine project. |
| 66 | Cuda-Captain | 23 | MIT OR Apache-2.0 (declared only, no LICENSE file) | 400 | DROP | Drop. No relevance to START resource management; licence unverified. |
| 67 | ash-flare | 24 | Apache-2.0 | 17,564 | ADJUST | Dependency (ash-flare 3.0.0), default features only (python feature OFF), local supervision only, distributed mode OFF (avoids the rkyv binary wire format), restarts apply to execution workers only and a restarted worker must never re-emit a verified verdict. Audit the supervisor core first (single-author, low adoption). |
| 68 | Tumult | 24 | Apache-2.0 | 151,498 | INSPIRATION-REBUILD | Rebuild the experiment pattern (hypothesis → baseline → fault → recovery measurement → evidence journal) as original small Rust/Python test tooling. Full platform deferred as heavyweight. |
| 69 | OpenIntelligentUI | 25 | MIT | 10,898 | DEFER | Defer the app (needs paid frontier-LLM keys, PostHog, an external router key). Its visualisation-router idea is a future rebuild pattern. |
| 70 | A2UI Engine | 25 | n/a — does not exist | 0 | DROP | Drop as named. The A2UI protocol (a2ui-project/a2ui) is worth a later audit if START ever builds a UI. |

## Per-module reasoning

### Module 1 — Core Framework (wasmCloud, Wasmtime, MetaCall, AWS Infinity Primitives)
The weakest module in the blueprint, and the sweep confirms it. One name does not exist; the rest are overstated for a lightweight local core. wasmCloud is a 275k-line operator/NATS/Kubernetes platform — deferred, though its deny-by-default capability model is worth keeping as a design principle. Wasmtime is the real sandboxing piece (533k lines), deferred as a dependency until START has a Wasm workload — i.e. until it decides to execute untrusted or generated code, at which point the adoption route is the `wasmtime` crate with WASI denied by default, not the CLI. MetaCall is C, not Rust, and its in-process polyglot FFI model would collapse the Planning/Verification/Governance trust boundaries, so it is deferred unless Eric explicitly approves in-process FFI; the standing rule is separate processes with JSON on the wire. AWS Infinity Primitives is dropped as named; hydro-project/infinity is the closest real project and is worth a later audit only with Eric's approval.

### Module 2 — Governance & Security (Cedar, Agent Governance Toolkit)
Cedar is already in use correctly (cedar-policy 4.14.1, dependency only, 233k lines of Rust — nothing small enough to copy, and the audit found no need to). The Agent Governance Toolkit is the opposite shape: a 225k-line, ~20-sub-package Python platform (wrong language for the module's Rust allocation) built around a separate ACS policy engine. Deferred as a whole; the one idea worth carrying forward is its deterministic pre-wire intent check. Governance in START stays small: Cedar as the policy engine, the verify step, and human approval.

### Module 3 — AI & Development (LLaMA-Factory, LM-Eval-Harness, Mojo-LLM, Llama3.mojo, MAX Engine)
Mojo-LLM does not exist; Llama3.mojo is a 1,659-line single file, inactive since 2024, and START's own Mojo samples already cover that pattern — deferred. LLaMA-Factory (66k lines, GPU-scale) would collapse START's from-scratch, CPU-portable training into an external framework — deferred; its dataset-template pattern is already in START in simpler form. MAX Engine is deferred on both halves: Mojo stays a toolchain dependency installed via pixi, and MAX itself is not adopted — its portions are under the MAX License, source-available rather than OSI open source. The one real gain here is LM-Eval-Harness: not as a dependency (107k lines), but as an inspiration-rebuild — its task registry, metric registry, and filter pipeline rebuilt as original Python in START's own evaluation area (`mini_ai/eval`).

### Module 4 — Reasoning & Planning (DeepSeek-R1, QwQ, MuZero.jl, AlphaZero.jl, egg, BehaviorTree.rs)
Two of the six are models, not engines, and both are dropped as engines: DeepSeek-R1 (its only usable artefact is the GRPO/cold-start recipe in its paper, as design reference) and QwQ (its eval harness is GPU-bound with an unsandboxed executor). AlphaZero.jl is the success of the sweep so far — MCTS + game interface copied, training loop rewritten, 239/239 planning-search tests. egg stays a dependency for the e-graph core; its only separable pieces are trivial structs cheaper to rewrite. The two rebuilds here are both strong: MuZero.jl's learned-dynamics search (2,163 lines, game-shaped and Flux-bound, so not copied — rebuilt as original Julia in planning-search/ with reward defined as verified-PASS plan quality under the JuMP+HiGHS gate) and BehaviorTree.rs's node types plus typed blackboard (6,450 lines, inactive since 2024 — rebuilt as original Rust with trees in JSON, never XML from an untrusted source).

### Module 5 — Agent Orchestration (LangGraph)
Dependency only, already in use (1.2.20). Do not copy the Pregel engine — it would drag in langchain-core (70,894 lines). The concepts worth rebuilding if the graph ever outgrows three nodes (channels, supersteps, interrupts) are already reproduced in ~150 lines of original Python in `adapters/orchestration.py`, with tests proving verification cannot be bypassed.

### Module 6 — Knowledge & Memory (Cognee, Graphiti)
Both systems are deferred; both yielded something small. Cognee (249k lines) defaults to a paid LLM, has no needs_human_decision hook and no verified/unverified distinction — deferred as a system, but its two stdlib-only chunking helpers (109 lines) are already copied into `helpers/borrowed_helpers.py`. Graphiti (41k lines) defaults to Neo4j + OpenAI with PostHog telemetry on by default and no verified flag — deferred as a system; the rebuild is its temporal-edge/episode field schema as original Python code. That rewrite is the next small copy candidate after this sweep, per Eric's "wait for the full sweep first" direction.

### Module 7 — Data Integration (Crawl4AI)
The crawler is dependency-only (47k lines); the copyable unit, `normalize_url` (~100 lines, stdlib-only), is already copied into `helpers/borrowed_helpers.py`. Two governance findings from the batch-2 audit stand: its robots.txt handling defaults off, and `CrawlResult` carries no licence/provenance fields — any future use as a dependency needs those addressed, not assumed.

### Module 8 — Observation & Monitoring (Elixir Circuits, Beam-Telemetry, RaRegistry)
There is no sensory core here, and the sweep confirms it. Elixir Circuits is a GPIO wrapper — dropped, since GPIO hardware control is not observation of plans, data, or models, and a physical-sensor deployment contradicts the data-first monitoring direction. RaRegistry is a 2,371-line consensus-backed registry, inactive and unproven, with no BEAM allocation — deferred. Beam-Telemetry is the one keeper as an idea: its execute/attach/detach event bus rebuilt as original Python in the orchestration/monitoring module, with each event carrying licence/provenance and a verified/unverified flag, and handlers restricted to logging/metrics — handlers must never mark a result verified.

### Module 9 — Multidisciplinary Intelligence (SciAgent/OpenDCAI, SciAgents Discovery)
SciAgent/OpenDCAI does not exist as named — a withdrawn paper with no code — dropped. SciAgents Discovery is a 1,036-line research prototype needing a paid OpenAI key and a separate GraphReasoning package, inactive since 2025-05 — deferred. Its Ontologist → Scientist → Critic role pattern and its 7-key structured JSON proposal schema survive as a design note for original Python code.

### Modules 10/12/13 — Julia SciML (Agents.jl, ModelingToolkit.jl, NetworkDynamics.jl, Symbolics.jl, Turing.jl, DifferentialEquations.jl, Jutul.jl, Trixi.jl, AgentBasedModeling.jl)
The strongest Julia block, and mostly already adopted: Agents.jl 7.1.0, ModelingToolkit.jl 11.46.1, Symbolics.jl 7.48.0, Turing.jl 0.49.0 and DifferentialEquations.jl 8.1.1 are all canonical in `julia-current/`, smoke-tested, and used as dependencies — nothing in them is small enough to copy, and nothing needs to be. Two licence notes were resolved by reading the files: ModelingToolkit's and Symbolics' "mismatch" flags are GitHub metadata/SPDX-detection quirks, not problems in the LICENSE files (both plain MIT); DifferentialEquations.jl's LICENSE.md quotes the full MIT grant, so dependency use is fine on the verified file text, but the GitHub NOASSERTION flag stays in LICENCES.md until the metadata agrees. NetworkDynamics.jl (16k lines, MIT) is the one USE not yet added — add it to `julia-current/` only when the first networked domain model is built. Jutul.jl (50k lines of finite-volume/AD infrastructure) and Trixi.jl (126k lines of DG/CFD machinery) are deferred: no START domain needs them. AgentBasedModeling.jl is deferred despite its small size (2,239 lines) — inactive, redundant with Agents.jl, and drags in a heavy stack.

### Module 11 — Scientific Research (AI-Scientist, Robin, InternAgent)
All three deferred, all three for the same structural reason: they need paid frontier-LLM APIs (and GPUs) to do anything, and they are built for autonomous experiment execution, which START must not do without the verify step and human approval. AI-Scientist is additionally barred from copying by its custom restrictive licence (v1, superseded by v2/v3) — its idea → experiment → writeup → review loop is a design note only. Robin's multi-trajectory runner pattern and InternAgent's memory-module structure are likewise design notes for original Python, not code to lift.

### Module 14 — Optimisation & Solving (HiGHS, CPMpy, CVXPY)
A genuinely strong, directly relevant stack, and already assembled: HiGHS via SciPy/highspy and HiGHS.jl, CPMpy 1.1.1, CVXPY 1.9.3 — all three reproduce the same synthetic totals (delivered 600 t, shortage 50 t). Nothing in any of them is small enough to copy (the solver core is 150k lines of C++; CVXPY's value is its 119k-line DCP/reduction machinery). Governance note, recorded in the workers' findings: a solver solves; it must never certify its own output — solver results stay candidates until the separate verify step and human approval. CVXPY's GPL-licensed solver extras are not in use.

### Module 15 — Forecasting & Analysis (polars-ts, OxiDiviner, Potts.jl, NumMojo, MAX Engine)
NumMojo does not exist; its closest real project NuMojo is a NumPy-like library, not a forecasting engine — dropped, no replacement needed. Potts.jl is a spatial cell-simulation library, not forecasting — dropped as forecasting. polars-ts and OxiDiviner are both deferred, and both for a reason that matters: each claims MIT with no LICENSE file (README/Cargo.toml only), so both fail START's per-source licence-verification rule, and OxiDiviner is inactive since 2025-07. If either is ever adopted, it is as a dependency for classical forecasting only. MAX Engine's forecasting role is deferred with the rest of Module 3 (see above).

### Module 16 — Engineering & Design (SolidCraft, GridapTopOpt.jl, JuliaFEM.jl)
All deferred: no consumer for CAD, topology optimisation, or FEA in the v0.3.2 allocation. SolidCraft is application-scale (1.1M lines); its parametric sketch constraint solver is too coupled to lift. GridapTopOpt.jl would be a dependency if a physical-design use case appears. JuliaFEM.jl's API is mid-reset toward 1.0 and quiet since 2026-05 — deferred on stability as well as need.

### Module 17 — Resource Accounting (ODYM, OSeMOSYS, Pymrio)
The most immediately useful module after the spine itself. ODYM is the smallest new USE item in the whole sweep: 3,672 lines, MIT, pip-installable, for stock-flow resource accounting in the Python layer — nothing needs copying. Pymrio is ADJUST: dependency only under LGPL-3.0 (never copy; keep the library unmodified and replaceable, keep the LGPL notice, add provenance/licence fields and a verify step around its outputs). OSeMOSYS is a model, not an engine — dropped as a component; if an energy-system model is ever needed, audit the Pyomo implementation later.

### Module 18 — Systems Planning (SpineModel, JuMP.jl)
SpineModel does not exist as named — dropped; its successor spine-tools/SpineOpt.jl is worth auditing later, and Module 18 is covered meanwhile by JuMP.jl, already assembled (1.32.1 + HiGHS 1.26.1, canonical). JuMP's MPL-2.0 is file-level copyleft: modifications to JuMP's own files must stay MPL-2.0, but using it as a dependency imposes no licence on START. Nothing in JuMP is small enough to copy.

### Module 19 — Collective Intelligence (Delibera, collective-intelligence, Collective-Intelligence-Library)
The weakest real module. Delibera is a legacy PHP WordPress plugin with no licence stated, inactive since 2017 — deferred, effectively unusable; its deliberation mechanics are at most a design note. collective-intelligence is a 967k-line multi-service platform with ~90 paid external model-provider dependencies under AGPL-3.0 copyleft — deferred, with no realistic unblock; only its Decision Layer idea (independent reasoning + verification + auditable provenance) survives as a design note. The Collective-Intelligence-Library is the one rebuild: effect-declared pure transforms over immutable graph state, rebuilt as original Python (JAX-free) as START's own mechanism-simulation module, with every pipeline result unverified until the verify step.

### Module 20 — Software Intelligence (OpenHands, Aider)
OpenHands is a 193k-line heavyweight TypeScript platform behind paid LLM APIs — deferred; nothing small and self-contained exists to lift. Aider is the rebuild: its repo map (867 lines — tree-sitter tag extraction plus ranked, token-budgeted whole-repo context) rebuilt as original Python alongside the existing self-edit/propose-and-approve machinery, producing the same kind of compact repo map for START's own code. The tool itself is never run as a START component, since it needs an LLM API and edits code directly.

### Module 21 — Interoperability (gRPC/Tonic, Apache Arrow)
Both already in use as dependencies. Tonic (spine pins 0.12; upgrade to 0.14.x when the real server is built) plus tonic-build codegen from `proto/constraint_evaluation.proto` — the next step is exactly assembly-report step 3, a real server exercised over the wire (Unix socket, since the VM egress proxy intercepts TCP loopback). Arrow (pyarrow 26.0.1, IPC round-trip tested) is in use for constraint-result tables locally; it does not change the START wire format, which stays JSON for inter-component messages. Note for the record: the blueprint names grpc/grpc-rust, but the Rust implementation actually used is hyperium/tonic — the worker verified the distinction.

### Module 22 — Evaluation & Learning (Agent-O1, Trace, DeepEval)
Agent-O1 states no licence — deferred, with nothing copyable or usable; its HITL-gate design (explicit approval for mutating actions, denial fed back as an observation) is an idea only. Trace needs a paid LLM API via LiteLLM for every optimisation step and is inactive since 2025-08 — deferred; its trace-based feedback propagation idea (attributing a failed verify to a step) belongs in original Python in the evaluation layer, built on the verified-only training loop. DeepEval is ADJUST: already adopted (4.3.3), but use is extended only to the deterministic, model-free metrics (ExactMatch, PatternMatch, JsonCorrectness) — no API key. The LLM-as-judge metrics (G-Eval, hallucination, faithfulness, answer relevancy) stay out unless Eric approves a paid LLM API key and they are used only on already-verified outputs.

### Module 23 — Resource Management (Cronoq, Spur, Cuda-Captain)
Cronoq is 0 stars at triage and very new — deferred; the only plausible slice later is the cronoq-core crate (6,202 lines, SQLite-backed) as a library, never the server/operator deployment. Spur is a Slurm-compatible cluster scheduler — deferred; START has no multi-node GPU cluster. Cuda-Captain is a 400-line, 1-star crate with no LICENSE file — dropped.

### Module 24 — Resilience & Continuity (ash-flare, Tumult)
ash-flare is ADJUST: use as a dependency (3.0.0), default features only (python feature OFF), local supervision only, distributed mode OFF (avoids the rkyv binary wire format), restarts apply to execution workers only, and a restarted worker must never re-emit a verified verdict — with the condition that the supervisor core is audited first, given single-author/low-adoption status. Tumult is the rebuild: its experiment pattern (hypothesis → baseline → fault → recovery measurement → evidence journal) as original small Rust/Python test tooling; the full 151k-line platform, with its daemon/UI and optional paid-LLM tutor, is deferred.

### Module 25 — Applications & UIs (OpenIntelligentUI, A2UI Engine)
A2UI Engine does not exist as named — dropped; the A2UI protocol (a2ui-project/a2ui) is worth a later audit if START ever builds a UI. OpenIntelligentUI is deferred: it needs paid frontier-LLM keys, PostHog telemetry, and an external router key, with no local-model route. Its visualisation-router idea (choosing text vs native component vs sandboxed generated UI per turn) is a future rebuild pattern, and it pairs with the A2UI protocol.

## Top 10 USE / ADJUST — what to copy or adjust next (smallest, highest-value first)

1. **ODYM as a pip dependency** (M17) — stock-flow resource accounting in the Python layer. 3,672 lines, MIT, nothing to copy. The smallest new USE item in the sweep, and it fills a real gap: START has no resource-accounting library yet. Note the worker's cautions: xlwt/xlrd are legacy Excel deps (read-only use is fine) and `MFAsystem` uses mutable default arguments — callers must pass explicit arguments.
2. **DeepEval deterministic metrics only** (M22) — extend from ExactMatch (already used) to PatternMatch and JsonCorrectness. No API key, already a dependency (4.3.3). The LLM-as-judge metrics stay out.
3. **Tonic real server** (M21) — run a real Rust server against the Python grpcio client using `proto/constraint_evaluation.proto`, exercised over the wire (Unix socket). Upgrade tonic 0.12 → 0.14.x when building it. This is already assembly-report step 3; the sweep confirms it is still the right next interop step.
4. **Pymrio as a pip dependency only** (M17) — never copy; keep the LGPL-3.0 notice, keep the library unmodified and replaceable, add provenance/licence fields and a verify step around its outputs. For multi-region input-output accounting.
5. **ash-flare as a dependency** (M24) — 3.0.0, default features only, local supervision only, distributed mode OFF; audit the supervisor core first (supervisor.rs, restart.rs, worker.rs).
6. **NetworkDynamics.jl** (M10) — add to `julia-current/` only when the first networked domain model is built (e.g. a resource/energy network whose nodes and edges are DAE components). Adding it now, with no model to run, would add dependency weight for nothing.
7. **Cognee helpers — DONE** (M6) — chunk_by_word + chunk_id, 109 lines, already in `helpers/borrowed_helpers.py`, 24/24 helper tests.
8. **Crawl4AI normalize_url — DONE** (M7) — ~100 lines, already in `helpers/borrowed_helpers.py`.
9. **AlphaZero MCTS + game interface — DONE** (M4) — copied, re-expressed in planning terms, 75/75 tests; training loop rewritten as original, 111/111.
10. **The assembled spine — DONE** (M5, M2, M4, M10, M12, M14, M18, M21, M22) — LangGraph, Cedar, egg, HiGHS/CPMpy/CVXPY/JuMP, the Julia SciML stack, Tonic, Arrow, DeepEval (ExactMatch) are already dependencies. Nothing further to do for these from this sweep.

## Top 10 INSPIRATION-REBUILD ideas

1. **LM-Eval-Harness task/metric registry** (M3) → original Python evaluation module in `mini_ai/eval`: a small task registry with YAML-defined eval tasks, a metric registry (accuracy, perplexity, exact-match), and a filter pipeline. No lm-eval dependency, no paid API.
2. **MuZero.jl learned-dynamics search** (M4) → original Julia in planning-search/: a dynamics model predicting next-state features and reward, with MinMaxStats-style value normalisation and a reanalyse step — reward defined as verified-PASS plan quality under the JuMP+HiGHS gate, never a win probability.
3. **Graphiti temporal-edge/episode schema** (M6) → original Python temporal knowledge fields (valid-from/valid-to, episode links, superseded-by). The next small rebuild after this sweep, per Eric's "wait for the full sweep first" direction.
4. **Aider repo map** (M20) → original Python repo-map module alongside the self-edit/propose-and-approve machinery: tree-sitter tag extraction plus ranked, token-budgeted whole-repo context for START's own code.
5. **BehaviorTree.rs node types** (M4) → original Rust orchestration: Sequence, Fallback, Decorator, Action, Condition plus a typed blackboard, trees defined in JSON.
6. **Beam-Telemetry event bus** (M8) → original Python monitoring bus: execute/attach/detach, events carrying licence/provenance + verified/unverified flags; handlers for logging/metrics only, never marking a result verified.
7. **Collective-Intelligence-Library pure transforms** (M19) → original Python mechanism-simulation: effect-declared pure transforms over immutable graph state, pipeline compiled from the read/write DAG, JAX-free, results unverified until the verify step.
8. **Tumult experiment pattern** (M24) → original small Rust/Python fault-injection test tooling: hypothesis → baseline → fault (kill/stall a worker, drop a message, corrupt a candidate) → recovery measurement → evidence journal.
9. **SciAgents role pattern** (M9) → original Python research roles: Ontologist → Scientist → Critic, with the 7-key structured JSON proposal schema.
10. **Trace feedback propagation** (M22) → original Python evaluation attribution: recording which step of a plan's execution a failed verify or a bad score belongs to, built on the verified-only training loop.

Honourable mentions (also worth rebuilding, ranked just below): Robin's multi-trajectory runner; InternAgent's memory-module structure; Delibera's deliberation mechanics (proposals, comments, votes); Agent-O1's HITL-gate (explicit approval for mutating actions, denial fed back as an observation); OpenIntelligentUI's visualisation router; wasmCloud's deny-by-default capability model; the Agent Governance Toolkit's deterministic pre-wire intent check; LLaMA-Factory's dataset-template pattern (already in START in simpler form); collective-intelligence's Decision Layer (independent reasoning + verification + auditable provenance).

## DEFER list — with blockers

| Candidate | Blocker | Unblocks when |
|---|---|---|
| wasmCloud | Heavyweight cloud platform (operator/NATS/K8s); no Wasm workload | START decides to run untrusted Wasm components |
| Wasmtime | No Wasm workload yet | Same as above — then adopt the `wasmtime` crate, WASI denied by default |
| MetaCall Core | C core outside the allocation; in-process FFI collapses trust boundaries | Only if Eric explicitly approves in-process polyglot FFI |
| Agent Governance Toolkit | Heavyweight (~225k lines, ~20 sub-packages); wrong language for M2 | Only if START wants a Python governance platform instead of the small Cedar-based layer |
| LLaMA-Factory | GPU-scale training stack; contradicts CPU-portable from-scratch direction | Only if Eric approves GPU-scale framework training |
| Llama3.mojo | Inactive 2+ years; 2024-era Mojo API drift; gated Meta weights licence | A maintained fork targets current Mojo with freely licensed weights |
| MAX Engine | MAX portions under MAX License (not OSI); inference-serving, not a START component | Never for MAX; Mojo stays a toolchain dependency |
| SciAgents Discovery | Paid OpenAI key + external GraphReasoning package; inactive since 2025-05 | A local LLM can fill the agent roles and the dependency is available |
| AI-Scientist | Custom restrictive licence; needs frontier LLM + GPU | Licence change plus a local model — effectively never for v1 as named |
| Robin | Paid Edison credits + frontier LLM; biomedical-only | Paid dependencies approved and the system generalised |
| InternAgent | Paid frontier-LLM keys; built for autonomous experiment execution | Local LLM available and execution gated by verify + human approval |
| Delibera | No licence; inactive since 2017; PHP/WordPress-only | Effectively no unblock (licence + maintained fork + port) |
| collective-intelligence | AGPL-3.0 copyleft; ~90 paid model-provider dependencies; multi-service platform | No realistic unblock |
| OpenHands | Heavyweight TypeScript platform; paid LLM APIs behind every agent | Only if START wants a self-hosted agent platform |
| Jutul.jl | No domain needs implicit finite-volume multiphysics | A concrete domain model requires it (e.g. reservoir/groundwater) and Eric approves |
| Trixi.jl | No domain needs conservation-law simulation | A concrete domain model requires it (e.g. fluid/atmospheric transport) and Eric approves |
| AgentBasedModeling.jl | Inactive; redundant with Agents.jl; heavy dependency stack | It revives AND a structured-population model is needed |
| polars-ts | MIT claimed with no LICENSE file (fails verification) | A LICENSE file appears; then dependency for classical forecasting only |
| OxiDiviner | MIT claimed with no LICENSE file; inactive since 2025-07 | A LICENSE file appears and it is maintained; then dependency if a Rust forecaster is needed |
| SolidCraft | Application-scale CAD (1.1M lines); no CAD consumer | START ever needs parametric CAD — then re-audit the sketch solver |
| GridapTopOpt.jl | No physical-design consumer; heavy Gridap/MPI/PETSc chain | A concrete physical-design use case appears |
| JuliaFEM.jl | API unstable mid-reset toward 1.0; no FEA consumer | API stabilises and an FEA consumer appears |
| RaRegistry | Inactive/unproven; no BEAM allocation | START adopts a distributed BEAM/Elixir component AND the project revives |
| Cronoq | Very new/unproven (0 stars); no scheduling need beyond START's own executor | Adoption/stability evidence plus a real scheduling requirement |
| Spur | Needs a multi-node GPU cluster / Slurm environment | START runs multi-node GPU training jobs |
| Agent-O1 | No licence stated; inactive single-commit repo | No unblock — no licence means no right to copy or use |
| Trace / Microsoft | Needs a paid LLM API via LiteLLM for every step; inactive since 2025-08 | A local-model route exists and the project is maintained |
| OpenIntelligentUI | Needs paid frontier-LLM keys, PostHog, external router key | A local-model AG-UI route exists |

## DROP list — with reasons

| Candidate | Reason |
|---|---|
| AWS Infinity Primitives | Does not exist as named. |
| Mojo-LLM | Does not exist as named. |
| SciAgent / OpenDCAI | Does not exist as named; withdrawn paper, no code. |
| NumMojo | Does not exist as named. |
| SpineModel | Does not exist as named. |
| A2UI Engine | Does not exist as named. |
| DeepSeek-R1 | A model, not an engine. |
| QwQ Series | A model, not an engine. |
| OSeMOSYS | A model, not an engine. |
| Elixir Circuits | No relevance — GPIO hardware control is not observation of plans, data, or models. |
| Potts.jl | No relevance as forecasting. |
| Cuda-Captain | No relevance to START resource management; licence unverified (no LICENSE file). |

## Follow-ups — replacements worth auditing later (only with Eric's approval)

- **hydro-project/infinity** (808 stars) — closest real project to AWS Infinity Primitives; matches the scale-to-zero claim, not Wasm sandboxing.
- **resitkurttr/mojo-llm** (single file, no autograd) or **dorjeduck/llm.mojo** — closest real projects to Mojo-LLM; only if Mojo LLM training becomes a demonstrated need.
- **spine-tools/SpineOpt.jl** (82 stars) — successor to SpineModel; the Module 18 systems-planning candidate.
- **a2ui-project/a2ui** — the A2UI protocol (not an "Engine"); genuinely relevant to Module 25 if START ever builds a UI, and it pairs with the OpenIntelligentUI visualisation-router idea.
- **OSeMOSYS_Pyomo** — the Pyomo implementation of OSeMOSYS, if an energy-system model (not engine) is ever needed.
- **NuMojo** — explicitly NOT worth auditing as a Module 15 replacement (a NumPy-like library, not a forecasting engine).

## Method note and limitations

- This sweep is an audit, not an adoption: no code was copied into START, no dependency was added, and no existing project file was modified outside the sweep working files and the two reports (this report and the ASSEMBLY_REPORT.md next-steps update). The per-group worker findings are the evidence base (`source-audit/sweep/group-a.json` … `group-f.json`, with `group-*.md` reasoning). Audit clones made by the workers are in `source-audit/sweep/scratch/` (and the workers' `/tmp` clones were deleted after the sweep — `/tmp` is a 512 MB tmpfs and filled during cloning).
- Depth: no worker marked any candidate "shallow — README only". Three DROP verdicts rest on there being no code to read (SciAgent/OpenDCAI, Mojo-LLM, and the model repos), and two DEFER verdicts rest partly on a missing LICENSE file (polars-ts, OxiDiviner) — those are findings, not gaps in the reading.
- Line counts are approximate and the counting basis varies by worker (repo-wide, `src/`-only, or package-only). They support the size/coupling judgement; they are not a precise census. Two figures the coordinator checked explicitly: DifferentialEquations.jl is genuinely a 34-line re-export umbrella (the solvers live in other repos), and DeepSeek-R1's 0 lines means the repo holds no engine code (weights, configs, and its paper).
- Batch 1 and batch 2 verdicts are folded in from their own audit reports, not re-derived here. The helpers copied from batch 2 (Cognee chunking helpers, Crawl4AI normalize_url) were already completed and tested (24/24) before this sweep, and Eric directed "wait for the full sweep first" before any further copying — so the next copy is picked from the ranked lists above, when he directs it.
- The v0.3.2 review work in `~/workspace/v032-review/` stays local and is untouched by this sweep. This report itself is assembly work, not review work.
