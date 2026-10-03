"""Vòng đời turn chat (Task 8) — CAS completion, ân hạn, cancel, recover.

Chạy trên schema `Base.metadata.create_all` của fixture `db_engine` (test DB không
chạy alembic). Mọi test commit trong session riêng rồi xác minh ở session mới để
không bị che bởi identity map (`expire_on_commit=False`).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.audit import verify_chain
from app.core.config import settings
from app.db.models import (
    ChatConversation,
    ChatMessage,
    ChatTurn,
    Organization,
    OrgType,
    TokenReservation,
    User,
    UserRole,
)
from app.services.budget import reserve
from app.services.chat_turns import (
    ActiveTurnExists,
    ChatTurnError,
    claim_turn,
    complete_turn,
    content_digest_of,
    create_turn,
    cancel_turn,
    recover_stale_turns,
)

pytestmark = pytest.mark.asyncio


async def _seed_conversation(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Tạo org + user + conversation; trả (conversation_id, user_id)."""
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T8",
            email=f"t8-{uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        conv = ChatConversation(created_by=user.id, title="t8")
        s.add(conv)
        await s.commit()
        return conv.id, user.id


async def _make_pending_turn(session_factory, conv_id, user_id, **kwargs):
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv_id)
        turn = await create_turn(s, conv, user_id, **kwargs)
        await s.commit()
        return turn


