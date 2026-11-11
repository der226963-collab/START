# ORIGINAL START code (2026-11-11) — canonical unit registry, constraint
# evaluation, aggregation, and schema-version check for the Julia
# core-spine.
#
# This is the ONE canonical implementation shared by every Julia
# evaluator: spine.jl / spine_lp.jl / spine_ode.jl (standalone
# scripts, via include) and planning-search/verify.jl (via
# PlanningSearch.jl, which includes this file before verify.jl).
# Do NOT copy these definitions into another file: include this
# one. The pinned envs julia/ and julia-1.11/ have their own
# copies of the old unit-free evaluator and are EVIDENCE ONLY —
# they are never updated.
#
# Rules (Eric's 2026-11-11 test-vector decisions, matching the
# Python contracts in v0.3.2 review copy contracts/units.py,
# contracts/constraints.py, contracts/statuses.py, and the Rust
# secondary verifier — all three languages must agree):
#  * Units are explicit. A constraint evaluation takes
#    value_unit and bound_unit (required keywords — omitting
#    them is a loud UndefKeywordError, never a silent
#    unit-free comparison). Unknown units -> UNKNOWN, never
#    PASS. Incompatible dimensions -> UNKNOWN, never PASS.
#    This fixes the 2026-11-11 finding that the old unit-free
#    evaluator silently PASSED 5 L <= 10 kg, and passed
#    0.008 m3 <= 10 L for the wrong reason (raw-number
#    comparison, not conversion — it would also have passed
#    0.02 m3 against 10 L, where conversion gives 20 L > 10 L
#    and the correct verdict is FAIL).
#  * Registry mirrors Python's contracts/units.py exactly,
#    plus a "m³" alias for "m3" (the wire cases use "m3").
#    Volume base is m3 (factor 1.0), L factor 0.001.
#    kcal/day, kcal/capita/day and kcal/person/day are all
#    dimension "food_energy_rate_per_capita", factor 1.0.
#    Mass tonne "t"/"tonne" factor 1000 (base kg).
#  * Range operator: "range" with bound_low/bound_high (in
#    bound_unit), INCLUSIVE with tolerance, mirroring
#    Python/Rust: bound_low - tolerance <= value <=
#    bound_high + tolerance. Missing bounds -> UNKNOWN, never
#    PASS. Inverted bounds (low > high) -> UNKNOWN, never PASS.
#  * Aggregation (overall_status) follows Python's
#    overall_from_checks exactly: empty -> NOT_CHECKED, FAIL
#    wins, then INCOMPLETE, then UNKNOWN, then NOT_CHECKED,
#    else PASS. (The old Julia rule collapsed INCOMPLETE and
#    NOT_CHECKED into UNKNOWN; that differed from Python and
#    is corrected here.)
#  * Schema versions: any same-major 1.x.y is accepted;
#    another major is rejected with the DISTINCT message
#    "unsupported major schema version: <v> (supported major
#    version 1)" — the exact string Python and Rust use.
#    See interop/CONTRACT_VERSIONING.md (patch/minor are
#    compatible within a major; only a major mismatch is
#    rejected).
#  * UNKNOWN / INCOMPLETE are never converted to PASS. The
#    1e-6 tolerance convention for LP floating-point noise in
#    verify.jl is a caller-side tolerance argument and is
#    untouched by this file.
#
# No new dependencies: stdlib only. Wire format stays JSON
# (Julia tests read the wire cases as data).

"""One registry entry: the dimension a unit belongs to and its
factor to that dimension's base unit."""
struct UnitDefinition
    dimension::String
    factor_to_base::Float64
end

"""Canonical unit registry. Mirrors Python contracts/units.py
(one entry added: "m³" as an alias for "m3")."""
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
    "m³" => UnitDefinition("volume", 1.0),
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
)

"""Registry lookup: the UnitDefinition for `unit`, or `nothing`
when the unit is not in the registry."""
function unit_definition(unit::AbstractString)
    return get(UNIT_REGISTRY, unit, nothing)
end

"""
    convert_units(value, source_unit, target_unit)
        -> (converted::Float64, reason::String)

Convert `value` from `source_unit` to `target_unit`, returning
the converted value and "OK". On failure returns
`(NaN, reason)` where reason is "unknown unit: <unit>" or
"incompatible units: <source> and <target>" — the caller turns
that into UNKNOWN, never PASS.
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

const SUPPORTED_SCHEMA_MAJOR = 1

"""
    check_schema_version(version) -> (accepted::Bool, reason::String)

