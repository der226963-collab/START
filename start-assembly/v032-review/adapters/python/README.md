# Python adapter boundary (scaffold)

Python remains the application/orchestration and reference implementation. Calls into Rust or Julia must be behind narrow adapter modules and must exchange only versioned payloads defined in `interop/schemas/`.

Do not import component internals into the agent, memory, retrieval, or governance layers. A component failure, timeout, unsupported schema, or malformed response must become an explicit `UNKNOWN` or `INCOMPLETE` result, never a success default.

The first runtime adapter is intentionally deferred until Rust and Julia toolchains are available in the target development environment. This repository currently contains source scaffolds and tests, not compiled native integrations.
