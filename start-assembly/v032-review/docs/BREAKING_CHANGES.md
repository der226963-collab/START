# Breaking changes vs v0.3.1 — aggregation of empty and unknown checks (ISSUE-02)

Date: 2026-11-11. Status: FIXED (documented + tested). Review copy only;
local, never pushed. This note is part of the v0.3.2 blocker work, not part
of the original v0.3.2 release text.

## The change, in one paragraph

v0.3.1 treated "nothing was checked" and "a check came back unknown" as
compatible with an overall pass. v0.3.2 reverses both: an empty check set
is `NOT_CHECKED`, and any `UNKNOWN` (or `INCOMPLETE`) check blocks an
overall pass. This is an **intentional breaking change, not continuity**.
v0.3.1's behaviour here was itself the bug v0.3.2 fixes: a plan that had
never been checked, or whose only check could not be evaluated, was
reported as passing.

## (i) The two rules, side by side

### v0.3.1 — `mini_ai/planning.py:308-359`, `check_plan_limits()`

```python
failed = [c for c in checks if c["status"] == "fail"]
return {"checks": checks, "passes_checked_limits": not failed, ...}
```

- `passes_checked_limits` is `not failed`: it is `True` whenever **no
  check failed**, regardless of how many checks ran or what they returned.
- Empty plan: no checks run, `failed` is empty, so the plan "passes".
- A check whose status is `"unknown"` is not a failure, so it is also
  compatible with a pass.

Reproduced live, read-only, 2026-11-11 (legacy function untouched):

| Call | Result |
|---|---|
| `check_plan_limits({})` | `{'checks': [], 'passes_checked_limits': True, 'failed_count': 0}` |
| `check_plan_limits({'nitrogen_fixation_tg_per_year': 165})` | one check, `{'limit': 'nitrogen_fixation_tg_per_year', 'proposed': 165, 'boundary': None, 'status': 'unknown', ...}`, `passes_checked_limits: True, failed_count: 0` |
| `check_plan_limits({'phosphorus_application_tg_per_year': 5.0, 'food_kcal_per_capita_per_day': 2600, 'planning_need_kcal_per_capita_per_day': 2500, 'paid_work_hours_per_week': 40})` | three checks, all `pass`, `passes_checked_limits: True` |

(The nitrogen key must be `nitrogen_fixation_tg_per_year`; the bare key
`nitrogen` matches no limit and silently produces zero checks — itself an
instance of the same "silence reads as pass" hazard.)

### v0.3.2 — `contracts/statuses.py:27-44`, `overall_from_checks()`

```python
def overall_from_checks(statuses):
    values = list(statuses)
    if not values: return CheckStatus.NOT_CHECKED
    if any FAIL:        return FAIL
    if any INCOMPLETE:  return INCOMPLETE
    if any UNKNOWN:     return UNKNOWN
    if any NOT_CHECKED: return NOT_CHECKED
    if all PASS:        return PASS
    return UNKNOWN
```

Precedence, highest first: **FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED >
all-PASS**. A plan passes only when at least one check ran and every check
is `PASS`. Empty → `NOT_CHECKED`; unknown-only → `UNKNOWN`; a single
`UNKNOWN` alongside passes → `UNKNOWN` (it dominates `PASS`); a single
`INCOMPLETE` dominates `UNKNOWN`.

The Rust kernel mirrors this exactly in
`components/rust-kernels/src/lib.rs:113-136`, `overall_from_checks()`
("UNKNOWN/INCOMPLETE are never converted to PASS"), and Julia's canonical
`overall_status` was aligned to the same rule in the 2026-11-11
test-vector work. The shared vectors are in
`interop/test-vectors.json`, `aggregation_cases` (`empty-checks`,
`unknown-only-checks`), conformance `must_agree`, with per-language
verified values dated 2026-11-11.

## (ii) Why this is breaking, and why it is deliberate

- Any caller that relied on `passes_checked_limits == True` (or on an
  empty/unknown result reading as a pass) will now get `NOT_CHECKED` or
  `UNKNOWN` instead, and must handle a non-pass outcome. That is the
  point: under v0.3.1 a plan with no applicable limits at all — or with
  its only limit unevaluable, as nitrogen is (no stored boundary, only the
  note "more than twice its boundary") — was indistinguishable from a plan
  that had passed every check. The label `"unknown"` survived in v0.3.1's
  output while its consequence was reversed: it looked cautious and acted
  as a pass.
- The fix keeps v0.3.2's safer rule. Nothing about the v0.3.1 *data* is
  changed by this: the nitrogen boundary is still unstored, and the
  legacy function itself is **unchanged** — see §(iv). The breaking
  change is in what "no failure" is allowed to mean.

