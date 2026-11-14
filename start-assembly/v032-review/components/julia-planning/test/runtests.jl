# Tests for the ISSUE-05 faithful Constraint implementation.
# Drives the shared interop/test-vectors.json cases (all 14 wire + 2
# aggregation + 3 version cases) through the Julia evaluator and asserts
# agreement with the Python/Rust verified values pinned in the file.
using Test
using JSON
using STARTPlanning

const VECTORS_PATH = joinpath(@__DIR__, "..", "..", "..", "interop", "test-vectors.json")

# Verified-status fields are dated (e.g. "python_verified_2026-11-11");
# newer cases carry a later date (ISSUE-34 cases: 2026-11-13). Pick
# the latest dated field so old and new cases are both read correctly.
function verified_status(case, lang)
    prefix = lang * "_verified_"
    dated = [k for k in keys(case) if startswith(k, prefix)]
    isempty(dated) && error("no $lang verified field in case $(case["id"])")
    return case[sort(dated)[end]]["status"]
end

# The exact 36 keys of Python contracts/units.py `_UNITS` (ISSUE-06
# conformance; ISSUE-34 added 12 keys 2026-11-13). Any key present in
# one registry and not the other is a test failure — same rule as the
# Rust conformance test.
const PYTHON_UNIT_KEYS = Set([
    "1", "person", "people", "kg", "g", "tonne", "t", "L", "m3", "m²",
    "ha", "kcal", "Mcal", "kWh", "MWh", "kcal/capita/day",
    "kcal/person/day", "kcal/day", "m3/day", "L/day", "kg/day",
    "tonne/day", "kWh/day", "MWh/day",
    "Tg", "Mt", "million tonnes", "Tg/yr", "Mt/yr", "tonne/yr",
    "kg/yr", "percent", "%", "hours/week", "hours/day", "hours",
])

@testset "unit registry mirrors Python exactly" begin
    @test Set(keys(UNIT_REGISTRY)) == PYTHON_UNIT_KEYS
    @test length(UNIT_REGISTRY) == 36
    # Spot-check dimensions and factors against Python.
    @test unit_definition("t") == UnitDefinition("mass", 1000.0)
    @test unit_definition("L") == UnitDefinition("volume", 0.001)
    @test unit_definition("m3") == UnitDefinition("volume", 1.0)
    @test unit_definition("kcal/day") ==
        UnitDefinition("food_energy_rate_per_capita", 1.0)
    @test unit_definition("kWh") == UnitDefinition("energy", 860.4206501)
    @test unit_definition("bucket") === nothing
    @test convert_units(0.008, "m3", "L") == (8.0, "OK")
    @test convert_units(5.0, "L", "kg")[2] == "incompatible units: L and kg"
    @test convert_units(5.0, "bucket", "kg")[2] == "unknown unit: bucket"
    # ISSUE-34 (2026-11-13): the 12 new units.
    @test unit_definition("Tg") == UnitDefinition("mass", 1e9)
    @test unit_definition("Mt") == UnitDefinition("mass", 1e9)
    @test unit_definition("million tonnes") == UnitDefinition("mass", 1e9)
    @test unit_definition("Tg/yr") == UnitDefinition("mass_rate_year", 1.0)
    @test unit_definition("tonne/yr") == UnitDefinition("mass_rate_year", 1e-6)
    @test unit_definition("kg/yr") == UnitDefinition("mass_rate_year", 1e-9)
    @test unit_definition("percent") == UnitDefinition("dimensionless", 0.01)
    @test unit_definition("%") == UnitDefinition("dimensionless", 0.01)
    @test unit_definition("hours/week") == UnitDefinition("work_time_rate", 1.0)
    @test unit_definition("hours/day") == UnitDefinition("work_time_rate", 7.0)
    @test unit_definition("hours") == UnitDefinition("time", 1.0)
    # Tg <-> Mt 1:1; 1 Tg = 1e9 kg; tonne/yr <-> kg/yr.
    @test convert_units(1.0, "Tg", "Mt") == (1.0, "OK")
    @test convert_units(1.0, "Mt", "Tg") == (1.0, "OK")
    @test convert_units(1.0, "Tg", "kg") == (1e9, "OK")
    # tonne/yr -> kg/yr divides by inexact 1e-9, so 1.0 * 1e-6 / 1e-9
    # comes out 999.9999999999999, not 1000.0 — approximate.
    @test convert_units(1.0, "tonne/yr", "kg/yr")[1] ≈ 1000.0
    @test convert_units(1.0, "kg/yr", "tonne/yr") == (0.001, "OK")
    # 33 percent = 0.33 dimensionless.
    @test convert_units(33.0, "percent", "1") == (0.33, "OK")
    @test convert_units(33.0, "%", "1") == (0.33, "OK")
    # 1 hour/day = 7 hours/week (7-day week).
    @test convert_units(1.0, "hours/day", "hours/week") == (7.0, "OK")
    @test convert_units(7.0, "hours/week", "hours/day") == (1.0, "OK")
    # Cross-dimension: Tg/yr vs tonne/day must NOT convert — different
    # dimensions (mass_rate_year vs mass_rate); a conversion would
    # need a stated days-per-year.
    @test convert_units(5.0, "Tg/yr", "tonne/day")[2] ==
        "incompatible units: Tg/yr and tonne/day"
    # Overflow on conversion never passes: 1e308 Tg converted to g
    # overflows to Inf, which is UNKNOWN / NON_FINITE, never PASS
    # (ISSUE-47 behaviour, checked here for the new Tg unit too).
    big_tg = Constraint(constraint_id="big-tg", operator="<=",
                        bound=10.0, unit="g")
    big_tg_out = evaluate_constraint(big_tg, 1e308, "Tg")
    @test big_tg_out.status == "UNKNOWN"
    @test big_tg_out.reason_code == "NON_FINITE"
