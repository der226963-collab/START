"""
STARTPlanning — Julia implementation of the START planning/constraint contract
(REVIEW.md ISSUE-05 fix, 2026-11-11).

Implements `Constraint` faithfully against the same wire contract as Python
(`contracts/constraints.py`, `contracts/units.py`, `contracts/statuses.py`)
and Rust (`components/rust-kernels/src/lib.rs`), driven by the shared
`interop/test-vectors.json` cases. Statuses are exactly the five contract
strings `PASS`, `FAIL`, `UNKNOWN`, `NOT_CHECKED`, `INCOMPLETE` — never
Symbols, never `:candidate_feasible` / `:candidate_infeasible`.

What was here before, and why it is gone
-----------------------------------------
The previous `STARTPlanning.jl` defined only `PlanningInput
{schema_version, input_id, coefficients, limits}` and
`evaluate_linear_balance`, whose sole computation was
`slack = limits .- coefficients` with status
`all(slack .>= 0) ? :candidate_feasible : :candidate_infeasible`. That
hard-coded a `<=` reading for every element, had no constraint_id,
operator, bound(s), unit, tolerance or objective, emitted statuses
outside the contract vocabulary, and reused `"1.0.0"` for a different
payload than the constraint-evaluation schema (REVIEW.md ISSUE-05,
ISSUE-07, ISSUE-10). Reproduced 2026-11-11 before removal: the food
domain's `>=` constraint (2800 kcal/capita/day vs requirement 2500)
came out `:candidate_infeasible`; 0.02 m³ vs 10 L came out
`:candidate_feasible` (conversion gives 20 L > 10 L, correct verdict
FAIL); 5 L vs 10 kg came out `:candidate_feasible` (correct verdict
UNKNOWN). No other code in the review-copy tree used `PlanningInput` /
`evaluate_linear_balance` (only its own test file), so the old path was
REMOVED rather than kept alongside the new one — two competing
semantics must not silently coexist. There is no separate schema/version
for the old payload because the old payload no longer exists.

Objective
---------
`Objective` mirrors Python's `contracts/constraints.py` `Objective`
(struct + validation: direction in maximize/minimize/target, a target
value required for direction "target", finite non-negative weight, known
unit). Python's `Objective` likewise defines NO evaluation method and
no objective value: an objective is a declared aim, not a computed
score, so this module computes no `objective_value` either. That is a
deliberate mirror of Python, not a dropped feature. Constraint
evaluation returns the normalized value in `ConstraintResult`, which is
what a caller compares against an objective's target.

Design notes (what was mirrored vs written fresh)
-------------------------------------------------
* Mirrored from the core-spine canonical Julia evaluator
  (`julia-current/units.jl`, a DIFFERENT tree — not copied): the
  registry-as-`Dict{String, UnitDefinition}` shape, the
  `convert_units` returning `(value, reason)` instead of throwing, the
  `evaluate_constraint` keyword shape with required units, the range
  rule (inclusive with tolerance), and the `overall_from_checks`
  precedence (FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED > PASS, empty
  is NOT_CHECKED). All code below is written fresh to fit this
  component's struct-based design (`Constraint` / `Objective` /
  `ConstraintResult` structs mirroring Python's dataclasses), not
  pasted from the core-spine file.
* Deliberate differences from the core-spine file: (1) this registry
  has EXACTLY the 36 keys of Python `contracts/units.py` — the
  core-spine file adds a `"m³"` alias for `"m3"` which Python does not
  have, so it is NOT included here; a conformance test asserts the
  exact 36-key set. (2) Version checking follows Python
  (`adapters/python/contracts.py`) and Rust exactly: a malformed
  version string is rejected with the distinct message
  `"invalid schema version: <v>"`, while a well-formed different
  major is rejected with `"unsupported major schema version: <v>
  (supported major version 1)"` — the core-spine file conflates the
  two. (3) Unknown units at the wire boundary return UNKNOWN (Rust /
  core-spine behaviour) rather than raising at construction (Python
  `Constraint.__post_init__` raises `ValueError`); the native
  `Constraint` constructor still rejects a bad operator, negative
  tolerance, non-finite bounds, or inverted range bounds with
  `ArgumentError`, mirroring Python's construction-time checks.
* UNKNOWN / INCOMPLETE are never converted to PASS. Wire format stays
  JSON: `evaluate_constraint_request` takes / the tests read plain
  parsed-JSON dicts.
"""
module STARTPlanning

