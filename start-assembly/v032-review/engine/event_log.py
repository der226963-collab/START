"""Structured JSON-lines logging for START planning (ISSUE-27).

Stdlib ``logging`` only; no third-party framework. Every record is one
JSON object on one line: ``timestamp`` (UTC ISO-8601), ``level``,
``logger`` (namespaced ``start.*``), ``event`` (stable machine-readable
name), ``message`` (human-readable), plus event-specific metadata fields
(ids, statuses, counts, paths).

Privacy rule (hard): INFO and above log metadata only — ids, statuses,
counts, paths. NEVER a full request or result payload at INFO or above.
DEBUG may include payloads. See docs/ARCHITECTURE.md.

Library rule (hard): importing this module — or any module that uses
it — configures nothing. :func:`configure_logging` is called only by
the CLI entry point (``cli/__main__.py``). Until then the ``start``
loggers have no handlers of their own and propagate to the root logger
as usual, so library use stays silent by default.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as one JSON object on one line.

    ``event`` and ``fields`` arrive via the ``extra`` dict passed by
    :func:`log_event`; anything else logged through a ``start`` logger
    without them still formats as a plain JSON record.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": utc_now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def logger(name: str) -> logging.Logger:
    """Return the ``start.<name>`` logger (no configuration)."""
    return logging.getLogger("start." + name)


def configure_logging(level: str = "WARNING", log_file: str | None = None) -> logging.Logger:
    """Configure the ``start`` logger tree. CLI entry point only.

    Default level WARNING to stderr; the CLI maps ``--verbose`` to INFO
    and ``--quiet`` to ERROR. ``log_file`` appends JSON-lines records to
    that path instead of writing to stderr. Calling this twice replaces
    the previous handler rather than stacking duplicates.
    """
    root = logging.getLogger("start")
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    if log_file is not None:
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    # Records are handled here; do not also bubble to the root logger.
    root.propagate = False
    return root


def log_event(
    logger_name: str,
    event: str,
    level: int = logging.INFO,
    message: str = "",
    **fields: object,
) -> None:
    """Emit one structured event on ``start.<logger_name>``.

    ``fields`` is metadata only (ids, statuses, counts, paths) at INFO
    and above — never a request or result payload. Pass payloads only
    at DEBUG, and only where a call site explicitly opts in.
    """
    log = logging.getLogger("start." + logger_name)
    log.log(level, message or event, extra={"event": event, "fields": fields})
