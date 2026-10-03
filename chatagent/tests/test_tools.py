"""Tests cho backend client + tool registry (Task 14 — spec F2/F8/F9/R6).

Phạm vi:
- `BackendClient` gửi đúng mức uỷ quyền (service token luôn; capability cho
  inventory/intent; KHÔNG capability cho outcome/reconcile; completion token cho
  finalization).
- Mọi lời gọi tool Velociraptor ghi intent TRƯỚC khi chạy và outcome SAU khi xong.
- Không có tham số do model cung cấp cho collection (code sở hữu argument).
- Kiểm tra schema bridge lúc khởi động — thiếu/khác → fail closed.
- Resolver hostname → client_id fail closed (ambiguity / 0 match / phân trang hỏng).
- Trần số collection enforce.
"""
from __future__ import annotations

import uuid

import httpx
import pytest

from chatagent.backend_client import BackendClient, BackendError
from chatagent.config import Settings
from chatagent.tools import (
    BridgeToolSpec,
    CollectionDeniedError,
    ToolCallContext,
    ToolRegistryError,
    build_tools,
    resolve_client_id,
)

# Tập tool bridge tối thiểu mà manifest yêu cầu (startup check).
ALL_BRIDGE_NAMES = {
    "list_clients",
    "get_client_metadata",
    "list_flows",
    "get_flow_results",
    "run_vql",
    "search_clients",
    "windows_pslist",
    "windows_netstat_enriched",
    "windows_event_logs",
    "windows_execution_prefetch",
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def _settings(**overrides) -> Settings:
    base = {
        "service_token": "svc-token",
        "backend_url": "http://backend.internal:8000",
    }
    base.update(overrides)
    return Settings(**base)


def _client_with_transport(settings: Settings, handler) -> BackendClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url=settings.backend_url, transport=transport)
    return BackendClient(settings, client=http)


class RecordingBridge:
    """Bridge MCP giả — ghi lại thứ tự gọi để kiểm chứng audit ordering."""

    def __init__(self, *, names=None, events=None, responses=None, additional_properties=True):
        self._names = set(names) if names is not None else set(ALL_BRIDGE_NAMES)
        self.events = events if events is not None else []
        self._responses = responses or {}
        self._additional = additional_properties

    async def list_tools(self) -> dict[str, BridgeToolSpec]:
        return {
            name: BridgeToolSpec(
                name=name,
                input_schema={"properties": {}, "additionalProperties": self._additional},
            )
            for name in self._names
        }

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.events.append(("bridge", name, dict(arguments)))
        if name in self._responses:
            return self._responses[name]
        if name == "search_clients":
            # Mặc định: echo hostname request → đúng 1 client_id (để test collection
            # tập trung vào audit/trần, không phải resolver).
            hostname = arguments.get("hostname")
            return {
                "ok": True,
                "items": [{"client_id": "C.autoresolved", "os_info": {"hostname": hostname}}],
                "total": 1,
            }
        return {"ok": True, "rows": [], "row_count": 0}


class RecordingBackend:
    """Backend giả — ghi lại thứ tự intent/outcome và trả kết quả cấu hình."""

    def __init__(self, *, events=None, executed=True, inventory_rows=None):
        self.events = events if events is not None else []
        self.executed = executed
        self.inventory_rows = inventory_rows or []

    async def audit_intent(self, **kwargs) -> dict:
        self.events.append(("intent", kwargs["tool_call_id"]))
        return {"intent_id": uuid.uuid4(), "audit_id": 1, "executed": self.executed}

    async def audit_outcome(self, **kwargs) -> dict:
        self.events.append(("outcome", kwargs["tool_call_id"], kwargs.get("outcome")))
        return {"outcome": kwargs["outcome"], "audit_id": 2, "idempotent": False}

    async def audit_reconcile(self, **kwargs) -> dict:
        return {"outcome": "unknown", "reconciled": True}

    async def inventory_query(self, **kwargs) -> dict:
        self.events.append(("inventory_query", kwargs["tool"]))
        return {
            "tool": kwargs["tool"],
            "ok": True,
            "rows": self.inventory_rows,
            "row_count": len(self.inventory_rows),
            "truncated": False,
            "byte_count": 10,
            "sql_digest": "d" * 64,
        }

    async def inventory_sql(self, **kwargs) -> dict:
        self.events.append(("inventory_sql", "inventory_sql"))
        return {
            "tool": "inventory_sql",
            "ok": True,
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "byte_count": 0,
            "sql_digest": "e" * 64,
        }


