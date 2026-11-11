"""Interop adapter: Apache Arrow round-trip + gRPC servers.

* Arrow: a constraint-result table (from adapters.statuses) is
  written to an in-memory Arrow table / IPC stream and read back.
  The round-trip must be lossless on constraint_id, status, verdict,
  actual/required values and unit. No data is sent anywhere.
* gRPC: the .proto is in ../proto/constraint_evaluation.proto.
  `serve()` / `evaluate_remote()` run the Python grpcio server
  (in-process, Unix socket) implementing Evaluate with the same
  <= / >= / == logic as statuses.evaluate_le/ge.
  `evaluate_remote_tonic()` instead calls the REAL Rust Tonic
  server (`start-tonic-server`, rust/src/server.rs) on a Unix
  socket given by the caller, with real protobuf stubs generated
  from the .proto by grpcio-tools. That is the cross-language wire
  path: Python client -> Rust server -> real verdict.
  If grpcio is NOT installed, the gRPC functions raise
  RuntimeError("grpcio not installed").
"""

import io
import os

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


_TONIC_STUBS = None


def _load_tonic_stubs():
    """Generate + import the protobuf stubs for the .proto once.

    Uses grpcio-tools (`python -m grpc_tools.protoc`, bundled
    libprotoc) into a fresh temp dir; no generated file is checked
    in. Raises RuntimeError if grpcio-tools is not installed.
    Returns (constraint_evaluation_pb2, constraint_evaluation_pb2_grpc).
    """
    global _TONIC_STUBS
    if _TONIC_STUBS is not None:
        return _TONIC_STUBS
    import subprocess
    import sys
    import tempfile

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = tempfile.mkdtemp(prefix="start-spine-tonic-pb2-")
    proc = subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc",
         "-I", os.path.join(root, "proto"),
         "--python_out", outdir, "--grpc_python_out", outdir,
         os.path.join(root, "proto", "constraint_evaluation.proto")],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            "grpcio-tools protoc failed: " + (proc.stderr or proc.stdout))
    sys.path.insert(0, outdir)
    import constraint_evaluation_pb2 as pb2
    import constraint_evaluation_pb2_grpc as pb2_grpc
    _TONIC_STUBS = (pb2, pb2_grpc)
    return _TONIC_STUBS


def evaluate_remote_tonic(request: dict, socket_path: str) -> dict:
    """Call the real Rust Tonic server over a Unix socket.

    `socket_path` is the socket a `start-tonic-server` process is
    listening on (the caller starts it; see tests/test_spine.py
    TestTonicServer). `request` is the wire-contract dict
    (schema_version "1.0.0", constraint_id, operator "<=" / ">=" /
    "==", numeric value/bound, units, tolerance). Returns the same
    dict shape as `_evaluate_local` / `evaluate_remote`.

    Transport notes (verified 2026-11-11):
    * Unix socket, never TCP: the VM's egress proxy intercepts TCP
      loopback and breaks gRPC HTTP/2 there (verified 2026-11-10).
    * The channel MUST set `grpc.default_authority` to a plain
      hostname (here "localhost"). grpcio's default authority for a
      Unix-socket target is the percent-encoded socket path
      (e.g. `tmp%2Fstart-spine-tonic-123.sock`); the Tonic/h2
      server rejects that `:authority` with RST_STREAM
      PROTOCOL_ERROR (error code 1) before the handler ever runs —
      reproduced with a socket-tap proxy that dumped the HTTP/2
      frames, and confirmed fixed by the override (plain hostnames
      `localhost` and `tonic-server` both work; the raw path
      `tmp/tonic-smoke.sock` fails the same way).
    * The verdict returned is one constraint check only. It does
      NOT mark anything verified and does not bypass the verify
      step or human approval.
    """
    try:
        import grpc
    except ImportError as exc:
        raise RuntimeError("grpcio not installed: gRPC adapter is stub-only") from exc
    pb2, pb2_grpc = _load_tonic_stubs()
    channel = grpc.insecure_channel(
        f"unix://{socket_path}",
        options=(("grpc.default_authority", "localhost"),))
    stub = pb2_grpc.ConstraintEvaluationStub(channel)
    req = pb2.ConstraintRequest(
        schema_version=request.get("schema_version", "1.0.0"),
        constraint_id=request.get("constraint_id", ""),
        operator=request.get("operator", ""),
        value=float(request.get("value", 0.0)),
        value_unit=request.get("value_unit", ""),
        bound=float(request.get("bound", 0.0)),
        bound_unit=request.get("bound_unit", ""),
        tolerance=float(request.get("tolerance", 0.0)))
    resp = stub.Evaluate(req, timeout=10)
    return {"schema_version": resp.schema_version,
            "constraint_id": resp.constraint_id,
            "status": resp.status,
            "normalized_value": resp.normalized_value,
            "normalized_unit": resp.normalized_unit,
            "reason_code": resp.reason_code,
            "details": resp.details}
