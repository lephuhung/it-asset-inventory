"""`LlmPlanner` — planner gọi LLM thật (OpenAI-compatible) cho ChatAgent.

Thay `StubPlanner` (P1) bằng vòng ReAct thật dùng **function calling**:

- `plan()`: gửi system prompt + lịch sử + tool catalog + các observation trước đó.
  Model trả `tool_calls` → trả `PlannedToolCall`; trả nội dung (không gọi tool) →
  kết thúc lập kế hoạch (`None`).
- `compose_stream()`: sinh câu trả lời cuối bằng **streaming thật** (SSE token),
  KHÔNG kèm `tools` để model buộc phải trả lời thay vì gọi thêm tool.
- `compose()`: bản non-streaming (fallback).
- `usage()`: token usage thật cộng dồn từ mọi lời gọi.

Bảo mật:
- `llm_runtime.system_prompt` **không** được dùng (đó là prompt DeepAgent); planner
  luôn dùng prompt chat riêng.
- Chỉ expose tool nằm trong catalog code-owned; model gọi tool lạ → `LlmError`.
- Tham số tool phải là JSON object; sai → `LlmError` (fail closed).
- Không log prompt/khoá; lỗi LLM map về category `chat_upstream_llm`.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from chatagent.agent import LlmRuntime, MachineContext, Message, PlannedToolCall
from chatagent.config import DEFAULT_CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

CATEGORY_UPSTREAM_LLM = "chat_upstream_llm"


class LlmError(RuntimeError):
    """Lỗi tầng LLM — map thẳng vào SSE error `chat_upstream_llm`."""

    category = CATEGORY_UPSTREAM_LLM

    def __init__(self, hint: str, *, retryable: bool = False) -> None:
        self.hint = hint
        self.retryable = retryable
        super().__init__(hint)


# ── Catalog tool (code-owned) ────────────────────────────────────────────────

# Schema view read-only cho `inventory_sql`. Phải khớp `MANIFEST_VIEWS` trong
# `server/app/services/chat_inventory.py` + migration `e3f4a5b6c7d8_chat_ro_views.py`.
# Cấp cho model để nó KHÔNG bịa bảng/cột (gây guardrail).
MANIFEST_SCHEMA = (
    "View read-only được phép (schema chat_ro_views) — CHỈ một câu SELECT/WITH, chỉ các view sau:\n"
    "- v_chat_machines(id, hostname, org_name, os_name, os_version, status, last_seen, eol_flag)\n"
    "- v_chat_machine_detail(id, hostname, org_name, os_name, os_version, cpu, ram_mb, disk_gb, status, last_seen)\n"
    "- v_chat_org_stats(org_name, machine_count, online_count, eol_count)\n"
    "- v_chat_software(machine_id, hostname, software_name, version, install_date)\n"
    "- v_chat_hardware(machine_id, hostname, component, value)\n"
    "- v_chat_alerts(id, machine_id, hostname, severity, category, created_at, status)"
)

# Manifest tool inventory — khớp `server/app/services/chat_inventory.py` (STRUCTURED_TOOLS + sql).
INVENTORY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "inventory_search": {
        "description": "Tìm máy theo từ khoá (hostname hoặc tên đơn vị). Dùng khi chưa biết máy cụ thể.",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Từ khoá tìm kiếm"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": [],
        },
    },
    "inventory_machine_detail": {
        "description": "Chi tiết cấu hình một máy (CPU, RAM, ổ đĩa, OS, đơn vị...).",
        "parameters": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string", "description": "UUID máy"},
                "hostname": {"type": "string", "description": "Tên máy"},
            },
            "required": [],
        },
    },
    "inventory_resolve_machine": {
        "description": "Phân giải chính xác hostname thành machine_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "hostname": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["hostname"],
        },
    },
    "inventory_stats": {
        "description": "Thống kê tổng hợp tài sản, có thể lọc theo tên đơn vị.",
        "parameters": {
            "type": "object",
            "properties": {
                "org_name": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": [],
        },
    },
    "inventory_software": {
        "description": "Danh sách phần mềm cài trên một máy (cần machine_id hoặc hostname).",
        "parameters": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "hostname": {"type": "string"},
                "name": {"type": "string", "description": "Lọc theo tên phần mềm"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": [],
        },
    },
    "inventory_hardware": {
        "description": "Linh kiện/phần cứng của một máy (cần machine_id hoặc hostname).",
        "parameters": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "hostname": {"type": "string"},
                "component": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": [],
        },
    },
    "inventory_alerts": {
        "description": "Cảnh báo an toàn thông tin của máy (hoặc toàn hệ thống).",
        "parameters": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "hostname": {"type": "string"},
                "severity": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": [],
        },
    },
    "inventory_sql": {
        "description": (
            "Truy vấn SQL read-only trên các view manifest (chỉ một câu SELECT/WITH). "
            + MANIFEST_SCHEMA
        ),
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
}


def tool_schemas(
    names: Sequence[str], *, sql_schema: str | None = None
) -> list[dict[str, Any]]:
    """Dựng mảng `tools` OpenAI; `sql_schema` (backend introspect) thay mô tả tĩnh."""
    out: list[dict[str, Any]] = []
    for name in names:
        spec = INVENTORY_TOOL_SCHEMAS.get(name)
        if spec is None:
            continue
        if name == "inventory_sql" and sql_schema:
            spec = {
                **spec,
                "description": (
                    "Truy vấn SQL read-only trên dữ liệu kiểm kê (chỉ một câu SELECT/WITH). "
                    "CHỈ dùng bảng/cột trong catalog sau:\n" + sql_schema
                ),
            }
        out.append({"type": "function", "function": {"name": name, **spec}})
    return out


def _machine_context_line(ctx: MachineContext | None) -> str | None:
    if ctx is None:
        return None
    parts = []
    if ctx.hostname:
        parts.append(f"hostname={ctx.hostname}")
    if ctx.machine_id:
        parts.append(f"machine_id={ctx.machine_id}")
    if ctx.client_id:
        parts.append(f"client_id={ctx.client_id}")
    if not parts:
        return None
    return (
        "Ngữ cảnh máy cho lượt hỏi này (chỉ áp dụng lượt này): "
        + ", ".join(parts)
        + ". Khi người dùng nói 'máy này', hiểu là máy trên."
    )


class LlmPlanner:
    """Planner thật: gọi `POST {base_url}/chat/completions` với function calling."""

    def __init__(
        self,
        runtime: LlmRuntime,
        *,
        client: httpx.AsyncClient | None = None,
        system_prompt: str | None = None,
        tool_names: Sequence[str] | None = None,
        max_output_tokens: int | None = None,
        max_calls: int | None = None,
        sql_schema: str | None = None,
    ) -> None:
        self._runtime = runtime
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=float(runtime.timeout_seconds))
        self._endpoint = f"{runtime.base_url.rstrip('/')}/chat/completions"
        # Prompt chat riêng — KHÔNG dùng `runtime.system_prompt`.
        self._system_prompt = system_prompt or DEFAULT_CHAT_SYSTEM_PROMPT
        names = list(tool_names) if tool_names is not None else list(INVENTORY_TOOL_SCHEMAS)
        self._tool_names = {n for n in names if n in INVENTORY_TOOL_SCHEMAS}
        self._tools = tool_schemas(names, sql_schema=sql_schema)
        self._max_tokens = max_output_tokens or runtime.max_tokens or 4096
        self._max_calls = max_calls or 16
        self._calls = 0
        self._conversation: list[dict[str, Any]] | None = None
        self._pending_tool: dict[str, str] | None = None
        self._usage = {"input_tokens": 0, "output_tokens": 0}

    # ── Public API (Planner Protocol) ────────────────────────────────────────

    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def plan(
        self,
        *,
        messages: list[Message],
        observations: list[str],
        machine_context: MachineContext | None,
    ) -> PlannedToolCall | None:
        self._ensure_conversation(messages, machine_context)
        if self._pending_tool is not None and observations:
            self._conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": self._pending_tool["id"],
                    "content": observations[-1],
                }
            )
            self._pending_tool = None

        data = await self._complete(
            {
                "model": self._runtime.model,
                "messages": self._conversation,
                "temperature": self._runtime.temperature,
                "max_tokens": self._max_tokens,
                "tools": self._tools,
                "tool_choice": "auto",
            }
        )
        message = _first_message(data)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return None

        call = tool_calls[0]
        name = (call.get("function") or {}).get("name")
        if not isinstance(name, str) or name not in self._tool_names:
            raise LlmError(f"model gọi tool ngoài catalog: {name!r}")
        raw_args = (call.get("function") or {}).get("arguments")
        params = _parse_arguments(raw_args)
        call_id = call.get("id") or f"call_{len(self._conversation)}"
        # Chỉ giữ tool_call đầu tiên: vòng lặp chỉ chạy 1 tool/lượt nên tool_call
        # còn lại sẽ thiếu message role=tool → API lỗi ở lượt sau.
        self._conversation.append(
            {"role": "assistant", "content": message.get("content"), "tool_calls": [call]}
        )
        self._pending_tool = {"id": str(call_id)}
        return PlannedToolCall(tool=name, params=params)

    async def compose(self, *, messages: list[Message], observations: list[str]) -> str:
        self._ensure_conversation(messages, None)
        data = await self._complete(
            {
                "model": self._runtime.model,
                "messages": self._conversation,
                "temperature": self._runtime.temperature,
                "max_tokens": self._max_tokens,
            }
        )
        return _first_message(data).get("content") or ""

    async def compose_stream(
        self, *, messages: list[Message], observations: list[str]
    ) -> AsyncIterator[str]:
        self._ensure_conversation(messages, None)
        body = {
            "model": self._runtime.model,
            "messages": self._conversation,
            "temperature": self._runtime.temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._calls += 1
        self._guard_calls()
        try:
            async with self._client.stream(
                "POST", self._endpoint, json=body, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    text = _error_text_from_bytes(await response.aread())
                    raise LlmError(
                        f"LLM trả HTTP {response.status_code}: {text}",
                        retryable=_retryable_status(response.status_code),
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    self._record_usage(chunk)
                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield delta
        except LlmError:
            raise
        except httpx.TimeoutException as exc:
            raise LlmError(f"LLM quá hạn khi trả lời: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"không kết nối được LLM: {exc}", retryable=True) from exc

    # ── Nội bộ ───────────────────────────────────────────────────────────────

    def _ensure_conversation(
        self, messages: list[Message], machine_context: MachineContext | None
    ) -> None:
        if self._conversation is not None:
            return
        # Chat template (Qwen/vLLM) chỉ chấp nhận MỘT system message ở đầu → gộp
        # ngữ cảnh máy vào chính system prompt, không thêm system thứ hai.
        system_content = self._system_prompt
        ctx_line = _machine_context_line(machine_context)
        if ctx_line:
            system_content = f"{system_content}\n\n{ctx_line}"
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]
        conversation.extend(
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        )
        self._conversation = conversation

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._runtime.api_key:
            headers["authorization"] = f"Bearer {self._runtime.api_key}"
        return headers

    async def _complete(self, body: dict[str, Any]) -> dict[str, Any]:
        self._calls += 1
        self._guard_calls()
        try:
            response = await self._client.post(
                self._endpoint, json=body, headers=self._headers()
            )
        except httpx.TimeoutException as exc:
            raise LlmError(f"LLM quá hạn: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"không kết nối được LLM: {exc}", retryable=True) from exc
        if response.status_code >= 400:
            raise LlmError(
                f"LLM trả HTTP {response.status_code}: {_error_text(response)}",
                retryable=_retryable_status(response.status_code),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmError("LLM trả về JSON không hợp lệ") from exc
        self._record_usage(data)
        return data

    def _guard_calls(self) -> None:
        if self._calls > self._max_calls:
            raise LlmError(f"vượt trần gọi LLM/turn ({self._max_calls})")

    def _record_usage(self, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        try:
            self._usage["input_tokens"] += int(usage.get("prompt_tokens") or 0)
            self._usage["output_tokens"] += int(usage.get("completion_tokens") or 0)
        except (TypeError, ValueError):
            return


# ── Helpers ──────────────────────────────────────────────────────────────────


def _first_message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    if not choices:
        raise LlmError("LLM không trả về choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LlmError("LLM trả về message không hợp lệ")
    return message


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        params = raw
    elif isinstance(raw, str):
        try:
            params = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmError("tham số tool của model không phải JSON hợp lệ") from exc
    else:
        raise LlmError("tham số tool của model sai kiểu")
    if not isinstance(params, dict):
        raise LlmError("tham số tool phải là JSON object")
    return params


def _retryable_status(status: int) -> bool:
    return status >= 500 or status in (408, 429)


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
        if isinstance(data.get("detail"), str):
            return data["detail"][:300]
    return response.text[:300]


def _error_text_from_bytes(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")[:300]
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
        if isinstance(data.get("detail"), str):
            return data["detail"][:300]
    return text