## (iii) Migration note for callers

1. **Empty check sets — never treat `NOT_CHECKED` as a pass.**
   `overall_from_checks([]) == NOT_CHECKED` means "nothing was verified
   yet", not "nothing failed, so it is fine". If your code branches on
   "passes", add an explicit branch: `NOT_CHECKED` → do not proceed;
   find out why no checks ran (wrong plan keys? no applicable limits?
   evaluator not invoked?) and run them. Do not substitute
   `status != FAIL` for `status == PASS`; that reintroduces the v0.3.1
   bug in your own code.
2. **Unknown checks — resolve them, or treat the plan as unverified.**
   An `UNKNOWN` check means the evaluator could not decide: a missing or
   incompatible unit, a missing bound (nitrogen has no stored boundary),
   or non-finite input. Either supply what is missing (the correct unit,
   the bound, finite values) and re-evaluate, or treat the whole plan as
   unverified and do not act on it. Never map `UNKNOWN` (or `INCOMPLETE`)
   to a pass, a default, or a skipped check.
3. **A plan is verified only when the status is `PASS` *and* a human
   approves.** `PASS` means every check that ran passed; it is not a
   decision. Human approval is a separate, required step — a `PASS`
   without it is still not verified, and no `UNKNOWN`/`INCOMPLETE`/
   `NOT_CHECKED` result can ever become verified by approval alone.
   (Same rule as the typed planning-package draft: empty checks →
   `NOT_CHECKED` / indeterminate, never a pass.)
4. **If you still call v0.3.1 `check_plan_limits()` directly**, its
   empty-plan behaviour is unchanged (see §(iv)): `check_plan_limits({})`
   still returns `passes_checked_limits: True`. The breaking change
   applies to the v0.3.2 contract path (`overall_from_checks` and the
   cross-language kernels). Migrate callers to the typed/contract path;
   the opt-in typed wrapper in the planning-package draft
   (`blocker-work/planning-package/NOTE.md`, `check_plan_limits_typed`)
   converts legacy rows and applies the v0.3.2 rule without touching the
   legacy function.

## (iv) Exact references

| Side | File / function | Behaviour |
|---|---|---|
| v0.3.1 (before-state, unchanged) | `~/workspace/ai-starter/mini_ai/planning.py:308-359`, `check_plan_limits()` — `passes_checked_limits = not failed` | `{}` → `True`, `failed_count: 0`; nitrogen-only → single `"unknown"` check, still `True` |
| v0.3.2 Python | `contracts/statuses.py:27-44`, `overall_from_checks()` | `[]` → `NOT_CHECKED`; `[UNKNOWN]` → `UNKNOWN`; precedence FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED > all-PASS |
| v0.3.2 Rust | `components/rust-kernels/src/lib.rs:113-136`, `overall_from_checks()` | byte-for-byte mirror of the Python rule |
| v0.3.2 Julia | canonical `units.jl` / `overall_status`, aligned 2026-11-11 (test-vector work) | same rule; `5 L` vs `10 kg` → `UNKNOWN`, never a pass |
| Shared vectors | `interop/test-vectors.json`, `aggregation_cases` | `empty-checks`, `unknown-only-checks`, `must_agree` |

Tests asserting the rule (all verified live passing 2026-11-11; nothing
was added — the test-vector job had already written them):

- Python `tests/test_contracts_and_food.py:25`
  (`test_empty_checks_are_not_pass`, `[] → NOT_CHECKED`), `:27`
  (`[PASS, UNKNOWN] → UNKNOWN`), `:28`
  (`[UNKNOWN, INCOMPLETE] → INCOMPLETE`), `:332-333`
  (`test_aggregation_cases_unchanged`, `[] → NOT_CHECKED`,
  `[UNKNOWN] → UNKNOWN`).
- Python `tests/test_test_vectors.py:121-129`
  (`TestVectorsAggregationCasesTest`, both aggregation cases driven from
  `interop/test-vectors.json` through `overall_from_checks`).
- Rust `components/rust-kernels/src/lib.rs:437-438`
  (`empty-checks` → `NotChecked`, `unknown-only-checks` → `Unknown`),
  `:440-446` (`overall_from_checks_mirrors_python_rules`, full
  precedence table), `:516-524` (both aggregation cases driven from the
  vectors file). Note: the `test-vectors.json` note that said "Rust has
  no aggregation entry point to test yet" is now stale — Rust has had
  `overall_from_checks` plus these tests since the 2026-11-11 ISSUE-03
  work; the note was corrected the same day this document was written.

Suite totals after this work: review-copy Python 69/69, review-copy Rust
28/28, 0 failed. No code was changed for ISSUE-02 beyond documentation:
the rule and its tests predate this document.

