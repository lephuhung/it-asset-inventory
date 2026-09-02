from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from deepagent.config import Settings
from deepagent.mcp_client import MCPPolicyError, MCPToolTimeout, VelociraptorMCP


class FakeTool:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        return self.response


def test_failed_mcp_envelope_logs_safe_failure_metadata(capsys) -> None:
    client = VelociraptorMCP.__new__(VelociraptorMCP)
    raw_evidence = "raw-evidence-should-never-appear"

    client._log_tool_result(
        tool_name="windows_pslist",
        payload={"ok": False, "error": f"bridge error: {raw_evidence}"},
        duration_ms=12.5,
    )

    event = json.loads(capsys.readouterr().out)
    assert event["outcome"] == "failed"
    assert event["error_type"] == "MCPToolFailure"
    assert event["error_message"] == "MCP tool returned a failed envelope."
    assert raw_evidence not in json.dumps(event)


@pytest.mark.asyncio
async def test_mcp_test_connection_only_samples_one_client() -> None:
    list_clients = FakeTool('{"ok": true, "data": [{"client_id":"C.1"}, {"client_id":"C.2"}]}')
    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings(velociraptor_org_id="org-a")
    client._tools = {"list_clients": list_clients, "windows_pslist": FakeTool("{}")}  # type: ignore[attr-defined]

    result = await client.test_connection()

    assert result["client_count_sampled"] == 1
    assert result["tools"] == ["list_clients", "windows_pslist"]
    assert list_clients.calls == [{"search": "", "limit": 1, "org_id": "org-a"}]


@pytest.mark.asyncio
async def test_mcp_test_connection_requires_read_only_list_clients() -> None:
    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings()
    client._tools = {}  # type: ignore[attr-defined]

    with pytest.raises(MCPPolicyError, match="list_clients"):
        await client.test_connection()


def test_mcp_tool_timeout_seconds_default_and_validation() -> None:
    assert Settings().mcp_tool_timeout_seconds == 180
    assert Settings(mcp_tool_timeout_seconds=10).mcp_tool_timeout_seconds == 10
    assert Settings(mcp_tool_timeout_seconds=1800).mcp_tool_timeout_seconds == 1800
    with pytest.raises(ValidationError):
        Settings(mcp_tool_timeout_seconds=9)
    with pytest.raises(ValidationError):
        Settings(mcp_tool_timeout_seconds=1801)


@pytest.mark.asyncio
async def test_mcp_tool_timeout_emits_safe_metadata(capsys) -> None:
    class HangingTool:
        async def ainvoke(self, _arguments):
            await asyncio.Event().wait()

    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings(mcp_tool_timeout_seconds=10)
    # Test the runtime deadline by overriding the bound below the floor.
    object.__setattr__(client.settings, "mcp_tool_timeout_seconds", 0.01)
    with pytest.raises(MCPToolTimeout):
        await client._invoke_tool(
            tool=HangingTool(),
            tool_name="windows_pslist",
            arguments={},
        )
    raw_output = capsys.readouterr().out
    event = json.loads(raw_output.splitlines()[-1])
    assert event["phase"] == "mcp_tool_call"
    assert event["outcome"] == "failed"
    assert event["tool_name"] == "windows_pslist"
    assert event["error_type"] == "MCPToolTimeout"
    assert event["error_message"] == "MCP tool call exceeded its configured deadline."
    assert "raw-evidence-should-never-appear" not in json.dumps(event)


@pytest.mark.asyncio
async def test_mcp_invocation_does_not_classify_tool_raised_timeout_as_deadline(capsys) -> None:
    raw_evidence = "raw-evidence-should-never-appear"

    class ToolRaisedTimeout:
        async def ainvoke(self, _arguments):
            raise TimeoutError(f"bridge raised timeout: {raw_evidence}")

    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings(mcp_tool_timeout_seconds=10)

    with pytest.raises(TimeoutError) as exc_info:
        await client._invoke_tool(
            tool=ToolRaisedTimeout(),
            tool_name="windows_pslist",
            arguments={},
        )
    assert type(exc_info.value) is TimeoutError

    raw_output = capsys.readouterr().out
    assert '"error_type":"MCPToolTimeout"' not in raw_output
    assert '"error_type":"RuntimeError"' not in raw_output
    assert raw_evidence not in raw_output


@pytest.mark.asyncio
async def test_mcp_tool_timeout_does_not_swallow_normal_results(capsys) -> None:
    list_clients = FakeTool('{"ok": true, "data": [{"client_id": "C.1"}]}')
    client = VelociraptorMCP.__new__(VelociraptorMCP)
    client.settings = Settings(mcp_tool_timeout_seconds=10)
    client._tools = {"list_clients": list_clients}  # type: ignore[attr-defined]

    payload, duration_ms = await client._invoke_tool(
        tool=list_clients,
        tool_name="list_clients",
        arguments={"search": "", "limit": 1},
    )
    assert payload == {"ok": True, "data": [{"client_id": "C.1"}]}
    assert duration_ms >= 0
    assert capsys.readouterr().out == ""