end

@testset "food domain >= constraint evaluates with its real meaning" begin
    # domains/food/production.py:95 — operator ">=", bound = requirement.
    # Under the old slack semantics this came out :candidate_infeasible.
    food = Constraint(constraint_id="food_energy_adequacy",
        name="Per-capita food energy meets stated requirement",
        resource_id="food_energy", operator=">=",
        bound=2500.0, unit="kcal/capita/day")
    @test evaluate_constraint(food, 2800.0, "kcal/capita/day").status == "PASS"
    @test evaluate_constraint(food, 2400.0, "kcal/capita/day").status == "FAIL"
    # Same constraint in the invented-but-decided kcal/day unit.
    food_day = Constraint(constraint_id="kday", operator=">=",
        bound=2500.0, unit="kcal/day")
    @test evaluate_constraint(food_day, 2800.0, "kcal/day").status == "PASS"
end

@testset "operators, tolerance and range" begin
    le = Constraint(constraint_id="le", operator="<=", bound=10.0, unit="L")
    @test evaluate_constraint(le, 8.0, "L").status == "PASS"
    @test evaluate_constraint(le, 12.0, "L").status == "FAIL"
    # Tolerance widens the passing interval, exactly as Python does.
    @test evaluate_constraint(
        Constraint(constraint_id="le-tol", operator="<=", bound=10.0,
                   unit="L", tolerance=2.5), 12.5, "L").status == "PASS"
    @test evaluate_constraint(
        Constraint(constraint_id="le-tol", operator="<=", bound=10.0,
                   unit="L", tolerance=2.5), 12.6, "L").status == "FAIL"
    eq = Constraint(constraint_id="eq", operator="==", bound=10.0,
                    unit="kg", tolerance=0.5)
    @test evaluate_constraint(eq, 10.4, "kg").status == "PASS"
    @test evaluate_constraint(eq, 10.6, "kg").status == "FAIL"
    # ISSUE-42 (Julia part): exact boundaries. value == bound passes
    # for <= and >=; == with zero tolerance passes only on exact
    # equality; range with tolerance passes exactly at bound_low - tol
    # and fails just below it.
    @test evaluate_constraint(le, 10.0, "L").status == "PASS"
    ge = Constraint(constraint_id="ge", operator=">=", bound=10.0, unit="L")
    @test evaluate_constraint(ge, 10.0, "L").status == "PASS"
    @test evaluate_constraint(ge, 9.9, "L").status == "FAIL"
    eq0 = Constraint(constraint_id="eq0", operator="==", bound=10.0,
                     unit="kg", tolerance=0.0)
    @test evaluate_constraint(eq0, 10.0, "kg").status == "PASS"
    @test evaluate_constraint(eq0, 10.1, "kg").status == "FAIL"
    rng_tol = Constraint(constraint_id="rng-tol", operator="range",
                         bound_low=2.0, bound_high=8.0, unit="L",
                         tolerance=0.5)
    @test evaluate_constraint(rng_tol, 1.5, "L").status == "PASS"
    @test evaluate_constraint(rng_tol, 1.4, "L").status == "FAIL"
    @test evaluate_constraint(rng_tol, 8.5, "L").status == "PASS"
    @test evaluate_constraint(rng_tol, 8.6, "L").status == "FAIL"
    # Overflow on conversion never passes: 1e308 tonne converted to g
    # overflows to Inf, which is UNKNOWN / NON_FINITE, never PASS.
    big = Constraint(constraint_id="big", operator="<=", bound=10.0, unit="g")
    big_out = evaluate_constraint(big, 1e308, "tonne")
    @test big_out.status == "UNKNOWN"
    @test big_out.reason_code == "NON_FINITE"
    rng = Constraint(constraint_id="rng", operator="range",
                     bound_low=2.0, bound_high=8.0, unit="L")
    @test evaluate_constraint(rng, 5.0, "L").status == "PASS"
    @test evaluate_constraint(rng, 2.0, "L").status == "PASS"  # inclusive
    @test evaluate_constraint(rng, 8.0, "L").status == "PASS"  # inclusive
    @test evaluate_constraint(rng, 1.0, "L").status == "FAIL"
    @test evaluate_constraint(rng, 9.0, "L").status == "FAIL"
    # Discriminating volume case (in the test-vectors note, not a wire
    # case): 0.02 m³ = 20 L > 10 L must FAIL, not PASS.
    vol = Constraint(constraint_id="vol", operator="<=", bound=10.0, unit="L")
    @test evaluate_constraint(vol, 0.008, "m3").status == "PASS"
    @test evaluate_constraint(vol, 0.02, "m3").status == "FAIL"
    @test evaluate_constraint(vol, 0.02, "m3").normalized_value == 20.0
