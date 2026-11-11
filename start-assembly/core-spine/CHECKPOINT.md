# Core-spine assembly — checkpoint 1
Date: 2026-11-10. Local only, no GitHub, no changes to ai-starter / v032-review / guardrails.
Toolchains verified: Python 3.12.3, SciPy 1.11.4, NumPy 1.26.4; rustc/cargo 1.99.1 at ~/.cargo/bin (not on PATH); Julia NOT FOUND.
Contracts read: REVIEW.md (54 issues), interop schemas 1.0.0, shared test-vectors + NOTE, planning-package models.py + NOTE, REPO_TRIAGE.md.
Status rules adopted: five internal states PASS/FAIL/UNKNOWN/NOT_CHECKED/INCOMPLETE; FAIL wins, then INCOMPLETE/UNKNOWN/NOT_CHECKED -> indeterminate; empty checks -> NOT_CHECKED, never PASS.
Next: venv + install attempts (langgraph, pyarrow, grpcio, cpmpy, cvxpy, deepeval), then adapters + tests.

# Checkpoint 2 — 2026-11-10, assembly complete (final verification run)
Python suite: 35/35 OK (.venv/bin/python -m unittest discover -s tests).
Rust suite: 9/9 OK (cargo test, rustc 1.99.1); binary start-spine also PASS.
Runner examples/run_spine.py: ALL ASSEMBLED ADAPTERS PASS.
DeepEval ExactMatchMetric: assembled, scores [1,1,1,0], accuracy 0.75, no API key.
Bugs found and fixed by the tests (not papered over):
  1. SciPy LP merged two equalities into one row -> production 0, delivered free. Fixed to 6 separate equalities.
  2. Cross-solver analytic totals were wrong (614/57 used 5%-loss potato area); correct loss-free totals are 600/50, verified by all three solvers.
  3. policies.cedar had a forbid but no permit for Publish/Execute -> Cedar default-deny blocked even verified+approved publishes. Permit added; Rust test now passes and agrees with the Python stub.
  4. gRPC TCP loopback client fails in this VM (egress proxy, frame type 101) despite the server speaking correct HTTP/2; switched to a Unix-domain socket, verified working.
  5. Solver string hardcoded "scipy 1.11.4"; now recorded dynamically (venv: 1.18.1).
Julia: NOT RUN — no toolchain. AlphaZero.jl unregistered (git-clone use in its own docs).
