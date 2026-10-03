"""Tests cho turn lifecycle service (Task 8 — spec F7/R4, V5 winner & grace).

Chạy trên schema `Base.metadata.create_all` dựng trong `db_engine` fixture (test DB
không chạy alembic). Mọi test dùng session riêng + commit để transaction/advisory lock
hoạt động thật.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import (
    ChatConversation,
    ChatMessage,
    ChatTurn,
    Organization,
    OrgType,
    User,
    UserRole,
)
from app.services.chat_turns import (
    ChatTurnError,
    CompletionResult,
    TurnAuthzError,
    TurnConflictError,
    TurnNotFoundError,
    cancel_turn,
    claim_turn,
    complete_turn,
    create_turn,
    recover_stale_turns,
)

pytestmark = pytest.mark.asyncio

GRACE = 120  # khớp settings.chat_completion_grace_seconds


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _seed_conversation(session_factory):
    """Tạo org + user + conversation; trả (conv_id, user_id)."""
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid.uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T8",
            email=f"t8-{uuid.uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        conv = ChatConversation(created_by=user.id, title="t8")
        s.add(conv)
        await s.commit()
        return conv.id, user.id


@pytest_asyncio.fixture
async def conv_and_user(session_factory):
    conv_id, user_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv_id)
        user = await s.get(User, user_id)
        return conv, user


# ── create_turn ─────────────────────────────────────────────────


async def test_create_turn_pending_and_audited(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(
            s, conversation=conv, actor=user, machine_id=None, machine_ref="WS-01"
        )
        await s.commit()
        assert turn.status == "pending"
        assert turn.machine_ref == "WS-01"
        assert turn.actor_id == user.id

    from app.db.models import AuditLog

    async with session_factory() as s:
        actions = (
            (await s.execute(select(AuditLog.action))).scalars().all()
        )
        assert "chat.turn.start" in actions


async def test_create_turn_second_active_conflicts(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        await create_turn(s, conversation=conv, actor=user)
        await s.commit()
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        with pytest.raises(TurnConflictError) as ei:
            await create_turn(s, conversation=conv, actor=user)
        await s.rollback()
        assert ei.value.category == "chat_conflict_active_turn"
        assert ei.value.http_status == 409
        assert ei.value.active_turn_id is not None


async def test_create_turn_idempotent_same_key_replays(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        t1 = await create_turn(s, conversation=conv, actor=user, idempotency_key="k1")
        await s.commit()
        t1_id = t1.id
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        t2 = await create_turn(s, conversation=conv, actor=user, idempotency_key="k1")
        await s.commit()
        assert t2.id == t1_id


# ── claim_turn ──────────────────────────────────────────────────


async def test_claim_turn_pending_to_streaming(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        claimed = await claim_turn(s, turn_id)
        await s.commit()
        assert claimed is not None
        assert claimed.status == "streaming"
        assert claimed.started_at is not None


async def test_claim_turn_none_when_not_pending(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        await claim_turn(s, turn_id)
        await s.commit()
    async with session_factory() as s:
        assert await claim_turn(s, turn_id) is None


# ── complete_turn: winner ───────────────────────────────────────


async def test_complete_turn_stop_completes_and_persists_message(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        res = await complete_turn(
            s, turn_id, content="xin chào", usage={"output_tokens": 5, "total_tokens": 7},
            finish_reason="stop",
        )
        await s.commit()
        assert res.status == "ok"
        assert res.turn_status == "completed"
        assert res.message_id is not None
    async with session_factory() as s:
        turn = await s.get(ChatTurn, turn_id)
        assert turn.status == "completed"
        assert turn.finish_reason == "stop"
        assert turn.completion_committed_at is not None
        msg = (
            await s.execute(select(ChatMessage).where(ChatMessage.turn_id == turn_id))
        ).scalar_one()
        assert msg.role == "assistant" and msg.content == "xin chào"


async def test_complete_turn_error_maps_to_failed(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        res = await complete_turn(
            s, turn_id, content="partial", usage={"error_category": "chat_timeout_llm"},
            finish_reason="error",
        )
        await s.commit()
        assert res.status == "ok"
        assert res.turn_status == "failed"
        assert res.error_category == "chat_timeout_llm"
    async with session_factory() as s:
        turn = await s.get(ChatTurn, turn_id)
        assert turn.status == "failed" and turn.error_category == "chat_timeout_llm"


async def test_complete_turn_canceled_finish_reason(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        res = await complete_turn(s, turn_id, content="", usage=None, finish_reason="canceled")
        await s.commit()
        assert res.turn_status == "canceled"
    async with session_factory() as s:
        assert (await s.get(ChatTurn, turn_id)).status == "canceled"


async def test_complete_turn_settles_budget(session_factory, conv_and_user):
    from app.db.models import TokenReservation
    from app.services.budget import reserve

    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        await reserve(
            s, scope="chat_turn", operation_id=turn_id, envelope=100, budget=1000
        )
        await s.commit()
    async with session_factory() as s:
        await complete_turn(
            s, turn_id, content="ok", usage={"total_tokens": 42}, finish_reason="stop"
        )
        await s.commit()
    async with session_factory() as s:
        row = (
            await s.execute(
                select(TokenReservation).where(TokenReservation.operation_id == turn_id)
            )
        ).scalar_one()
        assert row.state == "settled" and row.actual == 42


# ── complete_turn: idempotency / conflict ───────────────────────


async def test_complete_turn_idempotent_same_content(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        await complete_turn(s, turn_id, content="same", usage=None, finish_reason="stop")
        await s.commit()
    async with session_factory() as s:
        res = await complete_turn(s, turn_id, content="same", usage=None, finish_reason="stop")
        await s.commit()
        assert res.status == "idempotent"


async def test_complete_turn_conflict_different_content(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        await complete_turn(s, turn_id, content="first", usage=None, finish_reason="stop")
        await s.commit()
    async with session_factory() as s:
        res = await complete_turn(s, turn_id, content="second", usage=None, finish_reason="stop")
        await s.commit()
        assert res.status == "conflict"
    async with session_factory() as s:
        msgs = (
            await s.execute(select(ChatMessage).where(ChatMessage.turn_id == turn_id))
        ).scalars().all()
        assert len(msgs) == 1  # conflict không persist thêm


# ── complete_turn: late output (grace) ──────────────────────────


async def test_complete_turn_late_output_within_grace(session_factory, conv_and_user):
    """Turn terminal (failed) + chưa commit, completion tới trong grace → persist message,
    giữ status terminal, đánh dấu `chat_late_output`."""
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    # Kết thúc turn thủ công (failed) với ended_at trong grace.
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        t.status = "failed"
        t.finish_reason = "error"
        t.error_category = "chat_stream_lost"
        t.ended_at = datetime.now(UTC) - timedelta(seconds=GRACE - 30)
        await s.commit()
    async with session_factory() as s:
        res = await complete_turn(
            s, turn_id, content="late but in grace", usage={"total_tokens": 3},
            finish_reason="stop",
        )
        await s.commit()
        assert res.status == "ok"
        assert res.turn_status == "failed"  # giữ nguyên terminal
    async with session_factory() as s:
        msg = (
            await s.execute(select(ChatMessage).where(ChatMessage.turn_id == turn_id))
        ).scalar_one()
        assert msg.content == "late but in grace"
        assert msg.error_category == "chat_late_output"


async def test_complete_turn_late_output_after_grace_expires(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        t.status = "failed"
        t.finish_reason = "error"
        t.error_category = "chat_stream_lost"
        t.ended_at = datetime.now(UTC) - timedelta(seconds=GRACE + 60)
        await s.commit()
    async with session_factory() as s:
        res = await complete_turn(
            s, turn_id, content="too late", usage=None, finish_reason="stop"
        )
        await s.commit()
        assert res.status == "late_expired"
    async with session_factory() as s:
        msgs = (
            await s.execute(select(ChatMessage).where(ChatMessage.turn_id == turn_id))
        ).scalars().all()
        assert msgs == []  # không persist


# ── cancel_turn ─────────────────────────────────────────────────


async def test_cancel_turn_by_owner(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        status = await cancel_turn(s, turn_id, actor=user)
        await s.commit()
        assert status.status == "canceled"
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        assert t.status == "canceled" and t.ended_at is not None


async def test_cancel_turn_by_other_actor_denied(session_factory, conv_and_user):
    conv, user = conv_and_user
    other = User(
        org_id=user.org_id,
        full_name="Other",
        email=f"other-{uuid.uuid4()}@example.com",
        role=UserRole.SUPER_ADMIN.value,
        password_hash="x",
    )
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        s.add(other)
        await s.commit()
        with pytest.raises(TurnAuthzError):
            await cancel_turn(s, turn_id, actor=other)
        await s.rollback()


async def test_cancel_turn_terminal_conflicts(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        t.status = "completed"
        await s.commit()
    async with session_factory() as s:
        with pytest.raises(TurnConflictError):
            await cancel_turn(s, turn_id, actor=user)
        await s.rollback()


async def test_cancel_turn_not_found(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        with pytest.raises(TurnNotFoundError):
            await cancel_turn(s, uuid.uuid4(), actor=user)
        await s.rollback()


# ── recover_stale_turns ─────────────────────────────────────────


async def test_recover_stale_turns_marks_dispatch_stuck(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        turn = await create_turn(s, conversation=conv, actor=user)
        await s.commit()
        turn_id = turn.id
    # Đẩy created_at về quá khứ > turn_pending_timeout_seconds.
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        t.created_at = datetime.now(UTC) - timedelta(seconds=600)
        await s.commit()
    async with session_factory() as s:
        n = await recover_stale_turns(s)
        await s.commit()
        assert n == 1
    async with session_factory() as s:
        t = await s.get(ChatTurn, turn_id)
        assert t.status == "failed"
        assert t.error_category == "chat_dispatch_stuck"


async def test_recover_stale_turns_ignores_fresh(session_factory, conv_and_user):
    conv, user = conv_and_user
    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv.id)
        await create_turn(s, conversation=conv, actor=user)
        await s.commit()
    async with session_factory() as s:
        n = await recover_stale_turns(s)
        await s.commit()
        assert n == 0


# ── error contract ──────────────────────────────────────────────


def test_error_format_matches_spec():
    err = TurnConflictError("x", active_turn_id=uuid.uuid4())
    assert err.category == "chat_conflict_active_turn"
    assert "[chat_conflict_active_turn]" in str(err)
    assert "[HTTP 409]" in str(err)
    assert isinstance(err, ChatTurnError)


def test_completion_result_defaults():
    r = CompletionResult(status="ok")
    assert r.message_id is None and r.turn_status is None
