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

ISSUE-34 (2026-11-13): the registry now has 36 keys, identical in Python (`contracts/units.py`), Rust (`components/rust-kernels/src/lib.rs` `UNIT_TABLE`) and Julia (`components/julia-planning/src/STARTPlanning.jl` `UNIT_REGISTRY`) — 12 added for the nutrients and labour domains: `Tg`, `Mt`, `million tonnes` (mass, factor 1e9 kg); `Tg/yr`, `Mt/yr`, `tonne/yr`, `kg/yr` on their own dimension `mass_rate_year` (base Tg/yr, factors 1.0, 1.0, 1e-6, 1e-9); `percent` and `%` (dimensionless, factor 0.01); `hours/week`, `hours/day` (dimension `work_time_rate`, base hours/week, 1 hour/day = 7 hours/week on a 7-day week) and `hours` (dimension `time`, factor 1.0). Mass-per-year rates are deliberately NOT folded into `mass_rate` (per-day): folding them in would smuggle in a days-per-year assumption, so `Tg/yr` and `tonne/day` are NOT interconvertible — a conversion would need a stated days-per-year. Six new `must_agree` cases in `interop/test-vectors.json` pin the cross-language behaviour. ISSUE-47 overflow behaviour is preserved: a conversion overflowing to infinity raises (Python) / returns unknown (Rust/Julia), never a silent pass.

## Phosphorus / nitrogen / labour coverage (ISSUE-34, 2026-11-11; built 2026-11-13)

What exists: the P/N/labour constraint surface from v0.3.1 is present, via ISSUE-01, in `contracts/plan_limits.py` and the engine loads it by default (`engine/planning_engine.py:43` — `load_plan_limits()` in `PlanningEngine.__init__`; `check_plan()` refuses to run if it could not load). Verified live 2026-11-11: phosphorus 5.0 vs the 6.2 Tg/yr boundary → PASS; paid work 40 h/week vs the 48 h ILO threshold → PASS; nitrogen 165 Tg/yr → UNKNOWN with boundary None, never PASS; a plan containing all three has overall status UNKNOWN. Nitrogen is explicitly bound-less: the snapshot records fixation as more than twice its boundary but stores no exact boundary value, so no pass/fail is claimed.

Built 2026-11-13 — registry units: the 12 units those domains need are now in all three registries, which share exactly the same 36 keys (was 24): `Tg` / `Mt` / `million tonnes` (mass, 1e9 kg), `Tg/yr` / `Mt/yr` / `tonne/yr` / `kg/yr` on their own dimension `mass_rate_year` (base Tg/yr — NOT folded into `mass_rate`, so `Tg/yr` and `tonne/day` are not interconvertible), `percent` / `%` (dimensionless, 0.01), `hours/week` / `hours/day` (dimension `work_time_rate`, 1 hour/day = 7 hours/week) and `hours` (dimension `time`). See "Units" above; six new `must_agree` cases in `interop/test-vectors.json` pin the behaviour in all three languages.

Built 2026-11-13 — nutrients domain: `domains/nutrients/` holds one `NutrientsDomain` (`domain_id "nutrients"`) covering phosphorus and nitrogen, which share one balance shape. Phosphorus: applied 18.2 Tg/yr against the stored 6.2 Tg/yr boundary → FAIL, excess 12.0 Tg/yr, ratio 2.94. The stock-and-flow balance is `soil_change = inputs − uptake − losses` in Tg/yr, and uptake/losses are required explicit inputs — missing or `None` returns `INSUFFICIENT_INPUT`, never a silently-zeroed balance (the ISSUE-15 rule, as for food imports/losses). A caller-supplied phosphorus boundary must equal the stored snapshot bound exactly; a differing value is refused, never applied. Nitrogen: fixation 165 Tg/yr is reported, the boundary stays `None`, and the evaluation is always UNKNOWN with evidence quoting "more than twice its boundary" — no value of fixation can make it PASS. The v0.3.1 teaching example (100 applied / 50 uptake / 30 losses / 20 soil change) is used only as a labelled test input, never as real data. There is no independent verifier for this domain, so a completed run is `PARTIALLY_VERIFIED` by design (see "Adding a domain", rule 5). The example `examples/global_nutrient_balance.py` honestly shows `INSUFFICIENT_INPUT` for the balance — the snapshot carries no uptake/losses and inventing them is forbidden — and reproduces the boundary numbers through the domain's own constraint constructors, which need no uptake/losses.