async def _assistant_messages(session_factory, turn_id):
    async with session_factory() as s:
        return (
            (
                await s.execute(
                    select(ChatMessage)
                    .where(ChatMessage.turn_id == turn_id, ChatMessage.role == "assistant")
                    .order_by(ChatMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


# ── create_turn ──────────────────────────────────────────────────────────────


async def test_create_turn_basic(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id, machine_ref="WS-01")

    assert turn.status == "pending"
    assert turn.actor_id == user_id
    assert turn.machine_ref == "WS-01"
    assert turn.request_id is not None
    assert turn.completion_committed_at is None

    async with session_factory() as s:
        ok, bad = await verify_chain(s)
    assert ok is True, f"audit chain hỏng tại {bad}"


async def test_create_turn_idempotency_key_returns_existing(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    first = await _make_pending_turn(session_factory, conv_id, user_id, idempotency_key="k1")
    second = await _make_pending_turn(session_factory, conv_id, user_id, idempotency_key="k1")

    assert second.id == first.id

    async with session_factory() as s:
        count = len((await s.execute(select(ChatTurn.id))).scalars().all())
    assert count == 1


async def test_create_turn_active_conflict(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    first = await _make_pending_turn(session_factory, conv_id, user_id, idempotency_key="k1")

    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv_id)
        with pytest.raises(ActiveTurnExists) as excinfo:
            await create_turn(s, conv, user_id, idempotency_key="k2")
    assert excinfo.value.active_turn_id == first.id


async def test_create_turn_after_terminal_allowed(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    first = await _make_pending_turn(session_factory, conv_id, user_id, idempotency_key="k1")

    async with session_factory() as s:
        turn = await s.get(ChatTurn, first.id)
        turn.status = "completed"
        turn.finish_reason = "stop"
        turn.ended_at = datetime.now(UTC)
        await s.commit()

    second = await _make_pending_turn(session_factory, conv_id, user_id, idempotency_key="k2")
    assert second.id != first.id
    assert second.status == "pending"


# ── claim_turn ───────────────────────────────────────────────────────────────


async def test_claim_turn_moves_pending_to_streaming(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        claimed = await claim_turn(s, turn.id)
        await s.commit()

    assert claimed is not None
    assert claimed.status == "streaming"
    assert claimed.started_at is not None


async def test_claim_turn_returns_none_when_not_pending(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        assert await claim_turn(s, turn.id) is not None
        await s.commit()
    async with session_factory() as s:
        assert await claim_turn(s, turn.id) is None  # đã streaming
    async with session_factory() as s:
        assert await claim_turn(s, uuid.uuid4()) is None  # không tồn tại


# ── complete_turn ────────────────────────────────────────────────────────────


async def test_complete_turn_ok(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        result = await complete_turn(
            s,
            turn.id,
            content="xin chào",
            finish_reason="stop",
            usage={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
            content_digest=content_digest_of("xin chào"),
        )
        await s.commit()

    assert result.status == "ok"
    assert result.message_id is not None

    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
        assert saved.status == "completed"
        assert saved.finish_reason == "stop"
        assert saved.completion_committed_at is not None
        assert saved.ended_at is not None

    messages = await _assistant_messages(session_factory, turn.id)
    assert len(messages) == 1
    assert messages[0].content == "xin chào"
    assert messages[0].output_tokens == 7
    assert messages[0].input_tokens == 5
    assert messages[0].error_category is None

    async with session_factory() as s:
        ok, bad = await verify_chain(s)
    assert ok is True, f"audit chain hỏng tại {bad}"


async def test_complete_turn_error_failed(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        result = await complete_turn(
            s,
            turn.id,
            content="partial output",
            finish_reason="error",
            error_category="chat_timeout_llm",
            content_digest=content_digest_of("partial output"),
        )
        await s.commit()

    assert result.status == "ok"
    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
        assert saved.status == "failed"
        assert saved.finish_reason == "error"
        assert saved.error_category == "chat_timeout_llm"

    messages = await _assistant_messages(session_factory, turn.id)
    assert len(messages) == 1
    assert messages[0].error_category == "chat_timeout_llm"


async def test_complete_turn_error_rejects_unknown_category(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        with pytest.raises(ChatTurnError):
            await complete_turn(
                s,
                turn.id,
                content="x",
                finish_reason="error",
                error_category="not_in_taxonomy",
            )


async def test_complete_turn_invalid_finish_reason(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        with pytest.raises(ChatTurnError):
            await complete_turn(s, turn.id, content="x", finish_reason="bogus")


async def test_complete_turn_canceled(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        result = await complete_turn(
            s,
            turn.id,
            content="stopped",
            finish_reason="canceled",
            content_digest=content_digest_of("stopped"),
        )
        await s.commit()

    assert result.status == "ok"
    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
        assert saved.status == "canceled"
        assert saved.finish_reason == "canceled"


async def test_complete_turn_idempotent_same_content(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        first = await complete_turn(
            s,
            turn.id,
            content="same",
            finish_reason="stop",
            content_digest=content_digest_of("same"),
        )
        await s.commit()
    async with session_factory() as s:
        second = await complete_turn(
            s,
            turn.id,
            content="same",
            finish_reason="stop",
            content_digest=content_digest_of("same"),
        )
        await s.commit()

    assert first.status == "ok"
    assert second.status == "idempotent"
    assert second.message_id == first.message_id
    assert len(await _assistant_messages(session_factory, turn.id)) == 1


async def test_complete_turn_conflict_different_content(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        await complete_turn(
            s,
            turn.id,
            content="first",
            finish_reason="stop",
            content_digest=content_digest_of("first"),
        )
        await s.commit()
    async with session_factory() as s:
        second = await complete_turn(
            s,
            turn.id,
            content="second",
            finish_reason="stop",
            content_digest=content_digest_of("second"),
        )
        await s.commit()

    assert second.status == "conflict"
    messages = await _assistant_messages(session_factory, turn.id)
    assert len(messages) == 1
    assert messages[0].content == "first"


async def test_complete_turn_late_within_grace_preserves_terminal(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        status = await cancel_turn(s, turn.id, user_id)
        await s.commit()
    assert status.status == "canceled"

    async with session_factory() as s:
        result = await complete_turn(
            s,
            turn.id,
            content="late but in grace",
            finish_reason="stop",
            content_digest=content_digest_of("late but in grace"),
        )
        await s.commit()

    assert result.status == "ok"
    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
        assert saved.status == "canceled"  # giữ nguyên terminal
        assert saved.completion_committed_at is not None

    messages = await _assistant_messages(session_factory, turn.id)
    assert len(messages) == 1
    assert messages[0].error_category == "chat_late_output"


async def test_complete_turn_late_after_grace_rejected(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        await cancel_turn(s, turn.id, user_id)
        saved = await s.get(ChatTurn, turn.id)
        saved.ended_at = datetime.now(UTC) - timedelta(
            seconds=settings.chat_completion_grace_seconds + 60
        )
        await s.commit()

    async with session_factory() as s:
        result = await complete_turn(
            s,
            turn.id,
            content="too late",
            finish_reason="stop",
            content_digest=content_digest_of("too late"),
        )
        await s.commit()

    assert result.status == "late_expired"
    assert result.message_id is None
    assert await _assistant_messages(session_factory, turn.id) == []


async def test_complete_turn_not_found(session_factory):
    async with session_factory() as s:
        result = await complete_turn(s, uuid.uuid4(), content="x", finish_reason="stop")
    assert result.status == "not_found"


async def test_complete_turn_precedence_completion_before_cancel(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        await complete_turn(
            s,
            turn.id,
            content="done",
            finish_reason="stop",
            content_digest=content_digest_of("done"),
        )
        await s.commit()
    async with session_factory() as s:
        status = await cancel_turn(s, turn.id, user_id)
        await s.commit()

    assert status.status == "already_terminal"
    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
    assert saved.status == "completed"


# ── cancel_turn ──────────────────────────────────────────────────────────────


async def test_cancel_turn_active(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        status = await cancel_turn(s, turn.id, user_id)
        await s.commit()
    assert status.status == "canceled"

    async with session_factory() as s:
        saved = await s.get(ChatTurn, turn.id)
        assert saved.status == "canceled"
        assert saved.ended_at is not None


async def test_cancel_turn_missing(session_factory):
    async with session_factory() as s:
        status = await cancel_turn(s, uuid.uuid4(), uuid.uuid4())
    assert status.status == "not_found"


# ── recover_stale_turns ──────────────────────────────────────────────────────


async def test_recover_stale_turns(session_factory):
    stale_conv, stale_user = await _seed_conversation(session_factory)
    fresh_conv, fresh_user = await _seed_conversation(session_factory)
    stale = await _make_pending_turn(session_factory, stale_conv, stale_user)
    fresh = await _make_pending_turn(session_factory, fresh_conv, fresh_user)

    async with session_factory() as s:
        turn = await s.get(ChatTurn, stale.id)
        turn.created_at = datetime.now(UTC) - timedelta(
            seconds=settings.turn_pending_timeout_seconds + 30
        )
        await s.commit()

    async with session_factory() as s:
        recovered = await recover_stale_turns(s)
        await s.commit()

    assert recovered == 1
    async with session_factory() as s:
        stale_saved = await s.get(ChatTurn, stale.id)
        fresh_saved = await s.get(ChatTurn, fresh.id)
    assert stale_saved.status == "failed"
    assert stale_saved.error_category == "chat_dispatch_stuck"
    assert stale_saved.finish_reason == "error"
    assert fresh_saved.status == "pending"


# ── budget settle ────────────────────────────────────────────────────────────


async def test_complete_turn_settles_budget_actual(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        await reserve(
            s,
            scope="chat_turn",
            operation_id=turn.id,
            association_id=None,
            envelope=100,
            budget=100000,
        )
        await s.commit()

    async with session_factory() as s:
        await complete_turn(
            s,
            turn.id,
            content="x",
            finish_reason="stop",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            content_digest=content_digest_of("x"),
        )
        await s.commit()

    async with session_factory() as s:
        row = (
            await s.execute(
                select(TokenReservation).where(TokenReservation.operation_id == turn.id)
            )
        ).scalar_one()
    assert row.state == "settled"
    assert row.actual == 30


async def test_complete_turn_unknown_usage_charges_envelope(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    turn = await _make_pending_turn(session_factory, conv_id, user_id)

    async with session_factory() as s:
        await reserve(
            s,
            scope="chat_turn",
            operation_id=turn.id,
            association_id=None,
            envelope=100,
            budget=100000,
        )
        await s.commit()

    async with session_factory() as s:
        await complete_turn(
            s,
            turn.id,
            content="no usage reported",
            finish_reason="stop",
            usage=None,
            content_digest=content_digest_of("no usage reported"),
        )
        await s.commit()

    async with session_factory() as s:
        row = (
            await s.execute(
                select(TokenReservation).where(TokenReservation.operation_id == turn.id)
            )
        ).scalar_one()
    assert row.state == "unknown"
    assert row.reserved == 100
