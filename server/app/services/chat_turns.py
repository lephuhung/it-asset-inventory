"""Vòng đời turn chat — spec F7/R4, V3-3/V5.

Dịch vụ này sở hữu state machine của `chat_turns`:

    pending ──claim──▶ streaming ──complete──▶ completed
        │                  │
        │                  ├──▶ failed(error_category)
        │                  └──▶ canceled
        ├──▶ failed(chat_dispatch_stuck)   # recover_stale_turns
        └──▶ canceled                      # cancel_turn

**CAS trên `completion_committed_at`.** `complete_turn` khóa hàng bằng
`SELECT ... FOR UPDATE` rồi rẽ nhánh theo `completion_committed_at IS NULL`. Khóa
hàng tuần tự hóa mọi completer của cùng một turn, nên đúng một winner ghi
assistant message + `completion_committed_at` + usage; completer đến sau chỉ có
thể idempotent (trùng nội dung) hoặc conflict (khác nội dung) — không bao giờ ghi
đè.

**Idempotency completion.** DDL spec §"Hợp đồng dữ liệu" của `chat_turns` KHÔNG có
cột `content_digest`, nên không thể lưu digest trực tiếp. Thay vào đó, khi
`completion_committed_at` đã set, ta lấy assistant message đã persist của turn và
so digest nội dung của nó với `content_digest` do caller truyền (hợp đồng:
`content_digest == content_digest_of(content)`). Trùng → `idempotent`; khác →
`conflict` + audit `chat.turn.late_output`. Không thêm cột ngoài spec.

**Settle ngân sách là best-effort** (spec R8): kết quả hoàn thành đã persist phải
được giữ kể cả khi DB ngân sách lỗi. `_settle_best_effort` cô lập settle trong một
savepoint — lỗi ngân sách rollback về savepoint, giữ nguyên message + status, rồi
để caller commit. Không bao giờ biến một completion đã hoàn thành thành thất bại.

**Caller sở hữu transaction.** T8 chỉ `flush` (giống `append_audit`); route phải
commit. Caller phải reserve ngân sách (scope `chat_turn`, `operation_id=turn.id`)
TRƯỚC khi dispatch; `complete_turn` settle reservation đó.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit
from app.core.config import settings
from app.db.models import ChatConversation, ChatMessage, ChatTurn
from app.services.budget import BudgetConflict, BudgetUnavailable, settle

logger = logging.getLogger(__name__)

# Turn đang chiếm "active slot" (partial unique index `uq_chat_turn_active`).
ACTIVE_STATUSES = frozenset({"pending", "streaming"})
# Turn đã kết thúc — không còn active slot, nhưng còn cửa sổ ân hạn completion.
TERMINAL_STATUSES = frozenset({"completed", "failed", "canceled"})

# finish_reason (agent báo) → status turn (spec V5).
FINISH_REASON_TO_STATUS = {
    "stop": "completed",
    "length": "completed",
    "canceled": "canceled",
    "error": "failed",
}

# Error taxonomy (spec "SSE event schema"). `error_category` của turn failed phải
# thuộc tập này để route/portal map được.
ERROR_CATEGORIES = frozenset(
    {
        "chat_validation",
        "chat_authz",
        "chat_not_found",
        "chat_conflict_active_turn",
        "chat_conflict_idempotency",
        "chat_rate_limited",
        "chat_budget_exceeded",
        "chat_budget_unavailable",
        "chat_guardrail_sql",
        "chat_guardrail_vql",
        "chat_collection_denied",
        "chat_timeout_llm",
        "chat_timeout_tool",
        "chat_upstream_llm",
        "chat_upstream_velo",
        "chat_mcp_bridge",
        "chat_canceled",
        "chat_stream_lost",
        "chat_dispatch_stuck",
        "chat_internal",
    }
)

# Nhãn cho output đến muộn sau khi turn đã terminal (spec V5).
LATE_OUTPUT_ERROR_CATEGORY = "chat_late_output"


class ChatTurnError(ValueError):
    """Vi phạm ràng buộc vòng đời turn."""


class ActiveTurnExists(ChatTurnError):
    """Hội thoại đã có 1 turn active (partial unique index) — route map sang 409."""

    def __init__(self, active_turn_id: uuid.UUID) -> None:
        super().__init__(
            f"hội thoại đang có turn active {active_turn_id} (chat_conflict_active_turn)"
        )
        self.active_turn_id = active_turn_id


@dataclass(frozen=True)
class CompletionResult:
    """Kết quả `complete_turn` — một trong: ok | idempotent | conflict | not_found | late_expired."""

    status: str
    message_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TurnStatus:
    """Kết quả `cancel_turn` — một trong: canceled | already_terminal | not_found."""

    status: str
    turn_id: uuid.UUID | None = None


def content_digest_of(content: str) -> str:
    """Digest chuẩn của nội dung completion (hợp đồng cho tham số `content_digest`)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_error_category(error_category: str | None) -> None:
    if error_category is not None and error_category not in ERROR_CATEGORIES:
        raise ChatTurnError(f"error_category không thuộc taxonomy: {error_category!r}")


