# Architecture and extension guidance

## Separation of responsibilities

1. **Contracts** define shared data structures and status semantics.
2. **Domain modules** validate domain inputs and implement deterministic calculations and domain constraints.
3. **Planning engine** dispatches requests, handles failures and packages results.
4. **Verification** checks result structure/status consistency and performs independent arithmetic checks where implemented.
5. **Human/community governance** remains outside the engine. The engine does not decide priorities, allocate resources or approve plans.

## Resource, stock and flow

- `Resource` identifies a resource or scoped resource observation.
- `Stock` records a quantity held at a point in time (`as_of`).
- `Flow` records a quantity moving over a declared period and may include start/end identifiers.
- `Process` describes inputs and outputs but does not yet execute a transformation or enforce conservation laws.

A future material-balance layer must explicitly reconcile opening stock + inflows - outflows = closing stock, with unit and time compatibility checks. This is not implemented in this release.

## Units

`contracts.units` contains a deliberately limited registry and conversion function. It rejects unknown or dimensionally incompatible units. Extend it only with reviewed units and dimensions. Do not assume that similar-looking rates are interchangeable: `kg`, `kg/day` and `kg/capita/day` represent different dimensions.

## Phosphorus / nitrogen / labour coverage (ISSUE-34, 2026-11-11)

What exists: the P/N/labour constraint surface from v0.3.1 is present, via ISSUE-01, in `contracts/plan_limits.py` and the engine loads it by default (`engine/planning_engine.py:43` — `load_plan_limits()` in `PlanningEngine.__init__`; `check_plan()` refuses to run if it could not load). Verified live 2026-11-11: phosphorus 5.0 vs the 6.2 Tg/yr boundary → PASS; paid work 40 h/week vs the 48 h ILO threshold → PASS; nitrogen 165 Tg/yr → UNKNOWN with boundary None, never PASS; a plan containing all three has overall status UNKNOWN. Nitrogen is explicitly bound-less: the snapshot records fixation as more than twice its boundary but stores no exact boundary value, so no pass/fail is claimed.

What does not exist (regression vs the old planning layer, documented explicitly here rather than fixed): the unit registry cannot express the units those domains need — `Tg/yr`, `million tonnes`, `percent`, and `hours/week` (also `%` and `Tg`) are absent from all three registries (Python `contracts/units.py`, Rust `components/rust-kernels/src/lib.rs` `UNIT_TABLE`, Julia `components/julia-planning/src/STARTPlanning.jl` `UNIT_REGISTRY`), which share exactly the same 24 keys; the closest existing units are `tonne` (mass) and `kcal/capita/day`. There is no full phosphorus, nitrogen, or labour domain modelling beyond the constraint surface above — no P/N/labour domain module, no stock-and-flow or process model for those nutrients or for labour. And `Scenario.proposed_changes` accepts finite numbers only (`contracts/scenarios.py:23-25`, enforced in `__post_init__`), so a scenario can never change `source_ids`, geography, or any non-numeric field (verified live: a non-numeric change raises `ValueError`).

The remainder — registry units for those domains, any full domain modelling beyond the constraint surface, and non-numeric scenario changes — is recorded as DEFERRED: it is new modelling capability, not a bug fix, and needs a decision on whether v0.3.2 is meant to supersede the old planning layer's full domain surface before anything is built.

## Time and geography

The current fields are identifiers/labels, with one exception:
`Flow.start` and `Flow.end` are ISO-8601 dates (`YYYY-M-D`, month/day
zero-padding optional) or ISO-8601 datetimes (ISSUE-24, 2026-11-11).
They are parsed to `datetime.date` in `Flow.__post_init__` and
compared as dates, never as strings — the old lexicographic check
rejected valid non-padded dates ("2026-9-1" > "2026-10-1") and let
reversed pairs through. Unparseable or impossible dates (e.g.
"2026-02-30") raise `ValueError` with a clear message. Datetimes are
compared by calendar date. `Stock.as_of` is still only a label and is
not parsed (it may be e.g. "2026"). The strings are still not parsed
into timezone-aware datetime objects. Geography is not yet a canonical
place hierarchy or spatial geometry system.

## Contract validation rules (ISSUE-48, 2026-11-11)

One rule per concept, enforced in `__post_init__` in `contracts/`.
These rules are consistent with the ISSUE-12 rules already in place
(`Constraint` empty-id rejection, empty-unit-allowed-by-design for
unit-less constraints, `Resource` non-negative) — nothing there was
changed to make the scheme coherent.

