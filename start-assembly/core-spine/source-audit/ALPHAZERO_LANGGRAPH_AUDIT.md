# Source-code audit for borrowing — AlphaZero.jl and LangGraph

Date: 2026-11-11. Audit only. No code was copied from either repo into
START, the v0.3.2 review copy, or the core-spine assembly, and nothing
was pushed to GitHub. Local sources audited: the AlphaZero.jl clone at
`~/workspace/start-assembly/core-spine/alphazero/` (git HEAD
177a6eb04aedeff7542bbaeeaf2c3c6da221aa96, version 0.5.6) and the
installed LangGraph wheel at
`~/workspace/start-assembly/core-spine/.venv/lib/python3.12/site-packages/langgraph/`
(version 1.2.20). Licences were verified against the upstream repos
via the GitHub connector and match the local copies.

Rule (Eric, 2026-11-04/05, binding): check the code AND its licensing
first; if code cannot be directly copied, write original code producing
similar effects instead.

## Verdicts

| Repo | Licence (verified) | Source size (counted) | Verdict |
|---|---|---|---|
| AlphaZero.jl (`jonathan-laurent/AlphaZero.jl`) | MIT, Copyright (c) 2019 Jonathan Laurent | 9,370 lines of Julia across 70 `.jl` files (src 6,855; games 2,037; test 55; scripts/profile ~423) | **Mixed — borrow the MCTS search and the game interface; rewrite the training loop for planning; keep the Flux/CUDA network stack as a dependency, not copied code** |
| LangGraph (`langchain-ai/langgraph`) | MIT, Copyright (c) 2024 LangChain, Inc. | 38,801 lines of Python across 103 `.py` files in the `langgraph` package (incl. checkpoint 2,975 and prebuilt 3,710); `langgraph_sdk` is a separate 19,602-line client package; the `langchain-core` dependency is another 70,894 lines | **Dependency only — use the package as a dependency; do not copy the Pregel engine into START** |

## 1. Licences (verified from each repo's own LICENSE file)

Both repos are MIT-licensed. The MIT terms, in brief (not the full
text): "Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation files
(the 'Software'), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software,"
subject to one condition: "The above copyright notice and this
permission notice shall be included in all copies or substantial
portions of the Software." Both are provided "AS IS", without warranty.

- **AlphaZero.jl:** MIT, Copyright (c) 2019 Jonathan Laurent.
  Verified: local `LICENSE` in the clone, and upstream
  `jonathan-laurent/AlphaZero.jl` LICENSE (SHA f04e3a70…), identical.
  Copying is permitted, including into a differently-licensed project,
  provided the copyright + permission notice is included with the
  copied code. No copyleft, no same-licence requirement.
- **LangGraph:** MIT, Copyright (c) 2024 LangChain, Inc. Verified:
  local `langgraph-1.2.20.dist-info/licenses/LICENSE`, and upstream
  `langchain-ai/langgraph` `libs/langgraph/LICENSE` (SHA fc0602fe…),
  identical. Same MIT terms. The sibling packages
  `langgraph-checkpoint` 4.3.1 and `langgraph-prebuilt` 1.1.1 are also
  MIT, and `langgraph-sdk` 0.4.14 is MIT.

Dependency licences that would travel with borrowed code:

- **AlphaZero.jl** (from its `Project.toml`, 25 direct deps): Flux
  (MIT), CUDA.jl (MIT), cuDNN (MIT), Distributions, DataStructures,
  StaticArrays, Plots — all MIT/BSD-style in the Julia ecosystem.
  Copying AlphaZero's *own* code does not copy these libraries, but
  copying its training loop (`src/training.jl`, `src/learning.jl`,
  `src/networks/flux.jl`) only works if Flux/CUDA are also present,
  so the borrowed unit would drag in a ~200-package dependency tree
  (the local `alphazero/` env precompiled 201 dependencies in 740 s).
  Knet is a weak dependency (alternative backend, 177 lines).