export SCHEMA_VERSION, SUPPORTED_SCHEMA_MAJOR, CHECK_STATUSES,
    UnitDefinition, UNIT_REGISTRY, unit_definition, convert_units,
    check_schema_version, Constraint, Objective, ConstraintResult,
    evaluate_constraint, evaluate_constraint_request, overall_from_checks

const SCHEMA_VERSION = strip(read(
    joinpath(@__DIR__, "..", "..", "..", "interop", "SCHEMA_VERSION"),
    String,
))

"""Major schema version this component speaks. Same-major patch/minor
versions are accepted per `interop/CONTRACT_VERSIONING.md`; only a major
mismatch is rejected, with a distinct error.

ISSUE-10/54 fix (2026-11-11): `SCHEMA_VERSION` is read from the single
source of truth `interop/SCHEMA_VERSION` at load time, not a second
hard-coded copy — the same file Python and Rust read. It is derived
from that file, so `SUPPORTED_SCHEMA_MAJOR` follows it. (Caveat: the
value is fixed when the module is precompiled; if the version file
ever changes without a Julia source change, delete the precompiled
cache or touch this file. The testset \"schema version: single source
of truth\" asserts the loaded value still matches the file.)"""
const SUPPORTED_SCHEMA_MAJOR = parse(Int, split(SCHEMA_VERSION, ".")[1])

"""The exact contract status vocabulary (interop/CONTRACT_VERSIONING.md)."""
const CHECK_STATUSES = ("PASS", "FAIL", "UNKNOWN", "NOT_CHECKED", "INCOMPLETE")

# ---------------------------------------------------------------- units ---

"""One registry entry: the dimension a unit belongs to and its factor to
that dimension's base unit."""
struct UnitDefinition
    dimension::String
    factor_to_base::Float64
end

"""Unit registry. Mirrors Python `contracts/units.py` `_UNITS` exactly:
the same 36 keys, the same dimension names, the same factors. Volume
base is m³ (factor 1.0), L factor 0.001. `kcal/day`,
`kcal/capita/day` and `kcal/person/day` are all dimension
`food_energy_rate_per_capita`, factor 1.0. Mass tonne `t` / `tonne`
factor 1000 (base kg); `Tg` / `Mt` / `million tonnes` factor 1e9.
Mass-per-year rates are dimension `mass_rate_year` (base Tg/yr), NOT
`mass_rate` — see the registry comments on ISSUE-34."""
const UNIT_REGISTRY = Dict{String, UnitDefinition}(
    "1" => UnitDefinition("dimensionless", 1.0),
    "person" => UnitDefinition("people", 1.0),
    "people" => UnitDefinition("people", 1.0),
    "kg" => UnitDefinition("mass", 1.0),
    "g" => UnitDefinition("mass", 0.001),
    "tonne" => UnitDefinition("mass", 1000.0),
    "t" => UnitDefinition("mass", 1000.0),
    "L" => UnitDefinition("volume", 0.001),
    "m3" => UnitDefinition("volume", 1.0),
    "m²" => UnitDefinition("area", 1.0),
    "ha" => UnitDefinition("area", 10000.0),
    "kcal" => UnitDefinition("energy", 1.0),
    "Mcal" => UnitDefinition("energy", 1000.0),
    "kWh" => UnitDefinition("energy", 860.4206501),
    "MWh" => UnitDefinition("energy", 860420.6501),
    "kcal/capita/day" => UnitDefinition("food_energy_rate_per_capita", 1.0),
    "kcal/person/day" => UnitDefinition("food_energy_rate_per_capita", 1.0),
    "kcal/day" => UnitDefinition("food_energy_rate_per_capita", 1.0),
    "m3/day" => UnitDefinition("volume_rate", 1.0),
    "L/day" => UnitDefinition("volume_rate", 0.001),
    "kg/day" => UnitDefinition("mass_rate", 1.0),
    "tonne/day" => UnitDefinition("mass_rate", 1000.0),
    "kWh/day" => UnitDefinition("energy_rate", 1.0),
    "MWh/day" => UnitDefinition("energy_rate", 1000.0),
    # ISSUE-34 (2026-11-13): teragramme-scale mass. 1 Tg = 1 Mt = 1e9 kg
    # exactly, so Tg and Mt convert 1:1.
    "Tg" => UnitDefinition("mass", 1e9),
    "Mt" => UnitDefinition("mass", 1e9),
    "million tonnes" => UnitDefinition("mass", 1e9),
    # ISSUE-34 (2026-11-13): mass-per-year rates live on their OWN
    # dimension "mass_rate_year" (base Tg/yr), NOT folded into
    # "mass_rate" (base per-day). Folding them in would smuggle in a
    # days-per-year assumption; Tg/yr and tonne/day are therefore NOT
    # interconvertible — a conversion would need a stated days-per-year.
    "Tg/yr" => UnitDefinition("mass_rate_year", 1.0),
    "Mt/yr" => UnitDefinition("mass_rate_year", 1.0),
    "tonne/yr" => UnitDefinition("mass_rate_year", 1e-6),
    "kg/yr" => UnitDefinition("mass_rate_year", 1e-9),
    # ISSUE-34 (2026-11-13): percent is dimensionless, factor 0.01 —
    # 33 percent = 0.33, compatible with "1".
    "percent" => UnitDefinition("dimensionless", 0.01),
    "%" => UnitDefinition("dimensionless", 0.01),
    # ISSUE-34 (2026-11-13): labour time rates. Base is hours/week;
    # 1 hour/day = 7 hours/week (7-day week). "hours" is total time in
    # the labour domain (dimension "time", base hour).
    "hours/week" => UnitDefinition("work_time_rate", 1.0),
    "hours/day" => UnitDefinition("work_time_rate", 7.0),
    "hours" => UnitDefinition("time", 1.0),
)