## Correction to the shipped changelog

`CHANGELOG.md` under `0.3.2` says "No changes to the existing v0.3.1
Python reference behavior". That is no longer accurate: the aggregation
rule above *is* a change to v0.3.1 behaviour, and an intentional one.
A dated correction line has been added to `CHANGELOG.md` pointing here;
the original line is left in place as the historical record.

---

# Food formula change and stated losses/imports (ISSUE-15)

Date: 2026-11-11. Status: FIXED (documented + enforced). Review copy
only; local, never pushed. This is a second intentional breaking
change recorded in this file, after the ISSUE-02 aggregation change
above.

## The change

v0.3.1 `mini_ai/planning.py:35-56`, `food_balance()`: `surplus =
supply − need` (line 53: `round(supply -
planning_need_kcal_per_day, 1)`). No losses, no imports exist in the
formula at all.

v0.3.2 `domains/food/production.py:59-61`, `food_availability()`:

```python
effective_supply = supply_kcal_per_capita_per_day * (1.0 - losses_fraction)
total_available = math.fsum((effective_supply, imports_kcal_per_capita_per_day))
surplus = total_available - requirement_kcal_per_capita_per_day
```

## Worked numbers (verified live 2026-11-11)

| Inputs (supply / requirement / imports / losses) | v0.3.1 surplus | v0.3.2 total | v0.3.2 surplus |
|---|---|---|---|
| 2985 / 2500 / — / — | 485.0 | — | — |
| 2800 / 2500 / — / — | 300 | — | — |
| 2800 / 2500 / 100 / 0.08 | — | 2676.0 | 176.0 |
| 2985 / 2500 / 0.0 / 0.0 | — | 2985.0 | 485.0 |

The formulas agree **only** at losses 0 / imports 0. The 2800/2500
case is 300 under v0.3.1 and 176.0 under v0.3.2 (imports 100,
losses 0.08) — the same inputs, a different surplus, with no error
raised. Any surplus figure must therefore state which formula
produced it and what losses/imports were used.

## Why the new formula is kept, and why the inputs must be stated

Losses/imports are the better model: real food systems lose food
between recorded supply and availability, and trade food across
borders; ignoring both overstates availability whenever losses are
non-zero and understates it whenever imports are non-zero. But
silently defaulting them to 0.0 — as v0.3.2 did before this fix,
recording them as "explicit assumptions" — would silently reproduce
the v0.3.1 answer while claiming the v0.3.2 model's authority. So
`imports_kcal_per_capita_per_day` and `losses_fraction` are now
**required** food-domain inputs (`domains/food/schema.py`,
`REQUIRED_FOR_AVAILABILITY`): omitting either, or passing explicit
`None`, fails validation ("missing required field") and the
calculation returns `INSUFFICIENT_INPUT`. Stating 0.0 explicitly is
allowed — it is the caller asserting "no imports" / "no losses" —
and the ISSUE-01 global-balance reproduction (2985/2500/0/0 → 485.0)
does exactly that. The low-level `food_availability()` already
refused `None`/missing imports/losses with `INSUFFICIENT_INPUT` by
design; the domain layer and the independent verifier now agree.

## The ISSUE-13 normalisation — removed, decision (b)

ISSUE-13 had made `validate_inputs` record an explicit-`None`
imports/losses as "assumed to be 0.0" (ok=True) and made
`calculate()` and `engine/verification.py` normalise `None` to 0.0
so the recorded assumption was true. That normalisation is removed
in this change, in both places, rather than kept as a defensive
backstop for direct (unvalidated) callers. Reason: it is unreachable
through the validated path (validation now fails first), and keeping
it would reintroduce the silent zero one layer down — a direct
caller passing `None` would silently get the 0.0 answer instead of
`INSUFFICIENT_INPUT`. Treating `None` as missing everywhere is the
consistent rule. The ISSUE-13 tests that pinned the normalisation
(`tests/test_issue12_13.py`, `Issue13NoneMismatchTest`) are
superseded and updated to the new behaviour; see
`tests/test_issue15_food_formula.py`.

## Migration note for callers

State both fields on every food request, even when the value is 0.0:
`"imports_kcal_per_capita_per_day": 0.0, "losses_fraction": 0.0`.
The shipped examples already did (`examples/food_balance.py`:
100 / 0.08; `examples/global_food_balance.py`: 0.0 / 0.0) and pass
unchanged. Any caller that relied on omitting them now gets
`INSUFFICIENT_INPUT` with "missing required field:
imports_kcal_per_capita_per_day" / "losses_fraction" — add the
stated values (0.0 where the old default was intended) rather than
working around the validation.
