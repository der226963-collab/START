# Status vocabulary + one invalid/empty-input mapping (ISSUE-07)

Date: 2026-11-11. Status: FIXED (documented + tested). Review copy only;
local, never pushed. This note is part of the v0.3.2 blocker work, not part
of the original v0.3.2 release text.

## The issue, in one paragraph

REVIEW.md ISSUE-07: Julia invented statuses outside the contract
(`:candidate_feasible`, `:candidate_infeasible`, `:incomplete`), and the
three languages disagreed on invalid input — Julia → `:incomplete`;
Rust → `UNKNOWN` + `INVALID_REQUEST`; Python `Constraint.evaluate` on
non-finite → `UNKNOWN`, while the Python adapter raises `ValueError`,
and `overall_from_checks([])` → `NOT_CHECKED`. The ISSUE-05 fix
(2026-11-11) already removed the old Julia paths: the review-copy Julia
emits only the exact five statuses as strings. This note closes ISSUE-07
by (a) verifying that claim live on every path, (b) settling the Rust
`NOT_CHECKED`/`INCOMPLETE` question against the code, and (c) fixing one
invalid/empty-input mapping across all three languages and pinning it in
tests in each.

## (a) Julia emits only the five statuses — verified live, 2026-11-11

Grep of `components/julia-planning/src/STARTPlanning.jl` for status
strings finds only `"PASS"`, `"FAIL"`, `"UNKNOWN"` from
`evaluate_constraint`, `"UNKNOWN"` from `evaluate_constraint_request`,
and all five from `overall_from_checks`. The old Symbols survive only
as history in the module docstring (describing what was removed) and in
one test comment — no live path emits them. Every path below was driven
live (probe, 2026-11-11) and returns a status in
`{"PASS", "FAIL", "UNKNOWN", "NOT_CHECKED", "INCOMPLETE"}`:

- Non-finite / missing / wrong-typed value (`NaN`, `±Inf`, `nothing`,
  `true`, `"5"`) → `UNKNOWN` (`NON_FINITE`).
- Unknown value unit, unknown constraint unit, incompatible units
  (`5 L` vs `10 kg`) → `UNKNOWN` (`UNKNOWN_UNIT` / `INCOMPATIBLE_UNIT`).
- Missing `value_unit` while the constraint has a unit → `UNKNOWN`
  (`INVALID_REQUEST` — ISSUE-51 fix, 2026-11-11: the old
  `MISSING_UNIT` / `MISSING_BOUND` codes were not in the result
  schema's `reason_code` enum, so Julia now uses `INVALID_REQUEST`
  like Rust, with the distinct cause in `details`); missing bound,
  missing range bounds → `UNKNOWN` (`INVALID_REQUEST`).
- Empty / whitespace `constraint_id` → `UNKNOWN` (`INVALID_REQUEST`).
- Wire: missing fields, bad operator, empty / whitespace / non-string
  id, non-finite value/bound/tolerance, negative tolerance, string
  value, empty units, unknown units, missing bound, missing / inverted
  / non-finite range bounds, malformed version → `UNKNOWN`
  (`INVALID_REQUEST` / `NON_FINITE` / `UNKNOWN_UNIT`); major version
  `2.0.0` → `UNKNOWN` (`UNSUPPORTED_MAJOR_VERSION`).
- `overall_from_checks([])` → `NOT_CHECKED`; unrecognised status →
  `UNKNOWN`, never `PASS`.

Pinned in `components/julia-planning/test/runtests.jl`, testset
"ISSUE-07: every emitted status is in the exact five-status vocabulary",
which collects every status produced and asserts membership in
`CHECK_STATUSES`.

## (b) Rust NOT_CHECKED / INCOMPLETE — the finding, checked in code

`evaluate_constraint` in `components/rust-kernels/src/lib.rs` can only
ever return `Pass`, `Fail` or `Unknown`: every early return keeps the
initial `Unknown` and the only success path sets `Pass` or `Fail`.
`NotChecked` and `Incomplete` are unreachable *there* — the same shape
as Python `Constraint.evaluate` and Julia `evaluate_constraint`, which
likewise return only `PASS` / `FAIL` / `UNKNOWN`. So the ISSUE-07
parenthetical ("those two enum variants are dead") is true of
`evaluate_constraint` only, and false of the crate:

- `NotChecked` IS produced, by `overall_from_checks(&[])` — the
  empty-check-list rule, in all three languages.