"""Registry lookup: the `UnitDefinition` for `unit`, or `nothing` when
the unit is not in the registry."""
function unit_definition(unit::AbstractString)
    return get(UNIT_REGISTRY, unit, nothing)
end

"""
    convert_units(value, source_unit, target_unit) -> (converted, reason)

Convert `value` from `source_unit` to `target_unit`, returning the
converted value and `"OK"`. On failure returns `(NaN, reason)` where
reason is `"unknown unit: <unit>"` or
`"incompatible units: <source> and <target>"` — the caller turns that
into UNKNOWN, never PASS.
"""
function convert_units(value::Real, source_unit::AbstractString,
                       target_unit::AbstractString)
    source_def = unit_definition(source_unit)
    source_def === nothing &&
        return (NaN, "unknown unit: $source_unit")
    target_def = unit_definition(target_unit)
    target_def === nothing &&
        return (NaN, "unknown unit: $target_unit")
    source_def.dimension != target_def.dimension &&
        return (NaN, "incompatible units: $source_unit and $target_unit")
    return (Float64(value) * source_def.factor_to_base /
            target_def.factor_to_base, "OK")
end

# ------------------------------------------------------- schema version ---

"""
    check_schema_version(version) -> (accepted::Bool, reason::String)

Accept `SCHEMA_VERSION` and any same-major `1.x.y` version (`"OK"`).
A well-formed different major is rejected with the distinct message
`"unsupported major schema version: <v> (supported major version 1)"`
— the exact string Python and Rust use. A malformed version string
(not three dot-separated numbers) is rejected with the distinct
message `"invalid schema version: <v>"`.
"""
function check_schema_version(version::AbstractString)
    parts = split(version, ".")
    if length(parts) != 3 ||
            any(p -> isempty(p) || !all(isdigit, p), parts)
        return (false, "invalid schema version: $version")
    end
    major = parse(Int, parts[1])
    if major != SUPPORTED_SCHEMA_MAJOR
        return (false, "unsupported major schema version: $version " *
                       "(supported major version $SUPPORTED_SCHEMA_MAJOR)")
    end
    return (true, "OK")
end

# ------------------------------------------------------------ contracts ---

