"""Tests cho ReAct loop + SSE + lifecycle endpoints (Task 15 — spec F8/F10/V3-6).

Phạm vi:
- `POST /v1/chat` trả `text/event-stream` với thứ tự event `start → tool_start →
  tool_result → token → usage → done`.
- Loop bounded theo `limits.max_tool_calls`.
- Output tool bọc `<untrusted_tool_output tool="…">` trước khi đưa vào model.
- Cancel hủy loop; `.complete` LUÔN được gọi ở mọi nhánh terminal (kể cả error).
- Egress `llm_runtime.base_url` fail-closed khi `allow_cloud=false`.
- `GET /v1/chat/{turn_id}/status` + `POST /v1/chat/{turn_id}/cancel`.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from chatagent.agent import (
    AgentRequest,
    CancelRegistry,
    ChatAgent,
    Limits,
    LlmRuntime,
    Message,
    PlannedToolCall,
    StubPlanner,
    _hint_for,
)
from chatagent.api import app, get_agent, get_cancel_registry
from chatagent.config import Settings, get_settings
from chatagent.planner import LlmError
from chatagent.tools import ToolResult

# ── Helpers ──────────────────────────────────────────────────────────────────


def _settings(**overrides) -> Settings:
    base = {"service_token": "svc-token", "backend_url": "http://backend.internal:8000"}
    base.update(overrides)
    return Settings(**base)


def _request(**overrides) -> AgentRequest:
    base = {
        "conversation_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "messages": [Message(role="user", content="liệt kê phần mềm")],
        "chat_context": "cap-jwt",
        "llm_runtime": LlmRuntime(base_url="http://127.0.0.1:11434/v1", model="stub"),
        "completion_token": "completion-token",
    }
    base.update(overrides)
    return AgentRequest(**base)


def _parse_event(chunk: str) -> dict:
    data_line = next(ln for ln in chunk.splitlines() if ln.startswith("data: "))
    return json.loads(data_line[len("data: ") :])


async def _collect(agent: ChatAgent, request: AgentRequest) -> list[dict]:
    events: list[dict] = []
    async for chunk in agent.stream(request):
        events.append(_parse_event(chunk))
    return events


class FakeRegistry:
    """Registry giả — trả ToolResult cấu hình, ghi lại call, hỗ trợ raise."""

    def __init__(self, *, result: ToolResult | None = None, error: Exception | None = None):
        self.result = result or ToolResult(tool="inventory_search", ok=True, rows=[{"a": 1}])
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def run(self, ctx, tool: str, params: dict) -> ToolResult:
        self.calls.append((tool, dict(params)))
        if self.error is not None:
            raise self.error
        return self.result


class FakeBackend:
    """Backend giả — ghi lại các lần `complete` (durable completion)."""

    def __init__(self, *, message_id: str | None = None):
        self.message_id = message_id or str(uuid.uuid4())
        self.completions: list[dict] = []

    async def complete(self, **kwargs) -> dict:
        self.completions.append(kwargs)
        return {"status": "ok", "message_id": self.message_id}


class AlwaysPlanner:
    """Luôn trả về một tool call — dùng để kiểm tra trần `max_tool_calls`."""

    def __init__(self, tool: str = "inventory_search"):
        self.tool = tool
        self.observations: list[str] = []

    async def plan(self, *, messages, observations, machine_context) -> PlannedToolCall | None:
        self.observations = list(observations)
        return PlannedToolCall(tool=self.tool, params={"query": "x"})

    async def compose(self, *, messages, observations) -> str:
        return "xong"


class RecordingPlanner:
    """Trả 1 tool call rồi dừng — bắt lại observation đã bọc."""

    def __init__(self, tool: str = "inventory_search"):
        self.tool = tool
        self.seen_observations: list[str] = []
        self.calls = 0

    async def plan(self, *, messages, observations, machine_context) -> PlannedToolCall | None:
        self.seen_observations = list(observations)
        self.calls += 1
        if self.calls == 1:
            return PlannedToolCall(tool=self.tool, params={"query": "x"})
        return None

    async def compose(self, *, messages, observations) -> str:
        self.seen_observations = list(observations)
        return "kết quả"


# ── ChatAgent loop ───────────────────────────────────────────────────────────


async def test_stream_event_order_start_to_done() -> None:
    registry = FakeRegistry()
    backend = FakeBackend()
    agent = ChatAgent(
        registry=registry, backend=backend, settings=_settings(), cancel_registry=CancelRegistry()
    )
    events = await _collect(agent, _request())

    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "tool_start" in types
    assert types.index("tool_start") < types.index("tool_result")
    assert types.index("tool_result") < types.index("usage")
    assert types.index("usage") < types.index("done")
    assert all(e["v"] == "chat.sse/1" for e in events)
    # seq đơn điệu
    assert [e["seq"] for e in events] == list(range(len(events)))
    # complete được gọi đúng 1 lần, finish_reason=stop
    assert len(backend.completions) == 1
    assert backend.completions[0]["finish_reason"] == "stop"


async def test_tool_output_is_wrapped_untrusted() -> None:
    planner = RecordingPlanner()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner=planner,
        cancel_registry=CancelRegistry(),
    )
    await _collect(agent, _request())
    assert planner.seen_observations, "planner phải nhận observation"
    wrapped = planner.seen_observations[0]
    assert wrapped.startswith('<untrusted_tool_output tool="inventory_search">')
    assert wrapped.endswith("</untrusted_tool_output>")


async def test_loop_is_bounded_by_max_tool_calls() -> None:
    registry = FakeRegistry()
    agent = ChatAgent(
        registry=registry,
        backend=FakeBackend(),
        settings=_settings(max_tool_calls=3),
        planner=AlwaysPlanner(),
        cancel_registry=CancelRegistry(),
    )
    request = _request(limits=Limits(max_tool_calls=3))
    events = await _collect(agent, request)
    assert len(registry.calls) == 3
    assert sum(1 for e in events if e["type"] == "tool_start") == 3
    assert events[-1]["type"] == "done"


async def test_complete_called_on_tool_error() -> None:
    from chatagent.tools import CollectionDeniedError

    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(error=CollectionDeniedError("nope")),
        backend=backend,
        settings=_settings(),
        planner=AlwaysPlanner(),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    types = [e["type"] for e in events]
    assert "error" in types
    err = next(e for e in events if e["type"] == "error")
    assert err["category"] == "chat_collection_denied"
    assert len(backend.completions) == 1
    assert backend.completions[0]["finish_reason"] == "error"
    assert backend.completions[0]["error_category"] == "chat_collection_denied"


async def test_cancel_aborts_loop_and_completes_canceled() -> None:
    registry = CancelRegistry()
    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=backend,
        settings=_settings(),
        planner=AlwaysPlanner(),
        cancel_registry=registry,
    )
    request = _request()
    turn_id = str(request.turn_id)

    events: list[dict] = []
    async for chunk in agent.stream(request):
        event = _parse_event(chunk)
        events.append(event)
        if event["type"] == "tool_start":
            assert registry.cancel(turn_id) is True
    types = [e["type"] for e in events]
    # Loop dừng: không chạy hết các tool call của AlwaysPlanner
    assert sum(1 for e in events if e["type"] == "tool_start") == 1
    assert "error" in types
    assert next(e for e in events if e["type"] == "error")["category"] == "chat_canceled"
    assert len(backend.completions) == 1
    assert backend.completions[0]["finish_reason"] == "canceled"


async def test_public_llm_rejected_when_cloud_disabled() -> None:
    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=backend,
        settings=_settings(),
        planner=StubPlanner(),
        cancel_registry=CancelRegistry(),
    )
    request = _request(
        llm_runtime=LlmRuntime(base_url="https://api.example.com/v1", model="m", allow_cloud=False)
    )
    events = await _collect(agent, request)
    err = next(e for e in events if e["type"] == "error")
    assert err["category"] == "chat_upstream_llm"
    assert backend.completions[0]["finish_reason"] == "error"
    assert backend.completions[0]["error_category"] == "chat_upstream_llm"


async def test_allow_cloud_true_permits_public_endpoint() -> None:
    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=backend,
        settings=_settings(),
        planner=StubPlanner(),
        cancel_registry=CancelRegistry(),
    )
    request = _request(
        llm_runtime=LlmRuntime(base_url="https://api.example.com/v1", model="m", allow_cloud=True)
    )
    events = await _collect(agent, request)
    assert not any(e["type"] == "error" for e in events)
    assert backend.completions[0]["finish_reason"] == "stop"


async def test_wall_clock_exceeded_errors_and_completes() -> None:
    """Vượt trần wall_clock_seconds → error `chat_timeout_tool`, vẫn complete."""
    import chatagent.agent as agent_mod

    clock = {"t": 1000.0}
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(agent_mod.time, "monotonic", lambda: clock["t"])
    try:

        class AdvancingPlanner:
            async def plan(self, *, messages, observations, machine_context):
                clock["t"] += 100.0  # mỗi bước vượt xa wall_clock=10
                return PlannedToolCall(tool="inventory_search", params={"query": "x"})

            async def compose(self, *, messages, observations):
                return "x"

        backend = FakeBackend()
        agent = ChatAgent(
            registry=FakeRegistry(),
            backend=backend,
            settings=_settings(wall_clock_seconds=10),
            planner=AdvancingPlanner(),
            cancel_registry=CancelRegistry(),
        )
        events = await _collect(agent, _request())
        err = next(e for e in events if e["type"] == "error")
        assert err["category"] == "chat_timeout_tool"
        assert backend.completions[0]["finish_reason"] == "error"
    finally:
        monkeypatch.undo()


async def test_evidence_truncated_to_max_evidence_chars() -> None:
    """Observation bị cắt theo `chat_evidence_chars` (F11)."""
    huge = ToolResult(
        tool="inventory_search", ok=True, rows=[{"blob": "x" * 50_000}], row_count=1
    )
    planner = RecordingPlanner()
    agent = ChatAgent(
        registry=FakeRegistry(result=huge),
        backend=FakeBackend(),
        settings=_settings(),
        planner=planner,
        cancel_registry=CancelRegistry(),
    )
    request = _request(limits=Limits(max_evidence_chars=1000))
    await _collect(agent, request)
    assert planner.seen_observations
    assert len(planner.seen_observations[0]) <= 1000
    assert planner.seen_observations[0].startswith("<untrusted_tool_output")
    assert planner.seen_observations[0].endswith("</untrusted_tool_output>")


async def test_status_and_cancel_registry_lifecycle() -> None:
    registry = CancelRegistry()
    turn_id = str(uuid.uuid4())
    registry.register(turn_id)
    status = registry.status(turn_id)
    assert status["status"] == "running"
    assert status["alive_at"] is not None
    assert registry.cancel(turn_id) is True
    # cancel lần 2 không còn running
    assert registry.cancel(turn_id) is False
    assert registry.status(turn_id)["status"] == "canceled"


async def test_status_unknown_turn() -> None:
    registry = CancelRegistry()
    assert registry.status(str(uuid.uuid4())) == {"status": "unknown", "alive_at": None}


# ── HTTP surface ─────────────────────────────────────────────────────────────


_SPY: dict = {}


def _install_agent(*, planner=None) -> None:
    registry = CancelRegistry()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner=planner or StubPlanner(),
        cancel_registry=registry,
    )
    _SPY["agent"] = agent
    _SPY["registry"] = registry
    app.dependency_overrides[get_agent] = lambda: agent
    app.dependency_overrides[get_cancel_registry] = lambda: registry
    app.dependency_overrides[get_settings] = lambda: _settings()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_post_chat_requires_service_token() -> None:
    client = TestClient(app)
    response = client.post("/v1/chat", json=_request().model_dump(mode="json"))
    assert response.status_code == 401
    assert response.json()["detail"].startswith("[chat_authz]")


def test_post_chat_streams_sse() -> None:
    _install_agent()
    client = TestClient(app)
    body = _request().model_dump(mode="json")
    with client.stream(
        "POST", "/v1/chat", json=body, headers={"X-Service-Token": "svc-token"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    assert "event: start" in text
    assert "event: done" in text
    assert '"v": "chat.sse/1"' in text or '"v":"chat.sse/1"' in text


def test_status_endpoint() -> None:
    _install_agent()
    client = TestClient(app)
    turn_id = str(uuid.uuid4())
    _SPY["registry"].register(turn_id)
    response = client.get(
        f"/v1/chat/{turn_id}/status", headers={"X-Service-Token": "svc-token"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_cancel_endpoint_acks() -> None:
    _install_agent()
    client = TestClient(app)
    turn_id = str(uuid.uuid4())
    _SPY["registry"].register(turn_id)
    response = client.post(
        f"/v1/chat/{turn_id}/cancel", headers={"X-Service-Token": "svc-token"}
    )
    assert response.status_code == 200
    assert response.json()["ack"] is True
    assert _SPY["registry"].status(turn_id)["status"] == "canceled"


def test_lifecycle_endpoints_require_service_token() -> None:
    _install_agent()
    client = TestClient(app)
    assert client.get(f"/v1/chat/{uuid.uuid4()}/status").status_code == 401
    assert client.post(f"/v1/chat/{uuid.uuid4()}/cancel").status_code == 401


# ── LLM planner integration ──────────────────────────────────────────────────


async def test_planner_factory_receives_llm_runtime() -> None:
    """Agent dựng planner theo `llm_runtime` của từng turn qua factory."""
    seen: dict = {}

    class FactoryPlanner:
        async def plan(self, *, messages, observations, machine_context):
            return None

        async def compose(self, *, messages, observations):
            return "ok"

    def factory(runtime, sql_schema=None):
        seen["model"] = runtime.model
        seen["sql_schema"] = sql_schema
        return FactoryPlanner()

    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner_factory=factory,
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request(sql_schema="public.machines(id uuid)"))
    assert seen["model"] == "stub"
    assert seen["sql_schema"] == "public.machines(id uuid)"
    assert any(e["type"] == "done" for e in events)


async def test_compose_stream_emits_one_token_event_per_chunk() -> None:
    """Có `compose_stream` → mỗi delta là một event `token` (streaming thật)."""

    class StreamingPlanner:
        async def plan(self, *, messages, observations, machine_context):
            return None

        async def compose_stream(self, *, messages, observations):
            for part in ["Xin ", "chào"]:
                yield part

        def usage(self):
            return {"input_tokens": 7, "output_tokens": 2}

    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner=StreamingPlanner(),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    assert [e["text"] for e in events if e["type"] == "token"] == ["Xin ", "chào"]
    usage = next(e for e in events if e["type"] == "usage")
    assert usage["input_tokens"] == 7
    assert usage["output_tokens"] == 2


async def test_llm_error_maps_to_upstream_category() -> None:
    """`LlmError` → SSE error `chat_upstream_llm` (không rơi vào chat_internal)."""

    class FailingPlanner:
        async def plan(self, *, messages, observations, machine_context):
            raise LlmError("LLM sập", retryable=True)

        async def compose(self, *, messages, observations):
            return "x"

    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=backend,
        settings=_settings(),
        planner=FailingPlanner(),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    err = next(e for e in events if e["type"] == "error")
    assert err["category"] == "chat_upstream_llm"
    assert backend.completions[0]["error_category"] == "chat_upstream_llm"


async def test_planner_closed_after_turn() -> None:
    closed = {"v": False}

    class ClosablePlanner:
        async def plan(self, *, messages, observations, machine_context):
            return None

        async def compose(self, *, messages, observations):
            return "ok"

        async def aclose(self):
            closed["v"] = True

    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner=ClosablePlanner(),
        cancel_registry=CancelRegistry(),
    )
    await _collect(agent, _request())
    assert closed["v"] is True


async def test_empty_answer_gets_fallback_token() -> None:
    """Model trả nội dung rỗng → phải có token dự phòng, không để turn trống."""

    class EmptyPlanner:
        async def plan(self, *, messages, observations, machine_context):
            return None

        async def compose(self, *, messages, observations):
            return ""

    agent = ChatAgent(
        registry=FakeRegistry(),
        backend=FakeBackend(),
        settings=_settings(),
        planner=EmptyPlanner(),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens.strip()


async def test_observation_carries_row_count() -> None:
    """Observation phải nêu `row_count` để model trích dẫn đúng số dòng."""
    result = ToolResult(tool="inventory_stats", ok=True, rows=[{"a": 1}, {"a": 2}], row_count=2)
    planner = RecordingPlanner()
    agent = ChatAgent(
        registry=FakeRegistry(result=result),
        backend=FakeBackend(),
        settings=_settings(),
        planner=planner,
        cancel_registry=CancelRegistry(),
    )
    await _collect(agent, _request())
    assert '"row_count": 2' in planner.seen_observations[0]


async def test_backend_error_hint_is_not_double_wrapped() -> None:
    """Regression: hint phải là detail thô, không bị bọc lại `[category] … [HTTP …]`."""
    from chatagent.backend_client import BackendError

    exc = BackendError(400, "chat_guardrail_sql", "[chat_guardrail_sql] thiếu hostname [HTTP 400]")
    assert exc.hint == "[chat_guardrail_sql] thiếu hostname [HTTP 400]"
    assert _hint_for(exc) == "[chat_guardrail_sql] thiếu hostname [HTTP 400]"


# ── Guardrail errors are recoverable (model can correct itself) ───────────────


def _guardrail_error() -> Exception:
    from chatagent.backend_client import BackendError

    return BackendError(
        400,
        "chat_guardrail_sql",
        "[chat_guardrail_sql] bảng ngoài manifest bị cấm: manifest [HTTP 400]",
    )


class _RecoverThenAnswer:
    """Gọi sai 1 lần (guardrail) → nhận lỗi → trả lời trung thực."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen: list[str] = []

    async def plan(self, *, messages, observations, machine_context):
        self.calls += 1
        self.seen = list(observations)
        if self.calls == 1:
            return PlannedToolCall(tool="inventory_sql", params={"sql": "SELECT * FROM manifest"})
        return None

    async def compose(self, *, messages, observations):
        return "Dữ liệu kiểm kê chưa hỗ trợ phân loại máy cá nhân."


