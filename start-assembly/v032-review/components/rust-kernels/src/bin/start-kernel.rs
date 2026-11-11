//! JSON-lines process boundary: one request per line, one result per line.
use std::io::{self, BufRead, Write};
use std::process::ExitCode;
use start_rust_kernels::{evaluate_constraint, ConstraintRequest, ConstraintResult, CheckStatus, SCHEMA_VERSION};

/// Schema-valid sentinel used when a parse failure leaves no usable
/// `constraint_id` (ISSUE-40): the result schema requires
/// `constraint_id` `minLength: 1`, so the empty string the old code
/// emitted was itself a schema violation, and the caller's id was lost.
const UNKNOWN_ID: &str = "unknown";

/// Build the full result-shaped object for a request that could not be
/// parsed (ISSUE-40). Best-effort: echo the caller's `constraint_id`
/// when the raw line is JSON holding a non-empty string id (e.g. a
/// request rejected for an unknown top-level field); otherwise use the
/// `UNKNOWN_ID` sentinel so the emitted line always satisfies the
/// result schema (`constraint_id` minLength 1, all required fields).
fn parse_error_result(raw: &str) -> ConstraintResult {
    let constraint_id = serde_json::from_str::<serde_json::Value>(raw)
        .ok()
        .and_then(|v| v.get("constraint_id")?.as_str().map(str::to_string))
        .filter(|id| !id.trim().is_empty())
        .unwrap_or_else(|| UNKNOWN_ID.to_string());
    ConstraintResult {
        schema_version: SCHEMA_VERSION.into(),
        constraint_id,
        status: CheckStatus::Unknown,
        normalized_value: None,
        normalized_unit: None,
        reason_code: "INVALID_REQUEST".into(),
        details: Some("Could not parse request".into()),
    }
}

/// Serialise a result. The serialisation fallback (ISSUE-40) emits a
/// full result-shaped object, not the old `{"status":...}` fragment
/// that omitted `schema_version`, `constraint_id`,
/// `normalized_value`, `normalized_unit` — all required. That path is
/// latent/unreachable in practice (serialising this struct cannot
/// fail on these types); it is fixed anyway per the issue, and the
/// last-resort hardcoded string below is likewise a complete
/// result-shaped object.
fn serialise_result(result: &ConstraintResult) -> String {
    serde_json::to_string(result).unwrap_or_else(|_| {
        format!(
            "{{\"schema_version\":\"{SCHEMA_VERSION}\",\"constraint_id\":\"{}\",\"status\":\"UNKNOWN\",\"normalized_value\":null,\"normalized_unit\":null,\"reason_code\":\"INVALID_REQUEST\",\"details\":\"Could not serialise result\"}}",
            result.constraint_id,
        )
    })
}

/// Write one output line, handling write errors explicitly (ISSUE-41):
/// `println!` panics on a broken pipe; `writeln!` returns the error
/// instead, and we report it on stderr and exit non-zero rather than
/// panicking or silently dropping the line. Returns false when the
/// caller should stop.
fn emit_line(stdout: &mut impl Write, line: &str) -> bool {
    match writeln!(stdout, "{line}") {
        Ok(()) => true,
        Err(e) => {
            eprintln!("start-kernel: failed to write result line: {e}");
            false
        }
    }
}

fn main() -> ExitCode {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let output = match line {
            Ok(raw) => match serde_json::from_str::<ConstraintRequest>(&raw) {
                Ok(request) => serialise_result(&evaluate_constraint(&request)),
                // ISSUE-54 fix (2026-11-11): the version in this
                // parse-error result is the SCHEMA_VERSION constant,
                // not a second hard-coded version literal — a version
                // bump can no longer silently leave this path behind.
                // ISSUE-40: the caller's id is echoed when present,
                // else the UNKNOWN_ID sentinel — never "".
                Err(_) => serialise_result(&parse_error_result(&raw)),
            },
            // ISSUE-41: a stdin read error used to `break` silently
            // with exit 0, leaving the consumer a truncated stream
            // and a success exit code. Now emit a final
            // INVALID_REQUEST-shaped line (or, if even that cannot be
            // written, a stderr message) and exit non-zero.
            Err(e) => {
                let mut result = parse_error_result("");
                result.details = Some(format!("Failed to read request from stdin: {e}"));
                if !emit_line(&mut stdout, &serialise_result(&result)) {
                    eprintln!("start-kernel: failed to read request from stdin: {e}");
                }
                return ExitCode::from(1);
            }
        };
        if !emit_line(&mut stdout, &output) {
            return ExitCode::from(1);
        }
    }
    ExitCode::SUCCESS
}
