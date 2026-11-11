# Provenance — planning-search module

Date: 2026-11-11. Assembled locally; pushed to der226963-collab/START under `start-assembly/core-spine/` on 2026-11-11 (commit 674f6abc).

## Source

- Repository: **jonathan-laurent/AlphaZero.jl**
- Version: **0.5.6**, git HEAD **177a6eb04aedeff7542bbaeeaf2c3c6da221aa96**
- Local clone audited and copied from:
  `~/workspace/start-assembly/core-spine/alphazero/`
- Licence: **MIT, Copyright (c) 2019 Jonathan Laurent** — verified
  identical in the local clone's LICENSE and upstream. The full MIT
  copyright + permission notice is included at the top of EACH copied
  file (mcts.jl, game.jl), as the licence requires for copies or
  substantial portions. No copyleft, no same-licence requirement.

## Files copied (2)

| File in this folder | Original | Lines (original) | Status |
|---|---|---|---|
| `mcts.jl` | `src/mcts.jl` | 326 | Copied, adapted (see below) |
| `game.jl` | `src/game.jl` | 337 | Copied, adapted (see below) |

## Files NOT copied

- `src/training.jl` (360 lines) — self-play + arena pit assumes
  two-player zero-sum games and a Flux network; a planning search
  needs a different loop. Marked REWRITE ORIGINAL in the audit.
- `src/networks/` (~1,000 lines, Flux/CUDA backend) — DEPENDENCY
  ONLY in the audit; START's neural work is MiniGPT in Python.
- `src/memory.jl` (130 lines) — marked COPY in the audit, but not
  needed for this module (no training loop here); not copied.
- `games/connect-four/game.jl` (335 lines) — REWRITE ORIGINAL in
  the audit; only its pattern (how a domain implements the
  interface) was learned from. `planning_domain.jl` is original
  START code.
- Everything else in AlphaZero.jl (play.jl, simulations.jl,
  learning.jl, params.jl, UI, etc.) — not copied.

## Changes made to the copied files

### mcts.jl
- `using ..AlphaZero: GI, Util` →
  `using ..PlanningSearch: GI, apply_temperature` (standalone: no
  AlphaZero.jl import).
- `Util.apply_temperature` → `apply_temperature`, where
  `apply_temperature` is a small START-written helper in
  `PlanningSearch.jl` (written from the definition π^(1/τ),
  normalised; τ=0 gives a one-hot argmax). It is NOT copied from
  AlphaZero.jl's `util.jl`.
- Oracle docstring: value V is plan quality under constraints
  (0..1), NOT a win probability for "white".
- Comment "assuming the white player is to play" → "assuming the
  planner is to act (single-planner: no opponent, no player switch)".
- Local names in `rollout!` / `RolloutOracle` / `run_simulation!`:
  `wp` → `planner_acting`, `wr` → `step_reward` / `total_reward`.
  The `GI.white_playing` / `GI.white_reward` calls are kept — they
  are the copied interface names — with a mapping note in
  `run_simulation!` explaining that the q-sign flip never triggers
  in a planning domain (planner_acting is always true).
- Docstrings reworded from game/win language to planning language.
- The MCTS algorithm itself is unchanged: UCT selection,
  Dirichlet-noise exploration, rollouts, policy from visit counts.

### game.jl
- Module renamed `GameInterface` → `PlanningGameInterface`.
- `using ..AlphaZero: Util` removed (Util was not used in this file).
- Top docstring and the `white_playing` / `white_reward` docstrings
  re-expressed in planning terms (see the mapping note at the top
  of the file).
- `heuristic_value` docstring: "not needed by AlphaZero" →
  "not needed by the MCTS search".
- Planning aliases added at the end: `plan_reward`,
  `planner_acting`, `plan_terminated`. The original names are kept
  because the copied MCTS code calls them.
- The interface contract itself (functions a domain must implement)
  is unchanged.

## Term mapping (planning ↔ original game terms)

| Planning term (use in new START code) | Original term (kept in the copied code) |
|---|---|
| planner (single, no opponent) | "white" (the player) |
| plan_reward | white_reward |
| planner_acting (always true) | white_playing |
| plan_terminated | game_terminated |
| partial plan | state |
| allocation (hectares per crop) | action |
| plan quality under constraints, delivered / total demand | value V / win probability |
| candidate plan | game outcome |

## Dependencies

