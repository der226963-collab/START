//! Pure verification kernels. No I/O, network, persistence, or decision authority.
use serde::{Deserialize, Serialize};

/// The canonical schema version — the single source of truth is
/// `interop/SCHEMA_VERSION` (ISSUE-10/54 fix, 2026-11-11); this constant
/// is that file's contents, read at compile time, not a second copy.
/// The file must contain exactly `1.0.0` with NO trailing newline:
/// `include_str!` reads it verbatim, and the test below fails if a
/// newline (or any other drift) creeps in. Python
/// (`adapters/python/contracts.py`) and Julia
/// (`components/julia-planning/src/STARTPlanning.jl`) read the same
/// file at load time; a shared conformance test in the Python suite
/// asserts all three copies agree.
pub const SCHEMA_VERSION: &str = include_str!("../../../interop/SCHEMA_VERSION");

/// Major schema version this kernel speaks. Same-major patch/minor versions
/// are accepted per interop/CONTRACT_VERSIONING.md; only a major mismatch
/// is rejected, with a distinct error.
pub const SUPPORTED_MAJOR: u64 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConstraintRequest {
    pub schema_version: String,
    pub constraint_id: String,
    pub operator: String,
    pub value: f64,
    pub value_unit: String,
    /// Required for non-range operators; absent for `range` requests, which
    /// carry `bound_low`/`bound_high` instead.
    #[serde(default)]
    pub bound: Option<f64>,
    pub bound_unit: String,
    pub tolerance: f64,
    /// Range bounds; required only when `operator == "range"`.
    #[serde(default)]
    pub bound_low: Option<f64>,
    #[serde(default)]
    pub bound_high: Option<f64>,
    /// ISSUE-39 (2026-11-11): typed as a JSON object (a map), not a
    /// bare `serde_json::Value`, so a non-object context
    /// ("not-an-object", a number, an array, null) is a parse error,
    /// matching the request schema (`"context": {"type": "object"}`).
    /// An omitted context normalises to the empty object `{}` — the
    /// schema's shape for "no context" — rather than JSON null, which
    /// the schema would also reject. The evaluator ignores context;
    /// the type exists only to enforce the schema at the boundary.
    #[serde(default)]
    pub context: serde_json::Map<String, serde_json::Value>,
}

/// The exact five-status contract vocabulary
/// (`interop/CONTRACT_VERSIONING.md`): PASS, FAIL, UNKNOWN,
/// NOT_CHECKED, INCOMPLETE — serialised SCREAMING_SNAKE_CASE.
///
/// ISSUE-07 finding (2026-11-11) — which variants each entry point
/// can return, checked against the code, not assumed:
/// * `evaluate_constraint` can only ever return Pass, Fail or
///   Unknown. NotChecked and Incomplete are unreachable *there*:
///   every early return keeps the initial Unknown and the only
///   success path sets Pass or Fail. That is the same shape as
///   Python `Constraint.evaluate` and Julia `evaluate_constraint`,
///   which likewise return only PASS / FAIL / UNKNOWN.
/// * NotChecked IS produced, by `overall_from_checks(&[])` — the
///   empty-check-list rule (never PASS) — in all three languages.
/// * Incomplete is never *produced* by any single-constraint
///   evaluator in any language; it is produced upstream (in Python,
///   by the domain/engine layer when a calculation was not
///   completed, e.g. `FoodDomain.evaluate` / `PlanningEngine::run`)
///   and *propagated* by `overall_from_checks`, which returns
///   Incomplete when any input check is Incomplete. In Rust it is
///   therefore reachable only as an input to aggregation today,
///   because Rust has no domain/planning layer — but the variant is
///   not dead: `overall_from_checks` must accept it (a caller may
///   aggregate statuses produced in another language), and it is
///   part of the serialised wire vocabulary.
/// Removing either variant would be a breaking API change (wire
/// format + aggregation contract), so removal is OUT OF SCOPE here;
/// this note is the record of that decision.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CheckStatus { Pass, Fail, Unknown, NotChecked, Incomplete }

/// A single-constraint evaluation result, as emitted on the wire.
///
/// ISSUE-49 (2026-11-11): `deny_unknown_fields`, symmetric with
/// `ConstraintRequest` and with the result schema's
/// `additionalProperties: false`; and `details` is `Option<String>`
/// (omitted when `None`), because the schema lists `details` as
/// optional — a consumer deserialising a schema-valid result without
/// `details` into this struct used to fail. Every path in
/// `evaluate_constraint` still sets `details` to `Some(...)`, so the
/// emitted shape is unchanged (the key is always present on output);
/// only deserialisation is now as permissive as the schema.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConstraintResult {
    pub schema_version: String,
    pub constraint_id: String,
    pub status: CheckStatus,
    /// ISSUE-53 (2026-11-11): the request value expressed in
    /// `bound_unit` — the constraint's unit — via the reviewed
    /// registry conversion, matching Python `Constraint.evaluate`
    /// (which converts the value into the constraint's unit). NOT an
    /// echo of the input: 0.008 m³ against a 10 L bound normalises
    /// to 8.0 L. `None` when evaluation never reached a comparison
    /// (unknown/incompatible unit, invalid input). `null` on the wire.
    pub normalized_value: Option<f64>,
    /// The unit `normalized_value` is expressed in: always
    /// `bound_unit` when `normalized_value` is `Some`, else `None`
    /// (`null` on the wire). It is the constraint's unit, not the
    /// value's input unit, whenever the two differ.
    pub normalized_unit: Option<String>,
    pub reason_code: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub details: Option<String>,
}

/// The Rust unit registry: (unit string, dimension, factor to base unit).
/// Copied entry-by-entry from the reviewed conversion table in Python
/// `contracts/units.py` (`_UNITS`) — same dimension names, same factors.
/// ISSUE-06 (2026-11-11): the eight non-rate units missing from Rust
/// (`"1"`, `people`, `m²`, `ha`, `kcal`, `Mcal`, `kWh`, `MWh`) are now
/// here, and `person`'s dimension is `people` (Python's name), not the
/// `population` Rust previously invented — `person` and `people` must
/// convert 1:1, which they could not while their dimensions differed.
/// The registry is one table (not a match) so the conformance test below
/// can enumerate exactly these keys against Python's `_UNITS`: any key
/// present in one registry and not the other is a test failure.
/// Decision, per unit, for every Python `_UNITS` key: ACCEPT and convert
/// within its dimension. There is no Python key Rust rejects; unknown
/// strings stay UNKNOWN_UNIT (see `rejects_unknown_unit`).
const UNIT_TABLE: &[(&str, &str, f64)] = &[
    ("1", "dimensionless", 1.0),
    ("person", "people", 1.0),
    ("people", "people", 1.0),
    ("kg", "mass", 1.0),
    ("g", "mass", 0.001),
    ("tonne", "mass", 1000.0),
    ("t", "mass", 1000.0),
    ("L", "volume", 0.001),
    ("m3", "volume", 1.0),
    ("m²", "area", 1.0),
    ("ha", "area", 10000.0),
    ("kcal", "energy", 1.0),
    ("Mcal", "energy", 1000.0),
    ("kWh", "energy", 860.4206501),
    ("MWh", "energy", 860420.6501),
    ("kcal/capita/day", "food_energy_rate_per_capita", 1.0),
    ("kcal/person/day", "food_energy_rate_per_capita", 1.0),
    ("kcal/day", "food_energy_rate_per_capita", 1.0),
    ("m3/day", "volume_rate", 1.0),
    ("L/day", "volume_rate", 0.001),
    ("kg/day", "mass_rate", 1.0),
    ("tonne/day", "mass_rate", 1000.0),
    ("kWh/day", "energy_rate", 1.0),
    ("MWh/day", "energy_rate", 1000.0),
    // ISSUE-34 (2026-11-13): teragramme-scale mass. 1 Tg = 1 Mt = 1e9 kg
    // exactly, so Tg and Mt convert 1:1.
    ("Tg", "mass", 1e9),
    ("Mt", "mass", 1e9),
    ("million tonnes", "mass", 1e9),
    // ISSUE-34 (2026-11-13): mass-per-year rates live on their OWN
    // dimension "mass_rate_year" (base Tg/yr), NOT folded into
    // "mass_rate" (base per-day). Folding them in would smuggle in a
    // days-per-year assumption; Tg/yr and tonne/day are therefore NOT
    // interconvertible — a conversion would need a stated days-per-year.
    ("Tg/yr", "mass_rate_year", 1.0),
    ("Mt/yr", "mass_rate_year", 1.0),
    ("tonne/yr", "mass_rate_year", 1e-6),
    ("kg/yr", "mass_rate_year", 1e-9),
    // ISSUE-34 (2026-11-13): percent is dimensionless, factor 0.01 —
    // 33 percent = 0.33, compatible with "1".
    ("percent", "dimensionless", 0.01),
    ("%", "dimensionless", 0.01),
    // ISSUE-34 (2026-11-13): labour time rates. Base is hours/week;
    // 1 hour/day = 7 hours/week (7-day week). "hours" is total time in
    // the labour domain (dimension "time", base hour).
    ("hours/week", "work_time_rate", 1.0),
    ("hours/day", "work_time_rate", 7.0),
    ("hours", "time", 1.0),
];

