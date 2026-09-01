"""Test token auto cleanup — token hết hạn hoặc thu hồi tự động bị xóa khỏi list."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import EnrollToken, TokenStatus


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_pending_token_expires_lazily(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    # Token còn hiệu lực (72h) + token đã quá hạn (5 phút trước)
    token_valid_id = uuid.uuid4()
    token_expired_id = uuid.uuid4()
    async with session_factory() as s:
        s.add_all(
            [
                EnrollToken(
                    id=token_valid_id,
                    token_hash="hash-valid-1", org_id=org_id, created_by=uuid.UUID(seeded_env["admin_id"]),
                    full_name="Còn hiệu lực", expires_at=datetime.now(UTC) + timedelta(hours=72),
                    status=TokenStatus.PENDING.value,
                ),
                EnrollToken(
                    id=token_expired_id,
                    token_hash="hash-expired-1", org_id=org_id, created_by=uuid.UUID(seeded_env["admin_id"]),
                    full_name="Quá hạn 5 phút", expires_at=datetime.now(UTC) - timedelta(minutes=5),
                    status=TokenStatus.PENDING.value,
                ),
            ]
        )
        await s.commit()

    # List → token quá hạn tự động bị xóa khỏi list, chỉ còn token còn hạn
    r = await client.get("/api/tokens", headers=_auth(token))
    assert r.status_code == 200
    items = r.json()["items"]
    by_name = {t["full_name"]: t["status"] for t in items}
    assert "Còn hiệu lực" in by_name
    assert by_name["Còn hiệu lực"] == "pending"
    assert "Quá hạn 5 phút" not in by_name

    # Trong DB, token quá hạn đã bị xóa
    async with session_factory() as s:
        row = (await s.execute(select(EnrollToken).where(EnrollToken.token_hash == "hash-expired-1"))).scalar_one_or_none()
        assert row is None


async def test_revoke_token_removes_from_list(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])
    token_id = uuid.uuid4()

    async with session_factory() as s:
        s.add(
            EnrollToken(
                id=token_id,
                token_hash="hash-revoke-test", org_id=org_id, created_by=uuid.UUID(seeded_env["admin_id"]),
                full_name="Cần thu hồi", expires_at=datetime.now(UTC) + timedelta(hours=72),
                status=TokenStatus.PENDING.value,
            )
        )
        await s.commit()

    # Thu hồi token
    r_revoke = await client.post("/api/tokens/revoke", json={"token_id": str(token_id)}, headers=_auth(token))
    assert r_revoke.status_code == 200
    assert r_revoke.json()["ok"] is True

    # List → token bị thu hồi không còn trong list
    r_list = await client.get("/api/tokens", headers=_auth(token))
    assert r_list.status_code == 200
    by_name = {t["full_name"]: t["status"] for t in r_list.json()["items"]}
    assert "Cần thu hồi" not in by_name

    # Trong DB, token đã bị xóa
    async with session_factory() as s:
        row = (await s.execute(select(EnrollToken).where(EnrollToken.id == token_id))).scalar_one_or_none()
        assert row is None