- `Incomplete` is never *produced* by any single-constraint evaluator
  in any language. It is produced upstream — in Python, by the
  domain/engine layer when a calculation was not completed
  (`domains/food/evaluation.py`, `engine/planning_engine.py`) — and
  *propagated* by `overall_from_checks`, which returns `Incomplete`
  when any input check is `Incomplete`. In Rust it is reachable today
  only as an input to aggregation, because Rust has no domain/planning
  layer — but the variant is not dead: `overall_from_checks` must
  accept it (a caller may aggregate statuses produced in another
  language), and it is part of the serialised wire vocabulary.
  (The `test-vectors.json` note saying Rust had no aggregation entry
  point was already corrected in the review copy: `overall_from_checks`
  exists in `lib.rs` with consuming tests.)

Removing either variant would be a breaking API change (wire format +
aggregation contract). Removal is OUT OF SCOPE; the decision is recorded
here and in the `CheckStatus` doc comment in `lib.rs`, and the reachable
paths are pinned by `issue07_overall_from_checks_reachable_paths` and
`issue07_evaluate_constraint_never_returns_not_checked_or_incomplete`
(which also asserts no serialised result ever contains
`NOT_CHECKED`/`INCOMPLETE` from `evaluate_constraint`).

## (c) The one mapping — decided 2026-11-11

Three layers. The same rule in all three languages; where the mechanism
differs, the rule is stated in outcome terms and the difference is
deliberate, with its reason.

### Layer 1 — evaluator: invalid input → UNKNOWN, never PASS, never raise

`Constraint.evaluate` (Python), `evaluate_constraint` (Rust),
`evaluate_constraint` (Julia). A check that cannot be performed returns
`UNKNOWN`: non-finite / missing / wrong-typed value; unknown or
incompatible units; missing `value_unit` when the constraint has a unit;
missing bound(s); empty / whitespace `constraint_id`. Valid inputs still
decide `PASS` / `FAIL`. The evaluator is total: it never throws, so
aggregation can always proceed. `UNKNOWN` / `INCOMPLETE` are never
converted to `PASS`.

### Layer 2 — wire / adapter boundary: malformed request → rejected with a reason

A malformed request is never evaluated and never yields `PASS`/`FAIL`.
The rejection mechanism differs by language, deliberately:

- Python: `validate_constraint_request` / `evaluate_constraint_request`
  raise `ValueError` (with the reason in the message; a major mismatch
  raises the distinct `"unsupported major schema version: <v>
  (supported major version 1)"`). The adapter is a validating function
  whose contract is to raise, pinned by existing tests
  (`tests/test_contracts_and_food.py`, `InteropContractTests`) — changing
  it to return `UNKNOWN` would be a breaking change to a pinned
  contract, and belongs with ISSUE-09's boundary-validator work, not
  here.
- Rust: `evaluate_constraint` returns an `UNKNOWN` result with
  `reason_code` `INVALID_REQUEST` (or `UNSUPPORTED_MAJOR_VERSION`);
  a request that cannot even deserialise (missing field, string/boolean/
  null value, unknown extra field under `deny_unknown_fields`) never
  reaches the evaluator — `start-kernel` maps the failure to the same
  `UNKNOWN` / `INVALID_REQUEST` result line.
- Julia: `evaluate_constraint_request` never throws on wire data and
  returns an `UNKNOWN` result with the same reason codes as Rust.

Same rule, different idiom: the reason is preserved in every case
(exception message, or `reason_code` + `details`), and nothing malformed
is ever evaluated.

### Layer 3 — aggregation: empty → NOT_CHECKED; precedence fixed

`overall_from_checks([])` → `NOT_CHECKED` in all three languages, never
`PASS`. Precedence, identical everywhere: `FAIL` > `INCOMPLETE` >
`UNKNOWN` > `NOT_CHECKED` > `PASS`; all-`PASS` passes; an unrecognised
status falls through to `UNKNOWN`, never `PASS`.

### Construction: fail-fast, before evaluation

Building a constraint/objective with a bad operator, a non-finite bound,
a negative tolerance, or inverted range bounds raises/throws in Python
(`ValueError`) and Julia (`ArgumentError`); Rust has no fallible
constructor (plain struct) and reports the same inputs as `UNKNOWN` at
evaluation. Same guarantee, different layer: a malformed constraint can
never be evaluated into a `PASS`/`FAIL`.

### Two fixes made to establish the mapping (2026-11-11)

Both were cases where a check that was never really performed returned
`PASS` — the ISSUE-12 smell — while the other languages returned
`UNKNOWN`:

1. **Empty constraint_id (Python).** `Constraint.evaluate` did not look
   at `constraint_id` at all, so `Constraint("", ..., bound=10,
   unit="kg").evaluate(5, "kg")` returned `PASS`, while Rust and Julia
   returned `UNKNOWN`. Fixed in `contracts/constraints.py`: an empty,
   whitespace-only or non-string `constraint_id` now returns `UNKNOWN`.
   The check is in `evaluate`, not in `__post_init__`: construction
   behaviour is unchanged, and construction-time rejection of empty ids
   stays open under ISSUE-12, where it can be decided with its full
   scope.
