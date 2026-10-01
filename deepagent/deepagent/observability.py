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


# ---------------------------------------------------------------------------
# Error categorization
#
# Why: when an investigation fails, the error message currently surfaces as
# "External error message withheld to protect sensitive investigation
# data." — accurate, but useless to operators and end-users. The
# front-end (portal) renders `dfir_investigations.error` verbatim, so the
# only way to give operators an actionable signal without leaking
# sensitive content is to classify the exception into a stable category
# and pair it with a hand-written hint. Exception class names, HTTP status
# codes, and these static hint strings are the only safe-to-emit surface.
# ---------------------------------------------------------------------------

try:  # openai is required transitively; guard import for test isolation
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        BadRequestError,
        ContentFilterFinishReasonError,
        InternalServerError,
        LengthFinishReasonError,
        PermissionDeniedError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - openai always available at runtime
    APIConnectionError = APIStatusError = APITimeoutError = BadRequestError = None  # type: ignore[assignment]
    ContentFilterFinishReasonError = InternalServerError = None  # type: ignore[assignment]
    LengthFinishReasonError = PermissionDeniedError = RateLimitError = None  # type: ignore[assignment]


# (category, hint) tuples. Hints are short, hand-written, in Vietnamese to
# match the rest of the operator-facing UI. They MUST NOT include any
# fragment of the raw error message.
_CATEGORY_HINTS: dict[str, str] = {
    "llm_timeout": (
        "LLM backend timeout. Kiểm tra kết nối tới LLM endpoint và xem xét "
        "tăng `DEEPAGENT_LLM_TIMEOUT_SECONDS`."
    ),
    "llm_unreachable": (
        "Không kết nối được tới LLM backend. Kiểm tra base_url và network "
        "tới LLM server."
    ),
    "llm_output_truncated": (
        "LLM trả về output vượt quá max_tokens. Xem xét tăng max_tokens "
        "trong llm_config hoặc rút gọn prompt."
    ),
    "llm_content_filtered": (
        "LLM từ chối trả lời do bộ lọc nội dung. Kiểm tra lại prompt và "
        "dữ liệu đầu vào."
    ),
    "llm_rate_limited": (
        "LLM backend đang rate-limit. Đợi một lúc rồi retry investigation."
    ),
    "llm_bad_request": (
        "LLM backend từ chối request (400). Kiểm tra prompt có hợp lệ, "
        "schema đúng và không vượt context window."
    ),
    "llm_forbidden": (
        "LLM backend từ chối xác thực (403). Kiểm tra API key trong llm_config."
    ),
    "llm_server_error": (
        "LLM backend gặp lỗi 5xx. Kiểm tra trạng thái dịch vụ upstream."
    ),
    "internal": (
        "Lỗi nội bộ DeepAgent. Xem log chi tiết trong container `deepagent`."
    ),
}


def categorize_error(error: BaseException) -> tuple[str, str]:
    """Map an exception to a stable (category, hint) pair.

    The category is a short snake_case identifier; the hint is a static,
    hand-written Vietnamese string from `_CATEGORY_HINTS`. The raw error
    message is NEVER included — only the exception class name and HTTP
    status code are extracted for diagnostic display.
    """
    cls = type(error)
    name = cls.__name__

    # OpenAI exception classes (lazy-imported, may be None in tests).
    if LengthFinishReasonError is not None and isinstance(error, LengthFinishReasonError):
        return "llm_output_truncated", _CATEGORY_HINTS["llm_output_truncated"]
    if ContentFilterFinishReasonError is not None and isinstance(
        error, ContentFilterFinishReasonError
    ):
        return "llm_content_filtered", _CATEGORY_HINTS["llm_content_filtered"]
    if APITimeoutError is not None and isinstance(error, APITimeoutError):
        return "llm_timeout", _CATEGORY_HINTS["llm_timeout"]
    if APIConnectionError is not None and isinstance(error, APIConnectionError):
        return "llm_unreachable", _CATEGORY_HINTS["llm_unreachable"]
    if RateLimitError is not None and isinstance(error, RateLimitError):
        return "llm_rate_limited", _CATEGORY_HINTS["llm_rate_limited"]
    if BadRequestError is not None and isinstance(error, BadRequestError):
        return "llm_bad_request", _CATEGORY_HINTS["llm_bad_request"]
    if PermissionDeniedError is not None and isinstance(
        error, PermissionDeniedError
    ):
        return "llm_forbidden", _CATEGORY_HINTS["llm_forbidden"]
    if InternalServerError is not None and isinstance(
        error, InternalServerError
    ):
        return "llm_server_error", _CATEGORY_HINTS["llm_server_error"]
    if APIStatusError is not None and isinstance(error, APIStatusError):
        # Fallback for any other APIStatusError subclass.
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            if 500 <= status <= 599:
                return "llm_server_error", _CATEGORY_HINTS["llm_server_error"]
            if status == 429:
                return "llm_rate_limited", _CATEGORY_HINTS["llm_rate_limited"]
            if status == 401 or status == 403:
                return "llm_forbidden", _CATEGORY_HINTS["llm_forbidden"]
            if 400 <= status <= 499:
                return "llm_bad_request", _CATEGORY_HINTS["llm_bad_request"]

    # DeepAgent internal categories
    if name == "MCPToolTimeout" or "ToolTimeout" in name:
        return "mcp_timeout", (
            "Velociraptor MCP timeout. Tool chạy quá lâu. Xem xét tăng "
            "DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS hoặc thu hẹp time range."
        )
    if name == "MCPPolicyError":
        return "mcp_policy", (
            "MCP policy violation: tool hoặc argument bị chặn bởi allowlist. "
            "Kiểm tra catalog Tier 1 / Tier 2."
        )
    if name == "ArtifactPushError":
        return "velociraptor_push", (
            "Velociraptor không nhận artifact Custom.*. Kiểm tra artifact "
            "definition hợp lệ và push status trên portal admin."
        )

    return "internal", _CATEGORY_HINTS["internal"]
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
    """Return safe external diagnostics: category + hint + HTTP status.

    Output format (single-line, safe to render verbatim in the portal):
        `[<category>] <hint> [HTTP <status>]`

    `category` is a stable identifier (e.g. `llm_output_truncated`). `hint`
    is a hand-written Vietnamese string from `_CATEGORY_HINTS`. HTTP status
    code (4xx/5xx) is metadata an toàn — phân biệt được 400 (validation)
    vs 401 (auth) vs 404 (model) vs 500 (server) mà không lộ evidence
    hay secret.

    The raw exception body is NEVER included — only the exception class
    name (truncated) is allowed, and even that is wrapped inside the
    structured category hint.
    """
    category, hint = categorize_error(error)
    parts = [f"[{category}]", hint]
    status = _safe_http_status(error)
    if status is not None:
        parts.append(f"[HTTP {status}]")
    return " ".join(parts)


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
        category, _hint = categorize_error(error)
        event["error_category"] = category
        event["error_message"] = _safe_error_message(
            error, context.get("sensitive_values", ())
        )
        http_status = _safe_http_status(error)
        if http_status is not None:
            event["error_http_status"] = http_status
    _event_logger().info(json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":")))
