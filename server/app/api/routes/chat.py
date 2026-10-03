"""Public chat routes — `/api/chat` (spec §"Public", §"SSE event schema").

Session auth (`require_super_admin`, chấp nhận `admin_global` legacy) + ownership:
mọi route theo `{id}` chỉ chủ sở hữu (`conversation.created_by`) truy cập; SuperAdmin
khác nhận **404** (spec "Sở hữu (F12)").

Luồng gửi tin: `create_turn` (T8) → persist user message → SSE stream (P1 stub, chatagent
chưa nối ở T12–T15) → `complete_turn` persist assistant message. Turn lifecycle + audit
`chat.turn.start|complete` do T8 sở hữu; route audit `chat.conversation.*`.

SSE schema `chat.sse/1`: `start|token|usage|done`; lỗi trong stream → event `error` rồi
đóng. Non-resumable (không replay endpoint) — client mất kết nối reload hội thoại.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin
from app.core.audit import append_audit
from app.core.config import settings
from app.db.models import (
    ChatConversation,
    ChatMessage,
    ChatTurn,
    LlmConfig,
    Machine,
    User,
)
from app.db.session import get_db
from app.schemas.chat import (
    CancelIn,
    CancelOut,
    ConversationCreateIn,
    ConversationDetailOut,
    ConversationListOut,
    ConversationOut,
    ConversationPatchIn,
    MachineContextIn,
    MessageOut,
    SendMessageIn,
)
from app.services.budget import reserve
from app.services.chat_turns import (
    ACTIVE_STATUSES,
    ActiveTurnExists,
    cancel_turn,
    claim_turn,
    complete_turn,
    create_turn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SSE_SCHEMA_VERSION = "chat.sse/1"

# P1 stub: chatagent (T12–T15) chưa nối. Nội dung mẫu để kiểm tra luồng SSE +
# persist assistant message. Thay bằng stream thật khi chatagent sẵn sàng.
STUB_ASSISTANT_CONTENT = (
    "[chat P1] Trợ lý chưa được nối (chatagent T12–T15). "
    "Đây là phản hồi mẫu để kiểm tra luồng SSE và lưu trữ."
)


def _err(status: int, category: str, hint: str) -> HTTPException:
    """Lỗi theo taxonomy spec: `[<category>] <hint> [HTTP <code>]`."""
    return HTTPException(status, detail=f"[{category}] {hint} [HTTP {status}]")


def _sse(payload: dict) -> str:
    """1 SSE event: dòng `event:` + dòng `data:` + block ngăn cách."""
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {payload['type']}\ndata: {body}\n\n"


def _chunk_text(text: str, parts: int = 3) -> list[str]:
    if not text:
        return [""]
    size = max(1, (len(text) + parts - 1) // parts)
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _load_owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user: User
) -> ChatConversation:
    """Hội thoại phải tồn tại VÀ thuộc `user`; nếu không → 404 (không tiết lộ)."""
    conv = await db.get(ChatConversation, conversation_id)
    if conv is None or conv.created_by != user.id:
        raise _err(404, "chat_not_found", "hội thoại không tồn tại")
    return conv


async def _machine_ref_for(db: AsyncSession, machine_id: uuid.UUID | None) -> str | None:
    """Định danh bất biến cho audit: hostname của máy (nếu có)."""
    if machine_id is None:
        return None
    hostname = (
        await db.execute(select(Machine.hostname).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    return hostname


async def _resolve_machine_context(
    db: AsyncSession, conv: ChatConversation, ctx: MachineContextIn | None
) -> tuple[uuid.UUID | None, str | None]:
    """Snapshot `(machine_id, machine_ref)` cho turn — override per-turn (F12).

    Không đổi `conversation.machine_id` đã lưu; chỉ snapshot vào turn hiện tại.
    """
    if ctx is not None:
        machine_id = ctx.machine_id or conv.machine_id
        machine_ref = ctx.client_id or ctx.hostname
        if machine_ref is None:
            machine_ref = await _machine_ref_for(db, machine_id)
        return machine_id, machine_ref
    machine_id = conv.machine_id
    return machine_id, await _machine_ref_for(db, machine_id)


async def _reserve_budget(db: AsyncSession, turn_id: uuid.UUID) -> None:
    """Reserve ngân sách token cho turn (F11/R8) — fail closed nếu vượt.

    Không cấu hình `daily_token_budget` → không giới hạn (không reserve).
    """
    cfg = await db.get(LlmConfig, 1)
    if cfg is None or cfg.daily_token_budget is None:
        return
    reservation = await reserve(
        db,
        scope="chat_turn",
        operation_id=turn_id,
        association_id=turn_id,
        envelope=cfg.max_tokens,
        budget=cfg.daily_token_budget,
    )
    if reservation is None:
        raise _err(429, "chat_budget_exceeded", "vượt ngân sách token hôm nay")


# ── Conversation CRUD ────────────────────────────────────────────────────────


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreateIn,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    active = (
        await db.execute(
            select(func.count())
            .select_from(ChatConversation)
            .where(
                ChatConversation.created_by == user.id,
                ChatConversation.archived.is_(False),
            )
        )
    ).scalar_one()
    if active >= settings.chat_max_active_conversations_per_user:
        raise _err(429, "chat_rate_limited", "đã đạt trần số hội thoại active")

    if body.machine_id is not None and (
        await db.get(Machine, body.machine_id)
    ) is None:
        raise _err(404, "chat_not_found", "máy không tồn tại")

    conv = ChatConversation(
        created_by=user.id, title=body.title, machine_id=body.machine_id
    )
    db.add(conv)
    await db.flush()
    await append_audit(
        db,
        action="chat.conversation.create",
        actor=str(user.id),
        target=str(conv.id),
        machine_id=conv.machine_id,
        details={"title": conv.title, "machine_id": str(conv.machine_id) if conv.machine_id else None},
    )
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    archived: bool | None = None,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> ConversationListOut:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    where = [ChatConversation.created_by == user.id]
    if archived is not None:
        where.append(ChatConversation.archived.is_(archived))

    total = (
        await db.execute(select(func.count()).select_from(ChatConversation).where(*where))
    ).scalar_one()
    rows = (
        await db.execute(
            select(ChatConversation)
            .where(*where)
            .order_by(
                ChatConversation.last_message_at.desc().nullslast(),
                ChatConversation.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return ConversationListOut(
        items=[ConversationOut.model_validate(c) for c in rows], total=total
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailOut:
    conv = await _load_owned_conversation(db, conversation_id, user)
    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).scalars().all()
    active_turn_id = (
        await db.execute(
            select(ChatTurn.id).where(
                ChatTurn.conversation_id == conv.id,
                ChatTurn.status.in_(tuple(ACTIVE_STATUSES)),
            )
        )
    ).scalar_one_or_none()
    detail = ConversationDetailOut.model_validate(conv)
    detail.messages = [MessageOut.model_validate(m) for m in messages]
    detail.active_turn_id = active_turn_id
    return detail


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatchIn,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    conv = await _load_owned_conversation(db, conversation_id, user)
    changed: dict = {}
    if "title" in body.model_fields_set:
        conv.title = body.title
        changed["title"] = body.title
    if "machine_id" in body.model_fields_set:
        if body.machine_id is not None and (await db.get(Machine, body.machine_id)) is None:
            raise _err(404, "chat_not_found", "máy không tồn tại")
        conv.machine_id = body.machine_id
        changed["machine_id"] = str(body.machine_id) if body.machine_id else None
    conv.updated_at = datetime.now(UTC)
    await db.flush()
    await append_audit(
        db,
        action="chat.conversation.update",
        actor=str(user.id),
        target=str(conv.id),
        machine_id=conv.machine_id,
        details=changed,
    )
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> None:
    conv = await _load_owned_conversation(db, conversation_id, user)
    await append_audit(
        db,
        action="chat.conversation.delete",
        actor=str(user.id),
        target=str(conv.id),
        machine_id=conv.machine_id,
        details={"title": conv.title},
    )
    await db.delete(conv)
    await db.commit()


# ── Send + SSE ───────────────────────────────────────────────────────────────


async def _stream_stub(
    db: AsyncSession, turn: ChatTurn, assistant_content: str
):
    """SSE stub: start → token* → usage → complete → done (P1)."""
    seq = 0
    try:
        await claim_turn(db, turn.id)
        await db.commit()
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "start",
                "turn_id": str(turn.id),
                "message_id": None,
            }
        )
        seq += 1
        for chunk in _chunk_text(assistant_content):
            yield _sse(
                {"v": SSE_SCHEMA_VERSION, "seq": seq, "type": "token", "text": chunk}
            )
            seq += 1

        result = await complete_turn(
            db,
            turn.id,
            content=assistant_content,
            finish_reason="stop",
            usage={"input_tokens": 0, "output_tokens": 0},
        )
        await db.commit()

        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "usage",
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
        seq += 1
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "done",
                "message_id": str(result.message_id) if result.message_id else None,
                "finish_reason": "stop",
            }
        )
    except Exception:  # lỗi trong stream → event `error` rồi đóng
        logger.exception("chat.turn %s: stream thất bại", turn.id)
        await db.rollback()
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "error",
                "category": "chat_internal",
                "hint": "lỗi xử lý turn",
                "retryable": False,
            }
        )


async def _stream_replay(db: AsyncSession, turn: ChatTurn, stored: ChatMessage | None):
    """Replay idempotent: phát lại nội dung assistant đã persist (không chạy lại)."""
    seq = 0
    if stored is None:
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "error",
                "category": "chat_stream_lost",
                "hint": "turn đã kết thúc nhưng không có kết quả đã lưu",
                "retryable": False,
            }
        )
        return
    yield _sse(
        {
            "v": SSE_SCHEMA_VERSION,
            "seq": seq,
            "type": "start",
            "turn_id": str(turn.id),
            "message_id": str(stored.id),
        }
    )
    seq += 1
    for chunk in _chunk_text(stored.content):
        yield _sse({"v": SSE_SCHEMA_VERSION, "seq": seq, "type": "token", "text": chunk})
        seq += 1
    yield _sse(
        {
            "v": SSE_SCHEMA_VERSION,
            "seq": seq,
            "type": "usage",
            "input_tokens": stored.input_tokens,
            "output_tokens": stored.output_tokens,
        }
    )
    seq += 1
    yield _sse(
        {
            "v": SSE_SCHEMA_VERSION,
            "seq": seq,
            "type": "done",
            "message_id": str(stored.id),
            "finish_reason": turn.finish_reason or "stop",
        }
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageIn,
    request: Request,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    conv = await _load_owned_conversation(db, conversation_id, user)
    idempotency_key = request.headers.get("Idempotency-Key")

    # Idempotency: trùng key → replay nếu cùng nội dung, 409 nếu khác (F7).
    if idempotency_key:
        existing = (
            await db.execute(
                select(ChatTurn).where(
                    ChatTurn.conversation_id == conv.id,
                    ChatTurn.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status in ACTIVE_STATUSES:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "[chat_conflict_active_turn] turn đang chạy [HTTP 409]",
                        "active_turn_id": str(existing.id),
                    },
                )
            stored_user = (
                await db.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.turn_id == existing.id,
                        ChatMessage.role == "user",
                    )
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if stored_user is None or stored_user.content != body.content:
                raise _err(
                    409,
                    "chat_conflict_idempotency",
                    "Idempotency-Key đã dùng với nội dung khác",
                )
            stored_assistant = (
                await db.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.turn_id == existing.id,
                        ChatMessage.role == "assistant",
                    )
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return StreamingResponse(
                _stream_replay(db, existing, stored_assistant),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )

    if conv.message_count >= settings.chat_max_messages_per_conversation:
        raise _err(429, "chat_rate_limited", "hội thoại đã đạt trần số tin nhắn")

    machine_id, machine_ref = await _resolve_machine_context(db, conv, body.machine_context)

    try:
        turn = await create_turn(
            db,
            conv,
            user.id,
            machine_id=machine_id,
            machine_ref=machine_ref,
            idempotency_key=idempotency_key,
        )
    except ActiveTurnExists as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"[chat_conflict_active_turn] {exc} [HTTP 409]",
                "active_turn_id": str(exc.active_turn_id),
            },
        )

    await _reserve_budget(db, turn.id)

    db.add(
        ChatMessage(
            conversation_id=conv.id,
            turn_id=turn.id,
            role="user",
            content=body.content,
            machine_id=machine_id,
        )
    )
    conv.message_count += 1
    conv.last_message_at = datetime.now(UTC)
    conv.updated_at = datetime.now(UTC)
    await db.commit()

    return StreamingResponse(
        _stream_stub(db, turn, STUB_ASSISTANT_CONTENT),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/cancel", response_model=CancelOut)
async def cancel_conversation_turn(
    conversation_id: uuid.UUID,
    body: CancelIn,
    user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
) -> CancelOut:
    conv = await _load_owned_conversation(db, conversation_id, user)
    turn = await db.get(ChatTurn, body.turn_id)
    if turn is None or turn.conversation_id != conv.id:
        raise _err(404, "chat_not_found", "turn không thuộc hội thoại")

    result = await cancel_turn(db, body.turn_id, user.id)
    if result.status == "not_found":
        raise _err(404, "chat_not_found", "turn không tồn tại")
    if result.status == "unauthorized":
        await db.rollback()
        raise _err(403, "chat_authz", "không có quyền hủy turn")
    if result.status == "already_terminal":
        await db.rollback()
        raise _err(409, "chat_conflict_active_turn", "turn đã kết thúc")
    await db.commit()
    return CancelOut(status="canceled")