Pure function. Any same-major 1.x.y version is accepted
("OK"). Any other major is rejected with the distinct
message "unsupported major schema version: <v> (supported
major version 1)" — the exact string Python and Rust use.
An unparseable version is rejected with the same message.
"""
function check_schema_version(version::AbstractString)
    parts = split(version, ".")
    major = isempty(parts) ? nothing : tryparse(Int, parts[1])
    if major === nothing || major != SUPPORTED_SCHEMA_MAJOR
        return (false, "unsupported major schema version: $version " *
                       "(supported major version $SUPPORTED_SCHEMA_MAJOR)")
    end
    return (true, "OK")
end

"""
    evaluate_constraint(; constraint_id, operator, value, bound=nothing,
                        value_unit, bound_unit, tolerance=0.0,
                        bound_low=nothing, bound_high=nothing)
        -> (status::String, reason::String)

Evaluate one constraint with explicit units. `value_unit` and
`bound_unit` are REQUIRED keywords: there is no unit-free
comparison anywhere in this evaluator. Returns ("PASS"/"FAIL",
"OK") or ("UNKNOWN", reason) — UNKNOWN, never PASS, for an
empty constraint_id, a non-finite value/bound, an unknown or
incompatible unit, an unsupported operator, a missing bound,
or (for "range") missing or inverted bounds.

Operators: "<=", ">=", "==" (within `tolerance`), and "range"
(bound_low/bound_high in `bound_unit`, inclusive with
tolerance: bound_low - tolerance <= value <= bound_high +
tolerance). `value` is converted from `value_unit` to
`bound_unit` before comparison.
"""
function evaluate_constraint(; constraint_id, operator, value, bound=nothing,
                               value_unit, bound_unit, tolerance=0.0,
                               bound_low=nothing, bound_high=nothing)
    if isempty(constraint_id)
        return ("UNKNOWN", "empty constraint_id")
    end
    if value isa Bool || !(value isa Real) || !isfinite(value)
        return ("UNKNOWN", "non-finite value or bound")
    end
    if operator == "range"
        if bound_low === nothing || bound_high === nothing
            return ("UNKNOWN", "range bounds missing")
        end
        if bound_low isa Bool || bound_high isa Bool ||
                !(bound_low isa Real) || !(bound_high isa Real) ||
                !isfinite(bound_low) || !isfinite(bound_high)
            return ("UNKNOWN", "non-finite value or bound")
        end
        if bound_low > bound_high
            return ("UNKNOWN", "inverted range bounds")
        end
    else
        if bound === nothing || bound isa Bool ||
                !(bound isa Real) || !isfinite(bound)
            return ("UNKNOWN", "non-finite value or bound")
        end
    end
    if value_unit === nothing || bound_unit === nothing ||
            isempty(string(value_unit)) || isempty(string(bound_unit))
        return ("UNKNOWN", "missing unit")
    end
    converted, reason = convert_units(value, string(value_unit),
                                      string(bound_unit))
    if reason != "OK"
        return ("UNKNOWN", reason)
    end
    if !isfinite(converted)
        return ("UNKNOWN", "non-finite value or bound")
    end
    ok = if operator == "<="
        converted <= bound + tolerance
    elseif operator == ">="
        converted >= bound - tolerance
    elseif operator == "=="
        abs(converted - bound) <= tolerance
    elseif operator == "range"
        bound_low - tolerance <= converted <= bound_high + tolerance
    else
        return ("UNKNOWN", "unsupported operator: $operator")
    end
    return (ok ? "PASS" : "FAIL", "OK")
end

"""
    overall_status(statuses) -> String

Aggregate statuses, following Python's overall_from_checks
exactly: empty -> NOT_CHECKED (never PASS); FAIL wins; then
INCOMPLETE, then UNKNOWN, then NOT_CHECKED; otherwise PASS.
An unrecognised status falls through to UNKNOWN, never PASS.
"""
function overall_status(statuses)
    isempty(statuses) && return "NOT_CHECKED"
    "FAIL" in statuses && return "FAIL"
    "INCOMPLETE" in statuses && return "INCOMPLETE"
    "UNKNOWN" in statuses && return "UNKNOWN"
    "NOT_CHECKED" in statuses && return "NOT_CHECKED"
    all(s -> s == "PASS", statuses) && return "PASS"
    return "UNKNOWN"
end
