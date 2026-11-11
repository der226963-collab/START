//! START core-spine Rust kernels.
//!
//! * Cedar (cedar-policy/cedar, Apache-2.0): evaluate the policies in
//!   `../policies.cedar` with the real Cedar engine.
//! * egg (egraphs-good/egg, MIT): e-graph rewrite demo — simplify
//!   `x + 0` to `x`, the kind of symbolic rewrite the reasoning
//!   module needs. This is a demo, not a planner.
//! * Tonic (grpc/grpc-rust, MIT): the gRPC service from
//!   `../proto/constraint_evaluation.proto` is a STUB in this
//!   assembly — the trait and types are declared, no server is run
//!   in the tests. See `tonic_stub` module.

pub mod cedar_eval;
pub mod egg_demo;
pub mod tonic_stub;
