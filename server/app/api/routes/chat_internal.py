"""Internal chat routes — `/api/internal/chat` (spec §"Nội bộ", §V5).

Chỉ ChatAgent gọi các route này (service token `X-Service-Token`). Hai mức uỷ quyền:

- **Capability** (`X-Chat-Context`, HS256, turn-scoped — T4) cho `inventory/query`,
  `inventory/sql`, `audit/intent`: bắt buộc turn còn active + conversation.created_by
  == sub. Đây là danh tính thực thi.
- **Intent record** (`chat_audit_intents`) cho `audit/outcome`, `audit/reconcile`:
  KHÔNG cần capability (chạy được khi capability đã hết hạn/turn terminal). Actor
  lấy từ intent — reconcile không mở lại quyền chạy truy vấn.
- **Completion token** (`X-Chat-Completion`) cho `turns/{id}/complete`: thẩm quyền
  finalization riêng (V3-3), độc lập với `exp` của capability.

V5 — intent = danh tính thực thi: `(turn_id, tool_call_id)` định danh MỘT lần chạy.
Trùng + identity đầy đủ (`actor_id`, `tool`, `args_digest`, `client_id`) → trả bản ghi
cũ, **không** cho chạy lại; khác bất kỳ trường → `409`.

Audit dùng hash-chain T1 `append_audit` (chỉ flush) — route PHẢI commit.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.chat_capability import (
    CapabilityClaims,
    CapabilityError,
    hash_completion_token,
    verify_capability,
)
from app.core.config import settings
from app.db.models import ChatAuditIntent, ChatConversation, ChatTurn
from app.db.session import get_chat_ro_session, get_db
from app.services import chat_inventory
from app.services.chat_inventory import SqlGuardrailError
from app.services.chat_turns import complete_turn

router = APIRouter(prefix="/api/internal/chat", tags=["internal-chat"])

OUTCOME_VALUES = frozenset({"ok", "error", "canceled", "unknown"})
ACTIVE_STATUSES = frozenset({"pending", "streaming"})
INTENT_IDENTITY_FIELDS = ("tool", "args_digest", "client_id")


def _err(status: int, category: str, hint: str) -> HTTPException:
    """Lỗi theo taxonomy spec: `[<category>] <hint> [HTTP <code>]`."""
    return HTTPException(status, detail=f"[{category}] {hint} [HTTP {status}]")


# ── Auth dependencies ────────────────────────────────────────────────────────


def require_service_token(request: Request) -> None:
    """Service token bắt buộc cho MỌI endpoint nội bộ."""
    token = request.headers.get("X-Service-Token")
    if not token or not secrets.compare_digest(token, settings.chat_service_token):
        raise _err(401, "chat_authz", "service token không hợp lệ")


async def require_capability(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CapabilityClaims:
    """Verify capability + DB: turn active, conversation.created_by == sub."""
    token = request.headers.get("X-Chat-Context")
    if not token:
        raise _err(401, "chat_authz", "thiếu capability")
    try:
        claims = verify_capability(token)
    except CapabilityError as exc:
        raise _err(401, "chat_authz", str(exc)) from exc

    turn = await db.get(ChatTurn, claims.turn_id)
    if turn is None or turn.status not in ACTIVE_STATUSES:
        raise _err(401, "chat_authz", "turn không tồn tại hoặc đã kết thúc")
    if turn.conversation_id != claims.conversation_id:
        raise _err(401, "chat_authz", "capability không khớp turn")
    conv = await db.get(ChatConversation, claims.conversation_id)
    if conv is None or conv.created_by != claims.actor_id:
        raise _err(401, "chat_authz", "capability không khớp chủ sở hữu hội thoại")
    return claims


async def _load_intent(
    db: AsyncSession, turn_id: uuid.UUID, tool_call_id: str
) -> ChatAuditIntent:
    intent = (
        await db.execute(
            select(ChatAuditIntent).where(
                ChatAuditIntent.turn_id == turn_id,
                ChatAuditIntent.tool_call_id == tool_call_id,
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        raise _err(404, "chat_not_found", "intent không tồn tại")
    return intent


# ── DTOs ─────────────────────────────────────────────────────────────────────


class InventoryQueryIn(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


class InventorySqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


class InventoryOut(BaseModel):
    tool: str
    ok: bool
    rows: list[dict]
    row_count: int
    truncated: bool
    byte_count: int
    sql_digest: str


class IntentIn(BaseModel):
    tool_call_id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=64)
    args_digest: str | None = Field(default=None, max_length=64)
    client_id: str | None = Field(default=None, max_length=64)
    flow_id: str | None = Field(default=None, max_length=64)


class IntentOut(BaseModel):
    intent_id: uuid.UUID
    audit_id: int
    executed: bool


class OutcomeIn(BaseModel):
    turn_id: uuid.UUID
    tool_call_id: str = Field(min_length=1, max_length=64)
    outcome: str
    client_id: str | None = Field(default=None, max_length=64)
    flow_id: str | None = Field(default=None, max_length=64)


class OutcomeOut(BaseModel):
    outcome: str
    audit_id: int
    idempotent: bool


class ReconcileIn(BaseModel):
    turn_id: uuid.UUID
    tool_call_id: str = Field(min_length=1, max_length=64)


class ReconcileOut(BaseModel):
    outcome: str
    reconciled: bool


class CompleteIn(BaseModel):
    content: str
    finish_reason: str
    usage: dict | None = None
    content_digest: str | None = Field(default=None, max_length=64)
    error_category: str | None = Field(default=None, max_length=48)


class CompleteOut(BaseModel):
    status: str
    message_id: uuid.UUID | None = None


# ── Inventory ────────────────────────────────────────────────────────────────


@router.post("/inventory/query", dependencies=[Depends(require_service_token)])
async def inventory_query(
    body: InventoryQueryIn,
    claims: CapabilityClaims = Depends(require_capability),
    db: AsyncSession = Depends(get_db),
    ro: AsyncSession = Depends(get_chat_ro_session),
) -> InventoryOut:
    """Chạy tool inventory có cấu trúc trên pool read-only + audit (digest SQL)."""
    try:
        result = await chat_inventory.run_tool(ro, body.tool, body.params)
    except SqlGuardrailError as exc:
        await _audit_guardrail_denied(db, claims, body.tool, exc.hint)
        raise _err(exc.http_status, exc.CATEGORY, exc.hint) from exc

    turn = await db.get(ChatTurn, claims.turn_id)
    await append_audit(
        db,
        action="chat.query.inventory",
        actor=str(claims.actor_id),
        target=body.tool,
        request_id=str(claims.request_id),
        machine_id=turn.machine_id if turn else None,
        details={
            "turn_id": str(claims.turn_id),
            "conversation_id": str(claims.conversation_id),
            "machine_ref": turn.machine_ref if turn else None,
            "tool": body.tool,
            "row_count": result.row_count,
            "sql_digest": result.sql_digest,
            "truncated": result.truncated,
        },
    )
    await db.commit()
    return InventoryOut(
        tool=result.tool,
        ok=result.ok,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        byte_count=result.byte_count,
        sql_digest=result.sql_digest,
    )


@router.post("/inventory/sql", dependencies=[Depends(require_service_token)])
async def inventory_sql(
    body: InventorySqlIn,
    claims: CapabilityClaims = Depends(require_capability),
    db: AsyncSession = Depends(get_db),
    ro: AsyncSession = Depends(get_chat_ro_session),
) -> InventoryOut:
    """SQL ad-hoc read-only qua validator T9; audit chỉ digest, không raw SQL."""
    try:
        result = await chat_inventory.run_sql(ro, body.sql)
    except SqlGuardrailError as exc:
        await _audit_guardrail_denied(db, claims, "inventory_sql", exc.hint)
        raise _err(exc.http_status, exc.CATEGORY, exc.hint) from exc

    turn = await db.get(ChatTurn, claims.turn_id)
    await append_audit(
        db,
        action="chat.query.inventory.sql",
        actor=str(claims.actor_id),
        target=str(claims.turn_id),
        request_id=str(claims.request_id),
        machine_id=turn.machine_id if turn else None,
        details={
            "turn_id": str(claims.turn_id),
            "conversation_id": str(claims.conversation_id),
            "machine_ref": turn.machine_ref if turn else None,
            "tool": "inventory_sql",
            "row_count": result.row_count,
            "sql_digest": result.sql_digest,
            "truncated": result.truncated,
        },
    )
    await db.commit()
    return InventoryOut(
        tool=result.tool,
        ok=result.ok,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        byte_count=result.byte_count,
        sql_digest=result.sql_digest,
    )


async def _audit_guardrail_denied(
    db: AsyncSession, claims: CapabilityClaims, tool: str, hint: str
) -> None:
    """Ghi audit `chat.tool.denied` rồi commit — trước khi trả lỗi cho agent."""
    await append_audit(
        db,
        action="chat.tool.denied",
        actor=str(claims.actor_id),
        target=tool,
        request_id=str(claims.request_id),
        details={
            "turn_id": str(claims.turn_id),
            "conversation_id": str(claims.conversation_id),
            "tool": tool,
            "reason": hint,
        },
    )
    await db.commit()


# ── Audit intent / outcome / reconcile ───────────────────────────────────────


@router.post("/audit/intent", dependencies=[Depends(require_service_token)])
async def audit_intent(
    body: IntentIn,
    claims: CapabilityClaims = Depends(require_capability),
    db: AsyncSession = Depends(get_db),
) -> IntentOut:
    """Ghi intent TRƯỚC khi chạy tool Velociraptor. Intent fail → không chạy tool."""
    existing = (
        await db.execute(
            select(ChatAuditIntent).where(
                ChatAuditIntent.turn_id == claims.turn_id,
                ChatAuditIntent.tool_call_id == body.tool_call_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        same_identity = existing.actor_id == claims.actor_id and all(
            getattr(existing, name) == getattr(body, name)
            for name in INTENT_IDENTITY_FIELDS
        )
        if not same_identity:
            raise _err(
                409,
                "chat_conflict_idempotency",
                f"tool_call_id {body.tool_call_id!r} đã dùng với danh tính khác",
            )
        # V5: trùng identity đầy đủ → trả bản ghi cũ, KHÔNG cho chạy lại.
        return IntentOut(intent_id=existing.id, audit_id=0, executed=False)

    turn = await db.get(ChatTurn, claims.turn_id)
    intent = ChatAuditIntent(
        turn_id=claims.turn_id,
        tool_call_id=body.tool_call_id,
        conversation_id=claims.conversation_id,
        actor_id=claims.actor_id,
        tool=body.tool,
        args_digest=body.args_digest,
        client_id=body.client_id,
        flow_id=body.flow_id,
    )
    db.add(intent)
    try:
        await db.flush()
    except Exception as exc:  # race trên UNIQUE(turn_id, tool_call_id)
        await db.rollback()
        raise _err(
            409, "chat_conflict_idempotency", "intent đã tồn tại (race)"
        ) from exc

    audit = await append_audit(
        db,
        action="chat.query.velociraptor",
        actor=str(claims.actor_id),
        target=body.tool_call_id,
        request_id=str(claims.request_id),
        machine_id=turn.machine_id if turn else None,
        details={
            "phase": "intent",
            "turn_id": str(claims.turn_id),
            "conversation_id": str(claims.conversation_id),
            "machine_ref": turn.machine_ref if turn else None,
            "tool_call_id": body.tool_call_id,
            "tool": body.tool,
            "args_digest": body.args_digest,
            "client_id": body.client_id,
            "flow_id": body.flow_id,
        },
    )
    await db.commit()
    return IntentOut(intent_id=intent.id, audit_id=audit.id, executed=True)


@router.post("/audit/outcome", dependencies=[Depends(require_service_token)])
async def audit_outcome(
    body: OutcomeIn,
    db: AsyncSession = Depends(get_db),
) -> OutcomeOut:
    """Ghi outcome sau khi có kết quả/lỗi. KHÔNG cần capability — actor từ intent.

    Idempotent theo `(turn_id, tool_call_id)`: bản ghi terminal đầu thắng; trùng giá
    trị → ok; khác → `409`.
    """
    if body.outcome not in OUTCOME_VALUES:
        raise _err(400, "chat_validation", f"outcome không hợp lệ: {body.outcome!r}")

    intent = await _load_intent(db, body.turn_id, body.tool_call_id)
    if intent.outcome != "pending":
        if intent.outcome == body.outcome:
            return OutcomeOut(outcome=intent.outcome, audit_id=0, idempotent=True)
        raise _err(
            409,
            "chat_conflict_idempotency",
            f"intent đã có outcome {intent.outcome!r}, khác {body.outcome!r}",
        )

    intent.outcome = body.outcome
    intent.resolved_at = datetime.now(UTC)
    if body.client_id is not None:
        intent.client_id = body.client_id
    if body.flow_id is not None:
        intent.flow_id = body.flow_id

    audit = await append_audit(
        db,
        action="chat.query.velociraptor",
        actor=str(intent.actor_id),
        target=body.tool_call_id,
        request_id=str(intent.turn_id),
        details={
            "phase": "outcome",
            "turn_id": str(intent.turn_id),
            "conversation_id": str(intent.conversation_id),
            "tool_call_id": body.tool_call_id,
            "tool": intent.tool,
            "client_id": intent.client_id,
            "flow_id": intent.flow_id,
            "outcome": body.outcome,
        },
    )
    await db.commit()
    return OutcomeOut(outcome=body.outcome, audit_id=audit.id, idempotent=False)


@router.post("/audit/reconcile", dependencies=[Depends(require_service_token)])
async def audit_reconcile(
    body: ReconcileIn,
    db: AsyncSession = Depends(get_db),
) -> ReconcileOut:
    """Đóng intent mồ côi quá `audit_outcome_deadline` → `unknown` (actor từ intent)."""
    intent = await _load_intent(db, body.turn_id, body.tool_call_id)
    if intent.outcome != "pending":
        return ReconcileOut(outcome=intent.outcome, reconciled=False)

    created = intent.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - created).total_seconds()
    if age < settings.audit_outcome_deadline:
        return ReconcileOut(outcome="pending", reconciled=False)

    intent.outcome = "unknown"
    intent.resolved_at = datetime.now(UTC)
    await append_audit(
        db,
        action="chat.query.velociraptor",
        actor=str(intent.actor_id),
        target=body.tool_call_id,
        request_id=str(intent.turn_id),
        details={
            "phase": "reconcile",
            "turn_id": str(intent.turn_id),
            "conversation_id": str(intent.conversation_id),
            "tool_call_id": body.tool_call_id,
            "tool": intent.tool,
            "client_id": intent.client_id,
            "flow_id": intent.flow_id,
            "outcome": "unknown",
        },
    )
    await db.commit()
    return ReconcileOut(outcome="unknown", reconciled=True)


# ── Durable completion ───────────────────────────────────────────────────────


@router.post("/turns/{turn_id}/complete", dependencies=[Depends(require_service_token)])
async def complete_turn_route(
    turn_id: uuid.UUID,
    body: CompleteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CompleteOut:
    """Completion winner (V3-3/V5) — service token + completion token (không capability).

    Idempotent kể cả khi turn đã terminal (trong grace).
    """
    token = request.headers.get("X-Chat-Completion")
    if not token:
        raise _err(401, "chat_authz", "thiếu completion token")

    turn = await db.get(ChatTurn, turn_id)
    if turn is None:
        raise _err(404, "chat_not_found", "turn không tồn tại")
    if not turn.completion_token_hash or not secrets.compare_digest(
        hash_completion_token(token), turn.completion_token_hash
    ):
        raise _err(403, "chat_authz", "completion token không hợp lệ")

    result = await complete_turn(
        db,
        turn_id,
        content=body.content,
        finish_reason=body.finish_reason,
        usage=body.usage,
        content_digest=body.content_digest,
        error_category=body.error_category,
    )
    if result.status == "not_found":
        raise _err(404, "chat_not_found", "turn không tồn tại")
    if result.status == "late_expired":
        await db.commit()
        raise _err(409, "chat_conflict_idempotency", "completion quá hạn ân hạn")
    if result.status == "conflict":
        await db.commit()
        raise _err(409, "chat_conflict_idempotency", "completion khác nội dung đã commit")
    await db.commit()
    return CompleteOut(status=result.status, message_id=result.message_id)
