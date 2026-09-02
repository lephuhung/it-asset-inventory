from __future__ import annotations

import json

import pytest

from deepagent.config import Settings
from deepagent.mcp_client import MCPPolicyError, VelociraptorMCP


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