async def test_guardrail_error_is_recovered_and_turn_completes() -> None:
    planner = _RecoverThenAnswer()
    backend = FakeBackend()
    agent = ChatAgent(
        registry=FakeRegistry(error=_guardrail_error()),
        backend=backend,
        settings=_settings(),
        planner=planner,
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    types = [e["type"] for e in events]
    assert "error" not in types
    assert types[-1] == "done"
    # tool_result mang ok=false + category để UI hiển thị chip lỗi, không chặn turn
    failed = [e for e in events if e["type"] == "tool_result" and e["ok"] is False]
    assert failed and failed[0]["error_category"] == "chat_guardrail_sql"
    # model nhận lại lỗi dưới dạng observation đã bọc
    assert planner.seen and "chat_guardrail_sql" in planner.seen[-1]
    assert "untrusted_tool_output" in planner.seen[-1]
    assert backend.completions[0]["finish_reason"] == "stop"


async def test_guardrail_error_terminal_after_retry_cap() -> None:
    agent = ChatAgent(
        registry=FakeRegistry(error=_guardrail_error()),
        backend=FakeBackend(),
        settings=_settings(),
        planner=AlwaysPlanner(tool="inventory_sql"),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[0]["category"] == "chat_guardrail_sql"
    # cap 2 lần thử lại → tổng 3 lần gọi tool rồi mới fail
    assert sum(1 for e in events if e["type"] == "tool_start") == 3


async def test_policy_error_stays_terminal() -> None:
    """Lỗi ngoài guardrail (vd collection denied) vẫn fail-closed, không retry."""
    from chatagent.tools import CollectionDeniedError

    agent = ChatAgent(
        registry=FakeRegistry(error=CollectionDeniedError("nope")),
        backend=FakeBackend(),
        settings=_settings(),
        planner=AlwaysPlanner(),
        cancel_registry=CancelRegistry(),
    )
    events = await _collect(agent, _request())
    assert sum(1 for e in events if e["type"] == "tool_start") == 1
    err = next(e for e in events if e["type"] == "error")
    assert err["category"] == "chat_collection_denied"
