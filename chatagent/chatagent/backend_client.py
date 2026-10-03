"""Backend HTTP client cho ChatAgent (Task 14 — spec F2/R2/F3).

Agent gọi backend qua ba mức uỷ quyền tách biệt:

- **Service token** (`X-Service-Token`) — bắt buộc cho MỌI request nội bộ;
- **Capability** (`X-Chat-Context`, HS256 turn-scoped) — chỉ cho inventory +
  audit intent. Backend verify chữ ký + turn active + chủ sở hội thoại;
- **Completion token** (`X-Chat-Completion`) — chỉ cho finalization
  `/turns/{id}/complete`, độc lập `exp` của capability (V3-3).

Agent **không** tự khai `actor_id`: backend lấy actor từ capability (inventory,
intent) hoặc từ bản ghi intent (outcome/reconcile — R2). Vì vậy `audit_outcome`
và `audit_reconcile` **không** mang capability.

Lỗi backend trả về theo taxonomy `[<category>] <hint> [HTTP <code>]`; client
parse thành `BackendError` để tầng ReAct (T15) map thẳng vào SSE event `error`.
"""
from __future__ import annotations

import uuid
from typing import Any, Self

import httpx

from chatagent.config import Settings

# Endpoint nội bộ (khớp prefix router T10).
_PATH_INVENTORY_QUERY = "/api/internal/chat/inventory/query"
_PATH_INVENTORY_SQL = "/api/internal/chat/inventory/sql"
_PATH_AUDIT_INTENT = "/api/internal/chat/audit/intent"
_PATH_AUDIT_OUTCOME = "/api/internal/chat/audit/outcome"
_PATH_AUDIT_RECONCILE = "/api/internal/chat/audit/reconcile"


class BackendError(RuntimeError):
    """Lỗi từ backend — giữ HTTP status + category để map error taxonomy."""

    def __init__(self, status_code: int, category: str, detail: str) -> None:
        self.status_code = status_code
        self.category = category
        self.detail = detail
        super().__init__(f"[{category}] {detail} [HTTP {status_code}]")


def _parse_category(detail: str, status_code: int) -> tuple[str, str]:
    """Tách `[<category>] <hint>` từ detail; fallback `chat_internal`."""
    if detail.startswith("[") and "]" in detail:
        category = detail[1 : detail.index("]")]
        if category:
            return category, detail
    return "chat_internal", detail


class BackendClient:
    """httpx AsyncClient có header uỷ quyền theo từng loại request."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.backend_url.rstrip("/"),
            timeout=settings.chat_timeout_seconds,
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ── Nền tảng ────────────────────────────────────────────────────────────

    def _headers(
        self, *, capability: str | None = None, completion_token: str | None = None
    ) -> dict[str, str]:
        headers = {"X-Service-Token": self._settings.service_token}
        if capability is not None:
            headers["X-Chat-Context"] = capability
        if completion_token is not None:
            headers["X-Chat-Completion"] = completion_token
        return headers

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        capability: str | None = None,
        completion_token: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(
                path,
                json=body,
                headers=self._headers(capability=capability, completion_token=completion_token),
            )
        except httpx.HTTPError as exc:
            raise BackendError(502, "chat_internal", f"backend không kết nối: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("detail"), str):
                    detail = data["detail"]
            except ValueError:
                pass
            category, _ = _parse_category(detail, response.status_code)
            raise BackendError(response.status_code, category, detail)
        return response.json() if response.content else {}

    # ── Inventory (capability) ──────────────────────────────────────────────

    async def inventory_query(
        self, *, capability: str, tool: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            _PATH_INVENTORY_QUERY,
            {"tool": tool, "params": params},
            capability=capability,
        )

    async def inventory_sql(self, *, capability: str, sql: str) -> dict[str, Any]:
        return await self._post(_PATH_INVENTORY_SQL, {"sql": sql}, capability=capability)

    # ── Audit (intent cần capability; outcome/reconcile chỉ service token) ───

    async def audit_intent(
        self,
        *,
        capability: str,
        tool_call_id: str,
        tool: str,
        args_digest: str | None = None,
        client_id: str | None = None,
        flow_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            _PATH_AUDIT_INTENT,
            {
                "tool_call_id": tool_call_id,
                "tool": tool,
                "args_digest": args_digest,
                "client_id": client_id,
                "flow_id": flow_id,
            },
            capability=capability,
        )

    async def audit_outcome(
        self,
        *,
        turn_id: uuid.UUID | str,
        tool_call_id: str,
        outcome: str,
        client_id: str | None = None,
        flow_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            _PATH_AUDIT_OUTCOME,
            {
                "turn_id": str(turn_id),
                "tool_call_id": tool_call_id,
                "outcome": outcome,
                "client_id": client_id,
                "flow_id": flow_id,
            },
        )

    async def audit_reconcile(
        self, *, turn_id: uuid.UUID | str, tool_call_id: str
    ) -> dict[str, Any]:
        return await self._post(
            _PATH_AUDIT_RECONCILE,
            {"turn_id": str(turn_id), "tool_call_id": tool_call_id},
        )

    # ── Durable completion (service token + completion token) ────────────────

    async def complete(
        self,
        *,
        turn_id: uuid.UUID | str,
        completion_token: str,
        content: str,
        finish_reason: str,
        usage: dict[str, Any] | None = None,
        content_digest: str | None = None,
        error_category: str | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            f"/api/internal/chat/turns/{turn_id}/complete",
            {
                "content": content,
                "finish_reason": finish_reason,
                "usage": usage,
                "content_digest": content_digest,
                "error_category": error_category,
            },
            completion_token=completion_token,
        )
