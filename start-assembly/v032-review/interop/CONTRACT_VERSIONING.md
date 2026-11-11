# START inter-language contracts

## Authority

The JSON Schemas in this directory are the language-neutral wire contracts. Python, Julia and Rust implementations must conform to them. Language-native structs are adapters, not competing definitions.

## Versioning

- `schema_version` is mandatory on every inter-process message.
- Patch: clarifications or stricter validation that do not change valid payload meaning.
- Minor: additive optional fields only.
- Major: incompatible field, unit, status or semantic changes.
- A component must reject an unsupported major version. It must not silently reinterpret it.

### One canonical version per schema (ISSUE-10/54 fix, 2026-11-11)

- The single source of truth for the schema version is
  `interop/SCHEMA_VERSION` (currently `1.0.0`, no trailing newline).
  Python (`adapters/python/contracts.py`) and Julia
  (`components/julia-planning/src/STARTPlanning.jl`) read that file at
  load time; Rust (`components/rust-kernels/src/lib.rs`) reads it at
  compile time with `include_str!`; the `start-kernel` binary's
  parse-error result uses the Rust `SCHEMA_VERSION` constant, not a
  second literal. No language holds its own hard-coded copy any more.
  A shared conformance test (`tests/test_issue09_10_11_54.py`) asserts
  all copies agree, and each language has its own test pinning the
  value it loads.
- Both schemas (request and result) currently share that one canonical
  version, `1.0.0` — they are one schema family for one wire boundary.
  If the two schemas ever need different versions, `SCHEMA_VERSION`
  must gain per-schema entries; a silent split is not allowed.
- The schemas carry `schema_version` as a `pattern`
  (`^1\.[0-9]+\.[0-9]+$`), not the old `const "1.0.0"`: the const
  contradicted the same-major acceptance the code implements (a
  `1.0.1` request was accepted by the code but failed the schema).
  The pattern is the schema's own statement of the same-major rule;
  the canonical version stays `1.0.0`.
- The old Julia planning message (`PlanningInput` /
  `evaluate_linear_balance`) no longer exists — it was removed by the
  ISSUE-05 fix, and the review-copy Julia now speaks only the
  constraint-evaluation schema. There is therefore no second Julia
  payload needing its own schema/version; that half of ISSUE-10 is
  moot, not merely deferred.

### What the schemas cannot express (ISSUE-08/09 boundary, 2026-11-11)

The schemas are the wire contract, but they cannot state everything,
and validation must not claim otherwise:

- Unit-registry membership: the schemas only require `value_unit` /
  `bound_unit` to be non-empty strings. Membership is enforced by the
  Python boundary validator (unknown unit raises) and by the
  evaluators in all three languages (`UNKNOWN` / `UNKNOWN_UNIT`,
  never `PASS`).
- `bound_low <= bound_high` for `range`: the schema's `if`/`then` can
  only require both fields to be present. Ordering is enforced by the
  validators/evaluators.
- Finiteness of numbers from a non-JSON caller: JSON Schema
  `type: number` does not exclude `NaN` / `±inf` held in a Python
  `float`. The Python validator checks every numeric field finite.

## Numeric and status rules

- Quantities are finite JSON numbers; booleans are not quantities.
- Units are explicit strings. No implicit unit assumptions or cross-dimensional conversions.
- Missing, unknown and unverified are distinct concepts. A successful calculation does not make source data verified.
- Status vocabulary is exactly `PASS`, `FAIL`, `UNKNOWN`, `NOT_CHECKED`, `INCOMPLETE`.
- `PASS` is only valid when the requested check was actually performed with sufficient valid inputs.
- A verifier reports its scope; arithmetic verification does not establish source truth or policy legitimacy.

## Initial interface

The first Rust boundary is a pure constraint-evaluation kernel. It receives one request and returns one result. It has no filesystem, network, database, agent, or policy authority. Julia planning components consume and produce the same versioned data model; they do not certify their own outputs.
