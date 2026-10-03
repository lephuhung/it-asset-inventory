"""Tests cho `LlmPlanner` — planner gọi LLM thật (OpenAI-compatible) với function calling.

Không gọi mạng: dùng `httpx.MockTransport`.
"""
from __future__ import annotations

import json

import httpx
import pytest

from chatagent.agent import LlmRuntime, MachineContext, Message
from chatagent.planner import LlmError, LlmPlanner

# ── Helpers ──────────────────────────────────────────────────────────────────


def _runtime(**overrides) -> LlmRuntime:
    base = {
        "base_url": "http://llm.test/v1",
        "api_key": "",
        "model": "qwen-test",
        "temperature": 0.0,
        "timeout_seconds": 30,
        "max_tokens": 4096,
        "allow_cloud": True,
        "system_prompt": "PROMPT DEEPAGENT KHÔNG ĐƯỢC DÙNG",
    }
    base.update(overrides)
    return LlmRuntime(**base)


def _planner(handler, **overrides) -> LlmPlanner:
    client = httpx.AsyncClient(
        base_url="http://llm.test/v1", transport=httpx.MockTransport(handler)
    )
    return LlmPlanner(_runtime(**overrides), client=client, system_prompt="SYSTEM CHAT")


def _completion(message: dict, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": "tool_calls"}],
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
        },
    )


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


# ── plan() ───────────────────────────────────────────────────────────────────


def test_inventory_sql_schema_documents_manifest_views() -> None:
    from chatagent.planner import INVENTORY_TOOL_SCHEMAS

    desc = INVENTORY_TOOL_SCHEMAS["inventory_sql"]["description"]
    for name in (
        "chat_ro_views",
        "v_chat_machines",
        "v_chat_machine_detail",
        "v_chat_org_stats",
        "v_chat_software",
        "v_chat_hardware",
        "v_chat_alerts",
    ):
        assert name in desc


def test_tool_schemas_use_dynamic_sql_schema() -> None:
    from chatagent.planner import tool_schemas

    tools = tool_schemas(
        ["inventory_sql"], sql_schema="public.machines(id uuid, hostname varchar)"
    )
    desc = tools[0]["function"]["description"]
    assert "public.machines" in desc
    assert "hostname varchar" in desc


async def test_plan_returns_tool_call_and_sends_tools() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = _body(request)
        return _completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "inventory_stats",
                            "arguments": '{"limit": 5}',
                        },
                    }
                ],
            },
            usage={"prompt_tokens": 11, "completion_tokens": 3},
        )

    planner = _planner(handler)
    action = await planner.plan(
        messages=[Message(role="user", content="thống kê")],
        observations=[],
        machine_context=None,
    )

    assert action is not None
    assert action.tool == "inventory_stats"
    assert action.params == {"limit": 5}
    assert seen["path"].endswith("/chat/completions")
    assert seen["body"]["model"] == "qwen-test"
    assert seen["body"]["temperature"] == 0.0
    assert seen["body"]["tool_choice"] == "auto"
    names = {t["function"]["name"] for t in seen["body"]["tools"]}
    assert "inventory_stats" in names
    assert seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["messages"][0]["content"] == "SYSTEM CHAT"
    assert planner.usage() == {"input_tokens": 11, "output_tokens": 3}


async def test_plan_uses_chat_system_prompt_not_runtime_prompt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        assert "PROMPT DEEPAGENT" not in json.dumps(body["messages"])
        return _completion({"role": "assistant", "content": "trả lời luôn"})

    planner = _planner(handler)
    action = await planner.plan(
        messages=[Message(role="user", content="hi")], observations=[], machine_context=None
    )
    assert action is None