2. **Unit-less constraint + unknown supplied unit (Python and Julia).**
   When the constraint declared no unit, both ignored a supplied
   `value_unit` entirely, so `evaluate(5, "bucket")` returned `PASS` on
   the raw numbers; Rust rejects any unknown unit string
   (`UNKNOWN_UNIT`). Fixed in `contracts/constraints.py` and in Julia
   `evaluate_constraint`: a supplied `value_unit` must be a known
   registry unit (including non-empty / non-string checks) even when the
   constraint declares no unit, else `UNKNOWN`. A *known* `value_unit`
   on a unit-less constraint is still ignored (raw-number comparison) —
   there is no target unit to convert into — and Rust has no unit-less
   wire form at all (`bound_unit` is required and must be known).

### Deliberate remaining layer differences (not divergences to fix here)

- **Unknown constraint/bound unit:** Python raises `ValueError` at
  construction; Rust and Julia return `UNKNOWN` (`UNKNOWN_UNIT`) at
  evaluation. Same guarantee — never `PASS`/`FAIL` — different layer.
  Julia's choice (defer to evaluation) was settled by the ISSUE-05 fix
  and is not re-litigated here.
- **Unit-less constraints** exist in Python/Julia (raw-number comparison
  when no unit is supplied); Rust's wire shape has no unit-less form.
  Cross-language tests cover unit-ful constraints only.
- **Extra unknown fields** in a wire request: Rust rejects them
  (`deny_unknown_fields` → `UNKNOWN`/`INVALID_REQUEST`); Julia's
  request function ignores them. Python's adapter used to ignore them
  too — fixed by ISSUE-09 (2026-11-11): `validate_constraint_request`
  now rejects unknown fields (`additionalProperties: false` in the
  schema), so Python matches Rust here. Julia's ignoring of extra
  fields is unchanged.
- **Unknown units at the wire boundary:** Python's adapter now raises
  `ValueError` at validation (ISSUE-09, 2026-11-11 — unit-registry
  membership is enforced by the boundary validator); Rust and Julia
  still return `UNKNOWN` (`UNKNOWN_UNIT`) at evaluation. Same
  guarantee — never `PASS`/`FAIL` — different layer. The evaluator
  level is unchanged in all three languages: an unknown unit passed
  directly to an evaluator returns `UNKNOWN`.
- **Version handling** is ISSUE-10 territory, already decided
  (same-major accepted, major rejected with the distinct message); the
  wire rows in the matrix below only assert the already-decided
  behaviour, they do not change it.

## The cross-language test matrix

Same input → same status in every language, at each layer. Pinned in
`tests/test_issue07_status_mapping.py` (Python),
`components/rust-kernels/src/lib.rs` (`issue07_*` tests) and
`components/julia-planning/test/runtests.jl` (ISSUE-07 testset).
`n/a` means the input is inexpressible at that layer in that language
(e.g. Rust's `value` is `f64`, so JSON `null` cannot reach
`evaluate_constraint` — it fails deserialisation instead; Python's
unknown bound unit cannot reach `evaluate` — construction raises first).

| Input | Python evaluator | Rust evaluator | Julia evaluator |
|---|---|---|---|
| `NaN` / `±Inf` value | UNKNOWN | UNKNOWN / NON_FINITE | UNKNOWN / NON_FINITE |
| `None` / `nothing` value | UNKNOWN | n/a (NaN is the stand-in) | UNKNOWN / NON_FINITE |
| boolean / string value | UNKNOWN | n/a (deserialisation fails) | UNKNOWN / NON_FINITE |
| unknown `value_unit` ("bucket") | UNKNOWN | UNKNOWN / UNKNOWN_UNIT | UNKNOWN / UNKNOWN_UNIT |
| unknown bound unit ("bucket") | raises at construction | UNKNOWN / UNKNOWN_UNIT | UNKNOWN / UNKNOWN_UNIT |
| incompatible units (L vs kg) | UNKNOWN | UNKNOWN / INCOMPATIBLE_UNIT | UNKNOWN / INCOMPATIBLE_UNIT |
| missing `value_unit`, unit set | UNKNOWN | n/a (empty → UNKNOWN_UNIT) | UNKNOWN / INVALID_REQUEST |
| missing bound (non-range) | UNKNOWN | UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |
| range, missing bound(s) | UNKNOWN | UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |
| range, inverted bounds | raises at construction | UNKNOWN / INVALID_REQUEST | throws at construction |
| bad operator ("!=") | raises at construction | UNKNOWN / INVALID_REQUEST | throws at construction |
| empty / whitespace `constraint_id` | UNKNOWN | UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |
| unit-less + unknown `value_unit` | UNKNOWN | UNKNOWN / UNKNOWN_UNIT | UNKNOWN / UNKNOWN_UNIT |
| unit-less, no `value_unit` | PASS (raw compare) | n/a (no unit-less form) | PASS (raw compare) |
| valid `8 L <= 10 L` / `12 L <= 10 L` | PASS / FAIL | PASS / FAIL | PASS / FAIL |