- **LangGraph** (from its wheel metadata): `langchain-core<2,>=1.4.7`
  (MIT, 70,894 lines installed), `langgraph-checkpoint`,
  `langgraph-prebuilt`, `langgraph-sdk`, `pydantic>=2.7.4` (BSD-3),
  `xxhash>=3.5.0` (BSD-2). Copying the Pregel engine without
  `langchain-core` is not possible in practice: `pregel/main.py`
  imports `Runnable`, `RunnableConfig`, callbacks, and graph types
  from `langchain_core` throughout. The licence is permissive, but
  the *coupling* is the barrier, not the licence.

## 2. AlphaZero.jl — file inventory and how it works

Top-level layout: `src/` (library), `games/` (5 example games),
`test/` (3 files), `scripts/`, `docs/`, `Project.toml`,
`Manifest.toml`, `LICENSE`, `README.md`, `CITATION.bib`.

Most important files for START (line counts counted, not guessed):

| File | Lines | What it does |
|---|---|---|
| `src/mcts.jl` | 326 | Generic MCTS: UCT selection, Dirichlet-noise exploration, rollouts, policy from visit counts. Works with any `GameInterface` game and any oracle `(P, V)`. |
| `src/game.jl` | 337 | The game interface: `AbstractGameSpec` / `AbstractGameEnv` and the functions a domain must implement (`init`, `available_actions`, `play!`, `white_reward`, `game_terminated`, `vectorize_state`, `actions_mask`, `symmetries`, …). |
| `src/training.jl` | 360 | The training loop: `Env`, self-play, learning steps, arena pit (`pit_networks`, `compare_networks`), checkpointing. |
| `src/learning.jl` | 216 | `Trainer`: converts self-play samples to batches, loss (policy + value), gradient updates. |
| `src/networks/network.jl` | 330 | Abstract network interface: `forward`, `evaluate`, `train!`, optimisers (Adam, CyclicNesterov), CPU/GPU transfer. |
| `src/networks/flux.jl` | 146 | Flux backend for the network interface. |
| `src/networks/architectures/resnet.jl` | 103 | ResNet-style network used by the examples. |
| `src/memory.jl` | 130 | `MemoryBuffer`: circular buffer of `TrainingSample`s (state, MCTS policy π, discounted reward z, moves remaining t). |
| `src/params.jl` | 384 | All hyperparameters: MCTS (`cpuct`, `num_iters_per_turn`, temperature schedule, Dirichlet ε/α), simulation, network, arena. |
| `src/play.jl` | 379 | Playing a trained network against humans/other agents, with MCTS. |
| `games/connect-four/game.jl` | 335 | ConnectFour as a `GameInterface` implementation — the best worked example of the interface. |
| `src/simulations.jl` | 306 | Parallel self-play simulations across workers/processes. |
| `src/minmax.jl` | 116 | Plain minimax player, used as a baseline and in tests. |

How it actually works, in our own words: AlphaZero.jl is a loop of
three stages. (1) **Self-play:** the current neural network plays
games against itself; at each turn, MCTS runs `num_iters_per_turn`
simulations, guided by the network's prior policy `P` and value `V`,
using UCT scores with `cpuct` exploration and Dirichlet noise at the
root, and the move is sampled from the visit-count distribution
(π ∝ n^(1/τ)). (2) **Learning:** the positions, MCTS policies, and
final game outcomes are stored in the memory buffer, and the network
is trained to predict both the MCTS policy and the game outcome.
(3) **Arena:** the new network plays the previous best network, and
only replaces it if it wins. The generic part is the MCTS + oracle
interface: an "oracle" is just a function `state -> (P, V)`, so the
search does not care whether the oracle is a neural network, a
rollout, or a hand-written heuristic (`RolloutOracle`,
`RandomOracle` are in `src/mcts.jl`).

What is board-game-specific vs general: the *interface* is general
(state, actions, terminal, reward), but the *semantics* are
two-player, zero-sum, and win/loss: rewards are expressed "from the
point of view of the player called white", black minimises the reward,
and the value head estimates a win probability. A planning domain
(e.g. choosing crop allocations) is not a two-player zero-sum game:
there is no opponent, no win/loss, and the objective is a
multi-criterion plan (shortage, water, land) under constraints, not a
scalar game outcome. The ConnectFour example (7×6 board, 4-in-a-row)
is the cleanest illustration of the interface, but it is also the
most board-specific code in the repo.