* **Ids are non-empty everywhere.** `resource_id`, `stock_id`,
  `flow_id`, `process_id`, `objective_id`, `constraint_id`,
  `scenario_id` (and `ScenarioResult.scenario_id`) must be non-empty
  strings; whitespace-only counts as empty, non-strings raise.
  Reference ids (`Stock`/`Flow`/`ProcessInput`/`ProcessOutput`
  `.resource_id`) must likewise be non-empty — they identify the
  resource being observed. Names (`Constraint.name`,
  `Objective.name`, `Process.name`, `Scenario.name`) follow the same
  rule.
* **Unit: required for quantity-bearing types, optional for
  bounds/targets.** `Resource`, `Stock`, `Flow`, `ProcessInput`,
  `ProcessOutput` require a known registry unit *even when quantity
  is None* — the unit is part of the observation's identity, and a
  unit-less amount cannot be compared or converted later. No
  existing caller needs a unit-less quantity type (verified by grep
  2026-11-11). `Constraint` and `Objective` allow `unit=""`
  (deliberately unit-less, e.g. the plan_limits phosphorus and
  work-hours constraints); when a unit is given it must be a known
  registry unit.
* **Quantities (ISSUE-12/31): non-negative when present, None =
  unknown.** Zero is allowed. Negative quantities are never
  meaningful for `Resource`/`Stock`/`Flow`/`ProcessInput`/
  `ProcessOutput` — a deficit/shortfall is a signed metric, not one
  of these types, and direction for processes is expressed by input
  vs output role, never by sign.
* **Status (ISSUE-31): `VERIFIED` requires a quantity.**
  Constructing a `Resource`/`Stock`/`Flow` with
  `status=VERIFIED` and `quantity=None` raises — verification is a
  claim about a value, and with no value there is nothing verified.
  (`is_verified()` already returned False for None quantities; the
  fix is at construction, not in `is_verified()`.)
  `ProcessInput`/`ProcessOutput` have no status field, so the rule
  does not apply to them.

## Food-energy formula (ISSUE-15, 2026-11-11)

The food domain's formula **changed** between v0.3.1 and v0.3.2, and
the change is intentional — but it changes answers on identical
supply/requirement inputs, so it is stated here explicitly rather
than left to be discovered from differing outputs.

v0.3.1 (`mini_ai/planning.py: food_balance()`):

```
surplus = supply − need
```

No losses, no imports. v0.3.2 (`domains/food/production.py:
food_availability()`):

```
effective_supply = supply × (1 − losses_fraction)
total_available  = effective_supply + imports_kcal_per_capita_per_day
surplus          = total_available − requirement
```

Worked numbers, verified live 2026-11-11:

| Inputs (supply / requirement / imports / losses) | v0.3.1 surplus | v0.3.2 total | v0.3.2 surplus |
|---|---|---|---|
| 2985 / 2500 / — / — | 485.0 | — | — |
| 2800 / 2500 / — / — | 300 | — | — |
| 2800 / 2500 / 100 / 0.08 | — | 2676.0 | 176.0 |
| 2985 / 2500 / 0.0 / 0.0 | — | 2985.0 | 485.0 |

The two formulas agree **only** when losses are 0 and imports are 0
(the last row: 485.0 in both). Everywhere else they differ — the
2800/2500 case is 300 under the old formula and 176.0 under the new
one — so a surplus figure is meaningless without knowing which
formula produced it and what losses/imports were assumed.

Why losses/imports are the better model: real food systems lose food
between recorded supply and what is actually available to eat, and
trade food across borders. A supply figure that ignores both
overstates what is available whenever losses are non-zero, and
understates it whenever imports are non-zero. The v0.3.1 formula
could not express either fact.

