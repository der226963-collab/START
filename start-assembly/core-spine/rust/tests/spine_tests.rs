//! Rust spine tests: Cedar governance + egg rewrites + Tonic stub
//! evaluator + real Tonic server over a Unix socket.
//! Run with `cargo test` (rustc 1.99.1 at ~/.cargo/bin).

use start_core_spine::cedar_eval;
use start_core_spine::egg_demo;
use start_core_spine::proto::v1::constraint_evaluation_client::ConstraintEvaluationClient;
use start_core_spine::proto::v1::ConstraintRequest;
use start_core_spine::server::{serve_unix, EvaluatorService};
use start_core_spine::tonic_stub::{ConstraintEvaluationService, LocalEvaluator};

#[test]
fn cedar_planner_may_plan_synthetic() {
    assert_eq!(cedar_eval::planner_may_plan_synthetic().unwrap(), true);
}

#[test]
fn cedar_planner_may_not_plan_real() {
    assert_eq!(cedar_eval::planner_may_not_plan_real().unwrap(), false);
}

#[test]
fn cedar_publish_denied_when_unverified() {
    assert_eq!(cedar_eval::publish_denied_unverified().unwrap(), false);
}

#[test]
fn cedar_publish_allowed_when_verified_and_approved() {
    assert_eq!(
        cedar_eval::publish_allowed_verified_and_approved().unwrap(),
        true
    );
}

#[test]
fn egg_simplifies_add_zero() {
    assert_eq!(egg_demo::simplify_add_zero("(+ x 0)").unwrap(), "x");
}

#[test]
fn egg_simplifies_mul_one() {
    assert_eq!(egg_demo::simplify_add_zero("(* y 1)").unwrap(), "y");
}

#[test]
fn tonic_stub_evaluates_le_pass() {
    let ev = LocalEvaluator;
    assert_eq!(
        ev.evaluate("mass", "<=", 8.0, "t", 10.0, "t", 0.0),
        ("PASS".to_string(), "OK".to_string())
    );
}

#[test]
fn tonic_stub_unknown_on_incompatible_units() {
    let ev = LocalEvaluator;
    assert_eq!(
        ev.evaluate("vol", "<=", 5.0, "L", 10.0, "kg", 0.0),
        ("UNKNOWN".to_string(), "INCOMPATIBLE_UNIT".to_string())
    );
}

#[test]
fn tonic_stub_never_passes_unknown() {
    // Empty constraint_id must not pass.
    let ev = LocalEvaluator;
    let (status, _) = ev.evaluate("", "<=", 1.0, "kg", 10.0, "kg", 0.0);
    assert_ne!(status, "PASS");
}

// --- Real Tonic server over a Unix socket (Module 21) ---
//
// Each test starts the real server on its own fresh socket in a
// temp dir, then calls it with the real generated Tonic client over
// the wire. Nothing here calls the evaluator in-process: the verdict
// must cross the Unix socket as a gRPC call.

fn test_socket(name: &str) -> std::path::PathBuf {
    std::env::temp_dir()
        .join(format!("start-spine-tonic-test-{}-{}.sock", name, std::process::id()))
}