Already used by the spine: ConnectFour smoke 9/9 PASS, CPU only, no
training (`alphazero/logs/smoke-alphazero.log`); the full env is in
`alphazero/` with its own `Project.toml`/`Manifest.toml`.

## 3. LangGraph — file inventory and how it works

The installed wheel is the `langgraph` package only; the upstream
repo is a monorepo (`libs/langgraph`, `libs/checkpoint`,
`libs/prebuilt`, `libs/sdk`). Most important files for START:

| File | Lines | What it does |
|---|---|---|
| `pregel/main.py` | 4,557 | The Pregel engine: `Pregel` / `CompiledStateGraph`, `invoke`/`stream`, task scheduling, retries, interrupts, human-in-the-loop hooks. |
| `pregel/_loop.py` | 2,202 | The step loop: supersteps, pending writes, checkpointing per step. |
| `pregel/_algo.py` | 1,465 | Task preparation: which nodes run, in what order, with what input. |
| `pregel/_runner.py` | 948 | Runs tasks concurrently (threads/async). |
| `pregel/_retry.py` | 874 | Retry policies for failing nodes. |
| `graph/state.py` | 1,978 | `StateGraph`: defining nodes/edges, state schema, reducers, `compile()`. |
| `graph/_branch.py` | 225 | Conditional edges (routing). |
| `checkpoint/base/__init__.py` | 889 | `BaseCheckpointSaver`, `Checkpoint`/`CheckpointTuple` types, `put`/`get`/`list`, serde. |
| `checkpoint/memory/__init__.py` | — | `InMemorySaver`: in-memory checkpoint store (part of the 2,975-line `checkpoint/` subpackage). |
| `channels/*.py` | ~1,300 total | State channels: `LastValue`, `Topic`, `BinaryOperatorAggregate`, `EphemeralValue`, barriers. |
| `prebuilt/chat_agent_executor.py` | 1,015 | The prebuilt ReAct-style chat agent (`create_react_agent`). |
| `prebuilt/tool_node.py` | 2,064 | `ToolNode`: executes tool calls from an LLM. |
| `prebuilt/interrupt.py` | — | `HumanInterrupt` / `HumanResponse`: human-in-the-loop interrupts. |
| `store/base/` + `store/memory/` | — | Long-term memory store (separate from per-thread checkpoints). |

How it actually works, in our own words: LangGraph implements the
Pregel (bulk-synchronous-parallel) model for stateful graphs. A
`StateGraph` is nodes (functions) connected by edges (including
conditional edges). State lives in *channels* — named, typed slots
with reducers that say how concurrent node writes merge
(`LastValue` overwrites, `Topic` appends, `BinaryOperatorAggregate`
folds). Execution proceeds in *supersteps*: all runnable nodes run,
their writes are collected, channels update, a checkpoint is saved,
and the next superstep begins. `invoke()` runs to completion;
`stream()` yields per-step events. Checkpoints make a run resumable
and replayable, and `interrupt()` pauses a run for human input.
Everything is async-capable and retry-aware.

What is LLM-specific vs general orchestration: the *engine* (Pregel,
channels, checkpoints) is general — it does not know about LLMs.
The *surface* is LLM-shaped: `StateGraph(dict)` accepts any nodes
(START's adapter already uses plain Python functions for
plan/verify/report), but the prebuilt layer (`create_react_agent`,
`ToolNode`, message state with `add_messages`) assumes chat models,
tool calling, and `BaseMessage` objects, and the whole package is
built on `langchain_core`'s `Runnable`/`RunnableConfig` plumbing.
START's current use — a 3-node `StateGraph(dict)` with a
`plan -> verify -> report` chain, verified by the spine tests — uses
only the general engine, none of the LLM surface.

Already used by the spine: `adapters/orchestration.py` (124 lines)
builds the real `StateGraph` when langgraph is installed, with a
plain-Python `run_pipeline()` that must agree with it; tests prove
verification cannot be bypassed and `needs_human_decision` is always
True.

## 4. Borrowable vs dependency vs rewrite

