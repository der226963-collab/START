//! Real Tonic server for the constraint-evaluation RPC
//! (`proto/constraint_evaluation.proto`, service
//! `start.spine.v1.ConstraintEvaluation`, method `Evaluate`).
//!
//! The server EVALUATES: for each request it runs the same
//! constraint logic as the Python adapter
//! (`adapters/interop.py::_evaluate_local`) — schema-version and
//! constraint-id validation, non-finite and incompatible-unit
//! checks, then the `<=` / `>=` / `==` comparison with tolerance —
//! and returns a real PASS / FAIL / UNKNOWN verdict. It is not a
//! stub: a feasible plan passes and an over-limit plan fails, over
//! the wire.
//!
//! The server does NOT verify a plan. A PASS here is one constraint
//! check, not a verified plan: verification still means PASS *and*
//! the separate verify step (constraint verify + JuMP/HiGHS LP
//! cross-check) *and* human approval (`needs_human_decision=true`).
//! The server never marks anything verified and never bypasses the
//! verify step.
//!
//! Transport: Unix domain socket only, local only. No TLS and no
//! authentication on the socket — anyone who can reach the socket
//! file can call Evaluate, so the socket must live in a private
//! directory (the binary defaults to `/tmp` with a per-run name;
//! tests use a fresh temp dir). TCP loopback is deliberately not
//! used: the VM's egress proxy intercepts TCP loopback and breaks
//! gRPC HTTP/2 there (verified 2026-11-10); a Unix socket bypasses
//! that.

use std::path::{Path, PathBuf};

use tokio::net::UnixListener;
use tokio_stream::wrappers::UnixListenerStream;
use tonic::{Request, Response, Status};

use crate::proto::v1::constraint_evaluation_server::{
    ConstraintEvaluation, ConstraintEvaluationServer,
};
use crate::proto::v1::{ConstraintRequest, ConstraintResult};
use crate::tonic_stub::{ConstraintEvaluationService, LocalEvaluator};

/// The service implementation: one evaluator, no state.
#[derive(Debug, Default)]
pub struct EvaluatorService;

impl EvaluatorService {
    /// Pure evaluation of one decoded request, shared by the server
    /// and the unit tests. Mirrors `adapters/interop.py::_evaluate_local`.
    pub fn evaluate_request(req: &ConstraintRequest) -> ConstraintResult {
        let mut result = ConstraintResult {
            schema_version: "1.0.0".to_string(),
            constraint_id: req.constraint_id.clone(),
            status: "UNKNOWN".to_string(),
            normalized_value: req.value,
            normalized_unit: req.value_unit.clone(),
            reason_code: "INVALID_REQUEST".to_string(),
            details: String::new(),
        };
        if req.schema_version != "1.0.0" || req.constraint_id.is_empty() {
            result.details = "unsupported schema version or empty constraint_id"
                .to_string();
            return result;
        }
        if !req.value.is_finite() || !req.bound.is_finite() {
            result.reason_code = "NON_FINITE".to_string();
            result.details = "non-finite value/bound".to_string();
            return result;
        }
        if req.value_unit != req.bound_unit {
            result.reason_code = "INCOMPATIBLE_UNIT".to_string();
            result.details =
                "units differ; this server does not convert units".to_string();
            return result;
        }
        let ev = LocalEvaluator;
        let (status, reason) = ev.evaluate(
            &req.constraint_id,
            &req.operator,
            req.value,
            &req.value_unit,
            req.bound,
            &req.bound_unit,
            req.tolerance,
        );
        result.status = status;
        result.reason_code = reason;
        result.details = if result.reason_code == "OK" {
            format!(
                "{} {} {} {}",
                req.value, req.operator, req.bound, req.value_unit
            )
        } else {
            format!("unsupported operator: '{}'", req.operator)
        };
        result
    }
}

#[tonic::async_trait]
impl ConstraintEvaluation for EvaluatorService {
    async fn evaluate(
        &self,
        request: Request<ConstraintRequest>,
    ) -> Result<Response<ConstraintResult>, Status> {
        let req = request.into_inner();
        Ok(Response::new(Self::evaluate_request(&req)))
    }
}

/// Serve the constraint-evaluation service on a Unix socket at
/// `socket_path`, forever (until the process is stopped or the
/// future is dropped). Any stale socket file at the path is removed
/// first. Returns only on a serve error.
pub async fn serve_unix(socket_path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    serve_unix_on(socket_path, EvaluatorService).await
}

async fn serve_unix_on(
    socket_path: &Path,
    service: EvaluatorService,
) -> Result<(), Box<dyn std::error::Error>> {
    if socket_path.exists() {
        std::fs::remove_file(socket_path)?;
    }
    let listener = UnixListener::bind(socket_path)?;
    let stream = UnixListenerStream::new(listener);
    tonic::transport::Server::builder()
        .add_service(ConstraintEvaluationServer::new(service))
        .serve_with_incoming(stream)
        .await?;
    Ok(())
}

/// Default socket path used by the `start-tonic-server` binary when
/// no argument is given.
pub fn default_socket_path() -> PathBuf {
    PathBuf::from(format!("/tmp/start-spine-tonic-{}.sock", std::process::id()))
}