Why they must be **stated, never silently zero**: silently defaulting
losses/imports to 0.0 would silently reproduce the v0.3.1 answer
while claiming the v0.3.2 model's authority — the worst of both
formulas. So `imports_kcal_per_capita_per_day` and `losses_fraction`
are **required** food-domain inputs. A request that omits either, or
passes explicit `None` for either, fails validation ("missing
required field") and the calculation returns `INSUFFICIENT_INPUT`,
never a silently-zeroed balance. Stating 0.0 explicitly is allowed:
it is the caller asserting "no imports" / "no losses", and the
global-balance reproduction (2985/2500/0/0 → 485.0) does exactly
that. The low-level `food_availability()` already refused
`None`/missing imports/losses with `INSUFFICIENT_INPUT` by design;
the domain layer and the independent verifier now agree with it
instead of normalising `None` to 0.0 (the ISSUE-13 normalisation in
`FoodDomain.calculate()` and `engine/verification.py` was removed
2026-11-11 as part of this change — decision (b): treating `None` as
missing everywhere is the consistent rule, and keeping the
normalisation as a "defensive backstop" for direct callers would
reintroduce the silent zero one layer down).

### Two-layer defaulting rule (ISSUE-43, second half — verified resolved 2026-11-11)

The low-level and domain-level defaulting used to disagree:
`food_availability(100, 2000, 1800)` (imports/losses `None`)
returned `INSUFFICIENT_INPUT`, while `FoodDomain.calculate` on the
equivalent request silently defaulted them to 0.0. After ISSUE-15
that defaulting is gone and both layers agree — verified live
2026-11-11: both calls return `INSUFFICIENT_INPUT`. The rule, as it
now stands, is: **neither layer defaults anything**. The low level
refuses `None`/missing imports or losses with `INSUFFICIENT_INPUT`;
the domain layer refuses them at validation ("missing required
field"); the independent verifier refuses them too (a missing/`None`
imports or losses fails verification with an issue instead of
verifying against an assumed 0.0). There is no layer left in which a
silent zero can hide. Stating 0.0 explicitly remains the only way to
assert "no imports" / "no losses".

### One canonical expression (ISSUE-43, first half)

Production (`domains/food/production.py`) and the independent verifier
(`engine/verification.py`) compute the effective supply with the same
expression, `supply * (1.0 - losses_fraction)`. The verifier used to
compute `domestic - (domestic * loss_rate)`, which differs in
floating point; the difference was absorbed by the verification
tolerance, but an "independent" re-derivation that is textually a
different formula is fragile by construction. The total is
`math.fsum((effective, imports))` in production vs a plain `+` in the
verifier; for two operands both are correctly rounded, so they agree
exactly — the canonicalisation that matters is the `(1 - loss)`
factor. The per-metric verification tolerances are sized against the
remaining last-bit noise: see "Verification tolerances" below.

## Verification tolerances (ISSUE-22)

The verifier does not use one relative tolerance for every scale. A
single `rel_tol=1e-10` let a +100,000 kcal tamper pass at global
scale, because the true annual gap is 1,451,605,000,000,000.0 kcal/yr
and 1e-10 of that is ~145,160 kcal/yr of slack. The per-metric table
(`FOOD_METRIC_TOLERANCES` in `engine/verification.py`) is:

| Metric | rel_tol | abs_tol | Why |
|---|---|---|---|
| per-capita metrics (kcal/capita/day, ~1e3 scale) | 1e-10 | 1e-8 | unchanged; formula-difference noise is ~1 ulp (~5e-13) |
| `annual_gap_or_surplus_kcal` | 1e-11 | 1e-6 kcal/yr | at global scale allows ~14,516 kcal/yr — 10,000x the ~1–2 kcal/yr last-bit noise, but 7x smaller than the +100,000 kcal tamper, which now fails; the absolute cap is < 1 so the existing +1 kcal tamper test still fails |
| input echoes (supply, requirement, imports) | 1e-10 | 1e-8 | echoes are copied inputs, not computations |
| `population` echo | 1e-10 | 1.0 | one person is the smallest meaningful absolute slack |
| `annualization_days` | 0.0 | 0.0 | exact (365.0) |

## Constraint tolerance (ISSUE-30/35)

One coherent rule. The default tolerance stays **0.0** everywhere,
and a non-zero tolerance is always an explicit caller choice, never
read from a request (a request cannot smuggle a tolerance past
validation) and never silent:

* At tolerance 0.0, `==` is **exact float equality**, by design:
  `Constraint(operator="==", bound=0.3).evaluate(0.1 + 0.2)` is FAIL
  (0.30000000000000004 != 0.3). Requiring `tolerance > 0` for `==`
  was considered and rejected: it would have been a breaking change
  (every existing `==` construction uses the default) and would have
  hidden the real fact. Callers comparing computed floats must pass
  an explicit tolerance (e.g. 1e-9) and say so.
* A non-zero tolerance **can flip a verdict** (6.5 vs bound 6.2:
  FAIL at 0.0, PASS at 0.5). That is why the tolerance is always
  surfaced, never silent: `Constraint.to_dict()` includes it, and the
  food evaluation row includes it plus `verdict_without_tolerance`
  and `tolerance_changed_verdict`, with a warning in words when a
  flip occurs. A result that passes only because of its tolerance
  says so on its face.

## Synthetic data (ISSUE-36)

The v0.3.1 pilot guard — `pilot_summary()` raising if any
`household_id` lacks `SYNTH` — was dropped in v0.3.2:
`DataStatus.SYNTHETIC` is defined but was never enforced, and
`FoodDomain` accepts any `source_ids` strings. The raise-guard itself
is **intentionally deferred**, not silently lost: the synthetic pilot
file (`data/local_pilot_example.csv`) was deliberately NOT ported
into this tree (see `data/SNAPSHOT_PROVENANCE.md`), so there is no
pilot data in-tree to guard, and `FoodDomain` accepts free-form
`source_ids` strings, so it cannot verify provenance — a raise on
unmarked rows would be enforcing a convention no data in-tree follows.
What IS enforced is **SYNTHETIC labelling**: a food result whose
`source_ids` carry the `SYNTH` marker (the v0.3.1 convention) gets
`data_status: "synthetic"` plus a limitation stating the results are
teaching/test data and must not be used for a real allocation;
anything else gets `data_status: "unknown"` — source credibility is
not independently assessed, so no result may claim "observed" or
"verified" provenance it has not earned. If synthetic pilot data is
ever ported in, the raise-guard should be revisited at the port, not
retrofitted here.

Update 2026-11-11 (ISSUE-17): the deferral's premise no longer holds —
the pilot file WAS ported (byte-identical, see
`data/SNAPSHOT_PROVENANCE.md`), so the raise-guard is now ENFORCED in
the ported `domains/compat_v031.py:pilot_summary()` (non-SYNTH row
raises `ValueError`), and its result carries
`data_status: "synthetic"`; see `docs/COMPAT_V031_MAPPING.md` and
`tests/test_compat_v031.py` (`test_pilot_guard_raises_on_non_synthetic_row`).
The `FoodDomain` free-form `source_ids` labelling above is unchanged.

## Scenario convention

The generic scenario interface expects `scenario.metadata["base_request"]` to contain a valid domain request. `proposed_changes` override request fields by name. A domain may override `scenario_request` to enforce domain-specific change semantics. Food scenarios accept absolute replacement values for known food request fields. No scenario is ranked or selected.

**Geography/period (ISSUE-25, 2026-11-11):** the base request wins.
`scenario_request` uses `setdefault` for `geography` and `period` in
both the generic and the food paths — a base request's real
geography/period are never overwritten with the scenario's defaults
("unspecified"). Food used to overwrite them unconditionally, which
contradicted the documented generic convention; that override is
removed. A base without them still gets the scenario's values.

**Change allow-list (ISSUE-33/38, 2026-11-11):** one rule, not two.
The generic path used to apply any `proposed_changes` key, including
injected keys such as `"__injected__"`, while food raised
`ValueError` on unknown fields. Both now reject unknown fields the
same way: a domain declares the fields a scenario may change in
`DomainModule.scenario_change_fields` (default: none permitted — an
unknown field is rejected, never silently applied), and the shared
`DomainModule._check_scenario_changes` enforces it. Food declares
the five `REQUIRED_FOR_AVAILABILITY` fields — the same allow-list its
`validate_inputs` enforces via `domains/food/schema.py`
(`ALLOWED_REQUEST_FIELDS`); there is exactly one allow-list
mechanism, this attribute, driven by the schema set Food already
had. The base request itself is not allow-listed here: it is a full
domain request, checked later by the domain's own `validate_inputs`
(food rejects unknown request fields).

## Adding a domain

1. Implement `DomainModule` methods.
2. Validate finite numeric inputs, units, temporal scope, provenance identifiers and domain-specific physical constraints.
3. Return explicit assumptions and limitations.
4. Implement constraints using shared status semantics.
5. Add a domain-specific independent verifier before claiming `VERIFIED`.
6. Add adversarial and invariant tests before registering the domain in a production workflow.

A domain that has no independent mathematical verifier will remain `PARTIALLY_VERIFIED`; this is intentional.

## Multi-language groundwork (v0.3.2 scaffold)

The proposed division of responsibility is:

- **Python:** agent, memory, retrieval, governance, self-edit, orchestration and the existing reference implementation.
- **Julia:** planning contracts at the computational planning boundary, domain mathematical logic, simulation and optimization.
- **Rust:** deterministic constraint and verification kernels with narrow, side-effect-free interfaces.
- **PyTorch/Python:** neural-network development, MiniGPT training and inference for the current stage. No Mojo dependency is introduced.

The language-neutral wire format is versioned JSON, specified under `interop/schemas/`. The first native boundary is intentionally small: one constraint evaluation request and one result. Rust v1 accepts identical units only; conversion must happen explicitly using a reviewed conversion table outside this initial kernel. This avoids creating divergent unit semantics across languages.

The Julia package currently contains a small illustrative balance kernel to prove package boundaries and human-decision semantics. It is not a production optimizer. Python adapters currently validate payload shape and numeric safety; runtime process orchestration is deferred until the deployment environment has Rust and Julia installed.

### Trust and authority boundaries

- Optimizers propose; they do not approve.
- A component cannot certify its own output as independently verified.
- Rust checks computational invariants against supplied inputs; it cannot establish source-data truth.
- Unknown, incomplete, unsupported-version and failed states remain explicit.
- The Python v0.3.1 implementation remains the behavioral reference until cross-language conformance tests pass.
