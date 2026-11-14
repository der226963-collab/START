"""CLI entry point for START planning (ISSUE-27).

Run as ``python -m cli``. Stdlib only; file-in / file-out only.

Subcommands (all take ``--out <file>`` except ``list-domains``)::

    check-plan --plan <file> [--overrides <file>] --out <file>
    run --domain <id> --request <file> --out <file>
    run-scenario --domain <id> --scenario <file> --out <file>
    compare-scenarios --domain <id> --scenarios <file>... --out <file>
    list-domains

Global flags (before the subcommand): ``--verbose`` (INFO to stderr),
``--quiet`` (errors only), ``--log-file <path>`` (JSON-lines log
appended there instead of stderr), ``--force`` (allow overwriting an
existing output file).

Exit codes: 0 on success — including a result whose status is FAIL or
UNKNOWN (the plan outcome is data, not a CLI failure); 2 for
usage/validation errors; 1 for runtime failures. On any failure a
one-line error goes to stderr, the failure is logged, and NO output
file is written: inputs are validated and the engine is run before
the output path is opened. An existing output file is refused without
``--force`` (exit 1).

Every input file must be a persistence envelope (keys
``schema_version``, ``kind``, ``saved_at``, ``payload``). A bare
payload JSON without the envelope is rejected, never silently
accepted. The persisted ``result`` is the engine's result dict
verbatim — statuses are never rewritten.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from contracts.scenarios import Scenario
from domains import FoodDomain, LabourDomain, NutrientsDomain
from engine.event_log import configure_logging, log_event
from engine.planning_engine import PlanningEngine

# Envelope kinds the CLI understands, per the persistence interface
# (sibling worker, ISSUE-27): plan_request, scenario, result,
# plan_overrides.
KIND_PLAN_REQUEST = "plan_request"
KIND_PLAN_OVERRIDES = "plan_overrides"
KIND_SCENARIO = "scenario"
KIND_RESULT = "result"


class UsageError(Exception):
    """Exit 2: bad invocation, bad input, or failed validation."""


class RuntimeFailure(Exception):
    """Exit 1: the invocation was valid but the run could not complete."""


def _persistence():
    """Import the persistence interface (sibling worker, ISSUE-27).

    Imported lazily so ``--help`` and ``list-domains`` work even if the
    persistence package is not yet importable; a missing module is a
    runtime failure with a one-line message, never a traceback.
    """
    try:
        from persistence import load_envelope, save_envelope
    except ImportError as exc:
        raise RuntimeFailure(
            f"persistence module unavailable: {exc} (ISSUE-27 persistence package not installed)"
        ) from exc
    return load_envelope, save_envelope


def _one_line(message: object) -> str:
    """Collapse a message to a single line for the stderr error line."""
    return " ".join(str(message).split())


def _emit_error(message: object) -> None:
    print(f"error: {_one_line(message)}", file=sys.stderr)


def _build_engine() -> PlanningEngine:
    """One engine with exactly the three registered domains."""
    try:
        engine = PlanningEngine()
        engine.register(FoodDomain())
        engine.register(NutrientsDomain())
        engine.register(LabourDomain())
    except Exception as exc:
        raise RuntimeFailure(f"could not build planning engine: {exc}") from exc
    return engine


def _check_domain(engine: PlanningEngine, domain_id: str) -> None:
    available = engine.available_domains()
    if domain_id not in available:
        raise UsageError(
            f"unknown domain {domain_id!r}; available domains: {', '.join(available)}"
        )


def _bare_payload_message(path: str, expected_kind: str) -> str | None:
    """If ``path`` holds a bare payload (valid JSON, no envelope keys),
    return the expected-shape message; otherwise return None."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and ("schema_version" not in data or "kind" not in data):
        return (
            f"input file {path} is not a persistence envelope: expected an "
            f"envelope object with schema_version, kind, saved_at and payload "
            f"keys (e.g. {{\"schema_version\": \"1.0.0\", \"kind\": "
            f"\"{expected_kind}\", \"saved_at\": \"...\", \"payload\": {{...}}}}); "
            f"a bare payload without the envelope is not accepted"
        )
    return None


