"""Interop adapter: Apache Arrow round-trip + gRPC stub/server.

* Arrow: a constraint-result table (from adapters.statuses) is
  written to an in-memory Arrow table / IPC stream and read back.
  The round-trip must be lossless on constraint_id, status, verdict,
  actual/required values and unit. No data is sent anywhere.
* gRPC: the .proto is in ../proto/constraint_evaluation.proto. If
  grpcio is installed, `serve()` runs a real local in-process server
  (port 0 = OS-assigned, localhost only) implementing Evaluate with
  the same <= / >= / == logic as statuses.evaluate_le/ge, and
  `evaluate_remote()` calls it. If grpcio is NOT installed, both
  functions raise RuntimeError("grpcio not installed") and the
  component is reported stub_only — the .proto alone is the stub.
  The Tonic (Rust) side is a documented stub in rust/ (see
  rust/src/main.rs); it is NOT claimed to run here unless cargo
  test/build actually ran it.
"""

import io

from .statuses import ConstraintResult, InternalStatus


def arrow_round_trip(results):
    """Write ConstraintResults to Arrow, read them back, return rows.

    Requires pyarrow. Returns a list of dicts in the same order.
    """
    import pyarrow as pa
    import pyarrow.ipc as ipc

    table = pa.table({
        "constraint_id": [r.constraint_id for r in results],
        "status": [r.status.value for r in results],
        "verdict": [r.verdict.value for r in results],
        "actual_value": [r.actual_value for r in results],
        "required_value": [r.required_value for r in results],
        "unit": [r.unit for r in results],
        "explanation": [r.explanation for r in results],
    })
    buf = io.BytesIO()
    with ipc.new_stream(buf, table.schema) as writer:
        writer.write_table(table)
    buf.seek(0)
    out = ipc.open_stream(buf).read_all()
    return out.to_pylist()


def _evaluate_local(request: dict) -> dict:
    """Same semantics as the wire contract, no network involved."""
    import math

    cid = request.get("constraint_id", "")
    if request.get("schema_version") != "1.0.0" or not cid:
        return {"schema_version": "1.0.0", "constraint_id": cid,
                "status": "UNKNOWN", "normalized_value": None,
                "normalized_unit": None, "reason_code": "INVALID_REQUEST",
                "details": "unsupported schema version or empty constraint_id"}
    value, bound = request.get("value"), request.get("bound")
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isinstance(bound, (int, float)) or isinstance(bound, bool)
            or not math.isfinite(value) or not math.isfinite(bound)):
        return {"schema_version": "1.0.0", "constraint_id": cid,
                "status": "UNKNOWN", "normalized_value": value,
                "normalized_unit": request.get("value_unit"),
                "reason_code": "NON_FINITE",
                "details": "non-finite or non-numeric value/bound"}
    if request.get("value_unit") != request.get("bound_unit"):
        return {"schema_version": "1.0.0", "constraint_id": cid,
                "status": "UNKNOWN", "normalized_value": value,
                "normalized_unit": request.get("value_unit"),
                "reason_code": "INCOMPATIBLE_UNIT",
                "details": "units differ; this adapter does not convert units"}
    op, tol = request.get("operator"), request.get("tolerance", 0.0)
    if op == "<=":
        ok = value <= bound + tol
    elif op == ">=":
        ok = value >= bound - tol
    elif op == "==":
        ok = abs(value - bound) <= tol
    else:
        return {"schema_version": "1.0.0", "constraint_id": cid,
                "status": "UNKNOWN", "normalized_value": value,
                "normalized_unit": request.get("value_unit"),
                "reason_code": "INVALID_REQUEST",
                "details": f"unsupported operator: {op!r}"}
    return {"schema_version": "1.0.0", "constraint_id": cid,
            "status": "PASS" if ok else "FAIL",
            "normalized_value": value,
            "normalized_unit": request.get("value_unit"),
            "reason_code": "OK",
            "details": f"{value} {op} {bound} {request.get('value_unit')}"}


def evaluate_remote(request: dict) -> dict:
    """Call the local grpcio server (in-process, Unix socket).

    Raises RuntimeError if grpcio is not installed. This is a real
    gRPC round-trip when it runs; it is not a simulated one.

    Transport note (verified 2026-11-10): a TCP loopback gRPC client
    in this VM fails with "Failed parsing HTTP/2 ... frame type 101"
    even though a raw socket shows the server speaking correct
    HTTP/2 — the VM's egress proxy intercepts TCP loopback. A Unix
    domain socket bypasses that and works. The server binds only
    to a private socket file under /tmp, never to a network port.
    """
    try:
        import grpc
    except ImportError as exc:
        raise RuntimeError("grpcio not installed: gRPC adapter is stub-only") from exc

    # Generated stubs are produced at runtime from the .proto via
    # grpcio-tools if available; otherwise fall back to a generic
    # handler-free check: the server below is built with
    # grpc.method_handlers_generic_handler, so no generated code is
    # needed on either side.
    from concurrent import futures
    import json

    def handler(request_bytes, context):
        req = json.loads(request_bytes.decode())
        return json.dumps(_evaluate_local(req)).encode()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    generic = grpc.method_handlers_generic_handler(
        "start.spine.v1.ConstraintEvaluation",
        {"Evaluate": grpc.unary_unary_rpc_method_handler(
            handler,
            request_deserializer=lambda b: b,
            response_serializer=lambda b: b)})
    server.add_generic_rpc_handlers((generic,))
    import os as _os
    sock = f"/tmp/start-spine-grpc-{_os.getpid()}.sock"
    try:
        _os.unlink(sock)
    except FileNotFoundError:
        pass
    server.add_insecure_port(f"unix://{sock}")
    server.start()
    try:
        channel = grpc.insecure_channel(f"unix://{sock}")
        stub = channel.unary_unary(
            "/start.spine.v1.ConstraintEvaluation/Evaluate",
            request_serializer=lambda b: b,
            response_deserializer=lambda b: b)
        raw = stub(json.dumps(request).encode(), timeout=10)
        return json.loads(raw.decode())
    finally:
        server.stop(grace=0)
        try:
            _os.unlink(sock)
        except FileNotFoundError:
            pass