/// A unit's dimension and its factor to that dimension's base unit.
fn unit_definition(unit: &str) -> Option<(&'static str, f64)> {
    UNIT_TABLE
        .iter()
        .find(|(name, _, _)| *name == unit)
        .map(|(_, dim, factor)| (*dim, *factor))
}

/// Convert `value` from `source` into `target`; None when either unit is
/// unknown or the dimensions differ. Cross-dimension comparisons are never
/// converted into a PASS.
fn convert(value: f64, source: &str, target: &str) -> Option<f64> {
    let (dim_a, factor_a) = unit_definition(source)?;
    let (dim_b, factor_b) = unit_definition(target)?;
    if dim_a != dim_b {
        return None;
    }
    Some(value * factor_a / factor_b)
}

#[derive(Debug, PartialEq)]
enum VersionCheck {
    Ok,
    /// Malformed version string (not three dot-separated numbers).
    Malformed,
    /// Well-formed but a different major version.
    UnsupportedMajor,
}

fn check_schema_version(version: &str) -> VersionCheck {
    let parts: Vec<&str> = version.split('.').collect();
    if parts.len() != 3 || parts.iter().any(|p| p.is_empty() || !p.chars().all(|c| c.is_ascii_digit())) {
        return VersionCheck::Malformed;
    }
    let major: u64 = parts[0].parse().unwrap_or(u64::MAX);
    if major != SUPPORTED_MAJOR {
        return VersionCheck::UnsupportedMajor;
    }
    VersionCheck::Ok
}

/// Aggregate check statuses, mirroring Python `overall_from_checks`
/// (contracts/statuses.py) exactly: FAIL dominates all, then INCOMPLETE,
/// then UNKNOWN, then NOT_CHECKED; all-PASS passes; empty is NOT_CHECKED.
/// UNKNOWN/INCOMPLETE are never converted to PASS.
///
/// This is the only Rust function that can return NotChecked (empty
/// input) and the only one that can return Incomplete (propagated when
/// any input check is Incomplete — no Rust evaluator produces
/// Incomplete; see the `CheckStatus` note). ISSUE-07, 2026-11-11.
pub fn overall_from_checks(statuses: &[CheckStatus]) -> CheckStatus {
    if statuses.is_empty() {
        return CheckStatus::NotChecked;
    }
    if statuses.iter().any(|s| *s == CheckStatus::Fail) {
        return CheckStatus::Fail;
    }
    if statuses.iter().any(|s| *s == CheckStatus::Incomplete) {
        return CheckStatus::Incomplete;
    }
    if statuses.iter().any(|s| *s == CheckStatus::Unknown) {
        return CheckStatus::Unknown;
    }
    if statuses.iter().any(|s| *s == CheckStatus::NotChecked) {
        return CheckStatus::NotChecked;
    }
    if statuses.iter().all(|s| *s == CheckStatus::Pass) {
        return CheckStatus::Pass;
    }
    CheckStatus::Unknown
}

