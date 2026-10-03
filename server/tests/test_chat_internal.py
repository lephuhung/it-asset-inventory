"""Task 10 — internal chat routes `/api/internal/chat` (spec §"Nội bộ", §V5).

Auth hai lớp: service token (`X-Service-Token`) cho MỌI endpoint; capability
(`X-Chat-Context`) cho query/intent; intent record (`chat_audit_intents`) cho
outcome/reconcile — cố ý KHÔNG cần capability (chạy được cả khi capability đã hết
hạn, actor lấy từ intent).

Chạy trên schema `Base.metadata.create_all` của fixture `db_engine`. Inventory
route dùng chung session test (override `get_chat_ro_session`) đọc view
`v_chat_machines` tạo riêng trong fixture — không cần role `inventory_chat_ro`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.chat_capability import (
    hash_completion_token,
    new_completion_token,
    sign_capability,
)
from app.core.config import settings
from app.db.models import (
    ChatAuditIntent,
    ChatConversation,
    ChatMessage,
    ChatTurn,
    Organization,
    OrgType,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio

SERVICE = settings.chat_service_token
SERVICE_HEADERS = {"X-Service-Token": SERVICE}


# ── Fixtures / helpers ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api(client, session_factory):
    """`client` + override `get_chat_ro_session` + view manifest tối thiểu.

    View tạo trong schema mặc định của session test (không cần role thật T3):
    T10 chỉ kiểm tra route wiring; guardrail/role đã được T9/T3 phủ.
    """
    from app.db.session import get_chat_ro_session
    from app.main import app

    async with session_factory() as s:
        await s.execute(
            text(
                """
                CREATE OR REPLACE VIEW v_chat_machines AS
                SELECT id, hostname, org_name, os_name, os_version, status, last_seen,
                       eol_flag
                FROM (VALUES
                  ('00000000-0000-0000-0000-000000000001'::uuid, 'WS-01', 'Org A',
                   'Windows 11', '23H2', 'online', now(), false),
                  ('00000000-0000-0000-0000-000000000002'::uuid, 'WS-02', 'Org B',
                   'Windows 10', '22H2', 'offline', now(), true)
                ) AS t(id, hostname, org_name, os_name, os_version, status, last_seen,
                       eol_flag)
                """
            )
        )
        await s.commit()

    async def _override_ro():
        async with session_factory() as ro:
            yield ro

    app.dependency_overrides[get_chat_ro_session] = _override_ro
    yield client


async def _seed_turn(
    session_factory,
    *,
    status: str = "streaming",
    completion_token: str | None = None,
    created_at: datetime | None = None,
) -> dict:
    """Org + user + conversation + turn. Trả dict id."""
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        user = User(
            org_id=org.id,
            full_name="T10",
            email=f"t10-{uuid4()}@example.com",
            role=UserRole.SUPER_ADMIN.value,
            password_hash="x",
        )
        s.add(user)
        await s.flush()
        conv = ChatConversation(created_by=user.id, title="t10")
        s.add(conv)
        await s.flush()
        turn = ChatTurn(
            conversation_id=conv.id,
            actor_id=user.id,
            request_id=uuid4(),
            status=status,
            completion_token_hash=(
                hash_completion_token(completion_token) if completion_token else None
            ),
        )
        if created_at is not None:
            turn.created_at = created_at
        s.add(turn)
        await s.commit()
        return {"conv": conv.id, "user": user.id, "turn": turn.id}


def _cap(ids: dict, ttl: int = 300) -> str:
    return sign_capability(ids["user"], ids["conv"], ids["turn"], uuid4(), ttl=ttl)


def _cap_headers(ids: dict, ttl: int = 300) -> dict:
    return {**SERVICE_HEADERS, "X-Chat-Context": _cap(ids, ttl)}


async def _seed_intent(session_factory, ids: dict, *, outcome: str = "pending",
                       tool: str = "run_vql", created_at: datetime | None = None) -> dict:
    async with session_factory() as s:
        intent = ChatAuditIntent(
            turn_id=ids["turn"],
            tool_call_id=f"tc-{uuid4().hex[:12]}",
            conversation_id=ids["conv"],
            actor_id=ids["user"],
            tool=tool,
            args_digest="a" * 64,
            outcome=outcome,
        )
        if created_at is not None:
            intent.created_at = created_at
        s.add(intent)
        await s.commit()
        return {"tool_call_id": intent.tool_call_id, "intent_id": str(intent.id)}


# ── Service token gate ───────────────────────────────────────────────────────


async def test_missing_service_token_rejected(api):
    r = await api.post("/api/internal/chat/inventory/query", json={"tool": "inventory_search"})
    assert r.status_code == 401
    assert "chat_authz" in r.json()["detail"]


async def test_wrong_service_token_rejected(api):
    r = await api.post(
        "/api/internal/chat/inventory/query",
        json={"tool": "inventory_search"},
        headers={"X-Service-Token": "wrong-token-value"},
    )
    assert r.status_code == 401


async def test_service_token_required_for_outcome(api):
    r = await api.post(
        "/api/internal/chat/audit/outcome",
        json={"turn_id": str(uuid4()), "tool_call_id": "x", "outcome": "ok"},
    )
    assert r.status_code == 401


# ── Capability gate (query / intent) ─────────────────────────────────────────


async def test_inventory_query_requires_capability(api):
    r = await api.post(
        "/api/internal/chat/inventory/query",
        json={"tool": "inventory_search"},
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 401
    assert "chat_authz" in r.json()["detail"]


async def test_inventory_query_expired_capability_rejected(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/inventory/query",
        json={"tool": "inventory_search"},
        headers=_cap_headers(ids, ttl=-60),
    )
    assert r.status_code == 401


async def test_inventory_query_inactive_turn_rejected(api, session_factory):
    ids = await _seed_turn(session_factory, status="completed")
    r = await api.post(
        "/api/internal/chat/inventory/query",
        json={"tool": "inventory_search"},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 401


async def test_inventory_query_success(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/inventory/query",
        json={"tool": "inventory_search", "params": {"limit": 10}},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["row_count"] == 2
    assert {row["hostname"] for row in body["rows"]} == {"WS-01", "WS-02"}


async def test_inventory_sql_success_and_audited(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/inventory/sql",
        json={"sql": "SELECT hostname FROM v_chat_machines ORDER BY hostname"},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_count"] == 2
    assert len(body["sql_digest"]) == 64


async def test_inventory_sql_guardrail_rejects_dml(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/inventory/sql",
        json={"sql": "DELETE FROM v_chat_machines"},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 400
    assert "chat_guardrail_sql" in r.json()["detail"]


# ── Audit intent (V5 identity) ───────────────────────────────────────────────


async def test_audit_intent_requires_capability(api):
    r = await api.post(
        "/api/internal/chat/audit/intent",
        json={"tool_call_id": "tc-1", "tool": "run_vql"},
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 401


async def test_audit_intent_creates_row(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/audit/intent",
        json={"tool_call_id": "tc-1", "tool": "run_vql", "args_digest": "b" * 64},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executed"] is True
    async with session_factory() as s:
        row = (
            await s.execute(
                select(ChatAuditIntent).where(
                    ChatAuditIntent.turn_id == ids["turn"],
                    ChatAuditIntent.tool_call_id == "tc-1",
                )
            )
        ).scalar_one()
        assert row.actor_id == ids["user"]
        assert row.tool == "run_vql"


async def test_audit_intent_duplicate_same_identity_no_reexecution(api, session_factory):
    ids = await _seed_turn(session_factory)
    payload = {"tool_call_id": "tc-dup", "tool": "run_vql", "args_digest": "c" * 64}
    first = await api.post(
        "/api/internal/chat/audit/intent", json=payload, headers=_cap_headers(ids)
    )
    assert first.status_code == 200
    assert first.json()["executed"] is True

    second = await api.post(
        "/api/internal/chat/audit/intent", json=payload, headers=_cap_headers(ids)
    )
    assert second.status_code == 200
    assert second.json()["executed"] is False
    assert second.json()["intent_id"] == first.json()["intent_id"]


async def test_audit_intent_duplicate_different_identity_conflict(api, session_factory):
    ids = await _seed_turn(session_factory)
    await api.post(
        "/api/internal/chat/audit/intent",
        json={"tool_call_id": "tc-x", "tool": "run_vql", "args_digest": "d" * 64},
        headers=_cap_headers(ids),
    )
    r = await api.post(
        "/api/internal/chat/audit/intent",
        json={"tool_call_id": "tc-x", "tool": "run_vql", "args_digest": "e" * 64},
        headers=_cap_headers(ids),
    )
    assert r.status_code == 409
    assert "chat_conflict_idempotency" in r.json()["detail"]


# ── Audit outcome (service token + intent, NO capability) ────────────────────


async def test_audit_outcome_works_without_capability(api, session_factory):
    ids = await _seed_turn(session_factory)
    intent = await _seed_intent(session_factory, ids)
    # KHÔNG gửi X-Chat-Context — chỉ service token + intent.
    r = await api.post(
        "/api/internal/chat/audit/outcome",
        json={
            "turn_id": str(ids["turn"]),
            "tool_call_id": intent["tool_call_id"],
            "outcome": "ok",
        },
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "ok"

    async with session_factory() as s:
        row = (
            await s.execute(
                select(ChatAuditIntent).where(
                    ChatAuditIntent.tool_call_id == intent["tool_call_id"]
                )
            )
        ).scalar_one()
        assert row.outcome == "ok"
        assert row.resolved_at is not None


async def test_audit_outcome_unknown_intent_404(api, session_factory):
    ids = await _seed_turn(session_factory)
    r = await api.post(
        "/api/internal/chat/audit/outcome",
        json={
            "turn_id": str(ids["turn"]),
            "tool_call_id": "does-not-exist",
            "outcome": "ok",
        },
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 404


async def test_audit_outcome_idempotent_same_value(api, session_factory):
    ids = await _seed_turn(session_factory)
    intent = await _seed_intent(session_factory, ids, outcome="ok")
    r = await api.post(
        "/api/internal/chat/audit/outcome",
        json={
            "turn_id": str(ids["turn"]),
            "tool_call_id": intent["tool_call_id"],
            "outcome": "ok",
        },
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["idempotent"] is True


async def test_audit_outcome_conflicting_value_409(api, session_factory):
    ids = await _seed_turn(session_factory)
    intent = await _seed_intent(session_factory, ids, outcome="ok")
    r = await api.post(
        "/api/internal/chat/audit/outcome",
        json={
            "turn_id": str(ids["turn"]),
            "tool_call_id": intent["tool_call_id"],
            "outcome": "error",
        },
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 409
    assert "chat_conflict_idempotency" in r.json()["detail"]


# ── Audit reconcile ──────────────────────────────────────────────────────────


async def test_audit_reconcile_stale_intent_closes_unknown(api, session_factory):
    ids = await _seed_turn(session_factory)
    stale = datetime.now(UTC) - timedelta(seconds=settings.audit_outcome_deadline + 60)
    intent = await _seed_intent(session_factory, ids, created_at=stale)
    r = await api.post(
        "/api/internal/chat/audit/reconcile",
        json={"turn_id": str(ids["turn"]), "tool_call_id": intent["tool_call_id"]},
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "unknown"
    assert r.json()["reconciled"] is True


async def test_audit_reconcile_young_intent_stays_pending(api, session_factory):
    ids = await _seed_turn(session_factory)
    intent = await _seed_intent(session_factory, ids)
    r = await api.post(
        "/api/internal/chat/audit/reconcile",
        json={"turn_id": str(ids["turn"]), "tool_call_id": intent["tool_call_id"]},
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "pending"
    assert r.json()["reconciled"] is False


# ── Durable completion ───────────────────────────────────────────────────────


async def test_complete_requires_completion_token(api, session_factory):
    ids = await _seed_turn(session_factory, completion_token=new_completion_token())
    r = await api.post(
        f"/api/internal/chat/turns/{ids['turn']}/complete",
        json={"content": "hi", "finish_reason": "stop"},
        headers=SERVICE_HEADERS,
    )
    assert r.status_code == 401


async def test_complete_wrong_token_forbidden(api, session_factory):
    ids = await _seed_turn(session_factory, completion_token=new_completion_token())
    r = await api.post(
        f"/api/internal/chat/turns/{ids['turn']}/complete",
        json={"content": "hi", "finish_reason": "stop"},
        headers={**SERVICE_HEADERS, "X-Chat-Completion": "not-the-token"},
    )
    assert r.status_code == 403


async def test_complete_success_persists_message(api, session_factory):
    token = new_completion_token()
    ids = await _seed_turn(session_factory, completion_token=token)
    r = await api.post(
        f"/api/internal/chat/turns/{ids['turn']}/complete",
        json={"content": "the answer", "finish_reason": "stop", "usage": {"total_tokens": 7}},
        headers={**SERVICE_HEADERS, "X-Chat-Completion": token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"

    async with session_factory() as s:
        turn = await s.get(ChatTurn, ids["turn"])
        assert turn.status == "completed"
        assert turn.completion_committed_at is not None
        msgs = (
            await s.execute(
                select(ChatMessage).where(ChatMessage.turn_id == ids["turn"])
            )
        ).scalars().all()
        assert [m.content for m in msgs] == ["the answer"]


async def test_complete_error_finish_reason_marks_failed(api, session_factory):
    token = new_completion_token()
    ids = await _seed_turn(session_factory, completion_token=token)
    r = await api.post(
        f"/api/internal/chat/turns/{ids['turn']}/complete",
        json={
            "content": "partial",
            "finish_reason": "error",
            "error_category": "chat_upstream_llm",
        },
        headers={**SERVICE_HEADERS, "X-Chat-Completion": token},
    )
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        turn = await s.get(ChatTurn, ids["turn"])
        assert turn.status == "failed"
        assert turn.error_category == "chat_upstream_llm"
