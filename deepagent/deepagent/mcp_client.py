from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from time import perf_counter
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from deepagent.catalog import WINDOWS_TOOL_POLICIES
from deepagent.config import Settings
from deepagent.observability import log_event


class MCPPolicyError(RuntimeError):
    pass


class MCPToolTimeout(TimeoutError):
    """The caller deadline expired before an MCP tool returned.

    A DeepAgent-side timeout is only proof that the MCP call did not return
    before the configured deadline. It is NOT a Velociraptor flow-level
    guarantee. Flow-level diagnosis (client_unavailable, collection_timeout,
    flow_error, result_read_timeout) is owned by a tracked bridge patch/fork
    delivered in Phase 2; this class deliberately does not classify external
    causes from raw error text.
    """

    def __init__(self, tool_name: str) -> None:
        # Tool name is treated as non-sensitive allowlist metadata only.
        super().__init__(f"MCP tool call exceeded its configured deadline: {tool_name}")
        self.tool_name = tool_name


_MCP_TIMEOUT_MESSAGE = "MCP tool call exceeded its configured deadline."


async def _suppress_after_cancel(task: asyncio.Task) -> None:
    """Await a cancelled MCP tool task, discarding any error from cancel propagation."""
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001 - cleanup only
        return


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
            started_at = perf_counter()
            try:
                tools = await self._client.get_tools()
                self._tools = {tool.name: tool for tool in tools}
            except Exception as exc:
                log_event(
                    phase="mcp_initialization",
                    outcome="failed",
                    duration_ms=(perf_counter() - started_at) * 1000,
                    error=exc,
                )
                raise
            log_event(
                phase="mcp_initialization",
                outcome="succeeded",
                duration_ms=(perf_counter() - started_at) * 1000,
                tool_count=len(self._tools),
            )
        return self._tools

    async def _invoke_tool(
        self, *, tool: Any, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], float]:
        started_at = perf_counter()
        timeout_seconds = float(self.settings.mcp_tool_timeout_seconds)
        tool_task = asyncio.ensure_future(tool.ainvoke(arguments))
        try:
            _done, pending = await asyncio.wait(
                {tool_task}, timeout=timeout_seconds
            )
        except BaseException:
            tool_task.cancel()
            raise
        if pending:
            # The caller deadline expired before the tool finished. Cancel the
            # tool task and report the bounded deadline to the runner.
            tool_task.cancel()
            _ = await _suppress_after_cancel(tool_task)
            log_event(
                phase="mcp_tool_call",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                tool_name=tool_name,
                error_type="MCPToolTimeout",
                error_message=_MCP_TIMEOUT_MESSAGE,
                timeout_seconds=timeout_seconds,
            )
            raise MCPToolTimeout(tool_name) from None
        # Tool task finished in time. Surface its result or exception as-is so
        # a tool-raised TimeoutError is not misclassified as a caller deadline.
        try:
            raw = tool_task.result()
        except Exception as exc:
            log_event(
                phase="mcp_tool_call",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                tool_name=tool_name,
                error=exc,
            )
            raise
        payload = _decode_envelope(raw)
        return payload, (perf_counter() - started_at) * 1000

    @staticmethod
    def _result_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        truncated = isinstance(data, dict) and data.get("truncated") is True
        original_chars = data.get("original_chars") if truncated else len(serialized)
        return {
            "result_chars": original_chars,
            "result_truncated": truncated,
            "truncated_preview_chars": len(data.get("preview", "")) if truncated else None,
        }

    def _log_tool_result(
        self, *, tool_name: str, payload: dict[str, Any], duration_ms: float
    ) -> None:
        metadata = self._result_metadata(payload)
        if not payload.get("ok"):
            metadata.update(
                error_type="MCPToolFailure",
                error_message="MCP tool returned a failed envelope.",
            )
        log_event(
            phase="mcp_tool_call",
            outcome="succeeded" if payload.get("ok") else "failed",
            duration_ms=duration_ms,
            tool_name=tool_name,
            **metadata,
        )

    async def verify_target(self, *, client_id: str, org_id: str | None) -> dict[str, Any]:
        tools = await self._load_tools()
        tool = tools.get("list_clients")
        if tool is None:
            raise MCPPolicyError("MCP không cung cấp tool list_clients")
        payload, duration_ms = await self._invoke_tool(
            tool=tool,
            tool_name="list_clients",
            arguments={"search": f"^{client_id}$", "limit": 5, "org_id": org_id or ""},
        )
        self._log_tool_result(
            tool_name="list_clients", payload=payload, duration_ms=duration_ms
        )
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
        payload, duration_ms = await self._invoke_tool(
            tool=list_clients,
            tool_name="list_clients",
            arguments={"search": "", "limit": 1, "org_id": self.settings.velociraptor_org_id},
        )
        self._log_tool_result(
            tool_name="list_clients", payload=payload, duration_ms=duration_ms
        )
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

        payload, duration_ms = await self._invoke_tool(
            tool=tool, tool_name=tool_name, arguments=arguments
        )
        data = payload.get("data")
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        if len(serialized) > self.settings.max_tool_result_chars:
            payload["data"] = {
                "truncated": True,
                "original_chars": len(serialized),
                "preview": serialized[: self.settings.max_tool_result_chars],
            }
        self._log_tool_result(
            tool_name=tool_name, payload=payload, duration_ms=duration_ms
        )
        return payload
