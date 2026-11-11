//! Behaviour-tree orchestration (Module 4) — ORIGINAL Rust.
//!
//! Design inspiration only: BehaviorTree.rs (ncrothers/behaviortree-rs,
//! MIT, copyright (c) 2023 Nicholas Crothers, 6,450 lines, inactive
//! since 2024-02-05, v0.2.1, 14 stars at sweep time). NO code was
//! copied from that crate: this module was written from scratch from
//! the standard node taxonomy (Sequence / Fallback / Decorator /
//! Action / Condition) plus a typed blackboard, as recorded in
//! `source-audit/ALL_CANDIDATES_BORROWING_PLAN.md` (INSPIRATION-REBUILD).
//! The crate itself is NOT a dependency (unmaintained WIP); the ideas
//! rebuilt here are the node types and the typed blackboard only.
//! Trees are defined in JSON — never XML from an untrusted source, and
//! never pickle. Wire format stays JSON.
//!
//! This is orchestration of the plan → verify → report steps, mirroring
//! the LangGraph pipeline in `adapters/orchestration.py`. It is NOT a
//! replacement for the verify step, and it can NEVER mark a result
//! verified:
//!
//! * The `verify` Action calls the existing local evaluator
//!   ([`crate::tonic_stub::LocalEvaluator`]) — it does not invent its
//!   own verdict. It re-derives the check (delivered + shortage must
//!   equal demand, quantities non-negative) from the plan on the
//!   blackboard, exactly as `verify_step` does in Python.
//! * The `report` Action is a hard gate: it refuses (returns
//!   [`Status::Failure`] and emits nothing) unless the verify step ran
//!   AND passed in the same run, recorded on the blackboard as
//!   `verify_ran = true` and `verify_passed = true`. A tree that skips
//!   verification, or a JSON tree with the verify node removed, fails
//!   at the report step — the failure is explicit, never silent
//!   success. There is no `verified` key anywhere in this module.
//! * Every completed report records `needs_human_decision = true`.
//!   A report is a candidate for a human to approve, never an approval.
//!
//! Statuses are [`Status::Success`] / [`Status::Failure`] /
//! [`Status::Running`]. `Running` is genuinely exercised, not just
//! defined: the `defer_once` Action returns `Running` on its first
//! tick and `Success` on the next (see the test
//! `running_is_genuinely_exercised`). There is no async tick loop and
//! no background scheduler — `tick` is a single synchronous pass over
//! the tree; a caller that wants a later tick calls `tick` again.
//!
//! The Action steps are stubs that record what they did on the
//! blackboard (plan produced a candidate, verify evaluated it, report
//! emitted it). They do not re-implement planning or verification.

use crate::tonic_stub::{ConstraintEvaluationService, LocalEvaluator};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use std::fmt;

/// Tick result of a node.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Success,
    Failure,
    /// The node needs a later tick to finish. Genuinely exercised by
    /// the `defer_once` Action (first tick `Running`, next `Success`).
    /// No node returns this spuriously and there is no tick loop here.
    Running,
}

/// A value on the blackboard. One key holds exactly one typed value.
#[derive(Debug, Clone, PartialEq)]
pub enum BlackboardValue {
    Bool(bool),
    Int(i64),
    Float(f64),
    Text(String),
}

impl BlackboardValue {
    fn type_name(&self) -> &'static str {
        match self {
            BlackboardValue::Bool(_) => "bool",
            BlackboardValue::Int(_) => "int",
            BlackboardValue::Float(_) => "float",
            BlackboardValue::Text(_) => "text",
        }
    }
}

/// Blackboard error: a missing key or a wrong-type read. Never a
/// silent default and never a silent coercion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BlackboardError {
    Missing(String),
    WrongType {
        key: String,
        expected: &'static str,
        found: &'static str,
    },
}

impl fmt::Display for BlackboardError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BlackboardError::Missing(key) => write!(f, "blackboard key missing: {key}"),
            BlackboardError::WrongType {
                key,
                expected,
                found,
            } => write!(
                f,
                "blackboard key '{key}': expected {expected}, found {found}"
            ),
        }
    }
}

impl std::error::Error for BlackboardError {}