"""A single checkable constraint, mirroring Python
`contracts/constraints.py` `Constraint`. `bound` is the bound for
`<=` / `>=` / `==`; `bound_low` / `bound_high` are the bounds for
`"range"`. Bounds are expressed in `unit`; `tolerance` widens the
passing interval (see `evaluate_constraint`)."""
Base.@kwdef struct Constraint
    constraint_id::String
    name::String = ""
    resource_id::Union{Nothing, String} = nothing
    operator::String = "<="
    bound::Union{Nothing, Real} = nothing
    bound_low::Union{Nothing, Real} = nothing
    bound_high::Union{Nothing, Real} = nothing
    unit::String = ""
    geography::String = "unspecified"
    period::String = "unspecified"
    source_ids::Vector{String} = String[]
    notes::String = ""
    tolerance::Real = 0.0

    function Constraint(constraint_id, name, resource_id, operator, bound,
                        bound_low, bound_high, unit, geography, period,
                        source_ids, notes, tolerance)
        operator in ("<=", ">=", "==", "range") ||
            throw(ArgumentError("unsupported constraint operator: $operator"))
        for (label, v) in (("bound", bound), ("bound_low", bound_low),
                           ("bound_high", bound_high),
                           ("tolerance", tolerance))
            if v !== nothing && (v isa Bool || !(v isa Real) || !isfinite(v))
                throw(ArgumentError("$label must be finite numeric"))
            end
        end
        tolerance < 0 &&
            throw(ArgumentError("tolerance cannot be negative"))
        if operator == "range" && bound_low !== nothing &&
                bound_high !== nothing && bound_low > bound_high
            throw(ArgumentError("range lower bound exceeds upper bound"))
        end
        return new(constraint_id, name, resource_id, operator, bound,
                   bound_low, bound_high, unit, geography, period,
                   source_ids, notes, tolerance)
    end
end

"""A declared community objective, mirroring Python
`contracts/constraints.py` `Objective`. Like Python's, this is a
representation only: it defines no evaluation and no objective value.
`direction` is `"maximize"`, `"minimize"` or `"target"`; a `"target"`
objective requires a `target` value."""
Base.@kwdef struct Objective
    objective_id::String
    name::String
    description::String = ""
    resource_id::Union{Nothing, String} = nothing
    direction::String = "maximize"
    target::Union{Nothing, Real} = nothing
    unit::String = ""
    weight::Union{Nothing, Real} = nothing
    source_ids::Vector{String} = String[]

    function Objective(objective_id, name, description, resource_id,
                       direction, target, unit, weight, source_ids)
        direction in ("maximize", "minimize", "target") ||
            throw(ArgumentError("direction must be maximize, minimize, or target"))
        direction == "target" && target === nothing &&
            throw(ArgumentError("target objective requires a target value"))
        for (label, v) in (("target", target), ("weight", weight))
            if v !== nothing && (v isa Bool || !(v isa Real) || !isfinite(v))
                throw(ArgumentError("$label must be finite numeric"))
            end
        end
        weight !== nothing && weight < 0 &&
            throw(ArgumentError("objective weight cannot be negative"))
        if !isempty(unit) && unit_definition(unit) === nothing
            throw(ArgumentError("unknown objective unit: $unit"))
        end
        return new(objective_id, name, description, resource_id,
                   direction, target, unit, weight, source_ids)
    end
end

"""The result of evaluating one constraint: the exact five-status
vocabulary as a String, the value converted into the bound's unit
(`nothing` when no check was performed), and a machine-readable
`reason_code` (`"OK"` on a performed check)."""
struct ConstraintResult
    schema_version::String
    constraint_id::String
    status::String
    normalized_value::Union{Nothing, Float64}
    normalized_unit::Union{Nothing, String}
    reason_code::String
    details::String
end