def _load_input(path: str, expected_kind: str) -> dict[str, Any]:
    """Load one input envelope and return its payload dict.

    Raises UsageError (exit 2) for a missing/unreadable file, invalid
    JSON, an envelope problem (unknown kind, major version mismatch,
    missing keys), a wrong kind, or a non-dict payload.
    """
    load_envelope, _ = _persistence()
    # load_envelope reports every failure — including a missing file —
    # as ValueError, so check readability first for a precise message.
    if not os.path.exists(path):
        raise UsageError(f"input file not found: {path}")
    if os.path.isdir(path):
        raise UsageError(f"input path is a directory: {path}")
    try:
        envelope = load_envelope(path)
    except FileNotFoundError:
        raise UsageError(f"input file not found: {path}") from None
    except IsADirectoryError:
        raise UsageError(f"input path is a directory: {path}") from None
    except ValueError as exc:
        shape_message = _bare_payload_message(path, expected_kind)
        if shape_message is not None:
            raise UsageError(shape_message) from None
        # load_envelope's message already starts with "{path}: "; drop
        # the duplicate so the one-line error reads cleanly.
        detail = _one_line(exc)
        prefix = f"{path}: "
        if detail.startswith(prefix):
            detail = detail[len(prefix):]
        raise UsageError(f"invalid envelope in {path}: {detail}") from None
    except OSError as exc:
        raise UsageError(f"cannot read input file {path}: {exc}") from None
    if not isinstance(envelope, dict):
        raise UsageError(f"invalid envelope in {path}: envelope is not an object")
    kind = envelope.get("kind")
    if kind != expected_kind:
        raise UsageError(
            f"wrong envelope kind in {path}: expected {expected_kind!r}, got {kind!r}"
        )
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise UsageError(
            f"invalid envelope in {path}: payload for kind {expected_kind!r} must be an object"
        )
    return payload


def _load_scenario(path: str) -> Scenario:
    """Load one scenario envelope and build the Scenario (exit 2 on bad fields)."""
    payload = _load_input(path, KIND_SCENARIO)
    try:
        return Scenario(**payload)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"invalid scenario in {path}: {_one_line(exc)}") from None


def _save_result(path: str, result: dict[str, Any], force: bool) -> None:
    """Persist the result envelope. Raises RuntimeFailure (exit 1).

    Called only after the engine has run, so a failure here never
    leaves a partial result behind. Refusing to overwrite an existing
    file without --force is exit 1 (output cannot be written as asked).
    """
    _, save_envelope = _persistence()
    if not force and os.path.exists(path):
        raise RuntimeFailure(
            f"output file already exists: {path} (use --force to overwrite)"
        )
    try:
        save_envelope(path, KIND_RESULT, result, overwrite=force)
    except (OSError, ValueError) as exc:
        raise RuntimeFailure(f"cannot write output file {path}: {exc}") from None


def _result_status(command: str, result: dict[str, Any]) -> str | None:
    """A one-token status summary for the success log line (metadata only)."""
    if command == "check-plan":
        status = result.get("overall_status")
    else:
        calculation = result.get("calculation")
        status = calculation.get("calculation_status") if isinstance(calculation, dict) else None
        if status is None:
            status = result.get("calculation_status")
    return status if isinstance(status, str) else None


