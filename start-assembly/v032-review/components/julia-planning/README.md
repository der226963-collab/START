# STARTPlanning (Julia) — planning/constraint contract component

Faithful Julia implementation of the START planning/constraint contract
(REVIEW.md ISSUE-05 fix, 2026-11-11). See the module docstring in
`src/STARTPlanning.jl` for the full design record.

## What it implements

- `Constraint` — `constraint_id`, operator (`<=`, `>=`, `==` with
  tolerance, `range` with `bound_low`/`bound_high`), bound(s), unit,
  tolerance — mirroring Python `contracts/constraints.py`.
- `Objective` — struct + validation mirroring Python's `Objective`.
  Python's `Objective` defines no evaluation and no objective value,
  so neither does this module; an objective is a declared aim, not a
  computed score. Constraint evaluation returns the normalized value
  in `ConstraintResult`.
- Unit registry — exactly the 24 keys of Python
  `contracts/units.py`, same dimensions/factors, with conversion.
  Unknown or incompatible units give UNKNOWN, never PASS.
- Statuses — exactly the five contract strings `PASS`, `FAIL`,
  `UNKNOWN`, `NOT_CHECKED`, `INCOMPLETE`.
- `overall_from_checks` — mirrors Python exactly (FAIL >
  INCOMPLETE > UNKNOWN > NOT_CHECKED > PASS; empty is NOT_CHECKED).
- Schema versions — same-major `1.x.y` accepted; a major mismatch is
  rejected with the exact distinct message
  `unsupported major schema version: <v> (supported major version 1)`;
  a malformed version gets the distinct `invalid schema version: <v>`.
- `evaluate_constraint_request` — evaluates one parsed-JSON wire
  request; never throws on wire data (UNKNOWN, never PASS).

## What was removed, and why

The previous version of this component (`PlanningInput` +
`evaluate_linear_balance`, slack = limits − coefficients) hard-coded
a `<=` reading, emitted non-vocabulary statuses, and reused `"1.0.0"`
for a different payload. Reproduced 2026-11-11 before removal: the
food domain's `>=` constraint (2800 vs 2500 kcal/capita/day) came out
`:candidate_infeasible`; 0.02 m³ vs 10 L came out
`:candidate_feasible` (correct: FAIL); 5 L vs 10 kg came out
`:candidate_feasible` (correct: UNKNOWN). No other code in the
review-copy tree used it, so it was removed rather than kept
alongside the new implementation.

## Tests

`julia --project=. test/runtests.jl` — 256 tests, including a
conformance test asserting the exact 24-key registry, an ISSUE-07
testset driving every invalid/empty-input path (native + wire +
aggregation) and asserting every emitted status is in the exact
five-status vocabulary, and a test that drives all 8 wire + 2
aggregation + 3 version cases from
`interop/test-vectors.json` and asserts agreement with the
Python/Rust verified values pinned in the file.

## Dependencies

JSON.jl 1.13.4 (added 2026-11-11 for parsing the shared test vectors;
same version as the core-spine canonical env). Pinned/other envs
untouched; this component is review-copy local only, never pushed.