end

@testset "UNKNOWN never becomes PASS" begin
    c = Constraint(constraint_id="c", operator="<=", bound=10.0, unit="L")
    # Incompatible units: 5 L vs 10 kg (old kernel wrongly PASSED this).
    incomp = Constraint(constraint_id="incomp", operator="<=",
                        bound=10.0, unit="kg")
    @test evaluate_constraint(incomp, 5.0, "L").status == "UNKNOWN"
    @test evaluate_constraint(incomp, 5.0, "L").reason_code ==
        "INCOMPATIBLE_UNIT"
    # Unknown unit.
    @test evaluate_constraint(c, 5.0, "bucket").status == "UNKNOWN"
    # Non-finite value.
    @test evaluate_constraint(c, NaN, "L").status == "UNKNOWN"
    @test evaluate_constraint(c, Inf, "L").status == "UNKNOWN"
    # Missing value_unit while the constraint has a unit.
    @test evaluate_constraint(c, 5.0).status == "UNKNOWN"
    # Missing bound for a non-range operator.
    nobound = Constraint(constraint_id="nb", operator="<=", unit="L")
    @test evaluate_constraint(nobound, 5.0, "L").status == "UNKNOWN"
    # ISSUE-51: missing bound / missing unit are INVALID_REQUEST —
    # the code is in the result schema's reason_code enum (the old
    # MISSING_BOUND / MISSING_UNIT codes were not), matching Rust.
    # The distinct cause stays in `details`.
    @test evaluate_constraint(nobound, 5.0, "L").reason_code ==
        "INVALID_REQUEST"
    @test evaluate_constraint(nobound, 5.0, "L").details ==
        "missing bound for operator <="
    # Missing range bounds.
    norange = Constraint(constraint_id="nr", operator="range", unit="L")
    @test evaluate_constraint(norange, 5.0, "L").status == "UNKNOWN"
    @test evaluate_constraint(norange, 5.0, "L").reason_code ==
        "INVALID_REQUEST"
    @test evaluate_constraint(norange, 5.0, "L").details ==
        "range requires bound_low and bound_high"
    # Missing value_unit while the constraint has a unit (status
    # asserted above).
    @test evaluate_constraint(c, 5.0).reason_code == "INVALID_REQUEST"
    @test evaluate_constraint(c, 5.0).details ==
        "value_unit is required when the constraint has a unit"
    @test evaluate_constraint(
        Constraint(constraint_id="", operator="<=", bound=10.0,
                   unit="L"), 5.0, "L").status == "UNKNOWN"
    # Construction-time checks mirror Python __post_init__.
    @test_throws ArgumentError Constraint(constraint_id="x", operator="!=",
        bound=1.0, unit="L")
    @test_throws ArgumentError Constraint(constraint_id="x", operator="<=",
        bound=1.0, unit="L", tolerance=-1.0)
    @test_throws ArgumentError Constraint(constraint_id="x", operator="range",
        bound_low=8.0, bound_high=2.0, unit="L")
    # Every status produced here is in the exact five-status vocabulary.
    for s in ["PASS", "FAIL", "UNKNOWN"]
        @test s in CHECK_STATUSES
    end