Built 2026-11-13 — labour domain: `domains/labour/` holds `LabourDomain` (`domain_id "labour"`). Paid work hours/week are checked against the 48 h ILO long-hours threshold read from the stored plan limits: 40 and 43 h/week PASS, 55 FAIL. The snapshot context values — employed average 43 h/week, all-adults average 25 h/week (2026, Gethin and Saez IMF dataset) — are reported as context only and are not checked against the threshold; only the caller's stated paid-work figure is checked. Unpaid care: 16.4 billion hours/day (ILO 2018) split by the stated women's share 76.2% → women 12.4968 / men 3.9032 billion hours/day. Care per person is computed only with an explicitly supplied population (8.2e9 → 2.0 h/person/day), and combining the 2018 care figures with a 2024 population is a year mismatch stated as a limitation whenever both are combined. There is no independent verifier for this domain either, so a completed run is likewise `PARTIALLY_VERIFIED` by design.

Built 2026-11-13 — non-numeric scenario changes: `Scenario.proposed_changes` now accepts finite numbers, non-empty strings, and lists of non-empty strings (`contracts/scenarios.py`, enforced in `__post_init__`). Rejected: bool, `None`, dict/tuple/set, non-finite numbers, and empty/whitespace-only strings (inside a list or on their own). The companion allow-list `DomainModule.scenario_non_numeric_change_fields` (default `None` = none permitted) decides which fields may take a non-numeric change, enforced by the shared `_check_scenario_changes` by value shape — a numeric change needs its key in `scenario_change_fields`, a str/list change needs its key in `scenario_non_numeric_change_fields`. Nutrients and labour both declare `{"source_ids", "geography", "period"}`; food declares nothing non-numeric, so its scenario changes stay numeric-only. An explicit proposed change to `geography`/`period` wins over the base request (`request.update` runs before the `setdefault` defaults); the ISSUE-25 base-wins rule covers scenario defaults only. An empty list `[]` as a change value constructs — vacuously a list of non-empty strings — pinned by test.

What remains undone: (a) there is no independent mathematical verifier for the nutrients or labour domains, so both stay `PARTIALLY_VERIFIED` by design — that is the "Adding a domain" rule 5 outcome, not an oversight, and closing it means writing a verifier, not re-checking the arithmetic; (b) the nutrients example cannot show a completed soil-change balance from snapshot values alone, because the snapshot carries no uptake/losses and inventing them is forbidden — `examples/global_nutrient_balance.py` reports `INSUFFICIENT_INPUT` and shows the boundary reproduction instead. Nothing else is known to remain: the 2026-11-11 DEFERRED record for this issue — registry units, full domain modelling, non-numeric scenario changes — is closed by the work above.

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
removed. A base without them still gets the scenario's values. The
base-wins rule covers scenario *defaults* only: an *explicit*
proposed change to `geography`/`period` (ISSUE-34, 2026-11-13 — see
below) wins over the base request, because `request.update` runs
before the `setdefault` defaults.

**Change allow-list (ISSUE-33/38/34, 2026-11-11; non-numeric changes 2026-11-13):** one rule, not two.
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

Non-numeric changes (ISSUE-34, 2026-11-13): `Scenario.proposed_changes`
also accepts non-empty strings and lists of non-empty strings — the
forms a scenario needs to change `source_ids`, `geography`, or
`period`. The value shape is checked in `Scenario.__post_init__`
(`contracts/scenarios.py`); which field may take which form is
decided by a companion allow-list,
`DomainModule.scenario_non_numeric_change_fields` (default `None` =
none permitted), enforced by the same shared
`DomainModule._check_scenario_changes` by value shape — a numeric
change needs its key in `scenario_change_fields`, a str/list change
needs its key in `scenario_non_numeric_change_fields`. Nutrients and
labour both declare `{"source_ids", "geography", "period"}`; food
declares nothing non-numeric, so its scenario changes stay
numeric-only. Bool, `None`, dict/tuple/set, non-finite numbers and
empty strings are rejected at construction; an empty list `[]`
constructs (vacuously a list of non-empty strings, pinned by test).

## Adding a domain

1. Implement `DomainModule` methods.
2. Validate finite numeric inputs, units, temporal scope, provenance identifiers and domain-specific physical constraints.
3. Return explicit assumptions and limitations.
4. Implement constraints using shared status semantics.
5. Add a domain-specific independent verifier before claiming `VERIFIED`.
6. Add adversarial and invariant tests before registering the domain in a production workflow.

A domain that has no independent mathematical verifier will remain `PARTIALLY_VERIFIED`; this is intentional.

## Logging, persistence and CLI (ISSUE-27, built 2026-11-13)

The review found no logging, persistence or CLI anywhere (ISSUE-27, verified 2026-11-11). All three are now built, stdlib only. This section is the authoritative record of the shapes and rules; the README gives the short version.

### Log records