The copied files need only **Distributions** (Dirichlet noise in
MCTS). Checked 2026-11-11: neither copied file imports
DataStructures or StaticArrays (the audit's claim was checked
against the actual imports and is narrower in fact).
Distributions 0.25.134 was added as a direct dependency of the
canonical env (`julia-current/Project.toml`); it was already in
the Manifest as a transitive dependency, and `Pkg.resolve()`
confirmed the resolved set is unchanged (Agents 7.1.0,
ModelingToolkit 11.46.1, Symbolics 7.48.0, Turing 0.49.0,
DifferentialEquations 8.1.1, JuMP 1.32.1, HiGHS 1.26.1).

## Original START code in this folder

- `PlanningSearch.jl` — module wrapper, apply_temperature helper.
- `planning_domain.jl` — FoodPlanSpec / FoodPlanEnv, the synthetic
  1-site 2-crop domain, run_search, PlanningCandidate.
- `verify.jl` — evaluate_constraint / overall_status (mirroring
  spine.jl) and verify_candidate; the separate verify step.
  Stays loadable on Distributions alone; the LP wiring is NOT in
  this file (see verify_lp.jl below).
- `verify_lp.jl` — the second, independent JuMP+HiGHS LP
  cross-check (`verify_candidate_with_lp`, `lp_cross_check`,
  `solve_food_lp_from_spec`). NOT included by PlanningSearch.jl:
  it loads JuMP+HiGHS, so it lives in its own file plus the
  separate runner `run_verify_lp.jl` (split-stage pattern, as
  with spine_lp.jl / spine_ode.jl). The LP is solved from the
  spec alone in two stages (minimise shortage, then minimise
  production); the candidate and the search never influence it.
  Combined verdict PASS only if both checks pass; solver failure
  is UNKNOWN, never PASS; verified still requires PASS + human
  approval.
- `test/runtests.jl` — tests (see that file for the counts).
- `test/verify_lp.jl` — LP cross-check tests, a standalone script
  (loads JuMP+HiGHS), NOT included from `test/runtests.jl`, so
  the standalone tests stay JuMP-free.
- `training_loop.jl` — the planning training loop, ORIGINAL
  START code (see "Training loop" below). Included by
  `PlanningSearch.jl`; it takes the verify function as a
  parameter, so it stays loadable on Distributions alone.
  `test/training_loop.jl` — standalone tests (constraint
  verify only). `test/training_loop_lp.jl` — LP-split tests
  (combined verify). Runner `run_training_loop.jl`.

## Guardrails

- A search result is a CANDIDATE only (`PlanningCandidate.verified`
  is always `false` at creation, `status` is always `"CANDIDATE"`).
  It must go through `verify_candidate` and then a human approval
  (`verified_status` is true only for verdict PASS + human approval)
  before it can be called a plan. The search never verifies itself.
- Every result carries `needs_human_decision = true`.
- No self-edit or guardrail files were touched.

## Verified results (2026-11-11, Julia 1.13.3, canonical env)

- Tests: `test/runtests.jl` — 75/75 PASS, 0 failed (MIT notice 6,
  no-AlphaZero-import 15, interface contract 14, reward semantics 6,
  MCTS optimum 15, policy-before-explore 1, UNKNOWN/never-PASS 8,
  candidate-only 10).
- Default search `run_search()` (nsims=1000, visit-count policy,
  seed 1234): wheat 50 ha, potato 20 ha, delivered 600.0 t,
  shortage 50.0 t — the known optimum. Same result at nsims=1000
  on seeds 7, 42, 99, 2024; at nsims=2000 on all five seeds; and
  with `:mean_q` selection at nsims=500 on all five seeds.
- At nsims=500 the visit-count policy lags the Q-values (seed 1234:
  wheat 60 ha / potato 10 ha, delivered 440 t, while wheat 50 ha had
  mean Q 0.86 vs 0.65). Default is therefore nsims=1000.
- LP regression after this work: `spine_lp.jl` 15/15 PASS.

## LP cross-check (2026-11-11, Julia 1.13.3, canonical env)

- Tests: `test/verify_lp.jl` — 53/53 PASS, 0 failed (LP optimum
  from spec 8, good candidate passes both 10, suboptimal-but-
  feasible passes both 5, over-water fails both 7, better-than-
  optimum fails LP check 9, infeasible spec UNKNOWN 7, non-finite
  UNKNOWN 3, candidate-alone not verified 4).