def _within_grace(turn: ChatTurn, now: datetime) -> bool:
    """Completion đến muộn còn trong ân hạn tính từ `ended_at` (mốc terminal)."""
    if turn.ended_at is None:
        return False
    return now <= turn.ended_at + timedelta(seconds=settings.chat_completion_grace_seconds)


def _action_for_finish(finish_reason: str) -> str:
    if finish_reason == "error":
        return "chat.turn.fail"
    if finish_reason == "canceled":
        return "chat.turn.cancel"
    return "chat.turn.complete"


async def _lock_turn(db: AsyncSession, turn_id: uuid.UUID) -> ChatTurn | None:
    """Khóa hàng turn (`SELECT ... FOR UPDATE`) — nền tảng cho CAS completion.

    Dùng `populate_existing=True` để refresh mọi trường khi session đã load trước:
    tránh stale ORM state khi một session khác đã commit xong trong khi session này
    vẫn giữ bản cũ của đối tượng (CAS concurrent-completer attack).
    """
    return (
        await db.execute(
            select(ChatTurn)
            .where(ChatTurn.id == turn_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _audit_turn(
    db: AsyncSession,
    turn: ChatTurn,
    *,
    action: str,
    actor: str,
    details: dict | None = None,
) -> None:
    base_details = {
        "conversation_id": str(turn.conversation_id),
        "machine_ref": turn.machine_ref,
    }
    if details:
        base_details.update(details)
    await append_audit(
        db,
        action=action,
        actor=actor,
        target=str(turn.id),
        request_id=str(turn.request_id),
        machine_id=turn.machine_id,
        details=base_details,
    )


async def _settle_best_effort(db: AsyncSession, turn_id: uuid.UUID, actual: int | None) -> None:
    """Settle reservation của turn — best-effort (spec R8).

    Cô lập trong savepoint: lỗi ngân sách (`chat_budget_unavailable`) hoặc settle
    xung đột chỉ rollback về savepoint, KHÔNG làm abort transaction đang giữ
    assistant message + status. Nhờ đó caller vẫn commit được kết quả đã hoàn thành.

    Catch rộng (SQLAlchemyError) vì `settle` chỉ stage ORM fields và flush/raise có
    thể xảy ra khi savepoint context thoát, ngoài handler của `settle`.
    """
    try:
        async with db.begin_nested():
            await settle(db, scope="chat_turn", operation_id=turn_id, actual=actual)
    except (BudgetUnavailable, BudgetConflict):
        logger.exception(
            "chat.turn: settle ngân sách thất bại — giữ nguyên kết quả đã hoàn thành"
        )
    except SQLAlchemyError:
        logger.exception(
            "chat.turn: DB lỗi khi settle ngân sách — giữ nguyên kết quả đã hoàn thành"
        )


async def create_turn(
    db: AsyncSession,
    conversation: ChatConversation,
    actor: uuid.UUID,
    machine_id: uuid.UUID | None = None,
    machine_ref: str | None = None,
    idempotency_key: str | None = None,
) -> ChatTurn:
    """Tạo turn `pending` cho hội thoại. Chỉ 1 turn active/hội thoại.

    - `idempotency_key` trùng trong cùng hội thoại → trả lại turn cũ (retry an toàn).
    - Đã có turn active khác → `ActiveTurnExists` (route map `409` + `active_turn_id`).
    - Audit `chat.turn.start`. Caller commit.
    """
    conversation_id = conversation.id
    if idempotency_key is not None:
        existing = (
            await db.execute(
                select(ChatTurn).where(
                    ChatTurn.conversation_id == conversation_id,
                    ChatTurn.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    turn = ChatTurn(
        conversation_id=conversation_id,
        actor_id=actor,
        machine_id=machine_id,
        machine_ref=machine_ref,
        status="pending",
        idempotency_key=idempotency_key,
        request_id=uuid.uuid4(),
    )
    db.add(turn)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Rollback để giải phóng transaction đang abort, rồi phân loại race.
        await db.rollback()
        if idempotency_key is not None:
            replayed = (
                await db.execute(
                    select(ChatTurn).where(
                        ChatTurn.conversation_id == conversation_id,
                        ChatTurn.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if replayed is not None:
                return replayed
        active_id = (
            await db.execute(
                select(ChatTurn.id).where(
                    ChatTurn.conversation_id == conversation_id,
                    ChatTurn.status.in_(tuple(ACTIVE_STATUSES)),
                )
            )
        ).scalar_one_or_none()
        if active_id is not None:
            raise ActiveTurnExists(active_id) from exc
        raise ChatTurnError(f"không tạo được turn cho hội thoại {conversation_id}") from exc

    await _audit_turn(db, turn, action="chat.turn.start", actor=str(actor))
    return turn


async def claim_turn(db: AsyncSession, turn_id: uuid.UUID) -> ChatTurn | None:
    """Claim turn `pending` → `streaming` (bắt đầu xử lý). Trả `None` nếu không claim được.

    Chỉ turn `pending` mới claim được; turn đã `streaming`/terminal trả `None` để
    caller biết turn đã được (hoặc không còn) dispatch.
    """
    turn = await _lock_turn(db, turn_id)
    if turn is None or turn.status != "pending":
        return None
    turn.status = "streaming"
    turn.started_at = datetime.now(UTC)
    await db.flush()
    return turn


async def complete_turn(
    db: AsyncSession,
    turn_id: uuid.UUID,
    *,
    content: str,
    finish_reason: str,
    usage: dict | None = None,
    content_digest: str | None = None,
    error_category: str | None = None,
) -> CompletionResult:
    """Completion winner — CAS trên `completion_committed_at` (spec V3-3/V5).

    Turn `pending|streaming`: winner đặt status theo `finish_reason`
    (`stop|length`→completed, `canceled`→canceled, `error`→failed), persist assistant
    message (kể cả partial) + usage, set `completion_committed_at`, audit + settle.

    Turn đã terminal: trong ân hạn (tính từ `ended_at`) → giữ nguyên status, vẫn
    persist message (gắn `chat_late_output` nếu terminal là canceled/failed). Ngoài
    ân hạn → `late_expired` + audit. Đã có `completion_committed_at` → trùng digest
    thì `idempotent`, khác thì `conflict` + audit `chat.turn.late_output`.
    """
    if finish_reason not in FINISH_REASON_TO_STATUS:
        raise ChatTurnError(f"finish_reason không hợp lệ: {finish_reason!r}")
    _validate_error_category(error_category)
    # Spec V5 yêu cầu `failed` phải có `error_category` thuộc taxonomy. Mặc định
    # `chat_internal` nếu caller không truyền (route luôn có thể mappping bên được).
    if finish_reason == "error" and error_category is None:
        error_category = "chat_internal"

    now = datetime.now(UTC)
    turn = await _lock_turn(db, turn_id)
    if turn is None:
        return CompletionResult(status="not_found")

    digest = content_digest if content_digest is not None else content_digest_of(content)
    usage = usage or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")

    # ── Winner (chưa có completion nào commit) ──
    if turn.completion_committed_at is None:
        if turn.status in ACTIVE_STATUSES:
            turn.status = FINISH_REASON_TO_STATUS[finish_reason]
            turn.finish_reason = finish_reason
            turn.ended_at = now
            if finish_reason == "error":
                turn.error_category = error_category
            message_error_category = error_category if finish_reason == "error" else None
            action = _action_for_finish(finish_reason)
        elif _within_grace(turn, now):
            # Giữ nguyên status terminal; output muộn vẫn được persist.
            message_error_category = (
                LATE_OUTPUT_ERROR_CATEGORY if turn.status in {"canceled", "failed"} else None
            )
            action = {
                "completed": "chat.turn.complete",
                "failed": "chat.turn.fail",
                "canceled": "chat.turn.cancel",
            }.get(turn.status, "chat.turn.complete")
        else:
            await _audit_turn(
                db,
                turn,
                action="chat.turn.late_output_expired",
                actor=str(turn.actor_id),
                details={"finish_reason": finish_reason},
            )
            return CompletionResult(status="late_expired")

        message = ChatMessage(
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            role="assistant",
            content=content,
            machine_id=turn.machine_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_category=message_error_category,
        )
        db.add(message)
        turn.completion_committed_at = now
        await db.flush()
        await _audit_turn(db, turn, action=action, actor=str(turn.actor_id))
        await _settle_best_effort(db, turn.id, total_tokens)
        return CompletionResult(status="ok", message_id=message.id)

    # ── Đã có winner: idempotent (trùng nội dung) hoặc conflict (khác) ──
    stored = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.turn_id == turn.id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if stored is not None and content_digest_of(stored.content) == digest:
        return CompletionResult(status="idempotent", message_id=stored.id)

    await _audit_turn(
        db,
        turn,
        action="chat.turn.late_output",
        actor=str(turn.actor_id),
        details={"finish_reason": finish_reason},
    )
    return CompletionResult(status="conflict")


async def cancel_turn(db: AsyncSession, turn_id: uuid.UUID, actor: uuid.UUID) -> TurnStatus:
    """Hủy turn đang active (`pending|streaming`) → `canceled` + audit.

    Chỉ `conversation.created_by` (actor của turn) mới có thể hủy. Turn đã terminal
    → `already_terminal` (route map 409). Không tìm thấy → `not_found`. Không có
    quyền → `unauthorized`.
    """
    turn = await _lock_turn(db, turn_id)
    if turn is None:
        return TurnStatus(status="not_found")
    # AuthZ: chỉ actor của turn (chính là conversation.created_by) được hủy.
    if turn.actor_id != actor:
        return TurnStatus(status="unauthorized", turn_id=turn.id)
    if turn.status not in ACTIVE_STATUSES:
        return TurnStatus(status="already_terminal", turn_id=turn.id)

    turn.status = "canceled"
    turn.finish_reason = "canceled"
    turn.ended_at = datetime.now(UTC)
    await db.flush()
    await _audit_turn(db, turn, action="chat.turn.cancel", actor=str(actor))
    return TurnStatus(status="canceled", turn_id=turn.id)


async def recover_stale_turns(db: AsyncSession) -> int:
    """Fail các turn `pending` quá `turn_pending_timeout_seconds` → `failed(chat_dispatch_stuck)`.

    Trả số turn đã chuyển. Audit `chat.turn.fail` cho từng turn. Caller commit.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.turn_pending_timeout_seconds)
    rows = (
        await db.execute(
            update(ChatTurn)
            .where(ChatTurn.status == "pending", ChatTurn.created_at < cutoff)
            .values(
                status="failed",
                finish_reason="error",
                error_category="chat_dispatch_stuck",
                ended_at=datetime.now(UTC),
            )
            .returning(
                ChatTurn.id,
                ChatTurn.conversation_id,
                ChatTurn.actor_id,
                ChatTurn.request_id,
                ChatTurn.machine_id,
                ChatTurn.machine_ref,
            )
            .execution_options(synchronize_session=False)
        )
    ).all()
    for row in rows:
        await append_audit(
            db,
            action="chat.turn.fail",
            actor=str(row.actor_id),
            target=str(row.id),
            request_id=str(row.request_id),
            machine_id=row.machine_id,
            details={
                "conversation_id": str(row.conversation_id),
                "machine_ref": row.machine_ref,
                "error_category": "chat_dispatch_stuck",
            },
        )
    return len(rows)