def _run_check_plan(engine: PlanningEngine, args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_input(args.plan, KIND_PLAN_REQUEST)
    overrides = None
    if args.overrides is not None:
        overrides = _load_input(args.overrides, KIND_PLAN_OVERRIDES)
    try:
        return engine.check_plan(plan, overrides)
    except ValueError as exc:
        # Contradicting overrides, non-dict plan, or a bad plan value:
        # the input failed validation.
        raise UsageError(f"invalid plan: {_one_line(exc)}") from None
    except RuntimeError as exc:
        # Stored plan limits could not be loaded: the run cannot proceed.
        raise RuntimeFailure(str(exc)) from None
    except Exception as exc:
        raise RuntimeFailure(f"plan check failed: {type(exc).__name__}: {exc}") from None


def _run_run(engine: PlanningEngine, args: argparse.Namespace) -> dict[str, Any]:
    _check_domain(engine, args.domain)
    request = _load_input(args.request, KIND_PLAN_REQUEST)
    try:
        return engine.run(args.domain, request)
    except Exception as exc:
        raise RuntimeFailure(f"run failed: {type(exc).__name__}: {exc}") from None


def _run_run_scenario(engine: PlanningEngine, args: argparse.Namespace) -> dict[str, Any]:
    _check_domain(engine, args.domain)
    scenario = _load_scenario(args.scenario)
    try:
        return engine.run_scenario(args.domain, scenario)
    except Exception as exc:
        raise RuntimeFailure(f"scenario run failed: {type(exc).__name__}: {exc}") from None


def _run_compare_scenarios(engine: PlanningEngine, args: argparse.Namespace) -> dict[str, Any]:
    _check_domain(engine, args.domain)
    scenarios = [_load_scenario(path) for path in args.scenarios]
    try:
        return engine.compare_scenarios(args.domain, scenarios)
    except Exception as exc:
        raise RuntimeFailure(f"scenario comparison failed: {type(exc).__name__}: {exc}") from None


def _run_list_domains(engine: PlanningEngine, args: argparse.Namespace) -> int:
    for domain_id in engine.available_domains():
        print(domain_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="START planning CLI (ISSUE-27): file-in / file-out only. "
        "Every input is a persistence envelope; every output is a result envelope.",
    )
    parser.add_argument("--verbose", action="store_true",
                        help="log INFO records to stderr")
    parser.add_argument("--quiet", action="store_true",
                        help="log errors only")
    parser.add_argument("--log-file", metavar="PATH", default=None,
                        help="append JSON-lines log records to PATH instead of stderr")
    parser.add_argument("--force", action="store_true",
                        help="allow overwriting an existing output file")
    subparsers = parser.add_subparsers(dest="command", required=True,
                                       metavar="COMMAND")

    check_plan = subparsers.add_parser(
        "check-plan", help="check a plan against the stored limits")
    check_plan.add_argument("--plan", required=True, metavar="FILE",
                            help="plan_request envelope holding the plan dict")
    check_plan.add_argument("--overrides", default=None, metavar="FILE",
                            help="optional plan_overrides envelope holding the overrides dict")
    check_plan.add_argument("--out", required=True, metavar="FILE",
                            help="output file for the result envelope")

    run = subparsers.add_parser("run", help="run one domain on one request")
    run.add_argument("--domain", required=True, metavar="ID",
                     help="domain id (see list-domains)")
    run.add_argument("--request", required=True, metavar="FILE",
                     help="plan_request envelope holding the domain request dict")
    run.add_argument("--out", required=True, metavar="FILE",
                     help="output file for the result envelope")

    run_scenario = subparsers.add_parser(
        "run-scenario", help="run one domain on one scenario")
    run_scenario.add_argument("--domain", required=True, metavar="ID",
                              help="domain id (see list-domains)")
    run_scenario.add_argument("--scenario", required=True, metavar="FILE",
                              help="scenario envelope holding the Scenario fields")
    run_scenario.add_argument("--out", required=True, metavar="FILE",
                              help="output file for the result envelope")

    compare = subparsers.add_parser(
        "compare-scenarios",
        help="run one domain on several scenarios; reports consequences without ranking or selection")
    compare.add_argument("--domain", required=True, metavar="ID",
                         help="domain id (see list-domains)")
    compare.add_argument("--scenarios", required=True, nargs="+", metavar="FILE",
                         help="one or more scenario envelopes")
    compare.add_argument("--out", required=True, metavar="FILE",
                         help="output file for the result envelope")

    subparsers.add_parser("list-domains", help="print registered domain ids, one per line")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = "ERROR" if args.quiet else ("INFO" if args.verbose else "WARNING")
    try:
        configure_logging(level=level, log_file=args.log_file)
    except OSError as exc:
        _emit_error(f"cannot open log file {args.log_file!r}: {exc}")
        return 1

    command = args.command
    log_fields: dict[str, Any] = {"command": command}
    domain = getattr(args, "domain", None)
    if domain is not None:
        log_fields["domain"] = domain
    out = getattr(args, "out", None)
    if out is not None:
        log_fields["out"] = out
    log_event("cli", "cli_invoked", message=f"cli {command} invoked", **log_fields)

    try:
        engine = _build_engine()
        if command == "list-domains":
            return _run_list_domains(engine, args)
        if command == "check-plan":
            result = _run_check_plan(engine, args)
        elif command == "run":
            result = _run_run(engine, args)
        elif command == "run-scenario":
            result = _run_run_scenario(engine, args)
        elif command == "compare-scenarios":
            result = _run_compare_scenarios(engine, args)
        else:  # argparse `required=True` makes this unreachable.
            raise UsageError(f"unknown command: {command}")
        # Engine has run; only now is the output path touched.
        _save_result(args.out, result, args.force)
    except UsageError as exc:
        _emit_error(exc)
        log_event("cli", "cli_failed", level=logging.ERROR,
                  message=f"cli {command} failed", command=command, error=_one_line(exc))
        return 2
    except RuntimeFailure as exc:
        _emit_error(exc)
        log_event("cli", "cli_failed", level=logging.ERROR,
                  message=f"cli {command} failed", command=command, error=_one_line(exc))
        return 1
    except Exception as exc:  # Unexpected engine failure: exit 1, no output file.
        message = f"unexpected failure: {type(exc).__name__}: {exc}"
        _emit_error(message)
        log_event("cli", "cli_failed", level=logging.ERROR,
                  message=f"cli {command} failed", command=command, error=_one_line(message))
        return 1

    success_fields: dict[str, Any] = {"command": command, "out": args.out}
    status = _result_status(command, result)
    if status is not None:
        success_fields["status"] = status
    log_event("cli", "cli_succeeded", message=f"cli {command} succeeded", **success_fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
