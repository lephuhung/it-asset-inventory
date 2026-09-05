from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from deepagent.config import Settings
from deepagent.mcp_client import MCPToolTimeout, VelociraptorMCP
from deepagent.observability import investigation_context, log_event


def test_structured_event_includes_context_timing_and_redacts_sensitive_errors(capsys) -> None:
    api_key = "test-api-key-should-never-appear"
    yaml = "client_private_key: private-key-should-never-appear"
    prompt = "prompt-should-never-appear"

    with investigation_context(
        investigation_id="investigation-1",
        job_id="job-1",
        sensitive_values=(api_key, yaml, prompt),
    ):
        log_event(
            phase="assessment_model_call",
            outcome="failed",
            duration_ms=12.8,
            model="test-model",
            error=RuntimeError(f"api_key={api_key}; {yaml}; {prompt}"),
        )

    output = capsys.readouterr().out
    event = json.loads(output)
    assert event["investigation_id"] == "investigation-1"
    assert event["job_id"] == "job-1"
    assert event["phase"] == "assessment_model_call"
    assert event["outcome"] == "failed"
    assert event["duration_ms"] == 12
    assert event["model"] == "test-model"
    assert event["error_type"] == "RuntimeError"
    assert "[REDACTED]" in event["error_message"]
    assert api_key not in output
    assert yaml not in output
    assert prompt not in output


def test_structured_event_withholds_mixed_secret_and_raw_evidence(capsys) -> None:
    api_key = "test-api-key-should-never-appear"
    raw_evidence = "raw-evidence-should-never-appear"

    with investigation_context(
        investigation_id="investigation-1",
        sensitive_values=(api_key,),
    ):
        log_event(
            phase="mcp_tool_call",
            outcome="failed",
            error=RuntimeError(f"api_key={api_key}; evidence={raw_evidence}"),
        )

    event = json.loads(capsys.readouterr().out)
    assert event["error_message"] == "[REDACTED] External error message withheld to protect sensitive investigation data."
    assert api_key not in json.dumps(event)
    assert raw_evidence not in json.dumps(event)


@pytest.mark.asyncio
async def test_mcp_tool_event_reports_size_without_evidence_content(capsys) -> None:
    evidence = "raw-evidence-should-never-appear"

    class FakeTool:
        async def ainvoke(self, _arguments):
            return {"ok": True, "data": {"evidence": evidence}}

    mcp = VelociraptorMCP.__new__(VelociraptorMCP)
    mcp.settings = Settings(max_tool_result_chars=5)
    mcp._tools = {"windows_pslist": FakeTool()}  # type: ignore[attr-defined]

    with investigation_context(investigation_id="investigation-1", job_id="job-1"):
        payload = await mcp.collect(
            tool_name="windows_pslist",
            client_id="C.1",
            org_id=None,
            time_from=datetime.now(UTC),
            time_to=datetime.now(UTC),
        )

    event = json.loads(capsys.readouterr().out)
    assert payload["data"]["truncated"] is True
    assert event["phase"] == "mcp_tool_call"
    assert event["tool_name"] == "windows_pslist"
    assert event["outcome"] == "succeeded"
    assert event["duration_ms"] >= 0
    assert event["result_truncated"] is True
    assert event["result_chars"] > event["truncated_preview_chars"]
    assert evidence not in json.dumps(event)


def test_safe_error_detail_includes_http_status_for_api_errors() -> None:
    """HTTP status code (4xx/5xx) là metadata an toàn — phải xuất hiện trong
    safe_error_detail() để admin phân biệt được 400 (validation) vs 404 (model)
    vs 500 (server). Status được nối dạng '[HTTP {code}]' ở cuối — KHÔNG lộ
    nội dung evidence hay secret.
    """
    from deepagent.observability import safe_error_detail

    # Exception có status_code trong range HTTP error (4xx/5xx)
    class FakeApiError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"upstream message that must not leak: status={status_code}")
            self.status_code = status_code

    detail = safe_error_detail(FakeApiError(400), sensitive_values=())
    assert detail.startswith("FakeApiError: ")
    assert "[HTTP 400]" in detail
    # Nội dung gốc KHÔNG được lộ
    assert "upstream message" not in detail
    assert "must not leak" not in detail

    detail_404 = safe_error_detail(FakeApiError(404), sensitive_values=())
    assert "[HTTP 404]" in detail_404

    detail_500 = safe_error_detail(FakeApiError(500), sensitive_values=())
    assert "[HTTP 500]" in detail_500


