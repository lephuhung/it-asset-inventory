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