| Repo | Piece | Recommendation | Reason |
|---|---|---|---|
| AlphaZero.jl | MCTS search (`src/mcts.jl`, 326 lines) | **Copy** | MIT allows it with the notice; small, self-contained, oracle-agnostic — the most directly reusable search code in either repo. |
| AlphaZero.jl | Game interface (`src/game.jl`, 337 lines) | **Copy** | MIT allows it; a clean, minimal contract (state/actions/reward/terminal) that a planning domain can implement without the rest of the package. |
| AlphaZero.jl | Memory buffer (`src/memory.jl`, 130 lines) | **Copy** | MIT allows it; a small circular buffer of (state, policy, outcome) samples, easily adapted to (plan, search policy, outcome). |
| AlphaZero.jl | Training loop (`src/training.jl`, 360 lines) | **Rewrite original** | Self-play + arena pit assumes two-player zero-sum games and a Flux network; a planning search needs a different loop (search over plans, verified against constraints), so write a START-native loop using the copied MCTS as its search core. |
| AlphaZero.jl | Network / Flux backend (`src/networks/`, ~1,000 lines) | **Dependency only** | Use Flux via Julia Pkg if a network is ever needed; copying the backend drags in CUDA/cuDNN and the 200-package tree, and START's neural work is MiniGPT in Python, not Flux in Julia. |
| AlphaZero.jl | ConnectFour example (`games/connect-four/game.jl`, 335 lines) | **Rewrite original** | It is an example, not a library; copy its *pattern* (how a domain implements the interface) into a START-native planning domain, not its board code. |
| AlphaZero.jl | Simulations / distributed self-play (`src/simulations.jl`, 306 lines) | **Dependency only** | Only useful if START runs distributed self-play; until then it is dead weight, and it is tied to the training loop above. |
| LangGraph | Pregel engine (`pregel/main.py`, `_loop.py`, `_algo.py`, ~8,200 lines) | **Dependency only** | MIT allows copying, but the engine is inseparable from `langchain-core` (70,894 lines) and pydantic; using the package as a dependency gives the same engine without vendoring 38,801 lines. |
| LangGraph | Checkpoint stores (`checkpoint/base`, `InMemorySaver`) | **Dependency only** | Use via the package when running LangGraph graphs; do not copy the 889-line base + serde into START — a START-native JSON checkpoint store for `PlanningResult` would be ~100 lines of original code and avoids LangGraph's pickle-format option. |
| LangGraph | Prebuilt agents (`prebuilt/chat_agent_executor.py`, `tool_node.py`) | **Dependency only** | Only useful if START adopts LLM chat agents; START's orchestration nodes are plain functions, so these are not needed and should not be copied. |
| LangGraph | LangChain coupling (`langchain-core` Runnable/Config) | **Dependency only** | It travels with the package; it cannot be copied piecemeal, and START does not need LangChain's Runnable abstraction. |
| LangGraph | StateGraph API (`graph/state.py`) | **Dependency only** | The API is the package's public surface; START already uses it as a dependency in `adapters/orchestration.py`. |
| LangGraph | The *idea* of channels / supersteps / interrupts | **Rewrite original** | The concepts (typed state slots with reducers, step checkpoints, human interrupt before report) are general and small; START's plain-Python `run_pipeline()` already reproduces the 3-node case in ~150 lines, and a START-native version keeps verification separate by construction rather than by graph wiring. |

## 5. Fit to START

**AlphaZero.jl — what START would gain:** a real, tested search
algorithm for exploring large combinatorial spaces, and a clean
domain interface for plugging a planning problem into a search. The
smallest useful borrowed unit is `mcts.jl` + `game.jl` (663 lines
together): with those, START could run MCTS over *plan* choices
(e.g. crop/land allocations) using a cheap oracle first (a rollout
or the LP solver's own objective as the value estimate), and only
later attach a learned oracle. What must be generalised or stripped:
the two-player zero-sum reward (white vs black, win probability)
must become a planning objective (shortage, water, land, cost) with
hard constraints; the arena/self-play training loop must be replaced
by a planning loop; GPU/CUDA and the Flux network are optional, not
required — MCTS with a rollout oracle runs on CPU. The value head
must never be treated as verification: a search result is a
*candidate* plan, and it still goes through the separate verify step
with `needs_human_decision = True`.

**LangGraph — what START would gain:** very little beyond what it
already has as a dependency. START already uses the real `StateGraph`
for plan → verify → report, and the spine tests prove the no-bypass
property. The engine's extra power (concurrent multi-actor graphs,
streaming, durable checkpoints, human interrupts) matters only when
START grows multi-agent crews — which the ChatGPT conversation
flagged for evaluation *after* the v0.3.2 audit, not now. The
smallest useful borrowed unit is therefore none: keep it a
dependency, and if START ever outgrows it, rewrite the *concepts*
(channels, supersteps, interrupts) as original code rather than
copying 8,200 lines of Pregel internals.