end

@testset "ISSUE-07: every emitted status is in the exact five-status vocabulary" begin
    # Same matrix as Python tests/test_issue07_status_mapping.py and
    # Rust lib.rs (issue07_* tests): evaluator level returns UNKNOWN,
    # never PASS, never throws; the wire level rejects malformed
    # requests with a reason (here: an UNKNOWN result with
    # INVALID_REQUEST / UNSUPPORTED_MAJOR_VERSION — Python expresses
    # the same rejection as a raised ValueError); an empty check list
    # aggregates to NOT_CHECKED. Full mapping + rationale:
    # docs/STATUS_MAPPING_ISSUE-07.md. Every status produced below is
    # collected and asserted to be in CHECK_STATUSES.
    seen = String[]
    note(r) = (push!(seen, r.status); r)
    c = Constraint(constraint_id="c", operator="<=", bound=10.0, unit="L")
    # Evaluator: non-finite / missing / wrong-typed values.
    @test note(evaluate_constraint(c, NaN, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, Inf, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, -Inf, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, nothing, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, true, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, "5", "L")).status == "UNKNOWN"
    # Evaluator: unknown / incompatible units.
    @test note(evaluate_constraint(c, 5.0, "bucket")).status == "UNKNOWN"
    @test note(evaluate_constraint(c, 5.0, "bucket")).reason_code ==
        "UNKNOWN_UNIT"
    @test note(evaluate_constraint(
        Constraint(constraint_id="u", operator="<=", bound=10.0,
                   unit="bucket"), 5.0, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(
        Constraint(constraint_id="i", operator="<=", bound=10.0,
                   unit="kg"), 5.0, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(
        Constraint(constraint_id="i", operator="<=", bound=10.0,
                   unit="kg"), 5.0, "L")).reason_code ==
        "INCOMPATIBLE_UNIT"
    @test note(evaluate_constraint(c, 5.0)).status == "UNKNOWN"  # no value_unit
    # Evaluator: missing bounds.
    @test note(evaluate_constraint(
        Constraint(constraint_id="nb", operator="<=", unit="L"),
        5.0, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(
        Constraint(constraint_id="nr", operator="range", unit="L"),
        5.0, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(
        Constraint(constraint_id="nr", operator="range", bound_low=2.0,
                   unit="L"), 5.0, "L")).status == "UNKNOWN"
    # Evaluator: empty / whitespace constraint_id identifies no check.
    @test note(evaluate_constraint(
        Constraint(constraint_id="", operator="<=", bound=10.0,
                   unit="L"), 5.0, "L")).status == "UNKNOWN"
    @test note(evaluate_constraint(
        Constraint(constraint_id="   ", operator="<=", bound=10.0,
                   unit="L"), 5.0, "L")).status == "UNKNOWN"
    # Evaluator: unit-less constraint. A supplied unit string must be
    # a known registry unit even here (fixed 2026-11-11: it used to
    # PASS on the raw numbers — the same fix as Python). A known
    # value_unit, or none at all, still compares raw numbers: there
    # is no target unit to convert into, and Rust has no unit-less
    # wire form at all.
    unitless = Constraint(constraint_id="ul", operator="<=",
                          bound=10.0, unit="")
    @test note(evaluate_constraint(unitless, 5.0, "bucket")).status == "UNKNOWN"
    @test note(evaluate_constraint(unitless, 5.0, "")).status == "UNKNOWN"
    @test note(evaluate_constraint(unitless, 5.0)).status == "PASS"
    @test note(evaluate_constraint(unitless, 5.0, "L")).status == "PASS"
    @test note(evaluate_constraint(unitless, 12.0)).status == "FAIL"
    # Evaluator: valid checks still decide.
    @test note(evaluate_constraint(c, 8.0, "L")).status == "PASS"
    @test note(evaluate_constraint(c, 12.0, "L")).status == "FAIL"
    # Construction stays fail-fast (ArgumentError), mirroring
    # Python's ValueError; Rust has no fallible constructor and
    # reports the same inputs as UNKNOWN at evaluation.
    @test_throws ArgumentError Constraint(constraint_id="x",
        operator="!=", bound=1.0, unit="L")
    @test_throws ArgumentError Constraint(constraint_id="x",
        operator="<=", bound=NaN, unit="L")
    @test_throws ArgumentError Constraint(constraint_id="x",
        operator="range", bound_low=8.0, bound_high=2.0, unit="L")
    # Wire: malformed requests never throw and never pass.
    base = Dict("schema_version" => "1.0.0", "constraint_id" => "w",
                "operator" => "<=", "value" => 8.0, "value_unit" => "L",
                "bound" => 10.0, "bound_unit" => "L", "tolerance" => 0.0)
    @test note(evaluate_constraint_request(base)).status == "PASS"
    wire_cases = [
        ("missing fields", Dict("constraint_id" => "w"), "INVALID_REQUEST"),
        ("bad operator", merge(base, Dict("operator" => "!=")), "INVALID_REQUEST"),
        ("empty id", merge(base, Dict("constraint_id" => "")), "INVALID_REQUEST"),
        ("whitespace id", merge(base, Dict("constraint_id" => "  ")), "INVALID_REQUEST"),
        ("non-string id", merge(base, Dict("constraint_id" => 123)), "INVALID_REQUEST"),
        ("NaN value", merge(base, Dict("value" => NaN)), "NON_FINITE"),
        ("Inf bound", merge(base, Dict("bound" => Inf)), "NON_FINITE"),
        ("NaN tolerance", merge(base, Dict("tolerance" => NaN)), "NON_FINITE"),
        ("Inf tolerance", merge(base, Dict("tolerance" => Inf)), "NON_FINITE"),
        ("-Inf tolerance", merge(base, Dict("tolerance" => -Inf)), "NON_FINITE"),
        ("negative tolerance", merge(base, Dict("tolerance" => -1.0)), "INVALID_REQUEST"),
        ("string value", merge(base, Dict("value" => "8")), "NON_FINITE"),
        ("empty value_unit", merge(base, Dict("value_unit" => "")), "INVALID_REQUEST"),
        ("empty bound_unit", merge(base, Dict("bound_unit" => "")), "INVALID_REQUEST"),
        ("unknown value_unit", merge(base, Dict("value_unit" => "bucket")), "UNKNOWN_UNIT"),
        ("unknown bound_unit", merge(base, Dict("bound_unit" => "bucket")), "UNKNOWN_UNIT"),
        ("missing bound", Dict(k => v for (k, v) in base if k != "bound"), "INVALID_REQUEST"),
        ("major version", merge(base, Dict("schema_version" => "2.0.0")), "UNSUPPORTED_MAJOR_VERSION"),
        ("malformed version", merge(base, Dict("schema_version" => "1.0")), "INVALID_REQUEST"),
    ]
    for (label, req, code) in wire_cases
        out = note(evaluate_constraint_request(req))
        @test out.status == "UNKNOWN"
        @test out.reason_code == code
    end
    rbase = Dict("schema_version" => "1.0.0", "constraint_id" => "rng",
                 "operator" => "range", "value" => 5.0, "value_unit" => "L",
                 "bound_low" => 2.0, "bound_high" => 8.0,
                 "bound_unit" => "L", "tolerance" => 0.0)
    @test note(evaluate_constraint_request(rbase)).status == "PASS"
    for (label, req) in [
            ("range missing low",
             Dict(k => v for (k, v) in rbase if k != "bound_low")),
            ("range missing high",
             Dict(k => v for (k, v) in rbase if k != "bound_high")),
            ("range inverted",
             merge(rbase, Dict("bound_low" => 8.0, "bound_high" => 2.0))),
        ]
        out = note(evaluate_constraint_request(req))
        @test out.status == "UNKNOWN"
        @test out.reason_code == "INVALID_REQUEST"
    end
    # Aggregation: empty is NOT_CHECKED, never PASS; precedence
    # FAIL > INCOMPLETE > UNKNOWN > NOT_CHECKED > PASS, as in Python
    # and Rust.
    @test overall_from_checks(String[]) == "NOT_CHECKED"
    @test overall_from_checks(["UNKNOWN"]) == "UNKNOWN"
    @test overall_from_checks(["PASS", "FAIL"]) == "FAIL"
    @test overall_from_checks(["INCOMPLETE", "UNKNOWN"]) == "INCOMPLETE"
    @test overall_from_checks(["UNKNOWN", "NOT_CHECKED"]) == "UNKNOWN"
    @test overall_from_checks(["NOT_CHECKED", "PASS"]) == "NOT_CHECKED"
    @test overall_from_checks(["PASS", "PASS"]) == "PASS"
    # The sweep: nothing emitted anywhere above leaves the vocabulary.
    # (The old :candidate_feasible / :candidate_infeasible /
    # :incomplete Symbols survive only as history in the module
    # docstring describing what was removed — no live path emits them.)
    @test all(s -> s in CHECK_STATUSES, seen)
    @test Set(seen) ⊆ Set(CHECK_STATUSES)
end

@testset "Objective mirrors Python (representation, no computed value)" begin
    o = Objective(objective_id="obj", name="maximise food energy",
                  direction="maximize", unit="kcal/capita/day",
                  weight=1.0)
    @test o.direction == "maximize"
    @test_throws ArgumentError Objective(objective_id="o", name="n",
        direction="sideways")
    @test_throws ArgumentError Objective(objective_id="o", name="n",
        direction="target")  # target objective requires a target value
    @test_throws ArgumentError Objective(objective_id="o", name="n",
        direction="target", target=2500.0, weight=-1.0)
    @test_throws ArgumentError Objective(objective_id="o", name="n",
        unit="bucket")
    target = Objective(objective_id="o", name="n", direction="target",
                       target=2500.0, unit="kcal/capita/day")
    @test target.target == 2500.0
    # ISSUE-50, VERIFIED-DONE (2026-11-11): the old `decision_variables`
    # (mislabelled slack) and always-`nothing` `objective_value` are
    # gone with the ISSUE-05 rewrite — `decision_variables` occurs
    # nowhere in this component, and no struct carries an
    # `objective_value` field. What replaced them: `ConstraintResult`
    # carries `normalized_value` (the value converted into the bound's
    # unit), and `Objective` is a declared aim only — Python's
    # `Objective` likewise defines no evaluation and no objective
    # value, and the module docstring + component README record that
    # no objective is computed. These pins keep the removal removed.
    @test !isdefined(STARTPlanning, :decision_variables)
    @test !hasfield(ConstraintResult, :objective_value)
    @test !hasfield(Objective, :objective_value)
    @test !hasfield(Constraint, :objective_value)
    @test :normalized_value in fieldnames(ConstraintResult)
end

@testset "ISSUE-51: every emitted reason_code is in the result-schema enum" begin
    # The result schema is the authority for reason_code
    # (interop/schemas/constraint-evaluation-result.schema.json).
    # ISSUE-51 fix (2026-11-11): the evaluator used to emit
    # MISSING_BOUND / MISSING_UNIT, which are NOT in this enum — a
    # schema-valid consumer would reject those results. They are now
    # INVALID_REQUEST (matching Rust), with the distinct cause in
    # `details`. This testset reads the enum from the schema file
    # itself, so any future non-enum code fails here first.
    schema = JSON.parsefile(joinpath(@__DIR__, "..", "..", "..",
        "interop", "schemas",
        "constraint-evaluation-result.schema.json"))
    enum_codes = Set(schema["properties"]["reason_code"]["enum"])
    @test Set(["OK", "NON_FINITE", "UNKNOWN_UNIT", "INCOMPATIBLE_UNIT",
              "INVALID_REQUEST", "UNSUPPORTED_MAJOR_VERSION",
              "UNSUPPORTED_OPERATOR"]) ⊆ enum_codes
    seen = ConstraintResult[]
    c = Constraint(constraint_id="c", operator="<=", bound=10.0, unit="L")
    for r in [
            evaluate_constraint(c, 8.0, "L"),    # PASS / OK
            evaluate_constraint(c, 12.0, "L"),   # FAIL / OK
            evaluate_constraint(c, NaN, "L"),    # NON_FINITE
            evaluate_constraint(c, 5.0, "bucket"), # UNKNOWN_UNIT
            evaluate_constraint(
                Constraint(constraint_id="i", operator="<=",
                           bound=10.0, unit="kg"), 5.0, "L"), # INCOMPATIBLE_UNIT
            evaluate_constraint(
                Constraint(constraint_id="nb", operator="<=", unit="L"),
                5.0, "L"),                        # was MISSING_BOUND
            evaluate_constraint(
                Constraint(constraint_id="nr", operator="range", unit="L"),
                5.0, "L"),                        # was MISSING_BOUND
            evaluate_constraint(c, 5.0),          # was MISSING_UNIT
            evaluate_constraint(
                Constraint(constraint_id="", operator="<=", bound=10.0,
                           unit="L"), 5.0, "L"),  # INVALID_REQUEST
            evaluate_constraint(
                Constraint(constraint_id="big", operator="<=",
                           bound=10.0, unit="g"), 1e308, "tonne"), # NON_FINITE
        ]
        push!(seen, r)
    end
    base = Dict("schema_version" => "1.0.0", "constraint_id" => "w",
                "operator" => "<=", "value" => 8.0, "value_unit" => "L",
                "bound" => 10.0, "bound_unit" => "L", "tolerance" => 0.0)
    for req in [
            base,  # PASS / OK
            merge(base, Dict("tolerance" => NaN)),   # NON_FINITE, not INVALID_REQUEST
            merge(base, Dict("tolerance" => Inf)),   # NON_FINITE
            merge(base, Dict("tolerance" => -Inf)),  # NON_FINITE
            merge(base, Dict("tolerance" => -1.0)),  # INVALID_REQUEST (negative finite)
            merge(base, Dict("tolerance" => "x")),   # INVALID_REQUEST (wrong type)
            merge(base, Dict("tolerance" => true)),  # INVALID_REQUEST (bool)
            merge(base, Dict("value" => -Inf, "tolerance" => -1.0)), # NON_FINITE wins
            merge(base, Dict("schema_version" => "2.0.0")), # UNSUPPORTED_MAJOR_VERSION
            merge(base, Dict("constraint_id" => "")), # INVALID_REQUEST
            merge(base, Dict("value_unit" => "bucket")), # UNKNOWN_UNIT
        ]
        push!(seen, evaluate_constraint_request(req))
    end
    # Finiteness before sign (mirrors Rust's ISSUE-52 fix): a
    # negative-non-finite tolerance is NON_FINITE, a negative finite
    # one is INVALID_REQUEST, and a non-finite value beats a negative
    # tolerance.
    @test evaluate_constraint_request(
        merge(base, Dict("tolerance" => NaN))).reason_code == "NON_FINITE"
    @test evaluate_constraint_request(
        merge(base, Dict("tolerance" => -1.0))).reason_code ==
        "INVALID_REQUEST"
    @test evaluate_constraint_request(
        merge(base, Dict("value" => -Inf, "tolerance" => -1.0))).reason_code ==
        "NON_FINITE"
    # The conformance assertion: nothing emitted leaves the enum.
    @test all(r -> r.reason_code in enum_codes, seen)
    @test all(r -> r.status in CHECK_STATUSES, seen)
    # ISSUE-51 boundaries, recorded not implemented: the old gaps
    # "negative coefficients / limits" and "distinct empty-limits
    # reason" are MOOT — there are no coefficient/limit vectors any
    # more (no PlanningInput, no evaluate_linear_balance), so there is
    # nothing to sign-check; and the old (Bool, String) tuple is gone
    # from the validation surface — evaluate_constraint_request
    # returns a ConstraintResult with status + reason_code, and
    # check_schema_version's (Bool, String) tuple is an internal
    # helper only. Domain-level sign/range checks remain a boundary
    # for when a real domain is implemented in Julia (the issue says
    # so itself); no Julia domain exists, so none is invented here.
    @test !isdefined(STARTPlanning, :validate_input)
end

@testset "overall_from_checks mirrors Python exactly" begin
    @test overall_from_checks(String[]) == "NOT_CHECKED"
    @test overall_from_checks(["PASS"]) == "PASS"
    @test overall_from_checks(["PASS", "PASS"]) == "PASS"
    @test overall_from_checks(["UNKNOWN"]) == "UNKNOWN"
    @test overall_from_checks(["NOT_CHECKED"]) == "NOT_CHECKED"
    @test overall_from_checks(["INCOMPLETE"]) == "INCOMPLETE"
    @test overall_from_checks(["FAIL", "PASS"]) == "FAIL"
    @test overall_from_checks(["INCOMPLETE", "UNKNOWN"]) == "INCOMPLETE"
    @test overall_from_checks(["UNKNOWN", "NOT_CHECKED"]) == "UNKNOWN"
    @test overall_from_checks(["NOT_CHECKED", "PASS"]) == "NOT_CHECKED"
    @test overall_from_checks(["BOGUS"]) == "UNKNOWN"  # never PASS
end

@testset "schema version: single source of truth (ISSUE-10/54)" begin
    # SCHEMA_VERSION is read from interop/SCHEMA_VERSION at load time,
    # not a second hard-coded copy; the Python suite asserts the same
    # file agrees with the Rust and schema copies too.
    version_file = joinpath(@__DIR__, "..", "..", "..", "interop", "SCHEMA_VERSION")
    @test strip(read(version_file, String)) == "1.0.0"
    @test SCHEMA_VERSION == "1.0.0"
    @test SCHEMA_VERSION == strip(read(version_file, String))
    @test SUPPORTED_SCHEMA_MAJOR == 1
    @test SUPPORTED_SCHEMA_MAJOR ==
        parse(Int, split(SCHEMA_VERSION, ".")[1])
    # ISSUE-10, second half, is moot: the old Julia planning message
    # (PlanningInput / evaluate_linear_balance) was removed by the
    # ISSUE-05 fix — no such message exists any more, so there is no
    # second payload needing its own schema/version.
    @test !isdefined(STARTPlanning, :PlanningInput)
    @test !isdefined(STARTPlanning, :evaluate_linear_balance)
end

@testset "schema versions: same-major accepted, major rejected distinctly" begin
    @test check_schema_version("1.0.0") == (true, "OK")
    @test check_schema_version("1.0.1") == (true, "OK")
    @test check_schema_version("1.1.0") == (true, "OK")
    @test check_schema_version("2.0.0") == (false,
        "unsupported major schema version: 2.0.0 (supported major version 1)")
    accepted, reason = check_schema_version("banana")
    @test !accepted && startswith(reason, "invalid schema version: ")
    # The same rules through the wire request path.
    base = Dict("schema_version" => "1.0.1", "constraint_id" => "w",
                "operator" => "<=", "value" => 8.0, "value_unit" => "L",
                "bound" => 10.0, "bound_unit" => "L", "tolerance" => 0.0)
    @test evaluate_constraint_request(base).status == "PASS"
    major = merge(base, Dict("schema_version" => "2.0.0"))
    out = evaluate_constraint_request(major)
    @test out.status == "UNKNOWN"
    @test out.reason_code == "UNSUPPORTED_MAJOR_VERSION"
    @test out.details ==
        "unsupported major schema version: 2.0.0 (supported major version 1)"
    # A malformed wire request never throws and never passes.
    @test evaluate_constraint_request(Dict("constraint_id" => "w")).status ==
        "UNKNOWN"
    badop = merge(base, Dict("operator" => "!="))
    @test evaluate_constraint_request(badop).status == "UNKNOWN"
end

@testset "shared test vectors: every case agrees with Python/Rust" begin
    data = JSON.parsefile(VECTORS_PATH)
    # No case may still be an open decision after 2026-11-11.
    for section in ("cases", "version_cases", "aggregation_cases")
        for entry in data[section]
            @test entry["conformance"] != "open_decision"
        end
    end
    # All 14 wire cases, through evaluate_constraint_request.
    cases = data["cases"]
    @test length(cases) == 14
    for case in cases
        id = case["id"]
        req = case["request"]
        # The file pins all three languages to the same status.
        @test verified_status(case, "python") ==
            verified_status(case, "rust")
        @test verified_status(case, "julia") ==
            verified_status(case, "rust")
        out = evaluate_constraint_request(req)
        @test out.status == verified_status(case, "julia")
        @test out.status in CHECK_STATUSES
        @test out.constraint_id == req["constraint_id"]
    end
    # The decided range wire shape carries bound_low/bound_high, no bound.
    range_case = cases[findfirst(c -> c["id"] == "range-operator", cases)]
    @test range_case["request"]["operator"] == "range"
    @test range_case["request"]["bound_low"] == 2
    @test range_case["request"]["bound_high"] == 8
    @test !haskey(range_case["request"], "bound")
    # All 3 version cases, through the version check inside
    # evaluate_constraint_request (accepted -> PASS on a valid request,
    # major mismatch -> UNKNOWN / UNSUPPORTED_MAJOR_VERSION with the
    # exact distinct message).
    versions = data["version_cases"]
    @test length(versions) == 3
    for vc in versions
        version = vc["request_schema_version"]
        req = Dict("schema_version" => version, "constraint_id" => "water_limit",
                   "operator" => "<=", "value" => 8.0, "value_unit" => "L",
                   "bound" => 10.0, "bound_unit" => "L", "tolerance" => 0.0)
        out = evaluate_constraint_request(req)
        if vc["expected"]["accepted"]
            @test out.status == "PASS"
        else
            @test out.status == "UNKNOWN"
            @test out.reason_code == "UNSUPPORTED_MAJOR_VERSION"
            @test out.details == vc["expected"]["error"]
        end
    end
    # Both aggregation cases, through overall_from_checks.
    agg = data["aggregation_cases"]
    @test length(agg) == 2
    for ac in agg
        checks = String.(ac["input"]["checks"])
        @test overall_from_checks(checks) ==
            ac["julia_verified_2026-11-11"]["status"]
    end
end
