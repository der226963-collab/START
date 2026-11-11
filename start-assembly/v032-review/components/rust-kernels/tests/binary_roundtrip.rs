//! Binary round-trip tests for `start-kernel` (ISSUE-40/41/39/52).
//!
//! These drive the built binary through stdin/stdout, not the library:
//! `cargo test` builds the binary, and `CARGO_BIN_EXE_start-kernel`
//! points at it. Every line in must produce exactly one schema-shaped
//! line out, including the parse-error paths.
use std::io::Write;
use std::process::{Command, Stdio};

fn binary() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_BIN_EXE_start-kernel"))
}

fn run_lines(input: &str) -> (i32, String, String) {
    let mut child = Command::new(binary())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("start-kernel binary must spawn");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    let out = child.wait_with_output().expect("wait on start-kernel");
    (
        out.status.code().unwrap_or(-1),
        String::from_utf8(out.stdout).unwrap(),
        String::from_utf8(out.stderr).unwrap(),
    )
}

fn outputs(input: &str) -> Vec<serde_json::Value> {
    let (code, stdout, stderr) = run_lines(input);
    assert_eq!(code, 0, "start-kernel must exit 0 on well-formed stdin; stderr: {stderr}");
    stdout
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).unwrap_or_else(|e| panic!("output line is not JSON: {l} ({e})")))
        .collect()
}

fn valid_request() -> &'static str {
    r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#
}

#[test]
fn valid_request_round_trips() {
    let out = outputs(valid_request());
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["status"], "PASS");
    assert_eq!(out[0]["constraint_id"], "w");
    assert_eq!(out[0]["reason_code"], "OK");
    assert_eq!(out[0]["normalized_value"], 8.0);
    assert_eq!(out[0]["normalized_unit"], "L");
    // ISSUE-49: details is still emitted on the success path.
    assert_eq!(
        out[0]["details"],
        "Evaluated using finite inputs and reviewed-unit conversion"
    );
}

#[test]
fn issue39_non_object_context_is_a_parse_error_line() {
    // ISSUE-39, binary side: the request is rejected at the boundary
    // (UNKNOWN / INVALID_REQUEST), never evaluated to PASS, and the
    // caller's id is echoed so the error is correlatable.
    let bad = r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"context":"not-an-object"}"#;
    let out = outputs(bad);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["status"], "UNKNOWN");
    assert_eq!(out[0]["reason_code"], "INVALID_REQUEST");
    assert_eq!(out[0]["constraint_id"], "w");
    // Omitted context still evaluates (normalised to {}).
    let out = outputs(valid_request());
    assert_eq!(out[0]["status"], "PASS");
}

#[test]
fn issue40_unparseable_input_gets_schema_valid_sentinel_id() {
    // ISSUE-40: "not json at all" used to emit constraint_id "",
    // violating the result schema's minLength: 1. Now the sentinel.
    let out = outputs("not json at all\n");
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["schema_version"], "1.0.0");
    assert_eq!(out[0]["constraint_id"], "unknown");
    assert_eq!(out[0]["status"], "UNKNOWN");
    assert_eq!(out[0]["reason_code"], "INVALID_REQUEST");
    assert_eq!(out[0]["normalized_value"], serde_json::Value::Null);
    assert_eq!(out[0]["normalized_unit"], serde_json::Value::Null);
    assert!(out[0]["details"].is_string());
}

#[test]
fn issue40_unknown_field_echoes_the_callers_id() {
    // A request rejected by deny_unknown_fields still carries its id.
    let bad = r#"{"schema_version":"1.0.0","constraint_id":"my-id","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0,"extra":1}"#;
    let out = outputs(bad);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["constraint_id"], "my-id");
    assert_eq!(out[0]["status"], "UNKNOWN");
    assert_eq!(out[0]["reason_code"], "INVALID_REQUEST");
}

#[test]
fn issue52_unsupported_operator_via_binary() {
    let bad = r#"{"schema_version":"1.0.0","constraint_id":"w","operator":"!=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#;
    let out = outputs(bad);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["status"], "UNKNOWN");
    assert_eq!(out[0]["reason_code"], "UNSUPPORTED_OPERATOR");
}