`engine/event_log.py` is the single logging interface. Records are JSON-lines objects with keys `timestamp` (UTC ISO-8601, `Z` suffix), `level`, `logger` (namespaced `start.*`: `start.engine`, `start.contracts`, `start.persistence`, `start.cli`), `event` (stable machine-readable name, e.g. `engine.run.completed`), `message` (human-readable), plus event-specific metadata fields (domain/scenario ids, statuses, counts, paths).

Privacy rule (hard): INFO and above log **metadata only** — ids, statuses, counts, paths. NEVER a full request or result payload at INFO or above. DEBUG may include payloads. The logging tests assert distinctive request values and exception messages do not appear in INFO records.

Library rule (hard): importing the package configures nothing — no handlers, no `basicConfig`, no file writes. `configure_logging(level, log_file)` is called only by the CLI entry point. Default level WARNING to stderr; `--verbose` maps to INFO, `--quiet` to ERROR, `--log-file` appends JSON-lines to that path instead of stderr.

Events emitted: engine run started/completed (domain, calculation/overall status), check_plan started/completed (overall status, failed count), unknown-domain and validation-failure paths (WARNING), domain exceptions (ERROR, exception type only, never the message), persistence save/load success and failure (kind, path, schema version), CLI invocation/success/failure.

### Persistence envelope

`persistence/` (`save_envelope`, `load_envelope`, `KINDS`). Every persisted file is a JSON object with exactly four top-level keys:

- `schema_version` — from `adapters.python.contracts.SCHEMA_VERSION`, read at import from the single source of truth `interop/SCHEMA_VERSION` (currently `1.0.0`). No second hard-coded copy.
- `kind` — one of `plan_request`, `scenario`, `result`, `plan_overrides`, enumerated in `persistence.KINDS`.
- `saved_at` — UTC ISO-8601 with `Z` suffix.
- `payload` — the data; a `result` payload is the engine's result dict verbatim (a result that says UNKNOWN stays UNKNOWN on disk).

Versioning follows `interop/CONTRACT_VERSIONING.md` exactly: same-major patch/minor versions are accepted, a different major is rejected with both versions named. Extra top-level keys are tolerated on load (a same-major minor version may add optional fields); save always writes exactly the four keys. Kind-specific payload checks on load: `scenario` needs a non-empty string `scenario_id` and `name`; `result` needs `domain` (str) and `calculation` (dict); `plan_request`/`plan_overrides` need only be dicts (plan keys are validated by the engine at check time).

Writes are atomic: temp file in the same directory, flush + fsync, then `os.replace`, so a crash never leaves a half-written file; the temp file is removed on any failure. An existing file is never overwritten unless the caller passes `overwrite=True` (CLI: `--force`); without it the old file is left byte-identical. Paths are always caller-chosen; there is no hidden default store directory and parent directories are never auto-created. Any load failure raises `ValueError` naming the path and reason — never a half-loaded object. No SQLite, no database, JSON only.

### CLI

`cli/` (`python -m cli`; `pyproject.toml` defines no console scripts, so `python -m cli` is the entry point, following the `python -m examples.food_balance` pattern). All three built-in domains are registered: `food`, `nutrients`, `labour`. Subcommands:

- `check-plan --plan <file> [--overrides <file>] --out <file>` — plan envelope (`plan_request`) and optional overrides envelope (`plan_overrides`) in, result envelope out.
- `run --domain <id> --request <file> --out <file>` — request envelope (`plan_request`) in, result envelope out.
- `run-scenario --domain <id> --scenario <file> --out <file>` — scenario envelope in, result envelope out.
- `compare-scenarios --domain <id> --scenarios <file>... --out <file>` — one scenario envelope per file, result envelope out; consequences reported without ranking or selection.
- `list-domains` — registered domain ids, one per line, to stdout.

Global flags (before the subcommand): `--verbose`, `--quiet`, `--log-file <path>`, `--force`. Input files must be persistence envelopes — a bare payload JSON without the envelope is rejected with a message naming the expected envelope shape; both shapes are never silently accepted. Wrong kind, unknown domain (error lists the available domains), bad Scenario fields, missing input, corrupt JSON, and major version mismatch are usage errors. Everything is validated and the engine is run before the output path is touched, so on any failure no output file is written (never a partial result).

Exit codes: 0 on success, **including a result whose status is FAIL or UNKNOWN** — the plan outcome is data, not a CLI failure. 2 for usage/validation errors. 1 for runtime failures (output cannot be written, existing output without `--force`, log file unopenable, unexpected engine exception). On failure a one-line error goes to stderr and the failure is logged.

What remains undone: no interactive mode, no UI, no renderer, no network (Module 25 UI work is NOT approved — file-in/file-out only); no API server; persistence is plain JSON files, not a database — concurrent writers to the same path rely on `os.replace` atomicity only, with no locking.

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