/// Typed key/value store. A key holds one typed value; reading a key
/// with the wrong type is an error, never a silent coercion, and a
/// missing key is an error, never a default.
#[derive(Debug, Default)]
pub struct Blackboard {
    values: HashMap<String, BlackboardValue>,
}

impl Blackboard {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_bool(&mut self, key: &str, value: bool) {
        self.values
            .insert(key.to_string(), BlackboardValue::Bool(value));
    }

    pub fn set_int(&mut self, key: &str, value: i64) {
        self.values
            .insert(key.to_string(), BlackboardValue::Int(value));
    }

    pub fn set_float(&mut self, key: &str, value: f64) {
        self.values
            .insert(key.to_string(), BlackboardValue::Float(value));
    }

    pub fn set_text(&mut self, key: &str, value: &str) {
        self.values
            .insert(key.to_string(), BlackboardValue::Text(value.to_string()));
    }

    pub fn has(&self, key: &str) -> bool {
        self.values.contains_key(key)
    }

    fn get(&self, key: &str) -> Result<&BlackboardValue, BlackboardError> {
        self.values
            .get(key)
            .ok_or_else(|| BlackboardError::Missing(key.to_string()))
    }

    fn wrong_type(
        &self,
        key: &str,
        expected: &'static str,
    ) -> Result<BlackboardValue, BlackboardError> {
        let found = self.get(key)?.type_name();
        Err(BlackboardError::WrongType {
            key: key.to_string(),
            expected,
            found,
        })
    }

    pub fn get_bool(&self, key: &str) -> Result<bool, BlackboardError> {
        match self.get(key)? {
            BlackboardValue::Bool(v) => Ok(*v),
            _ => match self.wrong_type(key, "bool") {
                Ok(_) => unreachable!(),
                Err(e) => Err(e),
            },
        }
    }

    pub fn get_int(&self, key: &str) -> Result<i64, BlackboardError> {
        match self.get(key)? {
            BlackboardValue::Int(v) => Ok(*v),
            _ => match self.wrong_type(key, "int") {
                Ok(_) => unreachable!(),
                Err(e) => Err(e),
            },
        }
    }

    pub fn get_float(&self, key: &str) -> Result<f64, BlackboardError> {
        match self.get(key)? {
            BlackboardValue::Float(v) => Ok(*v),
            _ => match self.wrong_type(key, "float") {
                Ok(_) => unreachable!(),
                Err(e) => Err(e),
            },
        }
    }

    pub fn get_text(&self, key: &str) -> Result<String, BlackboardError> {
        match self.get(key)? {
            BlackboardValue::Text(v) => Ok(v.clone()),
            _ => match self.wrong_type(key, "text") {
                Ok(_) => unreachable!(),
                Err(e) => Err(e),
            },
        }
    }
}

/// A behaviour-tree node. Original Rust; the taxonomy (Sequence /
/// Fallback / Decorator / Action / Condition) is the standard one
/// shared with BehaviorTree.CPP and BehaviorTree.rs — the design
/// inspiration, not copied code.
#[derive(Debug, Clone)]
pub enum Node {
    /// Run children in order; first Failure (or Running) stops the
    /// sequence and is returned; Success only if every child succeeds.
    Sequence(Vec<Node>),
    /// Run children in order; first Success (or Running) is returned;
    /// Failure only if every child fails.
    Fallback(Vec<Node>),
    /// Inverter decorator: Success <-> Failure, Running passes through.
    Inverter(Box<Node>),
    /// Succeeder decorator: Failure becomes Success; Success and
    /// Running pass through unchanged.
    Succeeder(Box<Node>),
    /// A leaf step resolved by name by the runner (`plan`, `verify`,
    /// `report`, `fail`, `succeed`, `defer_once`).
    Action { step: String },
    /// A leaf check resolved by name (`verify_passed`, `plan_produced`).
    Condition { step: String },
}