def test_safe_error_detail_omits_http_status_for_non_http_errors() -> None:
    """Exception thông thường (không phải HTTP API error) không có status_code
    → không nối '[HTTP ...]'. Attribute 'status_code' ngoài range 400-599 bị bỏ.
    """
    from deepagent.observability import safe_error_detail

    # Exception không có status_code
    detail_plain = safe_error_detail(RuntimeError("boom"), sensitive_values=())
    assert "[HTTP" not in detail_plain
    assert detail_plain.startswith("RuntimeError: ")

    # status_code ngoài HTTP error range (vd: 200, 0, 100) phải bị bỏ
    class WeirdStatusError(Exception):
        status_code = 200  # success code, không phải error

    detail_ok = safe_error_detail(WeirdStatusError("ignored"), sensitive_values=())
    assert "[HTTP" not in detail_ok


def test_log_event_includes_error_http_status_when_available(capsys) -> None:
    """log_event phải capture error_http_status (nếu có) thành field riêng
    trong event JSON — phục vụ dashboard/alert rule, không chỉ console.
    """
    from deepagent.observability import log_event

    class FakeApiError(Exception):
        def __init__(self):
            super().__init__("body content with secret-key-leak=value")
            self.status_code = 400

    with investigation_context(investigation_id="inv-1", job_id="job-1"):
        log_event(
            phase="planning_model_call",
            outcome="failed",
            error=FakeApiError(),
        )

    event = json.loads(capsys.readouterr().out)
    assert event["error_type"] == "FakeApiError"
    assert event["error_http_status"] == 400
    # Body gốc vẫn bị redact
    assert "secret-key-leak" not in json.dumps(event)


def test_log_event_omits_error_http_status_when_not_http_error(capsys) -> None:
    """Không có status_code hợp lệ → field error_http_status không xuất hiện."""
    from deepagent.observability import log_event

    with investigation_context(investigation_id="inv-1"):
        log_event(
            phase="mcp_tool_call",
            outcome="failed",
            error=RuntimeError("plain runtime error"),
        )

    event = json.loads(capsys.readouterr().out)
    assert event["error_type"] == "RuntimeError"
    assert "error_http_status" not in event


@pytest.mark.asyncio
async def test_mcp_tool_timeout_event_keeps_caller_deadline_semantics(capsys) -> None:
    import asyncio

    class HangingTool:
        async def ainvoke(self, _arguments):
            await asyncio.Event().wait()

    mcp = VelociraptorMCP.__new__(VelociraptorMCP)
    mcp.settings = Settings(mcp_tool_timeout_seconds=10)
    object.__setattr__(mcp.settings, "mcp_tool_timeout_seconds", 0.01)
    mcp._tools = {"windows_pslist": HangingTool()}  # type: ignore[attr-defined]

    with investigation_context(investigation_id="investigation-1", job_id="job-1"), \
        pytest.raises(MCPToolTimeout):
        await mcp.collect(
            tool_name="windows_pslist",
            client_id="C.1",
            org_id=None,
            time_from=datetime.now(UTC),
            time_to=datetime.now(UTC),
        )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    timeout_event = next(event for event in events if event.get("error_type") == "MCPToolTimeout")
    serialized = json.dumps(timeout_event)
    assert timeout_event["phase"] == "mcp_tool_call"
    assert timeout_event["outcome"] == "failed"
    assert timeout_event["tool_name"] == "windows_pslist"
    assert timeout_event["error_message"] == "MCP tool call exceeded its configured deadline."
    # Caller deadline must never expose raw tool input or output.
    assert "raw-evidence-should-never-appear" not in serialized