def _ctx(tool_call_id: str = "tc-1") -> ToolCallContext:
    return ToolCallContext(
        capability="cap.jwt",
        turn_id=uuid.uuid4(),
        tool_call_id=tool_call_id,
    )


# ── BackendClient: uỷ quyền + endpoint ────────────────────────────────────────


async def test_service_token_on_every_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    client = _client_with_transport(_settings(), handler)
    await client.audit_outcome(turn_id=uuid.uuid4(), tool_call_id="tc", outcome="ok")
    await client.audit_reconcile(turn_id=uuid.uuid4(), tool_call_id="tc")
    assert len(seen) == 2
    for request in seen:
        assert request.headers["X-Service-Token"] == "svc-token"
        # outcome/reconcile KHÔNG mang capability (R2).
        assert "X-Chat-Context" not in request.headers


async def test_inventory_query_carries_capability_and_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"tool": "inventory_search", "ok": True, "rows": []})

    client = _client_with_transport(_settings(), handler)
    await client.inventory_query(capability="cap.jwt", tool="inventory_search", params={"q": "x"})
    assert seen[0].url.path == "/api/internal/chat/inventory/query"
    assert seen[0].headers["X-Chat-Context"] == "cap.jwt"
    assert seen[0].headers["X-Service-Token"] == "svc-token"


async def test_inventory_sql_carries_capability() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"tool": "inventory_sql", "ok": True, "rows": []})

    client = _client_with_transport(_settings(), handler)
    await client.inventory_sql(capability="cap.jwt", sql="SELECT 1")
    assert seen[0].url.path == "/api/internal/chat/inventory/sql"
    assert seen[0].headers["X-Chat-Context"] == "cap.jwt"


async def test_audit_intent_carries_capability() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"intent_id": str(uuid.uuid4()), "audit_id": 1, "executed": True}
        )

    client = _client_with_transport(_settings(), handler)
    await client.audit_intent(
        capability="cap.jwt", tool_call_id="tc", tool="windows_pslist", args_digest="a" * 64
    )
    assert seen[0].url.path == "/api/internal/chat/audit/intent"
    assert seen[0].headers["X-Chat-Context"] == "cap.jwt"


async def test_complete_carries_completion_token_not_capability() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok", "message_id": str(uuid.uuid4())})

    client = _client_with_transport(_settings(), handler)
    turn_id = uuid.uuid4()
    await client.complete(
        turn_id=turn_id,
        completion_token="completion-secret",
        content="hi",
        finish_reason="stop",
    )
    assert seen[0].url.path == f"/api/internal/chat/turns/{turn_id}/complete"
    assert seen[0].headers["X-Chat-Completion"] == "completion-secret"
    assert seen[0].headers["X-Service-Token"] == "svc-token"
    assert "X-Chat-Context" not in seen[0].headers


async def test_backend_error_extracts_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"detail": "[chat_conflict_active_turn] đang có turn [HTTP 409]"}
        )

    client = _client_with_transport(_settings(), handler)
    with pytest.raises(BackendError) as exc:
        await client.inventory_query(capability="c", tool="inventory_search", params={})
    assert exc.value.status_code == 409
    assert exc.value.category == "chat_conflict_active_turn"


# ── Audit ordering: intent → bridge → outcome ────────────────────────────────


async def test_collection_writes_intent_before_and_outcome_after() -> None:
    events: list = []
    bridge = RecordingBridge(
        events=events,
        responses={"windows_pslist": {"ok": True, "rows": [1, 2], "row_count": 2}},
    )
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())

    await registry.run(_ctx("tc-1"), "windows_pslist", {"hostname": "WS-01"})

    kinds = [e[0] for e in events]
    # Resolver SearchClients chạy trước (không audit); intent → pslist bridge → outcome.
    resolver_idx = next(i for i, e in enumerate(events) if e[0] == "bridge" and e[1] == "search_clients")
    intent_idx = kinds.index("intent")
    pslist_idx = next(i for i, e in enumerate(events) if e[0] == "bridge" and e[1] == "windows_pslist")
    outcome_idx = kinds.index("outcome")
    assert resolver_idx < intent_idx < pslist_idx < outcome_idx
    assert kinds[-1] == "outcome"