#[test]
fn issue42_json_lines_round_trip_through_binary() {
    // ISSUE-42 (2026-11-11): the binary previously had round-trip
    // tests only for single lines. A JSON-lines session — several
    // requests on stdin at once — must emit exactly one
    // schema-shaped line per input line, in order, covering the
    // operators the library tests added: ">=" (boundary), "=="
    // (tolerance), "range", a FAIL, and an invalid line that still
    // gets its own UNKNOWN line instead of truncating the stream.
    let input = [
        r#"{"schema_version":"1.0.0","constraint_id":"ge","operator":">=","value":2500.0,"value_unit":"kcal/day","bound":2500.0,"bound_unit":"kcal/day","tolerance":0.0}"#,
        r#"{"schema_version":"1.0.0","constraint_id":"eq","operator":"==","value":10.5,"value_unit":"kg","bound":10.0,"bound_unit":"kg","tolerance":0.5}"#,
        r#"{"schema_version":"1.0.0","constraint_id":"rng","operator":"range","value":5.0,"value_unit":"L","bound_low":2.0,"bound_high":8.0,"bound_unit":"L","tolerance":0.0}"#,
        r#"{"schema_version":"1.0.0","constraint_id":"fail","operator":"<=","value":12.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#,
        "not json at all",
        r#"{"schema_version":"1.0.0","constraint_id":"le","operator":"<=","value":8.0,"value_unit":"L","bound":10.0,"bound_unit":"L","tolerance":0.0}"#,
    ]
    .join("\n")
        + "\n";
    let out = outputs(&input);
    assert_eq!(out.len(), 6, "one output line per input line, got: {out:?}");
    assert_eq!((out[0]["constraint_id"].as_str(), out[0]["status"].as_str()), (Some("ge"), Some("PASS")));
    assert_eq!((out[1]["constraint_id"].as_str(), out[1]["status"].as_str()), (Some("eq"), Some("PASS")));
    assert_eq!((out[2]["constraint_id"].as_str(), out[2]["status"].as_str()), (Some("rng"), Some("PASS")));
    assert_eq!((out[3]["constraint_id"].as_str(), out[3]["status"].as_str()), (Some("fail"), Some("FAIL")));
    assert_eq!((out[4]["constraint_id"].as_str(), out[4]["status"].as_str()), (Some("unknown"), Some("UNKNOWN")));
    assert_eq!(out[4]["reason_code"], "INVALID_REQUEST");
    assert_eq!((out[5]["constraint_id"].as_str(), out[5]["status"].as_str()), (Some("le"), Some("PASS")));
    for line in &out {
        assert_eq!(line["schema_version"], "1.0.0");
        assert!(line["constraint_id"].as_str().map(|s| !s.is_empty()).unwrap_or(false));
        assert!(line["reason_code"].is_string());
    }
}

#[test]
fn issue47_conversion_overflow_via_binary() {
    // ISSUE-47, binary side: 1e308 tonne -> g overflows the
    // conversion. Before the fix the binary emitted PASS (for ">=")
    // with normalized_value null and reason OK. Now it must be
    // UNKNOWN / NON_FINITE, never PASS, with no normalised value.
    let input = r#"{"schema_version":"1.0.0","constraint_id":"ovf","operator":">=","value":1e308,"value_unit":"tonne","bound":1.0,"bound_unit":"g","tolerance":0.0}"#;
    let out = outputs(input);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["status"], "UNKNOWN");
    assert_eq!(out[0]["reason_code"], "NON_FINITE");
    assert_eq!(out[0]["normalized_value"], serde_json::Value::Null);
    assert_eq!(out[0]["details"], "normalized value must be finite");
}

#[test]
fn issue41_stdin_read_error_exits_nonzero_with_final_line() {
    // A directory as stdin: opening succeeds, reading fails (EISDIR),
    // which is a genuine stdin read error for .lines(). The binary
    // must emit a final INVALID_REQUEST-shaped line and exit non-zero
    // — it used to break silently and exit 0.
    let dir = std::fs::File::open(env!("CARGO_MANIFEST_DIR")).expect("open crate dir as stdin");
    let out = Command::new(binary())
        .stdin(Stdio::from(dir))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .expect("run start-kernel with a directory as stdin");
    assert_ne!(out.status.code().unwrap_or(0), 0, "stdin read error must exit non-zero");
    let stdout = String::from_utf8(out.stdout).unwrap();
    let lines: Vec<&str> = stdout.lines().filter(|l| !l.trim().is_empty()).collect();
    assert_eq!(lines.len(), 1, "exactly one final error line, got: {stdout}");
    let value: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
    assert_eq!(value["status"], "UNKNOWN");
    assert_eq!(value["reason_code"], "INVALID_REQUEST");
    assert_eq!(value["constraint_id"], "unknown");
    assert!(value["details"]
        .as_str()
        .unwrap()
        .contains("Failed to read request from stdin"));
}

#[test]
fn issue41_broken_pipe_exits_nonzero_without_panicking() {
    // No reader on stdout: once the pipe buffer fills, writes fail
    // with EPIPE. The old println! would panic; writeln! with
    // explicit handling must exit non-zero with no panic message.
    let mut child = Command::new(binary())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("start-kernel binary must spawn");
    drop(child.stdout.take());
    let mut stdin = child.stdin.take().unwrap();
    // Far more than a 64 KiB pipe buffer of request lines.
    let line = format!("{}\n", valid_request());
    for _ in 0..5000 {
        if stdin.write_all(line.as_bytes()).is_err() {
            break; // child already exited; that is the point
        }
    }
    drop(stdin);
    let out = child.wait_with_output().expect("wait on start-kernel");
    assert_ne!(out.status.code().unwrap_or(0), 0, "broken pipe must exit non-zero");
    let stderr = String::from_utf8(out.stderr).unwrap();
    assert!(!stderr.contains("panicked"), "must not panic on broken pipe; stderr: {stderr}");
}