"""
    evaluate_constraint(c::Constraint, value, value_unit=nothing)
        -> ConstraintResult

Evaluate one constraint, mirroring Python `Constraint.evaluate`
exactly:

* a missing / non-finite value → UNKNOWN, never PASS;
* a supplied `value_unit` that is not a known registry unit →
  UNKNOWN, even when the constraint itself declares no unit (ISSUE-07
  fix, 2026-11-11: Rust rejects any unknown unit string, and a
  unit-less constraint used to let one through into a raw-number
  PASS; a *known* `value_unit` on a unit-less constraint is still
  ignored — raw comparison — as there is no target unit to convert
  into; Python mirrors this);
* when the constraint has a unit and no `value_unit` is supplied →
  UNKNOWN (Python returns UNKNOWN; it never compares raw numbers
  while ignoring the supplied unit);
* unknown or incompatible units → UNKNOWN, never PASS;
* `"range"` needs both bounds (missing bounds → UNKNOWN) and is
  INCLUSIVE with tolerance:
  `bound_low - tolerance <= value <= bound_high + tolerance`;
* `"<="` passes when `value <= bound + tolerance`;
  `">="` passes when `value >= bound - tolerance`;
* `"=="` passes when `abs(value - bound) <= tolerance` (Python
  `math.isclose` with `rel_tol=0`, `abs_tol=tolerance`).

The value is converted from `value_unit` to the constraint's `unit`
before comparison, so the food domain's `>=` constraint evaluates
with its real meaning, not inverted.
"""
function evaluate_constraint(c::Constraint, value,
                             value_unit::Union{Nothing, AbstractString}=nothing)
    unknown(reason_code, details) = ConstraintResult(
        SCHEMA_VERSION, c.constraint_id, "UNKNOWN", nothing, nothing,
        reason_code, details)
    if isempty(strip(c.constraint_id))
        return unknown("INVALID_REQUEST", "empty constraint_id")
    end
    if value === nothing || value isa Bool || !(value isa Real) ||
            !isfinite(value)
        return unknown("NON_FINITE", "value must be a finite number")
    end
    if value_unit !== nothing &&
            unit_definition(string(value_unit)) === nothing
        return unknown("UNKNOWN_UNIT", "unknown unit: $value_unit")
    end
    if c.operator == "range"
        if c.bound_low === nothing || c.bound_high === nothing
            # ISSUE-51 fix (2026-11-11): the code is INVALID_REQUEST,
            # not MISSING_BOUND — MISSING_BOUND is not in the result
            # schema's reason_code enum
            # (interop/schemas/constraint-evaluation-result.schema.json),
            # and Rust reports the same case as INVALID_REQUEST. The
            # distinct cause stays in `details`.
            return unknown("INVALID_REQUEST", "range requires bound_low and bound_high")
        end
    elseif c.bound === nothing
        return unknown("INVALID_REQUEST", "missing bound for operator $(c.operator)")
    end
    if !isempty(c.unit)
        if value_unit === nothing || isempty(string(value_unit))
            # ISSUE-51 fix (2026-11-11): INVALID_REQUEST, not
            # MISSING_UNIT — same schema-enum reason as above.
            return unknown("INVALID_REQUEST", "value_unit is required when the constraint has a unit")
        end
        converted, reason = convert_units(value, string(value_unit), c.unit)
        if reason != "OK"
            code = startswith(reason, "unknown unit") ? "UNKNOWN_UNIT" : "INCOMPATIBLE_UNIT"
            return unknown(code, reason)
        end
    else
        converted = Float64(value)
    end
    if !isfinite(converted)
        return unknown("NON_FINITE", "normalized value must be finite")
    end
    tol = Float64(c.tolerance)
    ok = if c.operator == "<="
        converted <= Float64(c.bound) + tol
    elseif c.operator == ">="
        converted >= Float64(c.bound) - tol
    elseif c.operator == "=="
        abs(converted - Float64(c.bound)) <= tol
    elseif c.operator == "range"
        Float64(c.bound_low) - tol <= converted <= Float64(c.bound_high) + tol
    else
        return unknown("UNSUPPORTED_OPERATOR", "unsupported operator: $(c.operator)")
    end
    return ConstraintResult(SCHEMA_VERSION, c.constraint_id,
        ok ? "PASS" : "FAIL", converted, isempty(c.unit) ? nothing : c.unit,
        "OK", "Evaluated using finite inputs and reviewed-unit conversion")
end