/// Evaluate a single constraint. Units are converted through the reviewed
/// registry table above (same-dimension only); incompatible units stay
/// UNKNOWN and are never a PASS.
///
/// Returns only Pass, Fail or Unknown (see the `CheckStatus` note above:
/// NotChecked and Incomplete are unreachable here; they belong to
/// aggregation via `overall_from_checks`). Invalid input — non-finite
/// numbers, unknown or incompatible units, a missing bound, an
/// inverted range, a bad operator, an empty `constraint_id`, a
/// malformed or unsupported-major schema version — returns Unknown
/// with a `reason_code` (`INVALID_REQUEST`, `NON_FINITE`,
/// `UNKNOWN_UNIT`, `INCOMPATIBLE_UNIT`, `UNSUPPORTED_MAJOR_VERSION`,
/// `UNSUPPORTED_OPERATOR` — ISSUE-52: the unsupported-operator branch
/// has its own code, matching Julia, instead of sharing
/// `INVALID_REQUEST` with the schema/id/tolerance failures),
/// never Pass, never a panic. Check order (ISSUE-52): schema version,
/// then empty id, then FINITENESS of every numeric input, then the
/// tolerance sign check — so a negative-non-finite tolerance (e.g.
/// -inf, reachable only via direct library calls since JSON has no
/// Infinity/NaN) is reported `NON_FINITE`, not `INVALID_REQUEST`.
/// This is the Rust half of the ISSUE-07
/// mapping (see `docs/STATUS_MAPPING_ISSUE-07.md`): evaluator level
/// returns UNKNOWN; the wire level rejects malformed requests with a
/// reason; an empty check list aggregates to NOT_CHECKED.
pub fn evaluate_constraint(req: &ConstraintRequest) -> ConstraintResult {
    let mut result = ConstraintResult {
        schema_version: SCHEMA_VERSION.into(), constraint_id: req.constraint_id.clone(),
        status: CheckStatus::Unknown, normalized_value: None, normalized_unit: None,
        reason_code: "INVALID_REQUEST".into(), details: None,
    };
    match check_schema_version(&req.schema_version) {
        VersionCheck::UnsupportedMajor => {
            result.reason_code = "UNSUPPORTED_MAJOR_VERSION".into();
            result.details = Some(format!(
                "unsupported major schema version: {} (supported major version {})",
                req.schema_version, SUPPORTED_MAJOR
            ));
            return result;
        }
        VersionCheck::Malformed => {
            result.details = Some(format!("invalid schema version: {:?}", req.schema_version));
            return result;
        }
        VersionCheck::Ok => {}
    }
    if req.constraint_id.trim().is_empty() {
        result.details = Some("Unsupported schema version or invalid identifier/tolerance".into()); return result;
    }
    // ISSUE-52: finiteness BEFORE the tolerance sign check.
    if !req.value.is_finite() || !req.tolerance.is_finite() {
        result.reason_code = "NON_FINITE".into(); result.details = Some("All numeric inputs must be finite".into()); return result;
    }
    if req.tolerance < 0.0 {
        result.details = Some("tolerance cannot be negative".into()); return result;
    }
    // Range bounds, when present, must be finite; inverted bounds are
    // rejected, never PASS.
    if let Some(v) = req.bound_low {
        if !v.is_finite() { result.reason_code = "NON_FINITE".into(); result.details = Some("All numeric inputs must be finite".into()); return result; }
    }
    if let Some(v) = req.bound_high {
        if !v.is_finite() { result.reason_code = "NON_FINITE".into(); result.details = Some("All numeric inputs must be finite".into()); return result; }
    }
    if let Some(v) = req.bound {
        if !v.is_finite() { result.reason_code = "NON_FINITE".into(); result.details = Some("All numeric inputs must be finite".into()); return result; }
    }
    if unit_definition(&req.value_unit).is_none() || unit_definition(&req.bound_unit).is_none() {
        result.reason_code = "UNKNOWN_UNIT".into(); result.details = Some("Unit is not in the reviewed registry".into()); return result;
    }
    let normalized = match convert(req.value, &req.value_unit, &req.bound_unit) {
        Some(v) => v,
        None => {
            result.reason_code = "INCOMPATIBLE_UNIT".into();
            result.details = Some("Units are in different dimensions; conversion cannot apply".into());
            return result;
        }
    };
    // ISSUE-47 (2026-11-11): the conversion itself can overflow to
    // inf (e.g. 1e308 tonne -> g): the inputs are finite, so the
    // finiteness checks above pass, yet the normalised value is
    // infinite. A silent inf used to leak through — serde_json
    // serialises it as null, so the binary emitted a PASS with
    // normalized_value null for ">=" (and a FAIL for "<=" by
    // accident). An infinite normalised value is UNKNOWN /
    // NON_FINITE here, never PASS, matching Python (convert raises
    // ValueError -> Constraint.evaluate returns UNKNOWN) and Julia
    // (UNKNOWN/NON_FINITE on !isfinite(converted)).
    if !normalized.is_finite() {
        result.reason_code = "NON_FINITE".into();
        result.details = Some("normalized value must be finite".into());
        return result;
    }
    let pass = match req.operator.as_str() {
        "<=" | ">=" | "==" => {
            let bound = match req.bound {
                Some(b) => b,
                None => { result.details = Some("Missing bound for non-range operator".into()); return result; }
            };
            match req.operator.as_str() {
                "<=" => normalized <= bound + req.tolerance,
                ">=" => normalized >= bound - req.tolerance,
                _ => (normalized - bound).abs() <= req.tolerance,
            }
        }
        "range" => {
            let (low, high) = match (req.bound_low, req.bound_high) {
                (Some(lo), Some(hi)) => (lo, hi),
                _ => { result.details = Some("Range requires bound_low and bound_high".into()); return result; }
            };
            if low > high {
                result.details = Some("Range lower bound exceeds upper bound".into()); return result;
            }
            // Inclusive with tolerance, mirroring Python native semantics.
            low - req.tolerance <= normalized && normalized <= high + req.tolerance
        }
        // ISSUE-52: its own reason code, not INVALID_REQUEST.
        _ => { result.reason_code = "UNSUPPORTED_OPERATOR".into(); result.details = Some("Unsupported operator".into()); return result; }
    };
    result.status = if pass { CheckStatus::Pass } else { CheckStatus::Fail };
    result.normalized_value = Some(normalized);
    result.normalized_unit = Some(req.bound_unit.clone());
    result.reason_code = "OK".into();
    result.details = Some("Evaluated using finite inputs and reviewed-unit conversion".into());
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request(value: f64, unit: &str) -> ConstraintRequest {
        ConstraintRequest { schema_version: SCHEMA_VERSION.into(), constraint_id: "water_limit".into(), operator: "<=".into(), value, value_unit: unit.into(), bound: Some(10.0), bound_unit: "L".into(), tolerance: 0.0, bound_low: None, bound_high: None, context: serde_json::Map::new() }
    }
    fn request_version(value: f64, unit: &str, version: &str) -> ConstraintRequest {
        let mut r = request(value, unit);
        r.schema_version = version.into();
        r
    }
    fn range_request(value: f64, unit: &str, low: Option<f64>, high: Option<f64>) -> ConstraintRequest {
        ConstraintRequest { schema_version: SCHEMA_VERSION.into(), constraint_id: "rng".into(), operator: "range".into(), value, value_unit: unit.into(), bound: None, bound_unit: unit.into(), tolerance: 0.0, bound_low: low, bound_high: high, context: serde_json::Map::new() }
    }
    #[test] fn passes_valid_constraint() { assert_eq!(evaluate_constraint(&request(8.0, "L")).status, CheckStatus::Pass); }
    #[test] fn fails_exceeded_constraint() { assert_eq!(evaluate_constraint(&request(12.0, "L")).status, CheckStatus::Fail); }
    #[test] fn rejects_unknown_unit() { assert_eq!(evaluate_constraint(&request(8.0, "bucket")).reason_code, "UNKNOWN_UNIT"); }
    #[test] fn rejects_non_finite() { assert_eq!(evaluate_constraint(&request(f64::NAN, "L")).reason_code, "NON_FINITE"); }
    // UPDATED (2026-11-11, decision 1: m3/L CONVERT): the old test asserted
    // INCOMPATIBLE_UNIT for 0.008 m3 vs 10 L; conversion now passes it.
    #[test] fn converts_m3_to_litre_passes() {
        let r = evaluate_constraint(&request(0.008, "m3"));
        assert_eq!(r.status, CheckStatus::Pass);
        assert_eq!(r.normalized_value, Some(8.0));
        assert_eq!(r.normalized_unit.as_deref(), Some("L"));
    }
    #[test] fn m3_to_litre_discriminating_fail() {
        // 0.02 m3 = 20 L > 10 L, so FAIL; without conversion 0.02 <= 10
        // would wrongly PASS.
        assert_eq!(evaluate_constraint(&request(0.02, "m3")).status, CheckStatus::Fail);
    }
    #[test] fn litre_to_m3_other_direction() {
        let mut r = request(8.0, "L");
        r.bound = Some(0.01);
        r.bound_unit = "m3".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r2 = request(12.0, "L");
        r2.bound = Some(0.01);
        r2.bound_unit = "m3".into();
        assert_eq!(evaluate_constraint(&r2).status, CheckStatus::Fail);
    }
    #[test] fn incompatible_units_still_unknown() {
        let mut r2 = request(5.0, "L");
        r2.bound_unit = "kg".into();
        let out = evaluate_constraint(&r2);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INCOMPATIBLE_UNIT");
    }
    #[test] fn kcal_per_day_in_registry() {
        // Same family as kcal/capita/day, factor 1.0: converts 1:1.
        assert_eq!(convert(1.0, "kcal/day", "kcal/capita/day"), Some(1.0));
        assert_eq!(convert(1.0, "kcal/capita/day", "kcal/day"), Some(1.0));
        let mut r = request(2800.0, "kcal/day");
        r.operator = ">=".into();
        r.bound = Some(2500.0);
        r.bound_unit = "kcal/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r2 = request(2000.0, "kcal/day");
        r2.operator = ">=".into();
        r2.bound = Some(2500.0);
        r2.bound_unit = "kcal/day".into();
        assert_eq!(evaluate_constraint(&r2).status, CheckStatus::Fail);
    }
    #[test] fn kcal_per_capita_day_food_case() {
        let mut r = request(2800.0, "kcal/capita/day");
        r.operator = ">=".into();
        r.bound = Some(2500.0);
        r.bound_unit = "kcal/capita/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
    }
    #[test] fn mass_tonne_t_in_registry() {
        assert_eq!(convert(1.0, "t", "kg"), Some(1000.0));
        assert_eq!(convert(1.0, "tonne", "kg"), Some(1000.0));
        let mut r = request(8.0, "t");
        r.bound = Some(10.0);
        r.bound_unit = "t".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
    }
    #[test] fn rate_units_in_registry() {
        // ISSUE-03 (2026-11-11): remaining ISSUE-06 rate units, each
        // converting correctly against its dimension base, mirroring
        // Python contracts/units.py (volume_rate m3/day, mass_rate
        // kg/day, energy_rate kWh/day). Cross-dimension rate
        // comparisons stay UNKNOWN, never PASS.
        assert_eq!(convert(1.0, "m3/day", "L/day"), Some(1000.0));
        assert_eq!(convert(1.0, "L/day", "m3/day"), Some(0.001));
        assert_eq!(convert(1.0, "tonne/day", "kg/day"), Some(1000.0));
        assert_eq!(convert(1.0, "kg/day", "tonne/day"), Some(0.001));
        assert_eq!(convert(1.0, "MWh/day", "kWh/day"), Some(1000.0));
        assert_eq!(convert(1.0, "kWh/day", "MWh/day"), Some(0.001));
        // One evaluate_constraint case per new unit.
        // m3/day: 8 m3/day <= 10 m3/day PASS.
        let mut r = request(8.0, "m3/day");
        r.bound = Some(10.0); r.bound_unit = "m3/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // L/day: 8 L/day = 0.008 m3/day <= 0.01 m3/day PASS (conversion,
        // not raw-number compare); 20 L/day = 0.02 m3/day FAIL.
        let mut r = request(8.0, "L/day");
        r.bound = Some(0.01); r.bound_unit = "m3/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(20.0, "L/day");
        r.bound = Some(0.01); r.bound_unit = "m3/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // kg/day: 8 kg/day <= 10 kg/day PASS.
        let mut r = request(8.0, "kg/day");
        r.bound = Some(10.0); r.bound_unit = "kg/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // tonne/day: 8 tonne/day = 8000 kg/day <= 10000 kg/day PASS.
        let mut r = request(8.0, "tonne/day");
        r.bound = Some(10000.0); r.bound_unit = "kg/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // kWh/day: 8 kWh/day <= 10 kWh/day PASS.
        let mut r = request(8.0, "kWh/day");
        r.bound = Some(10.0); r.bound_unit = "kWh/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // MWh/day: 8 MWh/day = 8000 kWh/day <= 10000 kWh/day PASS.
        let mut r = request(8.0, "MWh/day");
        r.bound = Some(10000.0); r.bound_unit = "kWh/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // Cross-dimension rate comparison is never a PASS.
        let mut r = request(8.0, "kg/day");
        r.bound = Some(10.0); r.bound_unit = "m3/day".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INCOMPATIBLE_UNIT");
    }
    #[test] fn non_rate_units_in_registry() {
        // ISSUE-06 remainder (2026-11-11): the eight non-rate units
        // missing from Rust, each copied from Python contracts/units.py
        // (dimension, factor) exactly. Before this fix every case
        // below returned UNKNOWN / UNKNOWN_UNIT through the binary
        // while Python returned PASS; see the reproduction in the
        // ISSUE-06 job notes. Cross-dimension comparisons stay
        // UNKNOWN, never PASS.
        // Dimensionless "1": 8 <= 10 PASS; 12 FAIL.
        assert_eq!(convert(1.0, "1", "1"), Some(1.0));
        let mut r = request(8.0, "1");
        r.bound_unit = "1".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(12.0, "1");
        r.bound_unit = "1".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // people / person: same dimension "people", factor 1.0, 1:1.
        assert_eq!(convert(1.0, "people", "person"), Some(1.0));
        assert_eq!(convert(1.0, "person", "people"), Some(1.0));
        let mut r = request(8.0, "people");
        r.bound_unit = "people".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(8.0, "people");
        r.bound_unit = "person".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(12.0, "people");
        r.bound_unit = "person".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // Area: 1 ha = 10000 m². 8 m² = 0.0008 ha <= 0.001 ha PASS;
        // 0.0008 ha = 8 m² <= 10 m² PASS; 20 m² = 0.002 ha FAIL.
        assert_eq!(convert(1.0, "ha", "m²"), Some(10000.0));
        assert_eq!(convert(1.0, "m²", "ha"), Some(0.0001));
        let mut r = request(8.0, "m²");
        r.bound = Some(0.001); r.bound_unit = "ha".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(20.0, "m²");
        r.bound = Some(0.001); r.bound_unit = "ha".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        let mut r = request(0.0008, "ha");
        r.bound = Some(10.0); r.bound_unit = "m²".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(8.0, "ha");
        r.bound = Some(10.0); r.bound_unit = "ha".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // Energy: kcal base 1.0, Mcal 1000, kWh 860.4206501,
        // MWh 860420.6501. 8 kcal = 0.008 Mcal; 8 kWh = 6883.3652008
        // kcal <= 10000 kcal PASS; 8 MWh = 8000 kWh <= 10000 PASS.
        assert_eq!(convert(1.0, "Mcal", "kcal"), Some(1000.0));
        assert_eq!(convert(1.0, "kcal", "Mcal"), Some(0.001));
        assert_eq!(convert(1.0, "kWh", "kcal"), Some(860.4206501));
        assert_eq!(convert(1.0, "MWh", "kWh"), Some(1000.0));
        assert_eq!(convert(1.0, "kWh", "MWh"), Some(0.001));
        let mut r = request(8.0, "kcal");
        r.bound = Some(0.008); r.bound_unit = "Mcal".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(0.008, "Mcal");
        r.bound = Some(10.0); r.bound_unit = "kcal".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(8.0, "kWh");
        r.bound = Some(10000.0); r.bound_unit = "kcal".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(20.0, "kWh");
        r.bound = Some(10000.0); r.bound_unit = "kcal".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        let mut r = request(8.0, "MWh");
        r.bound = Some(10000.0); r.bound_unit = "kWh".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(12.0, "MWh");
        r.bound = Some(10000.0); r.bound_unit = "kWh".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // Same-unit PASS for each of the eight, plus a same-unit FAIL
        // for kcal and MWh as discriminating checks.
        for unit in ["kcal", "Mcal", "kWh", "MWh"] {
            let mut r = request(8.0, unit);
            r.bound = Some(10.0); r.bound_unit = unit.into();
            assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass, "{unit} same-unit");
        }
        // Cross-dimension: energy vs area is never a PASS.
        let mut r = request(8.0, "kcal");
        r.bound = Some(10.0); r.bound_unit = "m²".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INCOMPATIBLE_UNIT");
    }
    #[test] fn rust_registry_matches_python_registry_exactly() {
        // ISSUE-06 shared conformance test: enumerate EVERY Python
        // `_UNITS` key by parsing contracts/units.py itself (compiled
        // in via include_str!, so this test always sees the current
        // Python file) and require Rust's UNIT_TABLE to hold exactly
        // those keys, with the same dimension and factor. A future
        // Python key added without a Rust entry fails here (missing
        // key); a Rust entry Python does not have fails here too
        // (invented unit). Decision per unit: ACCEPT + convert within
        // dimension for every Python key; nothing is rejected.
        let source = include_str!("../../../contracts/units.py");
        let mut python: Vec<(String, String, f64)> = Vec::new();
        let mut in_table = false;
        for line in source.lines() {
            let line = line.trim();
            if line.starts_with("_UNITS = {") { in_table = true; continue; }
            if in_table && line == "}" { break; }
            if !in_table || !line.contains("UnitDefinition(") { continue; }
            // Line shape: "key": UnitDefinition("dimension", factor),
            let key = line.split('"').nth(1).expect("unit key").to_string();
            let dim = line.split("(\"").nth(1).expect("dimension")
                .split('"').next().expect("dimension end").to_string();
            let factor: f64 = line.split(", ").nth(1).expect("factor")
                .trim_end_matches("),").trim_end_matches(',').parse()
                .expect("factor parses as f64");
            python.push((key, dim, factor));
        }
        assert_eq!(python.len(), 36, "expected 36 Python _UNITS keys, parser found {}", python.len());
        assert_eq!(UNIT_TABLE.len(), python.len(), "Rust table size must equal Python _UNITS size");
        for (key, dim, factor) in &python {
            match unit_definition(key) {
                Some((rust_dim, rust_factor)) => {
                    assert_eq!(rust_dim, dim.as_str(), "dimension mismatch for {key}");
                    assert_eq!(rust_factor, *factor, "factor mismatch for {key}");
                }
                None => panic!("Python unit {key} ({dim}, {factor}) has no Rust entry — add it to UNIT_TABLE"),
            }
        }
        for (key, _, _) in UNIT_TABLE {
            assert!(python.iter().any(|(k, _, _)| k == key),
                "Rust unit {key} is not in Python _UNITS — invented unit, remove it or add it to Python first");
        }
    }
    #[test] fn range_in_range_passes() { assert_eq!(evaluate_constraint(&range_request(5.0, "L", Some(2.0), Some(8.0))).status, CheckStatus::Pass); }
    #[test] fn range_boundaries_pass_inclusive() {
        assert_eq!(evaluate_constraint(&range_request(2.0, "L", Some(2.0), Some(8.0))).status, CheckStatus::Pass);
        assert_eq!(evaluate_constraint(&range_request(8.0, "L", Some(2.0), Some(8.0))).status, CheckStatus::Pass);
    }
    #[test] fn range_out_of_range_fails() {
        assert_eq!(evaluate_constraint(&range_request(1.0, "L", Some(2.0), Some(8.0))).status, CheckStatus::Fail);
        assert_eq!(evaluate_constraint(&range_request(9.0, "L", Some(2.0), Some(8.0))).status, CheckStatus::Fail);
    }
    #[test] fn range_tolerance_expands_inclusively() {
        let mut r = range_request(1.5, "L", Some(2.0), Some(8.0));
        r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r2 = range_request(8.5, "L", Some(2.0), Some(8.0));
        r2.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r2).status, CheckStatus::Pass);
    }
    #[test] fn range_missing_bounds_never_pass() {
        for (lo, hi) in [(None, None), (Some(2.0), None), (None, Some(8.0))] {
            let out = evaluate_constraint(&range_request(5.0, "L", lo, hi));
            assert_eq!(out.status, CheckStatus::Unknown);
            assert_eq!(out.reason_code, "INVALID_REQUEST");
        }
    }
    #[test] fn range_inverted_bounds_never_pass() {
        let out = evaluate_constraint(&range_request(5.0, "L", Some(8.0), Some(2.0)));
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INVALID_REQUEST");
    }
    // ISSUE-10/54 (2026-11-11): SCHEMA_VERSION is include_str! of
    // interop/SCHEMA_VERSION, not a second hard-coded copy. If that
    // file gains a trailing newline (or any other drift) this fails.
    #[test] fn schema_version_is_the_canonical_single_source() {
        assert_eq!(SCHEMA_VERSION, "1.0.0");
        assert!(!SCHEMA_VERSION.contains('\n'));
        assert_eq!(SUPPORTED_MAJOR, 1);
        assert_eq!(SCHEMA_VERSION.split('.').next().unwrap().parse::<u64>().unwrap(), SUPPORTED_MAJOR);
    }
    #[test] fn version_1_0_0_still_accepted() { assert_eq!(evaluate_constraint(&request_version(8.0, "L", "1.0.0")).status, CheckStatus::Pass); }
    #[test] fn version_patch_accepted() { assert_eq!(evaluate_constraint(&request_version(8.0, "L", "1.0.1")).status, CheckStatus::Pass); }
    #[test] fn version_minor_accepted() { assert_eq!(evaluate_constraint(&request_version(8.0, "L", "1.1.0")).status, CheckStatus::Pass); }
    #[test] fn version_major_rejected_with_distinct_error() {
        let out = evaluate_constraint(&request_version(8.0, "L", "2.0.0"));
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "UNSUPPORTED_MAJOR_VERSION");
        assert_eq!(out.details.as_deref(), Some("unsupported major schema version: 2.0.0 (supported major version 1)"));
        assert_ne!(out.details.as_deref(), Some("unsupported schema version"));
    }
    #[test] fn version_malformed_rejected() {
        let out = evaluate_constraint(&request_version(8.0, "L", "1.0"));
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INVALID_REQUEST");
    }
    // ---- ISSUE-42 (2026-11-11): audit of the ISSUE-42 list against
    // the coverage already present. Already covered, so NOT
    // duplicated here: negative tolerance, empty/whitespace id,
    // wrong schema version, unknown *bound* unit and range (all in
    // issue07_evaluator_invalid_input_is_unknown, the version tests
    // and the range tests above), and JSON-lines round-trip through
    // the binary (tests/binary_roundtrip.rs). Genuinely missing and
    // added here: dedicated ">=" cases (previously only incidental,
    // well away from the bound, in the kcal/food cases), "=="
    // tolerance boundaries (previously only exact equality in the
    // cross-check), and "<="/">=" tolerance boundaries (previously
    // only the range operator had a tolerance-boundary test). ----
    #[test] fn issue42_ge_operator_boundaries() {
        // Exact boundary passes; just below fails.
        let mut r = request(2500.0, "kcal/day");
        r.operator = ">=".into(); r.bound = Some(2500.0); r.bound_unit = "kcal/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(2499.999, "kcal/day");
        r.operator = ">=".into(); r.bound = Some(2500.0); r.bound_unit = "kcal/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // Well above still passes (control).
        let mut r = request(2800.0, "kcal/day");
        r.operator = ">=".into(); r.bound = Some(2500.0); r.bound_unit = "kcal/day".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
    }
    #[test] fn issue42_ge_tolerance_boundaries() {
        // Exactly bound - tolerance passes; just beyond it fails.
        let mut r = request(9.5, "L");
        r.operator = ">=".into(); r.bound = Some(10.0); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(9.4999999, "L");
        r.operator = ">=".into(); r.bound = Some(10.0); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // Tolerance 0.0: the boundary itself passes, below fails.
        let mut r = request(10.0, "L");
        r.operator = ">=".into(); r.bound = Some(10.0);
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
    }
    #[test] fn issue42_le_tolerance_boundaries() {
        // Exactly bound + tolerance passes; just beyond it fails.
        let mut r = request(10.5, "L");
        r.bound = Some(10.0); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(10.5000001, "L");
        r.bound = Some(10.0); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
    }
    #[test] fn issue42_eq_tolerance_boundaries() {
        // |value - bound| == tolerance passes on both sides; just
        // beyond it fails. At tolerance 0.0 only exact equality
        // passes (0.1 + 0.2 != 0.3 in floats).
        let mut r = request(10.5, "kg");
        r.operator = "==".into(); r.bound = Some(10.0); r.bound_unit = "kg".into(); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(9.5, "kg");
        r.operator = "==".into(); r.bound = Some(10.0); r.bound_unit = "kg".into(); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(10.5000001, "kg");
        r.operator = "==".into(); r.bound = Some(10.0); r.bound_unit = "kg".into(); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        let mut r = request(9.4999999, "kg");
        r.operator = "==".into(); r.bound = Some(10.0); r.bound_unit = "kg".into(); r.tolerance = 0.5;
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        let mut r = request(0.1 + 0.2, "kg");
        r.operator = "==".into(); r.bound = Some(0.3); r.bound_unit = "kg".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
    }
    // ---- ISSUE-47, Rust side (2026-11-11): conversion overflow. ----
    #[test] fn issue47_conversion_overflow_is_unknown_never_pass() {
        // Repro before the fix: 1e308 tonne -> g overflowed the
        // conversion to inf; ">=" then returned PASS with
        // normalized_value serialised as null, and "<=" returned
        // FAIL only by accident (inf <= bound is false). Both must
        // now be UNKNOWN / NON_FINITE, with no normalised value.
        for operator in ["<=", ">=", "=="] {
            let mut r = request(1e308, "tonne");
            r.operator = operator.into(); r.bound = Some(1.0); r.bound_unit = "g".into();
            let out = evaluate_constraint(&r);
            assert_eq!(out.status, CheckStatus::Unknown, "operator {operator}: overflow must be UNKNOWN");
            assert_eq!(out.reason_code, "NON_FINITE", "operator {operator}");
            assert_eq!(out.details.as_deref(), Some("normalized value must be finite"));
            assert!(out.normalized_value.is_none(), "operator {operator}: no normalised value");
        }
        // The same overflow through the range path.
        let mut r = range_request(1e308, "tonne", Some(1.0), Some(2.0));
        r.bound_unit = "g".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "NON_FINITE");
        // Just below overflow still converts and decides normally
        // (approximate: float arithmetic need not reproduce the
        // decimal exactly).
        let v = convert(1e300, "tonne", "g").expect("1e300 tonne -> g is finite");
        assert!(v.is_finite() && (v - 1e306).abs() < 1e300);
    }
    // ---- ISSUE-34 (2026-11-13): the 12 new registry units. ----
    #[test] fn issue34_new_units_in_registry() {
        // Teragramme-scale mass: 1 Tg = 1 Mt = 1e9 kg exactly, Tg<->Mt 1:1.
        assert_eq!(convert(1.0, "Tg", "Mt"), Some(1.0));
        assert_eq!(convert(1.0, "Mt", "Tg"), Some(1.0));
        assert_eq!(convert(1.0, "Tg", "kg"), Some(1e9));
        assert_eq!(convert(1.0, "Mt", "kg"), Some(1e9));
        assert_eq!(convert(1.0, "million tonnes", "Tg"), Some(1.0));
        assert_eq!(convert(2.5, "million tonnes", "kg"), Some(2.5e9));
        assert_eq!(convert(1.0, "Tg", "tonne"), Some(1e6));
        // Mass-per-year rates, dimension "mass_rate_year" (base Tg/yr).
        assert_eq!(convert(1.0, "Tg/yr", "Mt/yr"), Some(1.0));
        // tonne/yr -> kg/yr divides by inexact 1e-9, so 1.0 * 1e-6 /
        // 1e-9 comes out 999.9999999999999, not 1000.0 — approximate.
        let v = convert(1.0, "tonne/yr", "kg/yr").expect("tonne/yr -> kg/yr");
        assert!((v - 1000.0).abs() < 1e-9, "tonne/yr -> kg/yr ≈ 1000, got {v}");
        assert_eq!(convert(1.0, "kg/yr", "tonne/yr"), Some(0.001));
        assert_eq!(convert(6.2, "Tg/yr", "tonne/yr"), Some(6.2e6));
        // Percent: dimensionless, factor 0.01 — 33 percent = 0.33.
        assert_eq!(convert(33.0, "percent", "1"), Some(0.33));
        assert_eq!(convert(33.0, "%", "1"), Some(0.33));
        assert_eq!(convert(0.33, "1", "percent"), Some(33.0));
        // Labour time rates: base hours/week; 1 hour/day = 7 hours/week.
        assert_eq!(convert(1.0, "hours/day", "hours/week"), Some(7.0));
        assert_eq!(convert(7.0, "hours/week", "hours/day"), Some(1.0));
        assert_eq!(convert(40.0, "hours/week", "hours/week"), Some(40.0));
        // One evaluate_constraint case per new unit family.
        // Tg/yr: 5.0 <= 6.2 PASS; 18.2 <= 6.2 FAIL.
        let mut r = request(5.0, "Tg/yr");
        r.bound = Some(6.2); r.bound_unit = "Tg/yr".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(18.2, "Tg/yr");
        r.bound = Some(6.2); r.bound_unit = "Tg/yr".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // Mt/yr: 5.0 Mt/yr = 5.0 Tg/yr <= 6.2 Tg/yr PASS.
        let mut r = request(5.0, "Mt/yr");
        r.bound = Some(6.2); r.bound_unit = "Tg/yr".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // tonne/yr / kg/yr: 1e6 tonne/yr = 1e9 kg/yr <= 2e9 kg/yr PASS.
        let mut r = request(1e6, "tonne/yr");
        r.bound = Some(2e9); r.bound_unit = "kg/yr".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // Percent: 33 percent == 0.33 dimensionless PASS.
        let mut r = request(33.0, "percent");
        r.operator = "==".into(); r.bound = Some(0.33); r.bound_unit = "1".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // hours/week: 40 <= 48 PASS; hours/day: 1 h/day = 7 h/week <= 7 PASS,
        // 2 h/day = 14 h/week > 7 FAIL.
        let mut r = request(40.0, "hours/week");
        r.bound = Some(48.0); r.bound_unit = "hours/week".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(1.0, "hours/day");
        r.bound = Some(7.0); r.bound_unit = "hours/week".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        let mut r = request(2.0, "hours/day");
        r.bound = Some(7.0); r.bound_unit = "hours/week".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Fail);
        // hours (total time): 8 <= 10 PASS.
        let mut r = request(8.0, "hours");
        r.bound = Some(10.0); r.bound_unit = "hours".into();
        assert_eq!(evaluate_constraint(&r).status, CheckStatus::Pass);
        // Cross-dimension rejection: Tg/yr vs tonne/day must NOT convert —
        // different dimensions ("mass_rate_year" vs "mass_rate"); a
        // conversion would need a stated days-per-year.
        let mut r = request(5.0, "Tg/yr");
        r.bound = Some(10.0); r.bound_unit = "tonne/day".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "INCOMPATIBLE_UNIT");
        assert_eq!(convert(5.0, "Tg/yr", "tonne/day"), None);
        // ISSUE-47 overflow for the NEW units: 1e308 Tg -> g overflows
        // to inf and must be UNKNOWN / NON_FINITE, never a silent inf.
        for operator in ["<=", ">=", "=="] {
            let mut r = request(1e308, "Tg");
            r.operator = operator.into(); r.bound = Some(1.0); r.bound_unit = "g".into();
            let out = evaluate_constraint(&r);
            assert_eq!(out.status, CheckStatus::Unknown, "operator {operator}: Tg overflow must be UNKNOWN");
            assert_eq!(out.reason_code, "NON_FINITE", "operator {operator}");
            assert!(out.normalized_value.is_none(), "operator {operator}: no normalised value");
        }
    }
    // ---- Cross-checks: agreed verdict on EVERY case in test-vectors.json ----
    #[test] fn crosscheck_all_wire_cases() {
        // (id, request, agreed status) — expected values are the Python-
        // verified values updated per the four 2026-11-11 decisions.
        let mut food = request(2800.0, "kcal/capita/day");
        food.constraint_id = "food_energy_adequacy".into();
        food.operator = ">=".into(); food.bound = Some(2500.0); food.bound_unit = "kcal/capita/day".into();
        let mut tonne = request(8.0, "t");
        tonne.constraint_id = "mass".into(); tonne.bound = Some(10.0); tonne.bound_unit = "t".into();
        let mut vol = request(0.008, "m3");
        vol.constraint_id = "vol".into(); // 0.008 m3 = 8 L <= 10 L
        let mut kday = request(2800.0, "kcal/day");
        kday.constraint_id = "kday".into(); kday.operator = ">=".into(); kday.bound = Some(2500.0); kday.bound_unit = "kcal/day".into();
        let mut eq = request(10.0, "kg");
        eq.constraint_id = "eq".into(); eq.operator = "==".into(); eq.bound = Some(10.0); eq.bound_unit = "kg".into();
        let fail = request(12.0, "L");
        let mut incomp = request(5.0, "L");
        incomp.constraint_id = "incomp".into(); incomp.bound_unit = "kg".into();
        let range = range_request(5.0, "L", Some(2.0), Some(8.0));
        // ISSUE-34 (2026-11-13) wire cases, mirroring interop/test-vectors.json.
        let mut tg_pass = request(5.0, "Tg/yr");
        tg_pass.constraint_id = "mass-rate-year-tg".into(); tg_pass.bound = Some(6.2); tg_pass.bound_unit = "Tg/yr".into();
        let mut tg_fail = request(18.2, "Tg/yr");
        tg_fail.constraint_id = "mass-rate-year-tg".into(); tg_fail.bound = Some(6.2); tg_fail.bound_unit = "Tg/yr".into();
        let mut pct = request(33.0, "percent");
        pct.constraint_id = "percent-conversion".into(); pct.operator = "==".into(); pct.bound = Some(0.33); pct.bound_unit = "1".into();
        let mut hrs_pass = request(1.0, "hours/day");
        hrs_pass.constraint_id = "hours-day-to-week".into(); hrs_pass.bound = Some(7.0); hrs_pass.bound_unit = "hours/week".into();
        let mut hrs_fail = request(2.0, "hours/day");
        hrs_fail.constraint_id = "hours-day-to-week".into(); hrs_fail.bound = Some(7.0); hrs_fail.bound_unit = "hours/week".into();
        let mut tg_incomp = request(5.0, "Tg/yr");
        tg_incomp.constraint_id = "mass-rate-year-vs-day".into(); tg_incomp.bound = Some(10.0); tg_incomp.bound_unit = "tonne/day".into();
        let cases: Vec<(&str, ConstraintRequest, CheckStatus)> = vec![
            ("food-energy-adequacy", food, CheckStatus::Pass),
            ("mass-tonne", tonne, CheckStatus::Pass),
            ("volume-m3-vs-litre", vol, CheckStatus::Pass),
            ("kcal-per-day-invented-unit", kday, CheckStatus::Pass),
            ("equality-kg", eq, CheckStatus::Pass),
            ("fail-litre", fail, CheckStatus::Fail),
            ("incompatible-units", incomp, CheckStatus::Unknown),
            ("range-operator", range, CheckStatus::Pass),
            ("mass-rate-year-tg-pass", tg_pass, CheckStatus::Pass),
            ("mass-rate-year-tg-fail", tg_fail, CheckStatus::Fail),
            ("percent-conversion", pct, CheckStatus::Pass),
            ("hours-day-to-week-pass", hrs_pass, CheckStatus::Pass),
            ("hours-day-to-week-fail", hrs_fail, CheckStatus::Fail),
            ("mass-rate-year-vs-day-incompatible", tg_incomp, CheckStatus::Unknown),
        ];
        for (id, req, expected) in cases {
            assert_eq!(evaluate_constraint(&req).status, expected, "wire case {id}");
        }
    }
    #[test] fn crosscheck_all_version_cases() {
        assert_eq!(evaluate_constraint(&request_version(8.0, "L", "1.0.1")).status, CheckStatus::Pass, "version-patch 1.0.1 accepted");
        assert_eq!(evaluate_constraint(&request_version(8.0, "L", "1.1.0")).status, CheckStatus::Pass, "version-minor 1.1.0 accepted");
        let out = evaluate_constraint(&request_version(8.0, "L", "2.0.0"));
        assert_eq!(out.status, CheckStatus::Unknown, "version-major 2.0.0 rejected");
        assert_eq!(out.reason_code, "UNSUPPORTED_MAJOR_VERSION");
        assert_eq!(out.details.as_deref(), Some("unsupported major schema version: 2.0.0 (supported major version 1)"));
    }
    #[test] fn crosscheck_aggregation_cases() {
        // test-vectors.json aggregation cases, via overall_from_checks.
        assert_eq!(overall_from_checks(&[]), CheckStatus::NotChecked, "empty-checks");
        assert_eq!(overall_from_checks(&[CheckStatus::Unknown]), CheckStatus::Unknown, "unknown-only-checks");
    }
    #[test] fn overall_from_checks_mirrors_python_rules() {
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::Fail]), CheckStatus::Fail);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::Unknown]), CheckStatus::Unknown);
        assert_eq!(overall_from_checks(&[CheckStatus::Unknown, CheckStatus::Incomplete]), CheckStatus::Incomplete);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::NotChecked]), CheckStatus::NotChecked);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::Pass]), CheckStatus::Pass);
        assert_eq!(overall_from_checks(&[CheckStatus::Fail, CheckStatus::Incomplete]), CheckStatus::Fail);
    }
    // ---- ISSUE-07 (2026-11-11): one invalid/empty-input mapping ----
    // Same matrix as Python tests/test_issue07_status_mapping.py and
    // Julia runtests.jl: evaluator level returns UNKNOWN (never PASS,
    // never a panic) for every invalid input; the wire level rejects
    // malformed requests with a reason; an empty check list aggregates
    // to NOT_CHECKED. Full mapping + rationale:
    // docs/STATUS_MAPPING_ISSUE-07.md.
    #[test] fn issue07_evaluator_invalid_input_is_unknown() {
        // (label, request, expected reason_code)
        let mut cases: Vec<(&str, ConstraintRequest, &str)> = Vec::new();
        cases.push(("non-finite NaN value", request(f64::NAN, "L"), "NON_FINITE"));
        cases.push(("non-finite +inf value", request(f64::INFINITY, "L"), "NON_FINITE"));
        cases.push(("non-finite -inf value", request(f64::NEG_INFINITY, "L"), "NON_FINITE"));
        cases.push(("non-finite tolerance", {
            let mut r = request(8.0, "L"); r.tolerance = f64::NAN; r }, "NON_FINITE"));
        cases.push(("negative tolerance", {
            let mut r = request(8.0, "L"); r.tolerance = -1.0; r }, "INVALID_REQUEST"));
        cases.push(("empty constraint_id", {
            let mut r = request(8.0, "L"); r.constraint_id = "".into(); r }, "INVALID_REQUEST"));
        cases.push(("whitespace constraint_id", {
            let mut r = request(8.0, "L"); r.constraint_id = "   ".into(); r }, "INVALID_REQUEST"));
        cases.push(("unknown value_unit", request(8.0, "bucket"), "UNKNOWN_UNIT"));
        cases.push(("unknown bound_unit", {
            let mut r = request(8.0, "L"); r.bound_unit = "bucket".into(); r }, "UNKNOWN_UNIT"));
        cases.push(("empty value_unit", request(8.0, ""), "UNKNOWN_UNIT"));
        cases.push(("incompatible units", {
            let mut r = request(5.0, "L"); r.bound_unit = "kg".into(); r }, "INCOMPATIBLE_UNIT"));
        cases.push(("missing bound, non-range", {
            let mut r = request(8.0, "L"); r.bound = None; r }, "INVALID_REQUEST"));
        cases.push(("range missing both bounds",
            range_request(5.0, "L", None, None), "INVALID_REQUEST"));
        cases.push(("range missing high bound",
            range_request(5.0, "L", Some(2.0), None), "INVALID_REQUEST"));
        cases.push(("range inverted bounds",
            range_request(5.0, "L", Some(8.0), Some(2.0)), "INVALID_REQUEST"));
        cases.push(("range non-finite low bound",
            range_request(5.0, "L", Some(f64::NAN), Some(8.0)), "NON_FINITE"));
        cases.push(("bad operator", {
            let mut r = request(8.0, "L"); r.operator = "!=".into(); r }, "UNSUPPORTED_OPERATOR"));
        cases.push(("non-finite bound", {
            let mut r = request(8.0, "L"); r.bound = Some(f64::NAN); r }, "NON_FINITE"));
        cases.push(("major version", request_version(8.0, "L", "2.0.0"), "UNSUPPORTED_MAJOR_VERSION"));
        cases.push(("malformed version", request_version(8.0, "L", "1.0"), "INVALID_REQUEST"));
        for (label, req, reason) in cases {
            let out = evaluate_constraint(&req);
            assert_eq!(out.status, CheckStatus::Unknown, "{label}: must be UNKNOWN");
            assert_eq!(out.reason_code, reason, "{label}: reason_code");
            assert!(out.normalized_value.is_none(), "{label}: no normalized value");
        }
        // Controls: the same shape with valid inputs still decides.
        assert_eq!(evaluate_constraint(&request(8.0, "L")).status, CheckStatus::Pass);
        assert_eq!(evaluate_constraint(&request(12.0, "L")).status, CheckStatus::Fail);
    }
    #[test] fn issue07_evaluate_constraint_never_returns_not_checked_or_incomplete() {
        // ISSUE-07 (b): NotChecked and Incomplete are unreachable from
        // evaluate_constraint — only Pass/Fail/Unknown. The battery
        // covers valid, failing and every invalid shape above; the
        // variants live only in overall_from_checks (see
        // issue07_overall_from_checks_reachable_paths).
        let mut reqs: Vec<ConstraintRequest> = vec![
            request(8.0, "L"), request(12.0, "L"),
            request(f64::NAN, "L"), request(8.0, "bucket"),
            range_request(5.0, "L", Some(2.0), Some(8.0)),
            range_request(5.0, "L", None, None),
            request_version(8.0, "L", "2.0.0"),
            request_version(8.0, "L", "1.0.1"),
        ];
        reqs.push({ let mut r = request(8.0, "L"); r.constraint_id = "".into(); r });
        reqs.push({ let mut r = request(8.0, "L"); r.operator = "!=".into(); r });
        for req in &reqs {
            let status = evaluate_constraint(req).status;
            assert!(matches!(status, CheckStatus::Pass | CheckStatus::Fail | CheckStatus::Unknown),
                "evaluate_constraint returned {status:?} for {req:?}");
        }
        // Serialised form likewise never carries the other two strings.
        for req in &reqs {
            let json = serde_json::to_string(&evaluate_constraint(req)).unwrap();
            assert!(!json.contains("NOT_CHECKED") && !json.contains("INCOMPLETE"),
                "serialised result must not contain NOT_CHECKED/INCOMPLETE: {json}");
        }
    }
    #[test] fn issue07_overall_from_checks_reachable_paths() {
        // ISSUE-07 (b): the two variants ARE reachable, just not from
        // evaluate_constraint. NotChecked is PRODUCED here (empty
        // input); Incomplete is PROPAGATED here (any Incomplete input)
        // — it is never produced by a single-constraint evaluator in
        // any language, only upstream (in Python, the domain/engine
        // layer when a calculation was not completed). Removing either
        // variant would be a breaking API change (wire vocabulary +
        // aggregation contract); removal is out of scope — this test
        // pins the reachable paths instead.
        assert_eq!(overall_from_checks(&[]), CheckStatus::NotChecked,
            "empty check list -> NOT_CHECKED, never PASS");
        assert_eq!(overall_from_checks(&[CheckStatus::Incomplete]), CheckStatus::Incomplete);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::Incomplete]), CheckStatus::Incomplete);
        assert_eq!(overall_from_checks(&[CheckStatus::Fail, CheckStatus::Incomplete]), CheckStatus::Fail);
        assert_eq!(overall_from_checks(&[CheckStatus::Unknown, CheckStatus::NotChecked]), CheckStatus::Unknown);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::NotChecked]), CheckStatus::NotChecked);
        assert_eq!(overall_from_checks(&[CheckStatus::Pass, CheckStatus::Pass]), CheckStatus::Pass);
    }
    #[test] fn issue07_malformed_wire_json_cannot_deserialize() {
        // Wire level, Rust side: a malformed request cannot even
        // construct a ConstraintRequest (serde), so it never reaches
        // evaluate_constraint. start-kernel maps the deserialisation
        // failure to an UNKNOWN / INVALID_REQUEST result line — the
        // same rejection-with-a-reason Python expresses as a raised
        // ValueError and Julia as an UNKNOWN result. JSON numbers are
        // finite by construction, so non-finite values arrive only
        // through the library API (see NON_FINITE cases above), and
        // null / string / boolean values fail here instead.
        let base = r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":{}}"#;
        assert!(serde_json::from_str::<ConstraintRequest>(base).is_ok());
        for (label, bad) in [
            ("missing constraint_id",
             r#"{"schema_version":"1.0.0","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#),
            ("value as string",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":"8","value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#),
            ("value as boolean",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":true,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#),
            ("value as null",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":null,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#),
            ("unknown extra field (deny_unknown_fields)",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"surprise":1}"#),
            // ISSUE-39 (2026-11-11): a non-object context violates
            // the request schema ("context": {"type": "object"}).
            // A string / number / array / null context must be a
            // parse error, never a PASS.
            ("context as string",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":"not-an-object"}"#),
            ("context as number",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":42}"#),
            ("context as array",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":[]}"#),
            ("context as null",
             r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":null}"#),
        ] {
            assert!(serde_json::from_str::<ConstraintRequest>(bad).is_err(),
                "{label}: malformed wire JSON must not deserialize");
        }
    }
    #[test] fn issue39_omitted_context_normalises_to_empty_object() {
        // ISSUE-39: an omitted context deserialises to the empty
        // object {} (the schema's shape for "no context"), not null.
        // A present object context is preserved verbatim.
        let omitted = r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#;
        let req: ConstraintRequest = serde_json::from_str(omitted).unwrap();
        assert!(req.context.is_empty(), "omitted context must be {{}}, got {:?}", req.context);
        let present = r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":{"source":"probe"}}"#;
        let req: ConstraintRequest = serde_json::from_str(present).unwrap();
        assert_eq!(req.context.get("source").and_then(|v| v.as_str()), Some("probe"));
        assert_eq!(evaluate_constraint(&req).status, CheckStatus::Pass);
    }
    // ---- ISSUE-49 (2026-11-11): ConstraintResult.details is optional
    // per the result schema, and the result struct carries
    // deny_unknown_fields like the request struct. ----
    #[test] fn issue49_result_without_details_deserializes() {
        // Schema-valid result with no "details" key at all.
        let json = r#"{"schema_version":"1.0.0","constraint_id":"w","status":"PASS","normalized_value":8.0,"normalized_unit":"L","reason_code":"OK"}"#;
        let result: ConstraintResult = serde_json::from_str(json)
            .expect("a schema-valid result without details must deserialize");
        assert_eq!(result.details, None);
        // Explicit null details is likewise accepted.
        let json_null = r#"{"schema_version":"1.0.0","constraint_id":"w","status":"PASS","normalized_value":8.0,"normalized_unit":"L","reason_code":"OK","details":null}"#;
        assert!(serde_json::from_str::<ConstraintResult>(json_null).is_ok());
        // A result WITH details still round-trips.
        let with = evaluate_constraint(&request(8.0, "L"));
        assert_eq!(with.details.as_deref(), Some("Evaluated using finite inputs and reviewed-unit conversion"));
        let back: ConstraintResult = serde_json::from_str(&serde_json::to_string(&with).unwrap()).unwrap();
        assert_eq!(back.details, with.details);
    }
    #[test] fn issue49_result_rejects_unknown_fields() {
        // deny_unknown_fields, symmetric with ConstraintRequest and
        // with the result schema's additionalProperties: false.
        let json = r#"{"schema_version":"1.0.0","constraint_id":"w","status":"PASS","normalized_value":8.0,"normalized_unit":"L","reason_code":"OK","surprise":1}"#;
        assert!(serde_json::from_str::<ConstraintResult>(json).is_err(),
            "result with an unknown field must not deserialize");
    }
    #[test] fn issue49_result_without_details_omits_the_key() {
        // skip_serializing_if: a None details is omitted on output,
        // so the emitted shape stays schema-valid either way.
        let result = ConstraintResult {
            schema_version: SCHEMA_VERSION.into(), constraint_id: "w".into(),
            status: CheckStatus::Unknown, normalized_value: None, normalized_unit: None,
            reason_code: "INVALID_REQUEST".into(), details: None,
        };
        let json = serde_json::to_string(&result).unwrap();
        assert!(!json.contains("details"), "None details must be omitted, got {json}");
        assert!(json.contains("\"constraint_id\":\"w\""));
    }
    // ---- ISSUE-52 (2026-11-11): unsupported operator gets its own
    // reason code (matching Julia's UNSUPPORTED_OPERATOR), and the
    // finiteness check runs before the tolerance sign check, so a
    // negative-non-finite tolerance is NON_FINITE, not
    // INVALID_REQUEST. Via the JSON wire these non-finite paths are
    // largely unreachable (JSON has no Infinity/NaN), so they are
    // tested here with DIRECT library calls, not through the binary.
    // ----
    #[test] fn issue52_unsupported_operator_has_its_own_reason_code() {
        let mut r = request(8.0, "L");
        r.operator = "!=".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Unknown);
        assert_eq!(out.reason_code, "UNSUPPORTED_OPERATOR");
        // The other INVALID_REQUEST paths keep their code.
        let mut r = request(8.0, "L");
        r.constraint_id = "".into();
        assert_eq!(evaluate_constraint(&r).reason_code, "INVALID_REQUEST");
        let mut r = request(8.0, "L");
        r.tolerance = -1.0;
        assert_eq!(evaluate_constraint(&r).reason_code, "INVALID_REQUEST");
    }
    #[test] fn issue52_finiteness_checked_before_tolerance_sign() {
        // Negative-non-finite tolerance: -inf is both negative and
        // non-finite; finiteness wins (NON_FINITE).
        for tol in [f64::NEG_INFINITY, f64::INFINITY, f64::NAN] {
            let mut r = request(8.0, "L");
            r.tolerance = tol;
            let out = evaluate_constraint(&r);
            assert_eq!(out.status, CheckStatus::Unknown, "tolerance {tol}");
            assert_eq!(out.reason_code, "NON_FINITE", "tolerance {tol}");
        }
        // Negative FINITE tolerance is still INVALID_REQUEST.
        let mut r = request(8.0, "L");
        r.tolerance = -1.0;
        assert_eq!(evaluate_constraint(&r).reason_code, "INVALID_REQUEST");
        // A negative-non-finite VALUE with a valid tolerance is
        // NON_FINITE regardless of evaluation order.
        let mut r = request(f64::NEG_INFINITY, "L");
        r.tolerance = -1.0;
        assert_eq!(evaluate_constraint(&r).reason_code, "NON_FINITE");
    }
    // ---- ISSUE-53 (2026-11-11): normalized_* is a real normalisation
    // — the value expressed in bound_unit (the constraint's unit),
    // matching Python Constraint.evaluate — not an echo of the input.
    // Conversion landed with the test-vector job, so the success path
    // already converts; these tests pin the definition, including
    // the range path and the same-unit identity case. ----
    #[test] fn issue53_normalized_is_value_in_bound_unit() {
        // 0.008 m3 = 8 L in the bound's unit; the echo would be 0.008 m3.
        let out = evaluate_constraint(&request(0.008, "m3"));
        assert_eq!(out.normalized_value, Some(8.0));
        assert_eq!(out.normalized_unit.as_deref(), Some("L"));
        // Reverse direction: 8000 g = 8 kg.
        let mut r = request(8000.0, "g");
        r.bound = Some(10.0);
        r.bound_unit = "kg".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.normalized_value, Some(8.0));
        assert_eq!(out.normalized_unit.as_deref(), Some("kg"));
        // Same unit is the identity: 8 L stays 8 L.
        let out = evaluate_constraint(&request(8.0, "L"));
        assert_eq!(out.normalized_value, Some(8.0));
        assert_eq!(out.normalized_unit.as_deref(), Some("L"));
        // Range path normalises too: 8000 g = 8 kg inside [2, 10] kg.
        let mut r = range_request(8000.0, "g", Some(2.0), Some(10.0));
        r.bound_unit = "kg".into();
        let out = evaluate_constraint(&r);
        assert_eq!(out.status, CheckStatus::Pass);
        assert_eq!(out.normalized_value, Some(8.0));
        assert_eq!(out.normalized_unit.as_deref(), Some("kg"));
        // Unknown / invalid input normalises to nothing, never an echo.
        let out = evaluate_constraint(&request(8.0, "bucket"));
        assert_eq!(out.normalized_value, None);
        assert_eq!(out.normalized_unit, None);
    }
    // ---- Consuming test: interop/test-vectors.json (ISSUE-04, 2026-11-11) ----
    // Loads the shared file (serde_json is already a dependency of this
    // crate) and drives evaluate_constraint / check_schema_version /
    // overall_from_checks from it. A disagreement between the file and
    // the evaluator is a test FAILURE. The file records all four
    // 2026-11-11 decisions; every case is must_agree or already_agrees.
    fn status_from_str(s: &str) -> CheckStatus {
        match s {
            "PASS" => CheckStatus::Pass,
            "FAIL" => CheckStatus::Fail,
            "UNKNOWN" => CheckStatus::Unknown,
            "NOT_CHECKED" => CheckStatus::NotChecked,
            "INCOMPLETE" => CheckStatus::Incomplete,
            other => panic!("unknown status in test-vectors.json: {other}"),
        }
    }
    // Verified-status fields are dated (e.g. "rust_verified_2026-11-11");
    // newer cases carry a later date (ISSUE-34 cases: 2026-11-13).
    // Pick the latest dated field so old and new cases are both read
    // correctly.
    fn verified_status<'a>(case: &'a serde_json::Value, lang: &str) -> &'a str {
        let prefix = format!("{lang}_verified_");
        let obj = case.as_object().expect("case must be an object");
        let mut dated: Vec<&String> = obj.keys().filter(|k| k.starts_with(&prefix)).collect();
        dated.sort();
        let key = dated.last().unwrap_or_else(|| panic!("no {lang} verified field in case {}", case["id"]));
        obj[*key]["status"].as_str().expect("verified status must be a string")
    }
    #[test] fn consumes_shared_test_vectors_file() {
        let text = include_str!("../../../interop/test-vectors.json");
        let data: serde_json::Value = serde_json::from_str(text)
            .expect("interop/test-vectors.json must parse");
        // No case may still be an open decision after 2026-11-11.
        for section in ["cases", "version_cases"] {
            for entry in data[section].as_array().expect("array") {
                assert_ne!(entry["conformance"].as_str().unwrap(), "open_decision",
                    "open_decision remains: {}", entry["id"]);
            }
        }
        // All 14 wire cases, through evaluate_constraint.
        let cases = data["cases"].as_array().expect("cases array");
        assert_eq!(cases.len(), 14, "expected 14 wire cases");
        for case in cases {
            let id = case["id"].as_str().unwrap();
            let req: ConstraintRequest = serde_json::from_value(case["request"].clone())
                .unwrap_or_else(|e| panic!("wire case {id} request must deserialize: {e}"));
            let expected = status_from_str(verified_status(case, "rust"));
            // The file also pins the other languages to the same status.
            for lang in ["python", "julia"] {
                assert_eq!(verified_status(case, lang),
                    verified_status(case, "rust"),
                    "languages disagree in file for {id}");
            }
            assert_eq!(evaluate_constraint(&req).status, expected, "wire case {id}");
        }
        // The decided range wire shape carries bound_low/bound_high, no "bound".
        let range = cases.iter().find(|c| c["id"] == "range-operator").unwrap();
        assert_eq!(range["request"]["operator"], "range");
        assert_eq!(range["request"]["bound_low"], 2.0);
        assert_eq!(range["request"]["bound_high"], 8.0);
        assert!(range["request"].get("bound").is_none() || range["request"]["bound"].is_null(),
            "range wire shape must not carry a bound");
        // All 3 version cases, through the version check inside
        // evaluate_constraint (accepted -> PASS on a valid request,
        // major mismatch -> UNKNOWN / UNSUPPORTED_MAJOR_VERSION with
        // the exact distinct message).
        let versions = data["version_cases"].as_array().expect("version_cases array");
        assert_eq!(versions.len(), 3, "expected 3 version cases");
        for vc in versions {
            let id = vc["id"].as_str().unwrap();
            let version = vc["request_schema_version"].as_str().unwrap();
            let out = evaluate_constraint(&request_version(8.0, "L", version));
            if vc["expected"]["accepted"].as_bool().unwrap() {
                assert_eq!(out.status, CheckStatus::Pass, "{id} {version} must be accepted");
            } else {
                assert_eq!(out.status, CheckStatus::Unknown, "{id} {version} must be rejected");
                assert_eq!(out.reason_code, "UNSUPPORTED_MAJOR_VERSION");
                assert_eq!(out.details.as_deref(), vc["expected"]["error"].as_str(), "{id} distinct error");
            }
        }
        // Both aggregation cases, through overall_from_checks.
        let agg = data["aggregation_cases"].as_array().expect("aggregation_cases array");
        assert_eq!(agg.len(), 2, "expected 2 aggregation cases");
        for ac in agg {
            let id = ac["id"].as_str().unwrap();
            let checks: Vec<CheckStatus> = ac["input"]["checks"].as_array().unwrap().iter()
                .map(|s| status_from_str(s.as_str().unwrap())).collect();
            let expected = status_from_str(ac["rust_verified_2026-11-11"]["status"].as_str().unwrap());
            assert_eq!(overall_from_checks(&checks), expected, "aggregation case {id}");
        }
    }
}