async def test_outcome_written_even_when_bridge_raises() -> None:
    events: list = []

    class BoomBridge(RecordingBridge):
        async def call_tool(self, name, arguments):
            self.events.append(("bridge", name, dict(arguments)))
            if name == "windows_pslist":
                raise RuntimeError("mcp down")
            return await super().call_tool(name, arguments)

    bridge = BoomBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())

    with pytest.raises(RuntimeError):
        await registry.run(_ctx("tc-2"), "windows_pslist", {"hostname": "WS-01"})

    kinds = [e[0] for e in events]
    assert "intent" in kinds
    assert kinds[-1] == "outcome"
    # intent trước bridge (pslist), outcome sau và ghi nhận lỗi.
    intent_idx = kinds.index("intent")
    pslist_idx = next(
        i for i, e in enumerate(events) if e[0] == "bridge" and e[1] == "windows_pslist"
    )
    assert intent_idx < pslist_idx < kinds.index("outcome")
    assert events[-1][2] == "error"


async def test_duplicate_intent_does_not_re_execute() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events, executed=False)  # trùng identity → không chạy lại
    registry = await build_tools(bridge, backend, _settings())

    result = await registry.run(_ctx("tc-dup"), "windows_pslist", {"hostname": "WS-01"})
    assert result.skipped is True
    # KHÔNG có bridge call cho chính tool này (chỉ resolver SearchClients được phép).
    assert not any(e[0] == "bridge" and e[1] == "windows_pslist" for e in events)


async def test_collection_arguments_are_code_owned_not_model_supplied() -> None:
    events: list = []
    captured: dict = {}

    class CaptureBridge(RecordingBridge):
        async def call_tool(self, name, arguments):
            if name != "search_clients":
                captured.update(arguments)
            return await super().call_tool(name, arguments)

    bridge = CaptureBridge(events=events)
    backend = RecordingBackend(events=events)
    settings = _settings(collection_max_time_range_hours=24, collection_max_rows=5000)
    registry = await build_tools(bridge, backend, settings)

    await registry.run(
        _ctx("tc-3"),
        "windows_pslist",
        {
            "hostname": "WS-01",
            "artifact": "Hack.Artifact",
            "fields": ["secret"],
            "params": {"evil": True},
            "limit": 999_999,
            "time_range_hours": 12,
        },
    )
    assert "artifact" not in captured
    assert "fields" not in captured
    assert "params" not in captured
    # `limit` do CODE đặt (không lấy từ model); time range hợp lệ được giữ trong trần.
    assert captured["limit"] == settings.collection_max_rows
    assert captured["time_range_hours"] == 12


async def test_inventory_tool_routes_to_backend_not_bridge() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events, inventory_rows=[{"hostname": "WS-01"}])
    registry = await build_tools(bridge, backend, _settings())

    result = await registry.run(_ctx("tc-4"), "inventory_search", {"q": "WS"})
    assert result.ok is True
    assert result.rows == [{"hostname": "WS-01"}]
    assert any(e[0] == "inventory_query" for e in events)
    assert all(e[0] != "bridge" for e in events)


async def test_inventory_sql_routes_to_backend() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())

    await registry.run(_ctx("tc-5"), "inventory_sql", {"sql": "SELECT 1"})
    assert any(e[0] == "inventory_sql" for e in events)


async def test_unknown_tool_rejected() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())
    with pytest.raises(ToolRegistryError):
        await registry.run(_ctx(), "rm_rf", {})


async def test_search_clients_is_not_agent_runnable() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())
    with pytest.raises(ToolRegistryError):
        await registry.run(_ctx(), "search_clients", {"hostname": "WS-01"})


async def test_run_vql_validates_before_executing() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())

    with pytest.raises(Exception) as exc:
        await registry.run(
            _ctx("tc-vql"), "run_vql", {"query": "SELECT collect_client() FROM scope()"}
        )
    assert "chat_guardrail_vql" in str(exc.value)
    assert all(e[0] != "bridge" for e in events)


