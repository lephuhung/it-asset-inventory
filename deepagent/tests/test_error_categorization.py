"""Tests for error categorization (LLM exceptions → safe category + hint).

The previous behavior suppressed every error message into a generic
"External error message withheld…", which left operators blind to
recurring classes of failures (LLM timeout, output truncation, rate
limit, etc.). The backend stores `error` in dfir_investigations and the
portal renders it directly — so the front-end receives only
non-actionable text.

This module asserts that `categorize_error()` maps well-known OpenAI
exception classes to safe (category, hint) pairs that the front-end
can render verbatim. Raw exception bodies are still suppressed to avoid
leaking prompt fragments or evidence; only exception class names,
HTTP status codes, and our own static hint strings escape.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    PermissionDeniedError,
    RateLimitError,
)

from deepagent.observability import (
    categorize_error,
    investigation_context,
    log_event,
    safe_error_detail,
)


# ---------------------------------------------------------------------------
# Exception factories — openai >=1.x requires specific kwargs for some
# subclasses (length/content finish reasons need `completion`; rate-limit
# family needs `message`, `body`, `response`). Use factories to keep the
# parametrize table readable.
# ---------------------------------------------------------------------------


def _length_finish() -> LengthFinishReasonError:
    return LengthFinishReasonError(completion=MagicMock())


def _content_filter_finish() -> ContentFilterFinishReasonError:
    return ContentFilterFinishReasonError()


def _rate_limit() -> RateLimitError:
    return RateLimitError(
        message="rate limited", response=MagicMock(), body=None
    )


def _bad_request() -> BadRequestError:
    return BadRequestError(message="bad", response=MagicMock(), body=None)


def _internal_server() -> InternalServerError:
    return InternalServerError(message="server err", response=MagicMock(), body=None)


def _permission_denied() -> PermissionDeniedError:
    return PermissionDeniedError(message="forbidden", response=MagicMock(), body=None)


# ===========================================================================
# categorize_error: openai exception → (category, hint)
# ===========================================================================


class TestCategorizeOpenAIExceptions:
    @pytest.mark.parametrize(
        "exc_factory,expected_category",
        [
            (lambda: APITimeoutError(request=None), "llm_timeout"),
            (lambda: APIConnectionError(request=None), "llm_unreachable"),
            (_length_finish, "llm_output_truncated"),
            (_content_filter_finish, "llm_content_filtered"),
            (_rate_limit, "llm_rate_limited"),
            (_bad_request, "llm_bad_request"),
            (_internal_server, "llm_server_error"),
            (_permission_denied, "llm_forbidden"),
        ],
    )
    def test_openai_exception_maps_to_category(
        self, exc_factory, expected_category: str
    ) -> None:
        category, _hint = categorize_error(exc_factory())
        assert category == expected_category

    def test_timeout_includes_actionable_hint(self) -> None:
        _category, hint = categorize_error(APITimeoutError(request=None))
        assert "timeout" in hint.lower() or "tăng" in hint.lower()

    def test_truncated_includes_actionable_hint(self) -> None:
        _category, hint = categorize_error(_length_finish())
        assert "max_tokens" in hint.lower() or "tăng" in hint.lower()

    def test_rate_limit_includes_actionable_hint(self) -> None:
        _category, hint = categorize_error(_rate_limit())
        assert "rate" in hint.lower() or "đợi" in hint.lower()

    def test_unmapped_exception_returns_internal_category(self) -> None:
        category, hint = categorize_error(ValueError("bad input"))
        assert category == "internal"
        assert hint  # must not be empty


# ===========================================================================
# safe_error_detail: includes category + hint + safe parts
# ===========================================================================


class TestSafeErrorDetailWithCategory:
    """`safe_error_detail` must include both the category AND the hint so
    the front-end can render an actionable error message.
    """

    def test_includes_category_in_safe_detail(self) -> None:
        detail = safe_error_detail(_length_finish())
        assert "llm_output_truncated" in detail
        assert "max_tokens" in detail.lower() or "tăng" in detail.lower()

    def test_includes_hint_in_safe_detail(self) -> None:
        detail = safe_error_detail(_length_finish())
        assert any(
            keyword in detail.lower()
            for keyword in ("max_tokens", "tăng", "increase", "retry")
        ), f"Expected actionable hint in detail, got: {detail!r}"

    def test_timeout_safe_detail_actionable(self) -> None:
        detail = safe_error_detail(APITimeoutError(request=None))
        assert "llm_timeout" in detail
        assert "timeout" in detail.lower() or "tăng" in detail.lower()

    def test_raw_message_with_sensitive_data_still_redacted(self) -> None:
        """Even with new categorization, sensitive content must not leak."""
        secret = "user-private-prompt-content"
        exc = APITimeoutError(request=None)
        exc.message = f"timeout during {secret}"
        detail = safe_error_detail(exc, sensitive_values=(secret,))
        assert secret not in detail

    def test_http_status_code_preserved(self) -> None:
        """HTTP status code (4xx/5xx) is safe metadata."""
        from openai import APIStatusError

        err = APIStatusError(
            "internal error",
            response=MagicMock(status_code=503),
            body=None,
        )
        detail = safe_error_detail(err)
        assert "503" in detail


# ===========================================================================
# log_event integrates the category as a structured field
# ===========================================================================


class TestLogEventEmitsErrorCategory:
    def test_log_event_includes_error_category(self, capsys) -> None:
        with investigation_context(investigation_id="inv-1"):
            log_event(
                phase="planning_model_call",
                outcome="failed",
                duration_ms=12.0,
                error=_length_finish(),
            )

        event = json.loads(capsys.readouterr().out)
        assert event["error_category"] == "llm_output_truncated"
        # Raw error message still suppressed — never leak prompt fragments
        assert "External error message withheld" in event["error_message"]
        assert "LengthFinishReasonError" in event["error_type"]
