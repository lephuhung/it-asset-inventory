"""ChatAgent HTTP surface (Task 12 skeleton; ReAct loop + SSE ở Task 15).

`POST /v1/chat` stream SSE theo schema `chat.sse/1`; `GET /v1/chat/{turn_id}/status`
+ `POST /v1/chat/{turn_id}/cancel` là kênh transport/liveness (F7/R4). Mọi route
yêu cầu service token (`X-Service-Token`) — agent không publish port (F5).
"""
from __future__ import annotations

import logging
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from chatagent.agent import AgentRequest, CancelRegistry, ChatAgent
from chatagent.backend_client import BackendClient
from chatagent.config import Settings, get_settings
from chatagent.tools import ToolRegistry

logger = logging.getLogger(__name__)

app = FastAPI(title="ChatAgent", version="0.1.0")

_cancel_registry = CancelRegistry()
_agent: ChatAgent | None = None


class _UnavailableBridge:
    """Bridge MCP mặc định khi chưa cấu hình — chỉ inventory chạy được."""

    async def list_tools(self) -> dict:
        raise RuntimeError("MCP bridge chưa được cấu hình cho chatagent (P1)")

    async def call_tool(self, name: str, arguments: dict) -> dict:
        raise RuntimeError("MCP bridge chưa được cấu hình cho chatagent (P1)")


def build_default_agent(settings: Settings, cancel_registry: CancelRegistry) -> ChatAgent:
    """Dựng agent thật (backend HTTP + bridge MCP chưa cấu hình ở P1)."""
    backend = BackendClient(settings)
    registry = ToolRegistry(bridge=_UnavailableBridge(), backend=backend, settings=settings)
    return ChatAgent(
        registry=registry,
        backend=backend,
        settings=settings,
        cancel_registry=cancel_registry,
    )


def get_cancel_registry() -> CancelRegistry:
    """FastAPI dependency — registry turn dùng chung cho status/cancel."""
    return _cancel_registry


def get_agent() -> ChatAgent:
    """FastAPI dependency — override trong test."""
    global _agent
    if _agent is None:
        _agent = build_default_agent(get_settings(), _cancel_registry)
    return _agent


def require_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Chỉ agent (service token) gọi được API nội bộ (spec "Ranh giới tin cậy")."""
    if not x_service_token or not secrets.compare_digest(
        x_service_token, settings.service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="[chat_authz] service token không hợp lệ [HTTP 401]",
        )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — không cần service token."""
    return {"status": "ok"}


@app.post("/v1/chat", dependencies=[Depends(require_service_token)])
async def chat(body: AgentRequest, agent: ChatAgent = Depends(get_agent)) -> StreamingResponse:
    """SSE turn stream — `start|tool_start|tool_result|token|usage|done|error`."""
    return StreamingResponse(
        agent.stream(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/chat/{turn_id}/status", dependencies=[Depends(require_service_token)])
async def chat_status(
    turn_id: str, registry: CancelRegistry = Depends(get_cancel_registry)
) -> dict:
    """`{status, alive_at}` của turn (kênh liveness F7)."""
    return registry.status(turn_id)


@app.post("/v1/chat/{turn_id}/cancel", dependencies=[Depends(require_service_token)])
async def chat_cancel(
    turn_id: str, registry: CancelRegistry = Depends(get_cancel_registry)
) -> dict:
    """Hủy turn đang chạy; trả ack (F7/R4)."""
    cancelled = registry.cancel(turn_id)
    return {"ack": True, "status": "canceling" if cancelled else "unknown", "turn_id": turn_id}