async def test_plan_feeds_tool_result_back_to_model() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_body(request))
        if len(calls) == 1:
            return _completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "inventory_search", "arguments": '{"q": "x"}'},
                        }
                    ],
                }
            )
        return _completion({"role": "assistant", "content": "xong"})

    planner = _planner(handler)
    action = await planner.plan(
        messages=[Message(role="user", content="liệt kê")],
        observations=[],
        machine_context=None,
    )
    assert action is not None
    await planner.plan(
        messages=[Message(role="user", content="liệt kê")],
        observations=['<untrusted_tool_output tool="inventory_search">{"ok":true}</untrusted_tool_output>'],
        machine_context=None,
    )
    # request thứ 2 phải chứa message role=tool mang kết quả đã bọc
    second = calls[-1]
    tool_msgs = [m for m in second["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "untrusted_tool_output" in tool_msgs[0]["content"]
    assert tool_msgs[0]["tool_call_id"] == "call_1"


async def test_machine_context_is_included_for_model() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return _completion({"role": "assistant", "content": "ok"})

    planner = _planner(handler)
    await planner.plan(
        messages=[Message(role="user", content="máy này cài gì")],
        observations=[],
        machine_context=MachineContext(machine_id="m-1", hostname="DESKTOP-X"),
    )
    blob = json.dumps(seen["body"]["messages"])
    assert "DESKTOP-X" in blob and "m-1" in blob


def test_chat_prompt_answers_naturally_without_tool_preamble() -> None:
    from chatagent.config import DEFAULT_CHAT_SYSTEM_PROMPT

    low = DEFAULT_CHAT_SYSTEM_PROMPT.lower()
    # Bỏ yêu cầu nêu tên công cụ + số dòng trong câu trả lời.
    assert "nêu công cụ đã dùng" not in low
    assert "không mở đầu" in low
    # Thiếu/không rõ → nói chưa đủ thông tin/căn cứ.
    assert "chưa đủ thông tin" in low
    assert "chưa đủ căn cứ" in low


async def test_chat_prompt_guides_classification_via_tags() -> None:
    from chatagent.config import DEFAULT_CHAT_SYSTEM_PROMPT

    low = DEFAULT_CHAT_SYSTEM_PROMPT.lower()
    assert "machine_tags" in low and "classification" in low and "cá nhân" in low


async def test_machine_context_does_not_add_second_system_message() -> None:
    """Chat template Qwen/vLLM từ chối system message thứ 2 → phải gộp vào system đầu tiên."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["msgs"] = _body(request)["messages"]
        return _completion({"role": "assistant", "content": "ok"})

    planner = _planner(handler)
    await planner.plan(
        messages=[Message(role="user", content="x")],
        observations=[],
        machine_context=MachineContext(machine_id="m-1", hostname="DESKTOP-X"),
    )
    systems = [m for m in seen["msgs"] if m["role"] == "system"]
    assert len(systems) == 1
    assert seen["msgs"][0]["role"] == "system"
    assert "DESKTOP-X" in systems[0]["content"] and "m-1" in systems[0]["content"]


async def test_invalid_tool_arguments_raise_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "inventory_stats", "arguments": "{not-json"},
                    }
                ],
            }
        )

    planner = _planner(handler)
    with pytest.raises(LlmError) as exc:
        await planner.plan(
            messages=[Message(role="user", content="x")], observations=[], machine_context=None
        )
    assert exc.value.category == "chat_upstream_llm"


async def test_unknown_tool_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "rm_rf", "arguments": "{}"},
                    }
                ],
            }
        )

    planner = _planner(handler)
    with pytest.raises(LlmError):
        await planner.plan(
            messages=[Message(role="user", content="x")], observations=[], machine_context=None
        )


# ── compose / streaming ──────────────────────────────────────────────────────


async def test_compose_stream_yields_tokens_without_tools() -> None:
    seen: dict = {}
    sse = (
        'data: {"choices":[{"delta":{"content":"Xin "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"chào"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _body(request)
        return httpx.Response(
            200,
            content=sse.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    planner = _planner(handler)
    tokens: list[str] = []
    async for chunk in planner.compose_stream(
        messages=[Message(role="user", content="hi")], observations=[]
    ):
        tokens.append(chunk)

    assert "".join(tokens) == "Xin chào"
    assert "tools" not in seen["body"]
    assert seen["body"]["stream"] is True
    assert planner.usage() == {"input_tokens": 7, "output_tokens": 2}


async def test_compose_non_streaming_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _completion({"role": "assistant", "content": "câu trả lời"})

    planner = _planner(handler)
    answer = await planner.compose(messages=[Message(role="user", content="hi")], observations=[])
    assert answer == "câu trả lời"


# ── error mapping ────────────────────────────────────────────────────────────


async def test_http_error_maps_to_upstream_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    planner = _planner(handler)
    with pytest.raises(LlmError) as exc:
        await planner.plan(
            messages=[Message(role="user", content="x")], observations=[], machine_context=None
        )
    assert exc.value.category == "chat_upstream_llm"
    assert exc.value.retryable is True


async def test_transport_error_maps_to_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("hết hạn")

    planner = _planner(handler)
    with pytest.raises(LlmError):
        await planner.plan(
            messages=[Message(role="user", content="x")], observations=[], machine_context=None
        )


async def test_stream_http_error_maps_to_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "busy"}})

    planner = _planner(handler)
    with pytest.raises(LlmError):
        async for _ in planner.compose_stream(
            messages=[Message(role="user", content="x")], observations=[]
        ):
            pass
