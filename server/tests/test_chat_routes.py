"""Task 11 — public chat routes `/api/chat` (spec §"Public", §"SSE event schema").

Session auth (`require_super_admin`) + ownership: mọi route theo `{id}` chỉ chủ sở
hữu (`conversation.created_by`) mới truy cập; SuperAdmin khác nhận **404** (không
tiết lộ tồn tại). SSE trả `text/event-stream` với schema `chat.sse/1`
(`start|token|usage|done`); P1 stub — chatagent chưa nối (T12–T15).

Chạy trên schema `Base.metadata.create_all` của fixture `db_engine` (test DB không
chạy alembic).
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api.routes import chat as chat_routes
from app.core.security import hash_password
from app.db.models import (
    ChatTurn,
    LlmConfig,
    Organization,
    OrgType,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio

# Nội dung tất định mà fake ChatAgent trả về (thay container thật trong test T11).
FAKE_AGENT_ANSWER = "Phản hồi kiểm thử từ ChatAgent."


@pytest_asyncio.fixture(autouse=True)
async def _fake_chatagent(monkeypatch):
    """Thay seam `_stream_agent` bằng stream SSE tất định (không cần container).

    Mô phỏng đúng chuỗi event `chat.sse/1` của ChatAgent: start → token → usage →
    done. Backend T11 là bên persist assistant message trong test này (agent thật
    tự gọi completion, idempotent).
    """

    async def _fake_stream(body):
        events = [
            {"v": "chat.sse/1", "seq": 0, "type": "start", "turn_id": body.get("turn_id"), "message_id": None},
            {"v": "chat.sse/1", "seq": 1, "type": "token", "text": FAKE_AGENT_ANSWER},
            {"v": "chat.sse/1", "seq": 2, "type": "usage", "input_tokens": 3, "output_tokens": 7},
            {"v": "chat.sse/1", "seq": 3, "type": "done", "message_id": None, "finish_reason": "stop"},
        ]
        for ev in events:
            yield f"event: {ev['type']}"
            yield f"data: {json.dumps(ev)}"
            yield ""

    monkeypatch.setattr(chat_routes, "_stream_agent", _fake_stream)


async def _login(client, email: str, password: str) -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(
    session_factory, *, role: str = UserRole.SUPER_ADMIN.value, password: str = "TestPass!123"
) -> dict:
    async with session_factory() as s:
        org = Organization(name=f"Org {uuid.uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        u = User(
            org_id=org.id,
            full_name="U",
            email=f"u-{uuid.uuid4()}@example.com",
            role=role,
            password_hash=hash_password(password),
        )
        s.add(u)
        await s.commit()
        return {"id": str(u.id), "email": u.email, "password": password, "org_id": str(org.id)}


@pytest_asyncio.fixture
async def api(client, session_factory):
    """`client` + 2 super admin (owner/other) đã login. Trả token + helper."""
    owner = await _make_user(session_factory)
    other = await _make_user(session_factory)
    owner_h = _auth(await _login(client, owner["email"], owner["password"]))
    other_h = _auth(await _login(client, other["email"], other["password"]))
    yield {
        "client": client,
        "owner": owner,
        "other": other,
        "owner_h": owner_h,
        "other_h": other_h,
        "session_factory": session_factory,
    }


async def _create_conv(api, *, title="C", machine_id=None, headers=None) -> dict:
    r = await api["client"].post(
        "/api/chat/conversations",
        json={"title": title, **({"machine_id": machine_id} if machine_id else {})},
        headers=headers or api["owner_h"],
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _parse_sse(body: str) -> list[dict]:
    """Parse SSE body thành list payload JSON (bỏ heartbeat `:hb`)."""
    events: list[dict] = []
    for block in body.strip().split("\n\n"):
        data_lines = [ln[len("data: "):] for ln in block.splitlines() if ln.startswith("data: ")]
        if not data_lines:
            continue
        events.append(json.loads("\n".join(data_lines)))
    return events


# ── CRUD + ownership ─────────────────────────────────────────────────────────


async def test_create_conversation(api):
    body = await _create_conv(api, title="Hỏi đáp")
    assert body["title"] == "Hỏi đáp"
    assert body["message_count"] == 0
    assert body["machine_id"] is None
    assert body["archived"] is False
    assert body["id"]
    # Audit chat.conversation.create
    from app.db.models import AuditLog

    async with api["session_factory"]() as s:
        rows = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "chat.conversation.create" in rows


async def test_list_only_own_conversations(api):
    await _create_conv(api, title="mine-1")
    await _create_conv(api, title="mine-2")
    await _create_conv(api, title="theirs", headers=api["other_h"])

    r = await api["client"].get("/api/chat/conversations", headers=api["owner_h"])
    assert r.status_code == 200, r.text
    data = r.json()
    titles = {i["title"] for i in data["items"]}
    assert titles == {"mine-1", "mine-2"}
    assert data["total"] == 2

    r = await api["client"].get("/api/chat/conversations", headers=api["other_h"])
    assert {i["title"] for i in r.json()["items"]} == {"theirs"}


async def test_detail_owner(api):
    conv = await _create_conv(api)
    r = await api["client"].get(f"/api/chat/conversations/{conv['id']}", headers=api["owner_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == conv["id"]
    assert body["messages"] == []
    assert body["active_turn_id"] is None


async def test_detail_not_owner_404(api):
    conv = await _create_conv(api)
    r = await api["client"].get(f"/api/chat/conversations/{conv['id']}", headers=api["other_h"])
    assert r.status_code == 404


async def test_patch_conversation(api):
    conv = await _create_conv(api, title="old")
    r = await api["client"].patch(
        f"/api/chat/conversations/{conv['id']}", json={"title": "new"}, headers=api["owner_h"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "new"


async def test_patch_machine_id_and_unset(api, session_factory):
    async with session_factory() as s:
        org = Organization(name=f"O {uuid.uuid4()}", type=OrgType.ROOT.value)
        s.add(org)
        await s.flush()
        from app.db.models import Machine

        m = Machine(org_id=org.id, machine_uuid=f"m-{uuid.uuid4()}", hostname="WS-9")
        s.add(m)
        await s.commit()
        mid = str(m.id)

    conv = await _create_conv(api)
    r = await api["client"].patch(
        f"/api/chat/conversations/{conv['id']}", json={"machine_id": mid}, headers=api["owner_h"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["machine_id"] == mid

    r = await api["client"].patch(
        f"/api/chat/conversations/{conv['id']}", json={"machine_id": None}, headers=api["owner_h"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["machine_id"] is None


async def test_patch_not_owner_404(api):
    conv = await _create_conv(api)
    r = await api["client"].patch(
        f"/api/chat/conversations/{conv['id']}", json={"title": "x"}, headers=api["other_h"]
    )
    assert r.status_code == 404


async def test_delete_conversation(api):
    conv = await _create_conv(api)
    r = await api["client"].delete(f"/api/chat/conversations/{conv['id']}", headers=api["owner_h"])
    assert r.status_code == 204
    r = await api["client"].get(f"/api/chat/conversations/{conv['id']}", headers=api["owner_h"])
    assert r.status_code == 404


async def test_delete_not_owner_404(api):
    conv = await _create_conv(api)
    r = await api["client"].delete(f"/api/chat/conversations/{conv['id']}", headers=api["other_h"])
    assert r.status_code == 404


async def test_requires_super_admin(api, session_factory):
    viewer = await _make_user(session_factory, role=UserRole.VIEWER.value)
    token = await _login(api["client"], viewer["email"], viewer["password"])
    r = await api["client"].get("/api/chat/conversations", headers=_auth(token))
    assert r.status_code == 403


# ── Send + SSE ───────────────────────────────────────────────────────────────


async def test_send_returns_sse_and_persists_assistant_message(api):
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "Xin chào"},
        headers=api["owner_h"],
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "token" in types
    assert types[-1] == "done"
    assert all(e["v"] == "chat.sse/1" for e in events)
    assert [e["seq"] for e in events] == list(range(len(events)))

    token_text = "".join(e["text"] for e in events if e["type"] == "token")
    assert token_text

    # Detail: user message + assistant message đã persist
    r = await api["client"].get(f"/api/chat/conversations/{conv['id']}", headers=api["owner_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][0]["content"] == "Xin chào"
    assert body["messages"][1]["content"] == token_text
    assert body["active_turn_id"] is None


async def test_send_not_owner_404(api):
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=api["other_h"],
    )
    assert r.status_code == 404


async def test_second_send_while_active_409(api, session_factory):
    conv = await _create_conv(api)
    async with session_factory() as s:
        s.add(
            ChatTurn(
                conversation_id=uuid.UUID(conv["id"]),
                actor_id=uuid.UUID(api["owner"]["id"]),
                request_id=uuid.uuid4(),
                status="pending",
            )
        )
        await s.commit()
        turn = (
            await s.execute(
                select(ChatTurn).where(ChatTurn.conversation_id == uuid.UUID(conv["id"]))
            )
        ).scalar_one()
        active_id = str(turn.id)

    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "again"},
        headers=api["owner_h"],
    )
    assert r.status_code == 409, r.text
    assert "chat_conflict_active_turn" in r.json()["detail"]
    assert r.json()["active_turn_id"] == active_id


async def test_send_message_too_long_rejected(api):
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "x" * 20000},
        headers=api["owner_h"],
    )
    assert r.status_code == 422


async def test_machine_context_snapshot_into_turn(api, session_factory):
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "ctx", "machine_context": {"hostname": "WS-CTX", "client_id": "C.ctx"}},
        headers=api["owner_h"],
    )
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        turn = (
            await s.execute(
                select(ChatTurn).where(ChatTurn.conversation_id == uuid.UUID(conv["id"]))
            )
        ).scalar_one()
    assert turn.machine_ref == "C.ctx"


async def test_idempotency_same_content_replays(api):
    conv = await _create_conv(api)
    h = {**api["owner_h"], "Idempotency-Key": "key-1"}
    r1 = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages", json={"content": "same"}, headers=h
    )
    assert r1.status_code == 200, r1.text
    ev1 = _parse_sse(r1.text)

    r2 = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages", json={"content": "same"}, headers=h
    )
    assert r2.status_code == 200, r2.text
    ev2 = _parse_sse(r2.text)
    # Replay cùng turn_id
    assert ev2[0]["turn_id"] == ev1[0]["turn_id"]
    assert [e["type"] for e in ev2][-1] == "done"


async def test_idempotency_diff_content_409(api):
    conv = await _create_conv(api)
    h = {**api["owner_h"], "Idempotency-Key": "key-2"}
    r1 = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages", json={"content": "one"}, headers=h
    )
    assert r1.status_code == 200, r1.text
    r2 = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages", json={"content": "two"}, headers=h
    )
    assert r2.status_code == 409, r2.text
    assert "chat_conflict_idempotency" in r2.json()["detail"]


async def test_budget_exceeded_429(api, session_factory):
    async with session_factory() as s:
        s.add(
            LlmConfig(
                id=1,
                enabled=True,
                base_url="http://127.0.0.1:11434/v1",
                model="m",
                max_tokens=64000,
                daily_token_budget=1,
            )
        )
        await s.commit()
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=api["owner_h"],
    )
    assert r.status_code == 429, r.text
    assert "chat_budget_exceeded" in r.json()["detail"]


# ── Cancel ───────────────────────────────────────────────────────────────────


async def test_cancel_active_turn(api, session_factory):
    conv = await _create_conv(api)
    async with session_factory() as s:
        turn = ChatTurn(
            conversation_id=uuid.UUID(conv["id"]),
            actor_id=uuid.UUID(api["owner"]["id"]),
            request_id=uuid.uuid4(),
            status="streaming",
        )
        s.add(turn)
        await s.commit()
        tid = str(turn.id)

    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/cancel",
        json={"turn_id": tid},
        headers=api["owner_h"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "canceled"

    r = await api["client"].get(f"/api/chat/conversations/{conv['id']}", headers=api["owner_h"])
    assert r.json()["active_turn_id"] is None


async def test_cancel_terminal_turn_409(api, session_factory):
    conv = await _create_conv(api)
    async with session_factory() as s:
        turn = ChatTurn(
            conversation_id=uuid.UUID(conv["id"]),
            actor_id=uuid.UUID(api["owner"]["id"]),
            request_id=uuid.uuid4(),
            status="completed",
        )
        s.add(turn)
        await s.commit()
        tid = str(turn.id)

    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/cancel",
        json={"turn_id": tid},
        headers=api["owner_h"],
    )
    assert r.status_code == 409, r.text


async def test_cancel_not_owner_404(api, session_factory):
    conv = await _create_conv(api)
    async with session_factory() as s:
        turn = ChatTurn(
            conversation_id=uuid.UUID(conv["id"]),
            actor_id=uuid.UUID(api["owner"]["id"]),
            request_id=uuid.uuid4(),
            status="streaming",
        )
        s.add(turn)
        await s.commit()
        tid = str(turn.id)

    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/cancel",
        json={"turn_id": tid},
        headers=api["other_h"],
    )
    assert r.status_code == 404


async def test_cancel_turn_not_in_conversation_404(api, session_factory):
    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/cancel",
        json={"turn_id": str(uuid.uuid4())},
        headers=api["owner_h"],
    )
    assert r.status_code == 404


async def test_agent_unreachable_emits_error_and_audits_gateway(api, monkeypatch):
    """Finding 1: agent không kết nối được → event `error`, turn `failed`,
    audit `chat.turn.gateway` (backend disconnect path)."""
    from app.api.routes import chat as chat_routes
    from app.db.models import AuditLog

    async def _boom(body):
        raise RuntimeError("chatagent down")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_routes, "_stream_agent", _boom)

    conv = await _create_conv(api)
    r = await api["client"].post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=api["owner_h"],
    )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["category"] == "chat_stream_lost"

    async with api["session_factory"]() as s:
        turn = (
            await s.execute(
                select(ChatTurn).where(ChatTurn.conversation_id == uuid.UUID(conv["id"]))
            )
        ).scalar_one()
        assert turn.status == "failed"
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "chat.turn.gateway" in actions