async def test_run_vql_accepts_safe_query() -> None:
    events: list = []
    bridge = RecordingBridge(
        events=events, responses={"run_vql": {"ok": True, "rows": []}}
    )
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())
    result = await registry.run(_ctx("tc-vql2"), "run_vql", {"query": "SELECT * FROM clients()"})
    assert result.ok is True
    assert any(e[0] == "bridge" for e in events)


# ── Startup schema check ─────────────────────────────────────────────────────


async def test_build_tools_fails_when_bridge_missing_tool() -> None:
    bridge = RecordingBridge(names={"windows_pslist"})  # thiếu nhiều tool bắt buộc
    backend = RecordingBackend()
    with pytest.raises(ToolRegistryError) as exc:
        await build_tools(bridge, backend, _settings())
    assert "thiếu" in str(exc.value)


async def test_build_tools_fails_on_argument_schema_mismatch() -> None:
    class StrictBridge(RecordingBridge):
        async def list_tools(self):
            specs = {}
            for name in await super().list_tools():
                # Chỉ chấp nhận "wrong_arg"; code-owned args không khớp.
                specs[name] = BridgeToolSpec(
                    name=name,
                    input_schema={"properties": {"wrong_arg": {}}, "additionalProperties": False},
                )
            return specs

    bridge = StrictBridge()
    backend = RecordingBackend()
    with pytest.raises(ToolRegistryError) as exc:
        await build_tools(bridge, backend, _settings())
    assert "schema bridge không khớp" in str(exc.value)


# ── Resolver fail-closed ─────────────────────────────────────────────────────


def _search_response(items, total):
    return {"ok": True, "items": items, "total": total}


async def test_resolve_unique_client() -> None:
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={
            "search_clients": _search_response(
                [{"client_id": "C.1", "os_info": {"hostname": "ws-01"}}], 1
            )
        },
    )
    assert await resolve_client_id(bridge, "WS-01", settings=_settings()) == "C.1"


async def test_resolve_ambiguity_fails_closed() -> None:
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={
            "search_clients": _search_response(
                [
                    {"client_id": "C.1", "os_info": {"hostname": "ws-01"}},
                    {"client_id": "C.2", "os_info": {"hostname": "ws-01"}},
                ],
                2,
            )
        },
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())


async def test_resolve_zero_match_fails_closed() -> None:
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={"search_clients": _search_response([], 0)},
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "NOPE-01", settings=_settings())


async def test_resolve_missing_total_fails_closed() -> None:
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={"search_clients": {"ok": True, "items": [], "total": None}},
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())


async def test_resolve_total_drift_fails_closed() -> None:
    calls = {"n": 0}

    class DriftBridge(RecordingBridge):
        async def call_tool(self, name, arguments):
            calls["n"] += 1
            if calls["n"] == 1:
                return _search_response(
                    [{"client_id": "C.1", "os_info": {"hostname": "ws-01"}}], 2
                )
            return _search_response(
                [{"client_id": "C.2", "os_info": {"hostname": "ws-01"}}], 3
            )

    bridge = DriftBridge(names={"search_clients"})
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())


async def test_resolve_incomplete_pagination_fails_closed() -> None:
    """Page đầu trả total=2 nhưng item rỗng (chưa đủ) → fail closed, không tự chọn."""
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={"search_clients": _search_response([], 2)},
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())


async def test_resolve_malformed_record_fails_closed() -> None:
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={
            "search_clients": _search_response(
                [{"client_id": "C.1", "os_info": "not-a-dict"}], 1
            )
        },
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())


# ── Trần số (rate limits) ────────────────────────────────────────────────────


async def test_time_range_over_maximum_rejected() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings(collection_max_time_range_hours=24))
    with pytest.raises(CollectionDeniedError):
        await registry.run(_ctx(), "windows_pslist", {"hostname": "WS-01", "time_range_hours": 25})


