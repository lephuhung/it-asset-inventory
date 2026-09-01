from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from deepagent.catalog import WINDOWS_TOOL_POLICIES
from deepagent.config import Settings


class MCPPolicyError(RuntimeError):
    pass


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _decode_envelope(value: object) -> dict[str, Any]:
    # LangChain MCP adapter thường trả ToolMessage; bridge Velociraptor đặt
    # envelope JSON ở `content` của message đó.
    if hasattr(value, "content"):
        return _decode_envelope(value.content)
    if isinstance(value, list):
        text = "\n".join(
            (
                item.get("text", "")
                if isinstance(item, dict)
                else getattr(item, "text", str(item))
            )
            for item in value
        )
        return _decode_envelope(text)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"ok": True, "data": value}
        if isinstance(decoded, dict) and "ok" in decoded:
            return decoded
        return {"ok": True, "data": decoded}
    if isinstance(value, Mapping):
        decoded = dict(value)
        if "ok" in decoded:
            return decoded
        return {"ok": True, "data": decoded}
    return {"ok": True, "data": value}


class VelociraptorMCP:
    """MCP adapter enforcing target, time range and a read-only tool allowlist."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = MultiServerMCPClient(
            {
                "velociraptor": {
                    "transport": "stdio",
                    "command": settings.mcp_command,
                    "args": settings.mcp_args(),
                    "env": settings.mcp_env(),
                }
            }
        )
        self._tools: dict[str, Any] | None = None

    async def _load_tools(self) -> dict[str, Any]:
        if self._tools is None:
            tools = await self._client.get_tools()
            self._tools = {tool.name: tool for tool in tools}
        return self._tools

    async def verify_target(self, *, client_id: str, org_id: str | None) -> dict[str, Any]:
        tools = await self._load_tools()
        tool = tools.get("list_clients")
        if tool is None:
            raise MCPPolicyError("MCP không cung cấp tool list_clients")
        raw = await tool.ainvoke(
            {"search": f"^{client_id}$", "limit": 5, "org_id": org_id or ""}
        )
        payload = _decode_envelope(raw)
        if not payload.get("ok"):
            raise MCPPolicyError(str(payload.get("error") or "Không xác minh được client"))
        rows = payload.get("data")
        if isinstance(rows, dict):
            rows = rows.get("clients") or rows.get("items") or rows.get("rows") or [rows]
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            found = row.get("client_id") or row.get("ClientId") or row.get("client_id")
            if found == client_id:
                return row
        raise MCPPolicyError(f"client_id {client_id} không tồn tại hoặc ngoài org được cấu hình")

    async def test_connection(self) -> dict[str, Any]:
        """Xác minh bridge MCP bằng một truy vấn read-only tối đa một client."""
        tools = await self._load_tools()
        list_clients = tools.get("list_clients")
        if list_clients is None:
            raise MCPPolicyError("MCP không cung cấp tool list_clients")
        raw = await list_clients.ainvoke(
            {"search": "", "limit": 1, "org_id": self.settings.velociraptor_org_id}
        )
        payload = _decode_envelope(raw)
        if not payload.get("ok"):
            raise MCPPolicyError(str(payload.get("error") or "MCP list_clients thất bại"))
        data = payload.get("data")
        if isinstance(data, dict):
            data = data.get("clients") or data.get("items") or data.get("rows") or [data]
        return {
            "tools": sorted(tools),
            "client_count_sampled": min(len(data), 1) if isinstance(data, list) else 0,
        }

    async def collect(
        self,
        *,
        tool_name: str,
        client_id: str,
        org_id: str | None,
        time_from: datetime,
        time_to: datetime,
    ) -> dict[str, Any]:
        policy = WINDOWS_TOOL_POLICIES.get(tool_name)
        if policy is None:
            raise MCPPolicyError(f"Tool bị chặn bởi allowlist: {tool_name}")
        tools = await self._load_tools()
        tool = tools.get(tool_name)
        if tool is None:
            raise MCPPolicyError(f"MCP không cung cấp tool: {tool_name}")

        arguments: dict[str, Any] = {
            "client_id": client_id,
            "org_id": org_id or self.settings.velociraptor_org_id,
        }
        if policy.uses_time_range:
            arguments["DateAfter"] = _iso_z(time_from)
            arguments["DateBefore"] = _iso_z(time_to)

        raw = await tool.ainvoke(arguments)
        payload = _decode_envelope(raw)
        data = payload.get("data")
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        if len(serialized) > self.settings.max_tool_result_chars:
            payload["data"] = {
                "truncated": True,
                "original_chars": len(serialized),
                "preview": serialized[: self.settings.max_tool_result_chars],
            }
        return payload
