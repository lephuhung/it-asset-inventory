"""Bounded ReAct loop + SSE events cho ChatAgent (Task 15 — spec F8/F10/V3-6).

Container `chatagent` chạy một vòng ReAct có trần cho mỗi turn, phát SSE theo schema
`chat.sse/1` và **luôn** gọi durable completion ở mọi nhánh terminal.

**Trần (F11).** `limits.max_tool_calls` / `max_evidence_chars` / `wall_clock_seconds`
do backend đặt, bị chặn thêm bởi `Settings.max_tool_calls` / `max_evidence_chars` /
`wall_clock_seconds`. Vượt → dừng/`error`.

**Prompt-injection (F10).** Output tool bọc `<untrusted_tool_output tool="…">` trước
khi đưa vào model; không credential vào log.

**Egress (V3-6).** `llm_runtime.base_url` được validate ngay trước khi gọi LLM:
`allow_cloud=false` chỉ cho loopback/private/link-local/CGNAT (IPv4+IPv6).

**P1 stub.** Chưa gọi LLM thật; `StubPlanner` sinh tool call tất định từ message cuối.
Loop/bounded/cancel/SSE/completion là hợp đồng thật, LLM chỉ là seam sau này.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import time
import urllib.parse
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from chatagent.config import Settings
from chatagent.tools import ToolCallContext, ToolRegistryError, args_digest

logger = logging.getLogger(__name__)

SSE_VERSION = "chat.sse/1"

# Category dùng khi không phân loại được lỗi cụ thể.
CATEGORY_INTERNAL = "chat_internal"
CATEGORY_TIMEOUT_TOOL = "chat_timeout_tool"
CATEGORY_UPSTREAM_LLM = "chat_upstream_llm"
CATEGORY_CANCELED = "chat_canceled"

# CGNAT 100.64.0.0/10 không nằm trong `ipaddress.is_private` ở mọi phiên bản Python.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

_CHUNK_CHARS = 400


# ── Egress (V3-6/R7) ─────────────────────────────────────────────────────────


class EgressError(RuntimeError):
    """`llm_runtime.base_url` không đạt chính sách egress."""


def _is_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_loopback or address.is_private or address.is_link_local:
        return True
    return address.version == 4 and address in _CGNAT


def assert_llm_egress(base_url: str, allow_cloud: bool) -> None:
    """Fail-closed nếu `base_url` public khi `allow_cloud=false` (spec V3-6/R7)."""
    if not base_url or not isinstance(base_url, str):
        raise EgressError("llm_runtime.base_url rỗng/không hợp lệ")
    try:
        parsed = urllib.parse.urlparse(base_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EgressError(f"llm_runtime.base_url không parse được: {exc}") from exc
    if parsed.scheme not in ("http", "https") or not host:
        raise EgressError("llm_runtime.base_url phải là http(s) có host")

    if allow_cloud:
        return

    default_port = 443 if parsed.scheme == "https" else 80
    try:
        infos = socket.getaddrinfo(
            host, port or default_port, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise EgressError(f"không resolve được host {host!r}: {exc}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise EgressError(f"host {host!r} không có địa chỉ")
    for raw_ip in addresses:
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise EgressError(f"địa chỉ IP không hợp lệ: {raw_ip!r}") from exc
        if not _is_private_address(address):
            raise EgressError(
                f"LLM endpoint public trong khi allow_cloud=false: {raw_ip}"
            )


# ── Request models (spec "Agent API") ────────────────────────────────────────


class MachineContext(BaseModel):
    machine_id: str | None = None
    client_id: str | None = None
    hostname: str | None = None


class Message(BaseModel):
    role: str
    content: str


class LlmRuntime(BaseModel):
    base_url: str
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: int = 120
    max_tokens: int = 4096
    allow_cloud: bool = False
    system_prompt: str = ""


class Limits(BaseModel):
    max_tool_calls: int = Field(default=12, ge=0)
    max_evidence_chars: int = Field(default=120_000, ge=1)
    wall_clock_seconds: int = Field(default=300, ge=1)


class AgentRequest(BaseModel):
    schema_version: str = "chat.agent.request/1.0"
    conversation_id: str
    turn_id: str
    request_id: str
    machine_context: MachineContext | None = None
    messages: list[Message]
    chat_context: str
    llm_runtime: LlmRuntime
    velociraptor_api_client_yaml: str | None = None
    completion_token: str
    limits: Limits = Field(default_factory=Limits)


# ── Planner seam ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlannedToolCall:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)


class Planner(Protocol):
    """Quyết định hành động kế tiếp của loop (P1 stub; thay bằng LLM thật sau)."""

    async def plan(
        self,
        *,
        messages: list[Message],
        observations: list[str],
        machine_context: MachineContext | None,
    ) -> PlannedToolCall | None: ...

    async def compose(self, *, messages: list[Message], observations: list[str]) -> str: ...


# Từ khoá → tool inventory (P1 stub). Không quyết định allowlist — catalog do code.
_TOOL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("vql", "run_vql"),
    ("phần mềm", "inventory_software"),
    ("software", "inventory_software"),
    ("cảnh báo", "inventory_alerts"),
    ("alert", "inventory_alerts"),
    ("phần cứng", "inventory_hardware"),
    ("hardware", "inventory_hardware"),
    ("thống kê", "inventory_stats"),
    ("stats", "inventory_stats"),
)


class StubPlanner:
    """Planner tất định cho P1 — chọn tool từ message user cuối, rồi dừng."""

    async def plan(
        self,
        *,
        messages: list[Message],
        observations: list[str],
        machine_context: MachineContext | None,
    ) -> PlannedToolCall | None:
        # KHÔNG giữ bộ đếm trên instance: `ChatAgent` là singleton
        # (chatagent/api.py `get_agent`), nên state sống suốt vòng đỗi process
        # và chỉ request ĐẦU TIÊN từng được chạy tool. Mỗi turn đã
        # có `observations` thì vòng lặp ReAct tự dừng — đây chỉ là chốt an toàn.
        if observations:
            return None
        text = ""
        for message in reversed(messages):
            if message.role == "user":
                text = message.content
                break
        lowered = text.lower()
        for keyword, tool in _TOOL_KEYWORDS:
            if keyword in lowered:
                if tool == "run_vql":
                    return PlannedToolCall(tool=tool, params={"query": text})
                if machine_context and machine_context.machine_id and tool == "inventory_software":
                    return PlannedToolCall(
                        tool=tool, params={"machine_id": machine_context.machine_id}
                    )
                return PlannedToolCall(tool=tool, params={"query": text})
        return None

    async def compose(self, *, messages: list[Message], observations: list[str]) -> str:
        if not observations:
            return "(chatagent P1) Không có công cụ nào cần chạy cho câu hỏi này."
        return (
            f"(chatagent P1) Đã chạy {len(observations)} công cụ; "
            "kết quả được audit và lưu cùng turn."
        )


# ── Cancel registry ──────────────────────────────────────────────────────────


@dataclass
class _TurnToken:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = "running"
    alive_at: float = field(default_factory=time.time)

    def is_cancelled(self) -> bool:
        return self.event.is_set()


class CancelRegistry:
    """Theo dõi turn đang chạy để phục vụ status + cancel (F7/R4)."""

    def __init__(self) -> None:
        self._turns: dict[str, _TurnToken] = {}

    def register(self, turn_id: str) -> _TurnToken:
        token = _TurnToken()
        self._turns[turn_id] = token
        return token

    def unregister(self, turn_id: str) -> None:
        self._turns.pop(turn_id, None)

    def cancel(self, turn_id: str) -> bool:
        token = self._turns.get(turn_id)
        if token is None or token.status != "running":
            return False
        token.event.set()
        token.status = "canceled"
        token.alive_at = time.time()
        return True

    def finish(self, turn_id: str, *, status: str) -> None:
        token = self._turns.get(turn_id)
        if token is not None:
            token.status = status
            token.alive_at = time.time()

    def status(self, turn_id: str) -> dict[str, Any]:
        token = self._turns.get(turn_id)
        if token is None:
            return {"status": "unknown", "alive_at": None}
        return {
            "status": token.status,
            "alive_at": _iso_time(token.alive_at),
        }


def _iso_time(epoch: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


# ── Agent ────────────────────────────────────────────────────────────────────


def _sse(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {payload['type']}\ndata: {body}\n\n"


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    return [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]


class ChatAgent:
    """Vòng ReAct bounded + SSE + durable completion (một turn)."""

    def __init__(
        self,
        *,
        registry: Any,
        backend: Any,
        settings: Settings,
        planner: Planner | None = None,
        cancel_registry: CancelRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        self._settings = settings
        self._planner = planner or StubPlanner()
        self._cancel = cancel_registry or CancelRegistry()

    async def stream(self, request: AgentRequest) -> AsyncIterator[str]:
        settings = self._settings
        turn_id = str(request.turn_id)
        limits = request.limits
        max_tool_calls = max(0, min(limits.max_tool_calls, settings.max_tool_calls))
        max_evidence = max(1, min(limits.max_evidence_chars, settings.max_evidence_chars))
        wall_clock = max(
            1.0, min(float(limits.wall_clock_seconds), float(settings.wall_clock_seconds))
        )

        token = self._cancel.register(turn_id)
        started = time.monotonic()
        seq = 0
        tool_calls = 0
        answer = ""
        observations: list[str] = []
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        finish_reason = "stop"
        error_category: str | None = None
        error_event: dict[str, Any] | None = None

        try:
            # Egress (V3-6) — validate TRƯỚC khi chạm LLM.
            assert_llm_egress(request.llm_runtime.base_url, request.llm_runtime.allow_cloud)

            yield _sse(
                {"v": SSE_VERSION, "seq": seq, "type": "start", "turn_id": turn_id, "message_id": None}
            )
            seq += 1

            while True:
                if token.is_cancelled():
                    finish_reason, error_category = "canceled", CATEGORY_CANCELED
                    error_event = _error(CATEGORY_CANCELED, "turn đã bị hủy")
                    break
                if time.monotonic() - started > wall_clock:
                    finish_reason, error_category = "error", CATEGORY_TIMEOUT_TOOL
                    error_event = _error(CATEGORY_TIMEOUT_TOOL, "vượt trần thời gian turn")
                    break
                if tool_calls >= max_tool_calls:
                    break

                action = await self._planner.plan(
                    messages=request.messages,
                    observations=list(observations),
                    machine_context=request.machine_context,
                )
                if action is None:
                    break

                tool_call_id = f"tc_{tool_calls}"
                tool_calls += 1
                yield _sse(
                    {
                        "v": SSE_VERSION,
                        "seq": seq,
                        "type": "tool_start",
                        "tool_call_id": tool_call_id,
                        "tool": action.tool,
                        "params_digest": args_digest(action.params),
                        "summary": _summarize(action.tool, action.params),
                    }
                )
                seq += 1

                if token.is_cancelled():
                    finish_reason, error_category = "canceled", CATEGORY_CANCELED
                    error_event = _error(CATEGORY_CANCELED, "turn đã bị hủy")
                    break

                ctx = ToolCallContext(
                    capability=request.chat_context,
                    turn_id=uuid.UUID(turn_id),
                    tool_call_id=tool_call_id,
                )
                try:
                    result = await asyncio.wait_for(
                        self._registry.run(ctx, action.tool, action.params),
                        timeout=settings.chat_timeout_seconds,
                    )
                except TimeoutError:
                    finish_reason, error_category = "error", CATEGORY_TIMEOUT_TOOL
                    error_event = _error(CATEGORY_TIMEOUT_TOOL, f"{action.tool}: quá hạn")
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — map mọi lỗi tool vào taxonomy
                    matched = _category_for(exc)
                    finish_reason, error_category = "error", matched
                    error_event = _error(matched, _hint_for(exc))
                    break

                yield _sse(
                    {
                        "v": SSE_VERSION,
                        "seq": seq,
                        "type": "tool_result",
                        "tool_call_id": tool_call_id,
                        "ok": result.ok,
                        "row_count": result.row_count,
                        "byte_count": result.byte_count,
                        "duration_ms": result.duration_ms,
                        "client_id": result.client_id,
                        "flow_id": result.flow_id,
                        "error_category": result.error_category,
                    }
                )
                seq += 1
                observations.append(
                    _wrap_observation(action.tool, result, max_evidence, observations)
                )

            if error_event is None:
                answer = await self._planner.compose(
                    messages=request.messages, observations=list(observations)
                )
                for chunk in _chunk_text(answer):
                    yield _sse({"v": SSE_VERSION, "seq": seq, "type": "token", "text": chunk})
                    seq += 1
                usage = _estimate_usage(request, answer, observations)
        except asyncio.CancelledError:
            finish_reason, error_category = "canceled", CATEGORY_CANCELED
            error_event = _error(CATEGORY_CANCELED, "turn đã bị hủy")
        except EgressError as exc:
            finish_reason, error_category = "error", CATEGORY_UPSTREAM_LLM
            error_event = _error(CATEGORY_UPSTREAM_LLM, str(exc))
        except Exception:
            logger.exception("chatagent turn %s: lỗi không mong đợi", turn_id)
            finish_reason, error_category = "error", CATEGORY_INTERNAL
            error_event = _error(CATEGORY_INTERNAL, "lỗi xử lý turn")

        # Durable completion — LUÔN gọi ở mọi nhánh terminal.
        completion: dict[str, Any] = {}
        try:
            completion = await self._backend.complete(
                turn_id=turn_id,
                completion_token=request.completion_token,
                content=answer,
                finish_reason=finish_reason,
                usage=usage,
                error_category=error_category if finish_reason == "error" else None,
            )
        except Exception:
            logger.exception("chatagent turn %s: gọi completion thất bại", turn_id)

        if error_event is not None:
            yield _sse({"v": SSE_VERSION, "seq": seq, "type": "error", **error_event})
        else:
            yield _sse({"v": SSE_VERSION, "seq": seq, "type": "usage", **usage})
            seq += 1
            yield _sse(
                {
                    "v": SSE_VERSION,
                    "seq": seq,
                    "type": "done",
                    "message_id": completion.get("message_id"),
                    "finish_reason": finish_reason,
                }
            )

        terminal_status = {
            "stop": "completed",
            "length": "completed",
            "canceled": "canceled",
            "error": "failed",
        }.get(finish_reason, "completed")
        self._cancel.finish(turn_id, status=terminal_status)
        self._cancel.unregister(turn_id)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _error(category: str, hint: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"category": category, "hint": hint, "retryable": retryable}


def _category_for(exc: Exception) -> str:
    category = getattr(exc, "category", None)
    if isinstance(category, str) and category:
        return category
    if isinstance(exc, ToolRegistryError):
        return "chat_guardrail_vql"
    return CATEGORY_INTERNAL


def _hint_for(exc: Exception) -> str:
    hint = getattr(exc, "hint", None)
    if isinstance(hint, str) and hint:
        return hint
    return str(exc)[:200] or exc.__class__.__name__


def _summarize(tool: str, params: dict[str, Any]) -> str:
    keys = sorted(params.keys())
    return f"{tool}({', '.join(keys)})" if keys else tool


def _wrap_observation(
    tool: str, result: Any, max_evidence: int, existing: list[str]
) -> str:
    """Bọc output tool trong `<untrusted_tool_output>` + cắt theo trần evidence."""
    payload = json.dumps(
        {"ok": result.ok, "rows": result.rows, "truncated": result.truncated},
        ensure_ascii=False,
        default=str,
    )
    used = sum(len(item) for item in existing)
    remaining = max(0, max_evidence - used)
    wrapped = f'<untrusted_tool_output tool="{tool}">{payload}</untrusted_tool_output>'
    if len(wrapped) > remaining:
        keep = max(0, remaining - len(f'<untrusted_tool_output tool="{tool}"></untrusted_tool_output>'))
        wrapped = f'<untrusted_tool_output tool="{tool}">{payload[:keep]}</untrusted_tool_output>'
    return wrapped


def _estimate_usage(request: AgentRequest, answer: str, observations: list[str]) -> dict[str, int]:
    """Usage tất định cho stub (LLM thật sẽ báo usage ở T15 successor)."""
    prompt_chars = sum(len(m.content) for m in request.messages) + sum(
        len(o) for o in observations
    )
    return {
        "input_tokens": max(1, prompt_chars // 4),
        "output_tokens": max(1, len(answer) // 4),
    }