/// Parse a tree from the original JSON format. Example:
///
/// ```json
/// {"type": "sequence", "children": [
///   {"type": "action", "step": "plan"},
///   {"type": "action", "step": "verify"},
///   {"type": "action", "step": "report"}
/// ]}
/// ```
///
/// Node types: `sequence`, `fallback`, `inverter`, `succeeder`,
/// `action` (with `step`), `condition` (with `step`). Decorators
/// take a single `child`; composites take `children`.
pub fn parse_tree(json: &str) -> Result<Node, String> {
    let value: JsonValue = serde_json::from_str(json)
        .map_err(|e| format!("invalid tree JSON: {e}"))?;
    parse_node(&value)
}

fn parse_node(value: &JsonValue) -> Result<Node, String> {
    let obj = value
        .as_object()
        .ok_or_else(|| "tree node must be a JSON object".to_string())?;
    let node_type = obj
        .get("type")
        .and_then(JsonValue::as_str)
        .ok_or_else(|| "tree node is missing a string \"type\"".to_string())?;
    match node_type {
        "sequence" | "fallback" => {
            let children = obj
                .get("children")
                .and_then(JsonValue::as_array)
                .ok_or_else(|| format!("{node_type} node needs a \"children\" array"))?;
            let mut nodes = Vec::with_capacity(children.len());
            for child in children {
                nodes.push(parse_node(child)?);
            }
            if node_type == "sequence" {
                Ok(Node::Sequence(nodes))
            } else {
                Ok(Node::Fallback(nodes))
            }
        }
        "inverter" | "succeeder" => {
            let child = obj
                .get("child")
                .ok_or_else(|| format!("{node_type} decorator needs a \"child\""))?;
            let child = parse_node(child)?;
            if node_type == "inverter" {
                Ok(Node::Inverter(Box::new(child)))
            } else {
                Ok(Node::Succeeder(Box::new(child)))
            }
        }
        "action" | "condition" => {
            let step = obj
                .get("step")
                .and_then(JsonValue::as_str)
                .ok_or_else(|| format!("{node_type} node needs a string \"step\""))?;
            if node_type == "action" {
                Ok(Node::Action {
                    step: step.to_string(),
                })
            } else {
                Ok(Node::Condition {
                    step: step.to_string(),
                })
            }
        }
        other => Err(format!("unknown tree node type: {other}")),
    }
}

/// Runs a tree against a shared typed blackboard. `trace` records the
/// step names in the order they ran, for tests and audit.
pub struct TreeRunner {
    pub blackboard: Blackboard,
    pub trace: Vec<String>,
}

impl TreeRunner {
    #[must_use]
    pub fn new() -> Self {
        Self {
            blackboard: Blackboard::new(),
            trace: Vec::new(),
        }
    }

    /// One synchronous tick over the tree. No tick loop: a node that
    /// returns [`Status::Running`] must be ticked again by the caller.
    pub fn tick(&mut self, node: &Node) -> Status {
        match node {
            Node::Sequence(children) => {
                for child in children {
                    match self.tick(child) {
                        Status::Success => {}
                        other => return other,
                    }
                }
                Status::Success
            }
            Node::Fallback(children) => {
                for child in children {
                    match self.tick(child) {
                        Status::Failure => {}
                        other => return other,
                    }
                }
                Status::Failure
            }
            Node::Inverter(child) => match self.tick(child) {
                Status::Success => Status::Failure,
                Status::Failure => Status::Success,
                Status::Running => Status::Running,
            },
            Node::Succeeder(child) => match self.tick(child) {
                Status::Failure => Status::Success,
                other => other,
            },
            Node::Action { step } => self.run_action(step),
            Node::Condition { step } => self.run_condition(step),
        }
    }

    fn run_condition(&mut self, step: &str) -> Status {
        // A condition reads the blackboard; a missing key or a
        // wrong-typed value is a failed condition, never a default.
        let passed = match step {
            "verify_passed" => self.blackboard.get_bool("verify_passed").unwrap_or(false),
            "plan_produced" => self.blackboard.get_bool("plan_produced").unwrap_or(false),
            _ => false,
        };
        if passed {
            Status::Success
        } else {
            Status::Failure
        }
    }