- Runner `run_verify_lp.jl` → VERIFY_LP RESULT: PASS (MCTS
  candidate 600/50 t, constraint PASS, LP PASS, combined PASS).
- The LP optimum from the spec alone: delivered 600.0 t, shortage
  50.0 t, production 600.0 t, land 70.0 ha, water 100,000.0 m³.
- The LP check catches what the constraint verify alone misses:
  a candidate claiming delivered 650 t / shortage 0 t passes the
  constraint verify (its arithmetic is consistent) and fails the
  LP cross-check; an over-water candidate (112,000 m³) fails both.
  A feasible but suboptimal candidate (delivered 400 t, shortage
  250 t) passes both — verification is feasibility, not optimality.
  An infeasible spec (land budget −1 ha) gives UNKNOWN, never PASS.
- Full suite after this work: Python 35/35, Rust 9/9, Julia
  157/157 — 201 passed, 0 failed. Combined `spine.jl` 16/16 PASS,
  `spine_lp.jl` 15/15 PASS, no regression.

## Training loop, rewritten for planning (2026-11-11, Julia 1.13.3, canonical env)

- `training_loop.jl` is ORIGINAL START code. It replaces
  AlphaZero.jl `src/training.jl` (360 lines, audit verdict
  REWRITE ORIGINAL): that file was read to understand the
  shape being replaced, and NO code was copied from it, nor
  from `src/learning.jl`, `src/simulations.jl`, or
  `src/networks/`. There is no self-play, no opponent, no
  win/loss, and no network library — the fitted model is ridge
  least squares (LinearAlgebra, stdlib) over eight
  spec-normalised plan features. A test checks the file's
  code lines (comments excluded) for the game-loop
  identifiers (`self_play`, `self-play`, `arena`,
  `pit_networks`, `compare_networks`, `simulate_distributed`,
  `Flux`, `Knet`, `MemoryBuffer`, `Trainer(`, `AlphaZero`) —
  none present.
- Loop: per iteration, one candidate per varied training spec
  (demand / land / water perturbed deterministically by seed,
  never a real region), verified with the verify function it
  is given; ONLY verify+LP PASS candidates become training
  samples. `VerifiedMemory` (bounded, oldest-first) holds
  verified samples only; `insert_verified!` throws for an
  unverified sample or a non-finite outcome.
- Replacement rule (replaces the arena pit): a new learned
  oracle replaces the current one only if, on held-out specs
  never used in its training, its MCTS candidates reach a
  verified-PASS rate at least as high as the rollout oracle's,
  with a mean shortage no worse. Training never marks a plan
  verified; a learned-oracle candidate still needs a PASS
  verdict plus human approval.
- Tests: `test/training_loop.jl` — 86/86 PASS, 0 failed
  (varied specs 9, verified memory 8, features 5, value model
  7, learned oracle 6, search with oracle 13, loop keeps
  verified samples 18, rejected never enter memory 3, trained
  oracle still candidate-only 6, no game-loop code 11).
  `test/training_loop_lp.jl` — 25/25 PASS, 0 failed (full
  loop with LP cross-check 15, held-out PASS rate not
  degraded 2, learned-oracle candidate still needs verify +
  approval 8).
- Runner `run_training_loop.jl` (3 iterations, 4 training +
  4 held-out specs, nsims=200, combined verify) →
  TRAINING_LOOP RESULT: PASS. 12 generated, 12 verified-kept,
  0 rejected, 24 samples in memory. Final iteration held-out:
  rollout PASS rate 1.0, learned PASS rate 1.0, rollout mean
  shortage 167.5 t, learned mean shortage 117.5 t — the
  learned oracle improves mean shortage by 50 t with PASS
  rates tied, so it replaced the current oracle in all three
  iterations. Fitted weights: [0.026, 0.0, 0.011, 0.018,
  -0.01, 0.026, 0.04, 0.0, 0.707] (bias dominates).
- Known limitation (measured, not hidden): the linear model
  cannot express interactions such as water committed to wheat
  while potato still needs water, so it ranks wheat 60 ha above
  wheat 50 ha as a first step on the base spec, even though
  50 ha is the better plan. That ranking is deliberately NOT
  asserted in the tests; the held-out comparison is what
  judges whether the oracle helps, and a worse oracle is
  never adopted.
- Full suite after this work: Python 35/35, Rust 9/9, Julia
  268/268 — 312 passed, 0 failed. Combined `spine.jl` 16/16
  PASS, `spine_lp.jl` 15/15 PASS, no regression.
