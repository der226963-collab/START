# START v0.3.2 — Corrected Foundational Planning Architecture

**Status:** corrected prototype; not a finished community planning system and not integrated into the live START repository.

This release preserves the original modular architecture and food pilot while correcting input validation, explicit assumptions, dimensional checks, constraint evaluation, calculation precision, scenario dispatch and result verification.

## What is included

| Path | Purpose |
|---|---|
| `contracts/` | Shared status, resource, stock, flow, process, constraint, objective, scenario and unit contracts |
| `domains/base.py` | Common domain interface and scenario request convention |
| `domains/food/` | Deterministic aggregate food-energy balance prototype |
| `engine/` | Domain dispatch, structured error handling, independent verification and scenario comparison |
| `tests/` | Acceptance-oriented unit tests |
| `docs/` | Architecture, verification scope and limitations |
| `examples/` | Runnable food-balance example |

## Design safeguards

- Missing required food inputs prevent calculation. `imports_kcal_per_capita_per_day` and `losses_fraction` are **required**, never silently defaulted to zero: a request that omits either, or passes explicit `None` for either, fails validation and the calculation returns `INSUFFICIENT_INPUT`. Stating 0.0 explicitly is allowed — it is the caller asserting "no imports" / "no losses". (ISSUE-15, 2026-11-11; see "Food-energy formula" below.)
- Booleans, non-finite numbers, invalid ranges and invalid population values are rejected.
- Full-precision values are used for evaluation; rounded values are presentation-only.
- Empty constraint lists never produce `PASS`.
- Unknown, incomplete and not-checked states remain visible.
- The food arithmetic is independently re-derived by the verification module.
- Generic domains without an independent mathematical verifier are marked `PARTIALLY_VERIFIED`, not fully verified.
- Engine exceptions become structured errors.
- Scenario comparison reports consequences but does not rank or select scenarios.
- Every planning result retains `needs_human_decision=True` — enforced at construction: `ScenarioResult` rejects `needs_human_decision=False` and any `calculation_status` outside `CalculationStatus`, and is frozen against later reassignment (ISSUE-14). There is no override.
- Engine result flags (ISSUE-37): `calculation_ok` (the calculation ran to `COMPLETED`), `verified` (the result was independently verified), `verified_ok` (both). `ok` is a deprecated alias for `verified_ok` and is kept only for existing consumers. **`ok: False` does not mean fail**: a correct calculation in a domain with no independent verifier returns `calculation_ok: True` with `verified: False` and `ok: False` (`PARTIALLY_VERIFIED`) — a limit of verification coverage, not a failed calculation. A failed calculation has `calculation_ok: False`.
- No allocation, approval or autonomous decision-making is implemented.

## Run

Python 3.10 or newer; no third-party dependencies.

From this directory:

```bash
python -m unittest discover -s tests -v
python -m examples.food_balance
```

## Example input

```python
{
    "population": 100000,
    "supply_kcal_per_capita_per_day": 2800,
    "requirement_kcal_per_capita_per_day": 2500,
    "imports_kcal_per_capita_per_day": 100,
    "losses_fraction": 0.08,
    "source_ids": ["local-food-survey-2026"],
    "geography": "community-example",
    "period": "2026"
}
```

## Food-energy formula (ISSUE-15, 2026-11-11)

The food formula **changed** between v0.3.1 and v0.3.2. v0.3.1 was
`surplus = supply − need`, with no losses or imports. v0.3.2 is
`effective_supply = supply × (1 − losses_fraction)`,
`total_available = effective_supply + imports_kcal_per_capita_per_day`,
`surplus = total_available − requirement`. The two agree **only**
when losses are 0 and imports are 0. Worked numbers, verified live:
2800/2500 gives 300 under v0.3.1 but total 2676.0 / surplus 176.0
under v0.3.2 with imports 100 and losses 0.08; 2985/2500 with
explicitly stated 0/0 gives 485.0 in both. Losses/imports are the
better model (real systems lose food and trade across borders), so
they are kept — but they must be stated, never silently zero: see
the safeguard above. Full discussion in `docs/ARCHITECTURE.md`.

## Important interpretation limits

A `PASS` in the food pilot means only that the **aggregate per-capita daily food-energy figure** meets the supplied planning threshold under the stated assumptions. It does not establish household access, distributional equity, dietary quality, micronutrient adequacy, food sovereignty, seasonal resilience or the truth of the input sources.

The current unit registry is intentionally small. Unknown units are rejected; this is not yet a comprehensive dimensional-analysis framework. Geography and period fields remain identifiers/labels rather than a full GIS or temporal database. Source identifiers are carried through results but there is no source registry or source-authenticity service yet.

## Not implemented

- Water, energy or land domains
- Cross-domain dependency graph or resource allocation
- Full stock-and-flow simulation or process execution
- Comprehensive source registry, evidence appraisal or provenance authentication
- Retrieval, memory or LLM orchestration
- Optimization or automatic scenario selection
- Governance workflows, voting, permissions or community decision interfaces
- Production-grade security, API or user interface
- (Logging, file persistence and a file-in/file-out CLI now exist — see below and `docs/ARCHITECTURE.md`.)

## Logging, persistence and CLI (ISSUE-27, built 2026-11-13)

The 2026-11-11 cleanup recorded logging, persistence and a CLI as DEFERRED pending Eric's call; he made that call on 2026-11-13 and all three are now built (stdlib only — `logging`, `argparse`, JSON files; no SQLite, no database, no third-party framework).

- **Logging** (`engine/event_log.py`): structured JSON-lines records — timestamp, level, `start.*` logger name, event, message, plus metadata fields (domain/scenario ids, statuses, counts, paths). INFO and above log metadata only, never request/result payloads. Importing the package configures nothing; logging is switched on only by the CLI.
- **Persistence** (`persistence/`): every saved file is a JSON envelope — `schema_version` (from `interop/SCHEMA_VERSION`, currently `1.0.0`), `kind` (`plan_request`, `scenario`, `result`, `plan_overrides`), `saved_at` (UTC ISO-8601), `payload`. Writes are atomic (temp file + rename) and refuse to overwrite unless forced. Loads reject unknown kinds and major version mismatches; a saved result is the engine's result dict verbatim.
- **CLI** (`python -m cli`): `check-plan`, `run`, `run-scenario`, `compare-scenarios`, `list-domains`. File in, file out; exit 0 on success even when a plan outcome is FAIL or UNKNOWN (that is data, not a CLI failure), 2 for usage/validation errors, 1 for runtime failures, and no output file is written on any failure. Example: `python -m cli check-plan --plan plan.json --out result.json`. Ready-made example inputs live in `examples/cli-inputs/` (with a README giving the command and expected outcome for each file); `tests/test_issue27_cli_examples.py` runs every one through the real CLI so they cannot go stale silently. See `docs/ARCHITECTURE.md` for the full subcommand, exit-code and envelope rules. There is no interactive mode, no UI and no network.

See `docs/ARCHITECTURE.md` and `docs/VERIFICATION.md` before extending the system.

## Multi-language groundwork

A preliminary v0.3.2 scaffold now records the agreed division of responsibilities: Python for agents/orchestration/governance and PyTorch, Julia for planning mathematics and domain logic, and Rust for deterministic constraint/verification kernels. Versioned JSON contracts live in `interop/schemas/`; initial Julia and Rust component packages live in `components/`. These are source scaffolds, not yet compiled or runtime-integrated. See `docs/ARCHITECTURE.md` and `interop/CONTRACT_VERSIONING.md`.