async fn start_server_on(sock: &std::path::Path) {
    if sock.exists() {
        std::fs::remove_file(sock).unwrap();
    }
    let sock = sock.to_path_buf();
    let sock_for_server = sock.clone();
    tokio::spawn(async move {
        serve_unix(&sock_for_server).await.unwrap();
    });
    // Wait until the socket file appears (server bound).
    for _ in 0..100 {
        if sock.exists() {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    panic!("server did not bind {:?}", sock);
}

async fn tonic_client(
    sock: &std::path::Path,
) -> ConstraintEvaluationClient<tonic::transport::Channel> {
    use hyper_util::rt::TokioIo;
    use tokio::net::UnixStream;
    use tonic::transport::{Endpoint, Uri};
    let sock = sock.to_path_buf();
    let mut last_err = None;
    for _ in 0..50 {
        let sock_for_conn = sock.clone();
        let channel = Endpoint::try_from("http://localhost")
            .unwrap()
            .connect_with_connector(tower::service_fn(move |_: Uri| {
                let sock = sock_for_conn.clone();
                async move {
                    UnixStream::connect(sock)
                        .await
                        .map(TokioIo::new)
                }
            }))
            .await;
        match channel {
            Ok(ch) => return ConstraintEvaluationClient::new(ch),
            Err(e) => {
                last_err = Some(e);
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
        }
    }
    panic!("could not connect to test server: {:?}", last_err);
}

fn wire_request(
    constraint_id: &str,
    operator: &str,
    value: f64,
    unit: &str,
    bound: f64,
) -> ConstraintRequest {
    ConstraintRequest {
        schema_version: "1.0.0".to_string(),
        constraint_id: constraint_id.to_string(),
        operator: operator.to_string(),
        value,
        value_unit: unit.to_string(),
        bound,
        bound_unit: unit.to_string(),
        tolerance: 0.0,
    }
}

#[tokio::test]
async fn tonic_wire_feasible_water_passes() {
    let sock = test_socket("water-pass");
    start_server_on(&sock).await;
    let mut client = tonic_client(&sock).await;
    // Feasible plan: 30,000 m3 of water against 40,000 m3 available.
    let r = client
        .evaluate(wire_request("water", "<=", 30_000.0, "m3", 40_000.0))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(r.status, "PASS");
    assert_eq!(r.reason_code, "OK");
    assert_eq!(r.constraint_id, "water");
}

#[tokio::test]
async fn tonic_wire_over_water_fails() {
    let sock = test_socket("water-fail");
    start_server_on(&sock).await;
    let mut client = tonic_client(&sock).await;
    // Over-water plan: 50,000 m3 against 40,000 m3 available.
    let r = client
        .evaluate(wire_request("water", "<=", 50_000.0, "m3", 40_000.0))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(r.status, "FAIL");
    assert_eq!(r.reason_code, "OK");
}

#[tokio::test]
async fn tonic_wire_over_land_fails_and_demand_shortfall_fails() {
    let sock = test_socket("land-demand");
    start_server_on(&sock).await;
    let mut client = tonic_client(&sock).await;
    // Over-land: 25 ha against 20 ha available.
    let r = client
        .evaluate(wire_request("land", "<=", 25.0, "ha", 20.0))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(r.status, "FAIL");
    // Demand shortfall: 550 t delivered against 600 t demanded.
    let r = client
        .evaluate(wire_request("demand", ">=", 550.0, "t", 600.0))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(r.status, "FAIL");
    // Demand met: 600 t delivered against 600 t demanded.
    let r = client
        .evaluate(wire_request("demand", ">=", 600.0, "t", 600.0))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(r.status, "PASS");
}

#[tokio::test]
async fn tonic_wire_incompatible_units_unknown() {
    let sock = test_socket("units");
    start_server_on(&sock).await;
    let mut client = tonic_client(&sock).await;
    let mut req = wire_request("vol", "<=", 5.0, "L", 10.0);
    req.bound_unit = "kg".to_string();
    let r = client.evaluate(req).await.unwrap().into_inner();
    assert_eq!(r.status, "UNKNOWN");
    assert_eq!(r.reason_code, "INCOMPATIBLE_UNIT");
    assert_ne!(r.status, "PASS");
}

#[test]
fn tonic_server_evaluate_request_unit() {
    // Pure (non-wire) check of the server's request handling, e.g.
    // that a wrong schema version is UNKNOWN, never PASS.
    let req = ConstraintRequest {
        schema_version: "2.0.0".to_string(),
        constraint_id: "water".to_string(),
        operator: "<=".to_string(),
        value: 1.0,
        value_unit: "m3".to_string(),
        bound: 10.0,
        bound_unit: "m3".to_string(),
        tolerance: 0.0,
    };
    let r = EvaluatorService::evaluate_request(&req);
    assert_eq!(r.status, "UNKNOWN");
    assert_eq!(r.reason_code, "INVALID_REQUEST");
}
