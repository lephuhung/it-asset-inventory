"""Safe, structured operational events for DeepAgent docker logs."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_EVENT_LOGGER_NAME = "deepagent.events"
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|client_private_key)\s*([:=])\s*[^\s,;]+"
)
_context: ContextVar[dict[str, Any] | None] = ContextVar("deepagent_log_context", default=None)


class _StdoutEventHandler(logging.Handler):
    """Resolve stdout at emit time so pytest and container stream capture both work."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(f"{self.format(record)}\n")
        sys.stdout.flush()


def _event_logger() -> logging.Logger:
    """Return a stdout logger without changing the application's root logging config."""
    logger = logging.getLogger(_EVENT_LOGGER_NAME)
    if not logger.handlers:
        handler = _StdoutEventHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


@contextmanager
def investigation_context(
    *,
    investigation_id: str,
    job_id: str | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> Iterator[None]:
    """Bind identifiers and values that must never escape into an event."""
    token = _context.set(
        {
            "investigation_id": investigation_id,
            "job_id": job_id,
            "sensitive_values": tuple(value for value in sensitive_values if value),
        }
    )
    try:
        yield
    finally:
        _context.reset(token)


def _safe_http_status(error: BaseException) -> int | None:
    """Extract HTTP status code from exception if it's a real HTTP error response.

    Returns the status code only when it's an integer in the 4xx/5xx range —
    i.e. an actual HTTP error, not an arbitrary attribute named ``status_code``
    or a 2xx success code. Returns ``None`` for non-HTTP exceptions.
    """
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and 400 <= status <= 599:
        return status
    return None


def _safe_error_message(error: BaseException, sensitive_values: tuple[str, ...]) -> str:
    """Never serialize an external error body, which may mix secrets and evidence."""
    message = str(error)
    contains_sensitive_value = any(value in message for value in sensitive_values)
    contains_sensitive_assignment = _SENSITIVE_ASSIGNMENT.search(message) is not None
    if contains_sensitive_value or contains_sensitive_assignment:
        return "[REDACTED] External error message withheld to protect sensitive investigation data."
    return "External error message withheld to protect sensitive investigation data."


def safe_error_detail(error: BaseException, sensitive_values: tuple[str, ...] = ()) -> str:
    """Return safe external diagnostics: exception type, redacted message, optional HTTP status.

    HTTP status code (4xx/5xx) là metadata an toàn — phân biệt được 400 (validation)
    vs 401 (auth) vs 404 (model) vs 500 (server) mà không lộ evidence hay secret.
    """
    detail = f"{type(error).__name__}: {_safe_error_message(error, sensitive_values)}"
    status = _safe_http_status(error)
    if status is not None:
        detail = f"{detail} [HTTP {status}]"
    return detail


def log_event(
    *,
    phase: str,
    outcome: str,
    duration_ms: float | None = None,
    error: BaseException | None = None,
    **metadata: Any,
) -> None:
    """Emit exactly one JSON object containing safe, machine-readable metadata."""
    context = _context.get() or {}
    event: dict[str, Any] = {
        "event": "deepagent_operational",
        "timestamp": datetime.now(UTC).isoformat(),
        "investigation_id": context.get("investigation_id"),
        "phase": phase,
        "outcome": outcome,
    }
    if context.get("job_id"):
        event["job_id"] = context["job_id"]
    if duration_ms is not None:
        event["duration_ms"] = max(0, int(duration_ms))
    event.update({key: value for key, value in metadata.items() if value is not None})
    if error is not None:
        event["error_type"] = type(error).__name__[:100]
        event["error_message"] = _safe_error_message(
            error, context.get("sensitive_values", ())
        )
        http_status = _safe_http_status(error)
        if http_status is not None:
            event["error_http_status"] = http_status
    _event_logger().info(json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":")))