| Malformed wire input | Python adapter | Rust wire | Julia wire |
|---|---|---|---|
| missing field | raises ValueError | deserialisation fails → UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |
| non-finite value/bound, NaN tolerance | raises ValueError | UNKNOWN / NON_FINITE (library API; JSON is finite by construction) | UNKNOWN / NON_FINITE (value/bound) or INVALID_REQUEST (tolerance) |
| negative / −inf tolerance | raises ValueError | UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |
| unknown `value_unit` | raises ValueError (ISSUE-09: boundary validator enforces registry membership; evaluator still returns UNKNOWN when called directly) | UNKNOWN / UNKNOWN_UNIT | UNKNOWN / UNKNOWN_UNIT |
| unknown bound unit | raises ValueError (validation, since ISSUE-09; previously at construction) | UNKNOWN / UNKNOWN_UNIT | UNKNOWN / UNKNOWN_UNIT |
| version `2.0.0` | raises ValueError, distinct message | UNKNOWN / UNSUPPORTED_MAJOR_VERSION | UNKNOWN / UNSUPPORTED_MAJOR_VERSION |
| version `1.0` (malformed) | raises ValueError | UNKNOWN / INVALID_REQUEST | UNKNOWN / INVALID_REQUEST |

| Aggregation input | Python | Rust | Julia |
|---|---|---|---|
| `[]` (empty) | NOT_CHECKED | NotChecked | "NOT_CHECKED" |
| `[UNKNOWN]` | UNKNOWN | Unknown | "UNKNOWN" |
| `[PASS, FAIL]` | FAIL | Fail | "FAIL" |
| `[INCOMPLETE, UNKNOWN]` | INCOMPLETE | Incomplete | "INCOMPLETE" |
| `[UNKNOWN, NOT_CHECKED]` | UNKNOWN | Unknown | "UNKNOWN" |
| `[NOT_CHECKED, PASS]` | NOT_CHECKED | NotChecked | "NOT_CHECKED" |
| `[PASS, PASS]` | PASS | Pass | "PASS" |

## ISSUE-12 addendum (2026-11-11) — Python construction strictness supersedes three pins above

ISSUE-12 decided the construction-time rejections this doc left open
("construction-time rejection of empty ids stays open under ISSUE-12").
Python-only; Rust and Julia were NOT changed by that worker, so the
matrix rows below now differ by language in mechanism, not in
guarantee (a malformed check is never PASS/FAIL):

- Empty/whitespace `constraint_id` (and empty `name`): Python now
  raises `ValueError` at construction; `evaluate()`'s UNKNOWN guard
  for an empty id remains only as defence for objects built without
  the constructor. Rust/Julia still return UNKNOWN at evaluation.
- Missing bound(s): Python now raises at construction for `<=`/`>=`/
  `==` without `bound` and for `range` without both bounds — EXCEPT
  an explicitly declared `boundless=True` constraint (bound must be
  `None`), which evaluates UNKNOWN by design. The only boundless
  cases in this tree are nitrogen in `contracts/plan_limits.py`
  (ISSUE-18: no stored boundary) and
  `default_food_constraints(None)`. Rust/Julia still return UNKNOWN.
- Unit-less constraint + a *known* supplied `value_unit`: Python
  `evaluate()` now raises `ValueError` instead of the raw-number
  PASS pinned above ("still ignored (raw-number comparison)"). A
  unit-less constraint may only be evaluated with no `value_unit`
  supplied; an unknown/empty/non-string `value_unit` still returns
  UNKNOWN. Julia still does the raw comparison; Rust has no
  unit-less wire form. The affected Python tests were updated
  deliberately with notes (`test_issue07_status_mapping.py`,
  `test_contracts_and_food.py`); see `tests/test_issue12_13.py`
  for the new pins.

## Verification (2026-11-11)

- Python: `python -m unittest discover -s tests` — 122 tests, 0 failures
  (101 baseline + 21 new in `tests/test_issue07_status_mapping.py`).
- Rust: `cargo test` — 34 tests, 0 failures (30 baseline + 4 new
  `issue07_*` tests); `cargo build` refreshed so the binary-driven
  Python tests run instead of skipping.
- Julia: `julia --project=. test/runtests.jl` — 216 tests, 0 failures
  (138 baseline + 78 new in the ISSUE-07 testset).
- No change to `interop/test-vectors.json`, the wire format (JSON), or
  any core-spine / v0.3.1 / guardrail file. No new dependencies.
