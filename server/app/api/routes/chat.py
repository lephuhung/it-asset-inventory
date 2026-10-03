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

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin
from app.core.audit import append_audit
from app.core.chat_capability import (
    hash_completion_token,
    new_completion_token,
    sign_capability,
)
from app.core.config import settings
from app.core.security import decrypt_aes_gcm
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
from app.services.budget import BudgetUnavailable, reserve
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

# Timeout gọi ChatAgent: connect ngắn, read dài (stream turn).
_AGENT_CONNECT_TIMEOUT = 5.0
_AGENT_READ_TIMEOUT = 300.0


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

    Dịch mọi lỗi hạ tầng ngân sách thành `503 [chat_budget_unavailable]`
    (spec F11/R8): DB ngân sách không khả dụng phải fail closed cho execution MỚI,
    không được rò rỉ `SQLAlchemyError` thô ra HTTP.
    """
    try:
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
    except BudgetUnavailable as exc:
        await db.rollback()
        raise _err(
            503, "chat_budget_unavailable", "dịch vụ ngân sách tạm thời không khả dụng"
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise _err(
            503, "chat_budget_unavailable", "không truy cập được dữ liệu ngân sách"
        ) from exc
    if reservation is None:
        await db.rollback()
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
        # `machine_id` KHÔNG được nằm trong `details`: nó là lookup mutable và bị
        # `_content_hash_v2` hash nếu lọt vào details, phá vỡ quy tắc R3 (chỉ
        # `machine_ref` bất biến mới hash-bound). Nó đã được truyền riêng qua kwarg
        # `machine_id=` ở trên.
        details={"title": conv.title},
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
        # `machine_id` KHÔNG vào `details` (bị hash v2) — chỉ báo cờ đã đổi; giá trị
        # thật truyền qua kwarg `machine_id=` bên dưới (R3).
        changed["machine_id_changed"] = True
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


async def _stream_agent(body: dict) -> AsyncIterator[str]:
    """Seam gọi `chatagent POST /v1/chat` và yield từng dòng SSE thô (T11).

    Là điểm duy nhất mở kết nối tới container chatagent — test patch seam này để
    chạy không cần container thật.
    """
    headers = {
        "X-Service-Token": settings.chat_service_token,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    timeout = httpx.Timeout(
        connect=_AGENT_CONNECT_TIMEOUT, read=_AGENT_READ_TIMEOUT, write=30.0, pool=5.0
    )
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client, client.stream(
        "POST", f"{settings.chat_agent_url}/v1/chat", json=body, headers=headers
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            yield line


async def _build_agent_request(
    db: AsyncSession,
    *,
    conv: ChatConversation,
    turn: ChatTurn,
    actor_id: uuid.UUID,
    machine_id: uuid.UUID | None,
    machine_ref: str | None,
) -> dict:
    """Dựng body `chat.agent.request/1.0` (spec §"Agent API") + cấp completion token.

    Cấp `chat_context` (capability HS256 turn-scoped) và `completion_token`; lưu
    hash của completion token vào turn để route `/turns/{id}/complete` xác thực.
    """
    completion_token = new_completion_token()
    turn.completion_token_hash = hash_completion_token(completion_token)
    await db.flush()

    capability = sign_capability(
        actor_id, conv.id, turn.id, turn.request_id, ttl=300
    )

    history = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(settings.chat_max_history_messages)
        )
    ).scalars().all()
    messages = [
        {"role": m.role, "content": m.content}
        for m in history
        if m.role in ("user", "assistant")
    ]

    machine_context = None
    if machine_id is not None:
        machine_context = {
            "machine_id": str(machine_id),
            "client_id": None,
            "hostname": machine_ref,
        }

    llm_runtime = await _agent_llm_runtime(db)

    return {
        "schema_version": "chat.agent.request/1.0",
        "conversation_id": str(conv.id),
        "turn_id": str(turn.id),
        "request_id": str(turn.request_id),
        "machine_context": machine_context,
        "messages": messages,
        "chat_context": capability,
        "llm_runtime": llm_runtime,
        "velociraptor_api_client_yaml": None,
        "completion_token": completion_token,
        "limits": {
            "max_tool_calls": settings.chat_max_tool_calls_per_turn,
            "max_evidence_chars": settings.chat_evidence_chars,
            "wall_clock_seconds": settings.chat_wall_clock_seconds,
        },
    }


async def _agent_llm_runtime(db: AsyncSession) -> dict:
    """Lấy `llm_runtime` từ `LlmConfig` cho request gửi ChatAgent."""
    cfg = await db.get(LlmConfig, 1)
    if cfg is None:
        return {
            "base_url": "",
            "api_key": "",
            "model": "",
            "temperature": 0.2,
            "timeout_seconds": 120,
            "max_tokens": 4096,
            "allow_cloud": False,
            "system_prompt": "",
        }
    api_key = ""
    if cfg.api_key_encrypted:
        try:
            api_key = decrypt_aes_gcm(cfg.api_key_encrypted)
        except Exception:  # noqa: BLE001
            logger.warning("Giải mã LLM api_key thất bại khi dispatch ChatAgent")
    return {
        "base_url": cfg.base_url,
        "api_key": api_key,
        "model": cfg.model,
        "temperature": float(cfg.temperature) if cfg.temperature is not None else 0.2,
        "timeout_seconds": cfg.request_timeout,
        "max_tokens": cfg.max_tokens,
        "allow_cloud": cfg.allow_cloud,
        "system_prompt": cfg.system_prompt or "",
    }


def _parse_agent_event(data_lines: list[str]) -> dict | None:
    """Gộp các dòng `data:` thành 1 payload JSON; bỏ qua block rỗng."""
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except ValueError:
        return None


async def _stream_from_agent(
    db: AsyncSession,
    *,
    conv: ChatConversation,
    turn: ChatTurn,
    actor_id: uuid.UUID,
    machine_id: uuid.UUID | None,
    machine_ref: str | None,
):
    """Proxy SSE thật từ ChatAgent `/v1/chat` (T11) — relay + persist winner.

    Claim turn → dựng request → gọi agent → relay từng event `chat.sse/1`. Trên
    `done`/`error` (hoặc agent không kết nối được), gọi `complete_turn` để đảm bảo
    assistant message được persist (idempotent với durable completion của agent).
    """
    seq = 0
    answer_parts: list[str] = []
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    finish_reason = "stop"
    error_category: str | None = None
    error_event: dict | None = None
    # Chụp trước mọi commit/rollback: ORM object có thể bị expire sau rollback
    # (MissingGreenlet nếu đọc `turn.id` trong nhánh lỗi).
    turn_id = turn.id

    try:
        await claim_turn(db, turn_id)
        await db.commit()
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "start",
                "turn_id": str(turn_id),
                "message_id": None,
            }
        )
        seq += 1

        body = await _build_agent_request(
            db,
            conv=conv,
            turn=turn,
            actor_id=actor_id,
            machine_id=machine_id,
            machine_ref=machine_ref,
        )
        await db.commit()

        data_lines: list[str] = []
        async for line in _stream_agent(body):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue
            # Dòng trống = hết 1 block SSE của agent → xử lý payload đã gom.
            if line.strip():
                continue
            event = _parse_agent_event(data_lines)
            data_lines = []
            if event is None:
                continue
            etype = event.get("type")
            if etype in ("start", "usage", "done", "error"):
                if etype == "usage":
                    usage = {
                        "input_tokens": int(event.get("input_tokens", 0) or 0),
                        "output_tokens": int(event.get("output_tokens", 0) or 0),
                    }
                elif etype == "done":
                    finish_reason = event.get("finish_reason", "stop")
                elif etype == "error":
                    error_category = event.get("category", "chat_internal")
                    error_event = event
                # `start` đã do backend phát — relay các event còn lại cho portal.
                if etype == "start":
                    continue
            elif etype == "token":
                answer_parts.append(event.get("text", ""))
            # relay event của agent (re-sequenced theo stream của backend)
            payload = {k: v for k, v in event.items() if k not in ("seq", "v")}
            payload["v"] = SSE_SCHEMA_VERSION
            payload["seq"] = seq
            yield _sse(payload)
            seq += 1

        if error_event is None and finish_reason not in ("canceled", "error"):
            finish_reason = "stop"

        await _finalize_turn(
            db,
            turn_id=turn_id,
            content="".join(answer_parts),
            usage=usage,
            finish_reason=finish_reason,
            error_category=error_category,
        )
        await db.commit()
    except Exception:  # agent/DB không kết nối được → stream lỗi, vẫn persist kết quả
        logger.exception("chat.turn %s: proxy ChatAgent thất bại", turn_id)
        await db.rollback()
        error_event = _error("chat_stream_lost", "mất kết nối tới ChatAgent")
        try:
            await _finalize_turn(
                db,
                turn_id=turn_id,
                content="".join(answer_parts),
                usage=usage,
                finish_reason="error",
                error_category="chat_stream_lost",
            )
            await db.commit()
            await append_audit(
                db,
                action="chat.turn.gateway",
                actor=str(actor_id),
                target=str(turn_id),
                details={"reason": "agent_unreachable", "category": "chat_stream_lost"},
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("chat.turn %s: persist sau lỗi proxy thất bại", turn_id)
        yield _sse(
            {
                "v": SSE_SCHEMA_VERSION,
                "seq": seq,
                "type": "error",
                **error_event,
            }
        )


async def _finalize_turn(
    db: AsyncSession,
    *,
    turn_id: uuid.UUID,
    content: str,
    usage: dict,
    finish_reason: str,
    error_category: str | None,
) -> None:
    """Persist assistant message qua T8 `complete_turn` (idempotent theo digest)."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    await complete_turn(
        db,
        turn_id,
        content=content,
        finish_reason=finish_reason,
        usage=usage,
        content_digest=digest,
        error_category=error_category,
    )


def _error(category: str, hint: str, *, retryable: bool = False) -> dict:
    return {"category": category, "hint": hint, "retryable": retryable, "http_status": 502}


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
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        # Ghi nhận admission thất bại (DB) → fail closed như ngân sách không khả dụng.
        await db.rollback()
        raise _err(
            503, "chat_budget_unavailable", "không ghi nhận được lượt gửi (admission)"
        ) from exc

    return StreamingResponse(
        _stream_from_agent(
            db,
            conv=conv,
            turn=turn,
            actor_id=user.id,
            machine_id=machine_id,
            machine_ref=machine_ref,
        ),
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