## 6. Risks

- **AlphaZero.jl is essentially single-author:** Jonathan Laurent,
  1,340 stars, 147 forks, 18 open issues; last commit in the clone
  2026-09-09, repo updated 2026-10-29. A single maintainer means
  upstream fixes are not guaranteed; copying the two small files
  (MCTS + interface) insulates START from that, depending on the
  whole package does not.
- **AlphaZero.jl is heavy as a dependency:** 25 direct deps, ~200
  in the resolved tree (Flux, CUDA, cuDNN, Plots); precompile took
  740 s in the local `alphazero/` env. Copying only `mcts.jl` +
  `game.jl` avoids almost all of that (they need only
  Distributions/DataStructures/StaticArrays).
- **AlphaZero.jl's game semantics do not fit planning as-is:**
  zero-sum, win/loss, white's reward. Borrowing it uncritically
  would smuggle a game-shaped objective into a planning system.
  The copied interface must be re-expressed in planning terms
  (states = partial plans, actions = allocations, reward = plan
  quality under constraints) and the search result must remain a
  candidate, never a verified plan.
- **LangGraph is heavy as a dependency:** 38,801 lines in the
  package, 70,894 more in `langchain-core`, plus pydantic and
  xxhash; the SDK alone is 19,602 lines. That is a large surface
  for a 3-node graph START could already run in ~150 lines of
  original code. The dependency is justified while START uses the
  real engine, but it should be re-evaluated if the graph stays
  small.
- **LangGraph is LLM-shaped by default:** its prebuilt agents,
  message state, and tool nodes assume chat models and external
  LLM providers. Nothing in the engine forces that, but adopting
  the prebuilt layer would pull START toward LLM-agent patterns
  and external services, away from the local-first, calculation-first
  design. The engine also offers a pickle checkpoint format option;
  START's wire format is JSON and should stay JSON — never load a
  pickle checkpoint from an untrusted source.
- **Guardrail conflicts:** neither repo knows START's guardrails.
  AlphaZero's self-play loop has no human-approval hook and no
  separation between proposing and verifying — a borrowed training
  loop must be wrapped so that search proposes and a separate
  verifier disposes, with `needs_human_decision` always True.
  LangGraph's `HumanInterrupt` exists and is compatible with that
  pattern, but it is opt-in: a graph that does not add an interrupt
  runs autonomously, so START's verify-before-report wiring must
  stay explicit (as it is in `adapters/orchestration.py`).
  Neither borrowing route touches self-edit or guardrail files,
  and neither should: both are audit-only here.

## 7. Notes on unverified claims

- LangGraph line counts are from the installed wheel (1.2.20), not
  from a clone of `langchain-ai/langgraph`; the upstream monorepo
  also contains TypeScript, docs, and server code that were not
  counted and are not part of the Python package.
- AlphaZero.jl line counts are from the local clone at HEAD 177a6eb
  (2026-09-09); the upstream repo was updated 2026-10-29, so a
  newer commit may differ slightly. The licence text was verified
  identical upstream.
- The claim that copying `mcts.jl` + `game.jl` needs only
  Distributions/DataStructures/StaticArrays is by reading their
  imports, not by running a stripped-down copy — no such copy was
  made in this audit, per the no-copy rule.
- Dependency licence statements (Flux/CUDA/cuDNN MIT, pydantic
  BSD-3, xxhash BSD-2) are from the packages' own metadata as
  installed; they were not each verified against upstream in this
  audit.
