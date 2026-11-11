//! Tonic / gRPC stub (grpc/grpc-rust, MIT).
//!
//! STUB ONLY in this assembly: the service shape from
//! `../proto/constraint_evaluation.proto` is declared here so the
//! Rust side has a contract to implement, but no Tonic server is
//! started and no network call is made. The runnable local gRPC
//! round-trip in this assembly is the Python grpcio server in
//! `adapters/interop.py`. Do NOT claim a Tonic server ran here
//! unless a later run actually starts one and a client call succeeds.

/// The constraint-evaluation service, as declared in the .proto.
/// Implementors must return exactly one of the wire statuses
/// PASS / FAIL / UNKNOWN / NOT_CHECKED / INCOMPLETE, and must never
/// turn UNKNOWN or INCOMPLETE into PASS.
pub trait ConstraintEvaluationService {
    fn evaluate(&self, constraint_id: &str, operator: &str, value: f64,
                value_unit: &str, bound: f64, bound_unit: &str,
                tolerance: f64) -> (String, String);
}

/// Pure, local evaluation with the same semantics as the Python
/// adapter (adapters/interop.py::_evaluate_local). No network.
pub struct LocalEvaluator;

impl ConstraintEvaluationService for LocalEvaluator {
    fn evaluate(&self, constraint_id: &str, operator: &str, value: f64,
                value_unit: &str, bound: f64, bound_unit: &str,
                tolerance: f64) -> (String, String) {
        if constraint_id.is_empty() {
            return ("UNKNOWN".to_string(), "INVALID_REQUEST".to_string());
        }
        if !value.is_finite() || !bound.is_finite() {
            return ("UNKNOWN".to_string(), "NON_FINITE".to_string());
        }
        if value_unit != bound_unit {
            return ("UNKNOWN".to_string(), "INCOMPATIBLE_UNIT".to_string());
        }
        let ok = match operator {
            "<=" => value <= bound + tolerance,
            ">=" => value >= bound - tolerance,
            "==" => (value - bound).abs() <= tolerance,
            _ => return ("UNKNOWN".to_string(), "INVALID_REQUEST".to_string()),
        };
        (if ok { "PASS" } else { "FAIL" }.to_string(), "OK".to_string())
    }
}