    fn run_action(&mut self, step: &str) -> Status {
        match step {
            "plan" => {
                // Planner stub: produce the synthetic candidate (the
                // same 600 t delivered / 50 t shortage / 650 t demand
                // as the Python pipeline). It may NOT verify it.
                self.blackboard.set_bool("plan_produced", true);
                self.blackboard.set_float("plan_delivered_t", 600.0);
                self.blackboard.set_float("plan_shortage_t", 50.0);
                self.blackboard.set_float("plan_demand_t", 650.0);
                self.trace.push("plan".to_string());
                Status::Success
            }
            "verify" => {
                // Verifier stub: independent re-derivation via the
                // existing local evaluator, never its own verdict.
                // Records that verify RAN and whether it PASSED; it
                // never writes any `verified` key.
                self.blackboard.set_bool("verify_ran", true);
                let evaluator = LocalEvaluator;
                let delivered = self.blackboard.get_float("plan_delivered_t");
                let shortage = self.blackboard.get_float("plan_shortage_t");
                let demand = self.blackboard.get_float("plan_demand_t");
                let passed = match (delivered, shortage, demand) {
                    (Ok(d), Ok(s), Ok(dem)) => {
                        // delivered + shortage must equal demand.
                        let (sum_status, _) = evaluator.evaluate(
                            "delivered-plus-shortage-equals-demand",
                            "<=",
                            d + s,
                            "t",
                            dem,
                            "t",
                            0.01,
                        );
                        let (nonneg_status, _) = evaluator.evaluate(
                            "non-negative-quantities",
                            ">=",
                            d,
                            "t",
                            0.0,
                            "t",
                            0.0,
                        );
                        // "<=" alone would also pass an under-delivery;
                        // require the sum to be (within tolerance) the
                        // demand from below as well: reuse the evaluator
                        // with ">=" so both directions are checked.
                        let (sum_status_lo, _) = evaluator.evaluate(
                            "delivered-plus-shortage-equals-demand",
                            ">=",
                            d + s,
                            "t",
                            dem,
                            "t",
                            0.01,
                        );
                        sum_status == "PASS"
                            && sum_status_lo == "PASS"
                            && nonneg_status == "PASS"
                    }
                    _ => false,
                };
                self.blackboard.set_bool("verify_passed", passed);
                self.trace.push("verify".to_string());
                if passed {
                    Status::Success
                } else {
                    Status::Failure
                }
            }
            "report" => {
                // HARD GATE, mirroring adapters/orchestration.py:
                // report refuses unless verify ran AND passed in this
                // same run. Any missing key, wrong type, or false
                // value is a refusal — the report is NOT emitted and
                // the tree fails explicitly.
                let ran = self.blackboard.get_bool("verify_ran").unwrap_or(false);
                let passed = self
                    .blackboard
                    .get_bool("verify_passed")
                    .unwrap_or(false);
                if !(ran && passed) {
                    self.trace.push("report_refused".to_string());
                    return Status::Failure;
                }
                self.blackboard.set_bool("report_emitted", true);
                self.blackboard.set_text("report_status", "PASS");
                self.blackboard.set_bool("needs_human_decision", true);
                self.trace.push("report".to_string());
                Status::Success
            }
            "fail" => {
                self.trace.push("fail".to_string());
                Status::Failure
            }
            "succeed" => {
                self.trace.push("succeed".to_string());
                Status::Success
            }
            "defer_once" => {
                // The Running exerciser: first tick Running, later
                // ticks Success. Proves Running is a real status a
                // node can return, not just a defined variant.
                if self.blackboard.get_bool("defer_seen").unwrap_or(false) {
                    self.trace.push("defer_once".to_string());
                    Status::Success
                } else {
                    self.blackboard.set_bool("defer_seen", true);
                    self.trace.push("defer_once".to_string());
                    Status::Running
                }
            }
            _ => {
                // An unknown step name is a failure, never a silent skip.
                self.trace.push(format!("unknown_step:{step}"));
                Status::Failure
            }
        }
    }
}

impl Default for TreeRunner {
    fn default() -> Self {
        Self::new()
    }
}

/// Parse a JSON tree and run one tick over it.
pub fn run_json_tree(json: &str, runner: &mut TreeRunner) -> Result<Status, String> {
    let tree = parse_tree(json)?;
    Ok(runner.tick(&tree))
}
