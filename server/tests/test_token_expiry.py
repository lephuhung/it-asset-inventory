"""Test lazy-expire token — token pending quá hạn tự chuyển expired khi list/stats."""
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

    # Token còn hiệu lực (72h) + token đã quá hạn (5 phút trước) — cả 2 đang pending
    async with session_factory() as s:
        s.add_all(
            [
                EnrollToken(
                    token_hash="hash-valid-1", org_id=org_id, created_by=uuid.UUID(seeded_env["admin_id"]),
                    full_name="Còn hiệu lực", expires_at=datetime.now(UTC) + timedelta(hours=72),
                    status=TokenStatus.PENDING.value,
                ),
                EnrollToken(
                    token_hash="hash-expired-1", org_id=org_id, created_by=uuid.UUID(seeded_env["admin_id"]),
                    full_name="Quá hạn 5 phút", expires_at=datetime.now(UTC) - timedelta(minutes=5),
                    status=TokenStatus.PENDING.value,
                ),
            ]
        )
        await s.commit()

    # List → token quá hạn tự chuyển expired, token còn hạn vẫn pending
    r = await client.get("/api/tokens", headers=_auth(token))
    assert r.status_code == 200
    by_name = {t["full_name"]: t["status"] for t in r.json()["items"]}
    assert by_name["Còn hiệu lực"] == "pending"
    assert by_name["Quá hạn 5 phút"] == "expired"

    # Stats → expired_tokens ≥ 1
    r = await client.get("/api/stats/overview", headers=_auth(token))
    assert r.json()["expired_tokens"] >= 1

    # Trong DB đã được cập nhật thật
    async with session_factory() as s:
        row = (await s.execute(select(EnrollToken).where(EnrollToken.token_hash == "hash-expired-1"))).scalar_one()
        assert row.status == TokenStatus.EXPIRED.value