"""
    evaluate_constraint_request(req) -> ConstraintResult

Evaluate one wire request (a parsed-JSON dict in the
`interop/schemas/constraint-evaluation.schema.json` shape:
`schema_version`, `constraint_id`, `operator`, `value`,
`value_unit`, `bound_unit`, `tolerance`, plus `bound` for
`<=` / `>=` / `==` or `bound_low` / `bound_high` for `"range"`).
Never throws on wire data: a malformed request returns UNKNOWN with
reason code `INVALID_REQUEST` (or `UNSUPPORTED_MAJOR_VERSION` with
the exact distinct message for a major mismatch, `NON_FINITE` for a
non-finite numeric input — ISSUE-51, finiteness before sign, mirroring
Rust's ISSUE-52 fix), never PASS. Every `reason_code` this function
or `evaluate_constraint` emits is in the result schema's enum
(`interop/schemas/constraint-evaluation-result.schema.json`); the
testset "ISSUE-51: every emitted reason_code is in the result-schema
enum" enforces that against the schema file itself.
"""
function evaluate_constraint_request(req::AbstractDict)
    fallback_id = string(get(req, "constraint_id", ""))
    unknown(reason_code, details) = ConstraintResult(
        SCHEMA_VERSION, fallback_id, "UNKNOWN", nothing, nothing,
        reason_code, details)
    for key in ("schema_version", "constraint_id", "operator", "value",
                "value_unit", "bound_unit", "tolerance")
        haskey(req, key) ||
            return unknown("INVALID_REQUEST", "missing required field: $key")
    end
    version = req["schema_version"]
    version isa AbstractString ||
        return unknown("INVALID_REQUEST", "invalid schema version: $version")
    accepted, reason = check_schema_version(version)
    if !accepted
        code = startswith(reason, "unsupported major schema version") ?
            "UNSUPPORTED_MAJOR_VERSION" : "INVALID_REQUEST"
        return unknown(code, reason)
    end
    constraint_id = req["constraint_id"]
    constraint_id isa AbstractString && !isempty(strip(constraint_id)) ||
        return unknown("INVALID_REQUEST", "constraint_id must be a non-empty string")
    operator = req["operator"]
    operator in ("<=", ">=", "==", "range") ||
        return unknown("INVALID_REQUEST", "unsupported operator: $operator")
    value = req["value"]
    if value isa Bool || !(value isa Real) || !isfinite(value)
        return unknown("NON_FINITE", "value must be a finite number")
    end
    tolerance = req["tolerance"]
    # ISSUE-51 fix (2026-11-11): finiteness BEFORE the sign check,
    # mirroring Rust's ISSUE-52 fix — a non-finite tolerance is
    # NON_FINITE, not INVALID_REQUEST; only a negative FINITE
    # tolerance is INVALID_REQUEST. (A wrong-typed tolerance is
    # INVALID_REQUEST.)
    if tolerance isa Bool || !(tolerance isa Real)
        return unknown("INVALID_REQUEST", "tolerance must be a finite number >= 0")
    end
    if !isfinite(tolerance)
        return unknown("NON_FINITE", "tolerance must be a finite number")
    end
    if tolerance < 0
        return unknown("INVALID_REQUEST", "tolerance cannot be negative")
    end
    for key in ("value_unit", "bound_unit")
        req[key] isa AbstractString && !isempty(strip(req[key])) ||
            return unknown("INVALID_REQUEST", "$key must be a non-empty string")
    end
    if operator == "range"
        for key in ("bound_low", "bound_high")
            haskey(req, key) ||
                return unknown("INVALID_REQUEST", "missing required field: $key")
            if req[key] isa Bool || !(req[key] isa Real) || !isfinite(req[key])
                return unknown("NON_FINITE", "$key must be a finite number")
            end
        end
        req["bound_low"] > req["bound_high"] &&
            return unknown("INVALID_REQUEST", "range lower bound exceeds upper bound")
        c = Constraint(constraint_id=string(constraint_id), operator="range",
                       bound_low=req["bound_low"], bound_high=req["bound_high"],
                       unit=string(req["bound_unit"]),
                       tolerance=Float64(tolerance))
    else
        haskey(req, "bound") ||
            return unknown("INVALID_REQUEST", "missing required field: bound")
        if req["bound"] isa Bool || !(req["bound"] isa Real) ||
                !isfinite(req["bound"])
            return unknown("NON_FINITE", "bound must be a finite number")
        end
        c = Constraint(constraint_id=string(constraint_id),
                       operator=string(operator), bound=req["bound"],
                       unit=string(req["bound_unit"]),
                       tolerance=Float64(tolerance))
    end
    return evaluate_constraint(c, value, string(req["value_unit"]))
end

"""
    overall_from_checks(statuses) -> String

Aggregate check statuses, mirroring Python
`contracts/statuses.py` `overall_from_checks` exactly: empty →
NOT_CHECKED (never PASS); FAIL wins, then INCOMPLETE, then UNKNOWN,
then NOT_CHECKED; otherwise PASS. An unrecognised status falls
through to UNKNOWN, never PASS.
"""
function overall_from_checks(statuses)
    isempty(statuses) && return "NOT_CHECKED"
    "FAIL" in statuses && return "FAIL"
    "INCOMPLETE" in statuses && return "INCOMPLETE"
    "UNKNOWN" in statuses && return "UNKNOWN"
    "NOT_CHECKED" in statuses && return "NOT_CHECKED"
    all(s -> s == "PASS", statuses) && return "PASS"
    return "UNKNOWN"
end

end # module
