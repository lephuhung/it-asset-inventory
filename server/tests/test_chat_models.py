"""Constraint tests cho schema Chat Assistant (Task 2).

Chạy trên schema do `Base.metadata.create_all` dựng trong `db_engine` fixture
(test DB không chạy alembic) — nên các ràng buộc ORM/model phải khớp DDL spec
§"Hợp đồng dữ liệu".
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.audit import append_audit
from app.db.models import (
    AuditLog,
    ChatAuditIntent,
    ChatConversation,
    ChatMessage,
    ChatToolCall,
    ChatTurn,
    Organization,
    OrgType,
    TokenReservation,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio


async def _seed_owner_and_conversation(session_factory):
    """Tạo org + user + conversation (không turn); trả (conv_id, user_id)."""
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T2",
            email=f"t2-{uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        conv = ChatConversation(created_by=user.id, title="t2")
        s.add(conv)
        await s.commit()
        return conv.id, user.id


async def _seed_conversation(session_factory):
    """Tạo org + user + conversation + 1 turn 'pending'; trả (conv_id, user_id, turn_id)."""
    conv_id, user_id = await _seed_owner_and_conversation(session_factory)
    async with session_factory() as s:
        turn = ChatTurn(
            conversation_id=conv_id,
            actor_id=user_id,
            request_id=uuid4(),
            status="pending",
            idempotency_key=f"idem-{uuid4()}",
        )
        s.add(turn)
        await s.commit()
        return conv_id, user_id, turn.id


@pytest_asyncio.fixture
async def make_conversation(session_factory):
    """Fixture: tạo hội thoại (chưa có turn) trong DB test."""

    async def _make() -> ChatConversation:
        conv_id, _ = await _seed_owner_and_conversation(session_factory)
        async with session_factory() as s:
            return await s.get(ChatConversation, conv_id)

    return _make


# ── chat_turns: 1 active turn / hội thoại (partial unique index) ─────────────


async def test_only_one_active_turn_per_conversation(session_factory, make_conversation):
    conv = await make_conversation()
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="pending",
                idempotency_key=f"a-{uuid4()}",
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="streaming",
                idempotency_key=f"b-{uuid4()}",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_terminal_turn_then_new_active_turn_allowed(session_factory, make_conversation):
    """Turn cũ đã 'completed' không chặn turn 'pending' kế tiếp (partial index)."""
    conv = await make_conversation()
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="completed",
                idempotency_key=f"done-{uuid4()}",
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="pending",
                idempotency_key=f"new-{uuid4()}",
            )
        )
        await s.commit()  # không được raise


async def test_turn_idempotency_key_unique_per_conversation(session_factory, make_conversation):
    """uq_chat_turn_idem: cùng (conversation_id, idempotency_key) bị từ chối.

    Cả hai turn ở trạng thái terminal ('completed') để lỗi chắc chắn đến từ
    constraint idempotency — nếu cả hai là 'pending', lỗi có thể đến từ index
    `uq_chat_turn_active` (1 active turn/hội thoại) và test sẽ pass sai lý do.
    """
    conv = await make_conversation()
    key = f"dup-{uuid4()}"
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="completed",
                idempotency_key=key,
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=conv.id,
                actor_id=conv.created_by,
                request_id=uuid4(),
                status="completed",
                idempotency_key=key,
            )
        )
        with pytest.raises(IntegrityError) as exc:
            await s.commit()
        assert "uq_chat_turn_idem" in str(exc.value.orig)
        await s.rollback()


# ── chat_messages: composite FK + check constraint ───────────────────────────


async def test_message_turn_must_belong_to_same_conversation(session_factory):
    """Message không được trỏ turn thuộc hội thoại khác (composite FK)."""
    _, _, turn_a = await _seed_conversation(session_factory)
    conv_b, _, _ = await _seed_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            ChatMessage(
                conversation_id=conv_b,  # khác conversation của turn_a
                turn_id=turn_a,
                role="user",
                content="cross-conversation",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_message_turn_in_same_conversation_allowed(session_factory):
    conv_id, _, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            ChatMessage(
                conversation_id=conv_id,
                turn_id=turn_id,
                role="user",
                content="ok",
            )
        )
        await s.commit()


async def test_non_system_message_requires_turn(session_factory, make_conversation):
    """ck_chat_msg_turn: role user/assistant bắt buộc có turn_id."""
    conv = await make_conversation()
    async with session_factory() as s:
        s.add(
            ChatMessage(
                conversation_id=conv.id,
                turn_id=None,
                role="assistant",
                content="no turn",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_system_message_without_turn_allowed(session_factory, make_conversation):
    conv = await make_conversation()
    async with session_factory() as s:
        s.add(
            ChatMessage(
                conversation_id=conv.id,
                turn_id=None,
                role="system",
                content="system note",
            )
        )
        await s.commit()


# ── chat_tool_calls: FK turn + unique + FK audit_log ─────────────────────────


async def test_tool_call_unique_per_turn(session_factory):
    _, _, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            ChatToolCall(
                turn_id=turn_id,
                tool_call_id="call-1",
                tool="inventory_search",
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            ChatToolCall(
                turn_id=turn_id,
                tool_call_id="call-1",
                tool="inventory_search",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_tool_call_audit_intent_ref_is_integer_fk_to_audit_log(session_factory):
    """audit_intent_id là INTEGER FK -> audit_log.id; hàng audit không tồn tại phải bị từ chối."""
    _, _, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        # trỏ tới audit_log id không tồn tại
        s.add(
            ChatToolCall(
                turn_id=turn_id,
                tool_call_id="call-audit",
                tool="run_vql",
                audit_intent_id=999_999_999,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_tool_call_audit_intent_ref_accepts_real_audit_row(session_factory):
    """audit_intent_id nhận id của hàng audit_log thật do append_audit sinh."""
    _, _, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        audit = await append_audit(
            s, action="chat.query.velociraptor", actor="u", target="t"
        )
        s.add(
            ChatToolCall(
                turn_id=turn_id,
                tool_call_id="call-audit-2",
                tool="run_vql",
                audit_intent_id=audit.id,
            )
        )
        await s.commit()
        assert isinstance(audit.id, int)


async def test_audit_intent_id_column_type_is_integer(session_factory):
    from sqlalchemy import BigInteger, Integer

    assert type(ChatToolCall.__table__.c.audit_intent_id.type) is Integer
    assert type(ChatToolCall.__table__.c.audit_outcome_id.type) is Integer
    assert type(AuditLog.__table__.c.id.type) is Integer
    # BigInteger là subclass của Integer — khẳng định loại trừ rõ ràng.
    assert not isinstance(ChatToolCall.__table__.c.audit_intent_id.type, BigInteger)


# ── chat_audit_intents: bền vững, KHÔNG cascade theo hội thoại ────────────────


async def test_audit_intent_survives_conversation_delete(session_factory):
    """R2: xoá hội thoại (cascade) không được xoá chat_audit_intents."""
    conv_id, user_id, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            ChatAuditIntent(
                turn_id=turn_id,
                tool_call_id="intent-1",
                conversation_id=conv_id,
                actor_id=user_id,
                tool="run_vql",
                args_digest="d" * 64,
            )
        )
        await s.commit()

    async with session_factory() as s:
        conv = await s.get(ChatConversation, conv_id)
        await s.delete(conv)
        await s.commit()

    async with session_factory() as s:
        remaining = (
            await s.execute(select(ChatAuditIntent).where(ChatAuditIntent.turn_id == turn_id))
        ).scalars().all()
        assert len(remaining) == 1


async def test_audit_intent_unique_turn_tool_call(session_factory):
    conv_id, user_id, turn_id = await _seed_conversation(session_factory)
    async with session_factory() as s:
        s.add(
            ChatAuditIntent(
                turn_id=turn_id,
                tool_call_id="intent-dup",
                conversation_id=conv_id,
                actor_id=user_id,
                tool="run_vql",
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            ChatAuditIntent(
                turn_id=turn_id,
                tool_call_id="intent-dup",
                conversation_id=conv_id,
                actor_id=user_id,
                tool="run_vql",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


# ── token_reservations ───────────────────────────────────────────────────────


async def test_token_reservation_unique_scope_operation(session_factory):
    op = uuid4()
    async with session_factory() as s:
        s.add(
            TokenReservation(
                scope="chat_turn",
                operation_id=op,
                budget_date=datetime.now(UTC).date(),
                reserved=10,
            )
        )
        await s.commit()
    async with session_factory() as s:
        s.add(
            TokenReservation(
                scope="chat_turn",
                operation_id=op,
                budget_date=datetime.now(UTC).date(),
                reserved=10,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_token_reservation_same_operation_different_scope_allowed(session_factory):
    op = uuid4()
    async with session_factory() as s:
        s.add_all(
            [
                TokenReservation(
                    scope="chat_turn",
                    operation_id=op,
                    budget_date=datetime.now(UTC).date(),
                    reserved=10,
                ),
                TokenReservation(
                    scope="investigation_analysis",
                    operation_id=op,
                    budget_date=datetime.now(UTC).date(),
                    reserved=10,
                ),
            ]
        )
        await s.commit()


# ── chat_conversations: FK machines/users ────────────────────────────────────


async def test_conversation_created_by_required(session_factory):
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        s.add(ChatConversation(created_by=uuid4(), title="no user"))
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_uuid_primary_keys_have_db_server_default(session_factory):
    """Finding 2: mọi PK chat dùng DEFAULT gen_random_uuid() ở tầng DB.

    Chèn thẳng bằng SQL, KHÔNG truyền `id`, để chứng minh server default của
    PostgreSQL sinh id — không phải Python default của ORM.
    """
    conv_id, user_id = await _seed_owner_and_conversation(session_factory)

    async with session_factory() as s:
        await s.execute(
            text("INSERT INTO chat_conversations (created_by) VALUES (:u)"),
            {"u": user_id},
        )
        await s.execute(
            text(
                "INSERT INTO chat_turns (conversation_id, actor_id, request_id) "
                "VALUES (:c, :a, :r)"
            ),
            {"c": conv_id, "a": user_id, "r": uuid4()},
        )
        await s.flush()
        turn_id = (await s.execute(text("SELECT id FROM chat_turns LIMIT 1"))).scalar_one()
        await s.execute(
            text(
                "INSERT INTO chat_messages (conversation_id, role, content) "
                "VALUES (:c, 'system', 'x')"
            ),
            {"c": conv_id},
        )
        await s.execute(
            text(
                "INSERT INTO chat_tool_calls (turn_id, tool_call_id, tool) "
                "VALUES (:t, 'raw-1', 'run_vql')"
            ),
            {"t": turn_id},
        )
        await s.execute(
            text(
                "INSERT INTO chat_audit_intents "
                "(turn_id, tool_call_id, conversation_id, actor_id, tool) "
                "VALUES (:t, 'raw-intent-1', :c, :a, 'run_vql')"
            ),
            {"t": turn_id, "c": conv_id, "a": user_id},
        )
        await s.execute(
            text(
                "INSERT INTO token_reservations "
                "(scope, operation_id, budget_date, reserved) "
                "VALUES ('chat_turn', :op, CURRENT_DATE, 5)"
            ),
            {"op": uuid4()},
        )
        await s.commit()

    async with session_factory() as s:
        for table in (
            "chat_conversations",
            "chat_turns",
            "chat_messages",
            "chat_tool_calls",
            "chat_audit_intents",
            "token_reservations",
        ):
            generated = (await s.execute(text(f"SELECT id FROM {table}"))).scalars().all()
            assert generated, f"{table}: không có hàng nào"
            for value in generated:
                assert value is not None, f"{table}: id NULL"
                assert isinstance(value, UUID), f"{table}: id không phải UUID ({value!r})"


async def test_created_at_default_is_fresh_per_insert(session_factory):
    """Finding 1: default timestamp phải là callable — mỗi insert một mốc mới.

    Nếu dùng `default=datetime.now(UTC)` (không phải lambda), giá trị bị đóng
    băng ngay lúc import module: mọi insert dùng CÙNG một mốc và mốc đó nhỏ hơn
    `before` của test này.
    """

    async def _new_conversation() -> tuple[UUID, datetime]:
        async with session_factory() as s:
            org = Organization(name=f"Org {uuid4()}", type=OrgType.ROOT.value)
            s.add(org)
            await s.flush()
            user = User(
                org_id=org.id,
                full_name="ts",
                email=f"ts-{uuid4()}@example.com",
                role=UserRole.SUPER_ADMIN.value,
                password_hash="x",
            )
            s.add(user)
            await s.flush()
            conv = ChatConversation(created_by=user.id, title="ts")
            s.add(conv)
            await s.commit()
            return conv.id, conv.created_at

    before = datetime.now(UTC)
    conv_a, created_a = await _new_conversation()
    await asyncio.sleep(0.002)
    conv_b, created_b = await _new_conversation()
    after = datetime.now(UTC)

    # Mỗi insert một mốc mới — không đóng băng tại thời điểm import.
    assert before <= created_a <= after
    assert before <= created_b <= after
    assert created_a < created_b

    async with session_factory() as s:
        row_a = await s.get(ChatConversation, conv_a)
        row_b = await s.get(ChatConversation, conv_b)
        assert row_a.created_at is not None and row_b.created_at is not None
        assert before <= row_a.created_at <= after
        assert before <= row_b.created_at <= after
        assert row_a.created_at < row_b.created_at
        assert before <= row_a.updated_at <= after
        assert before <= row_b.updated_at <= after