async def test_row_cap_truncates() -> None:
    events: list = []
    bridge = RecordingBridge(
        events=events,
        responses={"windows_pslist": {"ok": True, "rows": list(range(10)), "row_count": 10}},
    )
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings(collection_max_rows=5))
    result = await registry.run(_ctx("tc-cap"), "windows_pslist", {"hostname": "WS-01"})
    assert result.truncated is True
    assert result.row_count == 5


async def test_per_hour_limit_enforced_per_client() -> None:
    events: list = []
    bridge = RecordingBridge(events=events)
    backend = RecordingBackend(events=events)
    settings = _settings(collection_per_machine_per_hour=2, collection_max_outstanding_per_client=5)
    registry = await build_tools(bridge, backend, settings)

    for _ in range(2):
        await registry.run(_ctx(str(uuid.uuid4())), "windows_pslist", {"hostname": "WS-01"})
    with pytest.raises(CollectionDeniedError):
        await registry.run(_ctx(str(uuid.uuid4())), "windows_pslist", {"hostname": "WS-01"})


async def test_outstanding_limit_per_client() -> None:
    bridge = RecordingBridge()
    backend = RecordingBackend()
    settings = _settings(
        collection_max_outstanding_per_client=1, collection_per_machine_per_hour=100
    )
    registry = await build_tools(bridge, backend, settings)

    registry.rate_limiter.try_acquire("C.1")
    with pytest.raises(CollectionDeniedError):
        registry.rate_limiter.try_acquire("C.1")
    registry.rate_limiter.try_acquire("C.2")  # client khác vẫn OK


# ── Final-fix regressions: cancellation/timeout outcome + resolver overrun ────


async def test_cancelled_bridge_call_audits_canceled_not_ok() -> None:
    """Finding 5: hủy giữa lời gọi ghi outcome `canceled`, KHÔNG phải `ok`."""
    import asyncio

    events: list = []

    class CancelBridge(RecordingBridge):
        async def call_tool(self, name, arguments):
            self.events.append(("bridge", name, dict(arguments)))
            if name == "windows_pslist":
                raise asyncio.CancelledError()
            return await super().call_tool(name, arguments)

    bridge = CancelBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(bridge, backend, _settings())

    with pytest.raises(asyncio.CancelledError):
        await registry.run(_ctx("tc-cancel"), "windows_pslist", {"hostname": "WS-01"})

    outcomes = [e for e in events if e[0] == "outcome"]
    assert outcomes, "phải ghi outcome"
    assert outcomes[-1][2] == "canceled"


async def test_collection_flow_deadline_audits_unknown_and_holds_slot() -> None:
    """Finding 6: vượt deadline flow → outcome `unknown` + giữ slot per-machine."""
    import asyncio

    from chatagent.tools import CollectionFlowTimeoutError

    events: list = []

    class SlowBridge(RecordingBridge):
        async def call_tool(self, name, arguments):
            self.events.append(("bridge", name, dict(arguments)))
            if name == "windows_pslist":
                await asyncio.sleep(5)
            return await super().call_tool(name, arguments)

    bridge = SlowBridge(events=events)
    backend = RecordingBackend(events=events)
    registry = await build_tools(
        bridge, backend, _settings(collection_flow_deadline_seconds=1)
    )

    with pytest.raises(CollectionFlowTimeoutError):
        await registry.run(_ctx("tc-timeout"), "windows_pslist", {"hostname": "WS-01"})

    outcomes = [e for e in events if e[0] == "outcome"]
    assert outcomes and outcomes[-1][2] == "unknown"
    # Slot per-machine KHÔNG được giải phóng (flow chưa verified terminal).
    with pytest.raises(CollectionDeniedError):
        registry.rate_limiter.try_acquire("C.autoresolved")


async def test_resolve_total_overrun_fails_closed() -> None:
    """Finding 8: offset + len(items) > total → fail closed (không tự chọn)."""
    bridge = RecordingBridge(
        names={"search_clients"},
        responses={
            "search_clients": _search_response(
                [
                    {"client_id": "C.1", "os_info": {"hostname": "ws-01"}},
                    {"client_id": "C.2", "os_info": {"hostname": "ws-01"}},
                ],
                1,
            )
        },
    )
    with pytest.raises(CollectionDeniedError):
        await resolve_client_id(bridge, "WS-01", settings=_settings())
