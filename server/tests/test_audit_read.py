"""Test audit log read + hash chain verify (mục 7.2, Sprint 4)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import AuditLog, Machine, User, UserRole


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_audit_list_and_filters(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])

    # Login + tạo token sinh nhiều dòng audit
    await client.post("/api/tokens", json={"org_id": seeded_env["org_id"], "full_name": "Audit Test"}, headers=_auth(token))

    r = await client.get("/api/audit", headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 2  # auth.login + token.create (+ auth.login của test)
    assert isinstance(data["items"], list)

    # Lọc theo action
    r = await client.get("/api/audit", params={"action": "token.create"}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all(i["action"] == "token.create" for i in r.json()["items"])

    # Tìm kiếm q
    r = await client.get("/api/audit", params={"q": "token.create"}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # Phân trang
    r = await client.get("/api/audit", params={"limit": 1, "offset": 0}, headers=_auth(token))
    assert len(r.json()["items"]) == 1

    # Danh sách actions
    r = await client.get("/api/audit/actions", headers=_auth(token))
    assert "token.create" in r.json()


async def test_audit_rbac_scopes(client, session_factory, seeded_env):
    org_id = uuid.UUID(seeded_env["org_id"])

    # Máy A thuộc org của admin (seeded); máy B thuộc org khác
    async with session_factory() as s:
        from app.db.models import Organization, OrgType

        other = Organization(name="Sở khác", type=OrgType.SO_BAN_NGANH.value)
        s.add(other)
        await s.flush()
        ma = Machine(org_id=org_id, machine_uuid="uuid-aud-a", hostname="PC-A", status="offline", enrolled_at=datetime.now(UTC))
        mb = Machine(org_id=other.id, machine_uuid="uuid-aud-b", hostname="PC-B", status="offline", enrolled_at=datetime.now(UTC))
        s.add_all([ma, mb])
        await s.flush()
        s.add_all([
            AuditLog(actor="agent:1", action="enroll.success", target="x", ts=datetime.now(UTC), prev_hash="0" * 64, content_hash="a" * 64, machine_id=ma.id),
            AuditLog(actor="agent:2", action="enroll.success", target="y", ts=datetime.now(UTC), prev_hash="0" * 64, content_hash="b" * 64, machine_id=mb.id),
        ])
        s.add(
            User(
                org_id=org_id, full_name="Admin org", email="admin.org@example.gov.vn",
                role=UserRole.ORG_ADMIN.value, password_hash=hash_password("ChangeMe!123"),
            )
        )
        s.add(
            User(
                org_id=org_id, full_name="Viewer", email="viewer.audit@example.gov.vn",
                role=UserRole.VIEWER.value, password_hash=hash_password("ChangeMe!123"),
            )
        )
        await s.commit()

    # Super admin thấy cả 2 dòng máy
    stoken = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get("/api/audit", params={"action": "enroll.success"}, headers=_auth(stoken))
    assert r.json()["total"] == 2

    # Org admin chỉ thấy dòng gắn máy trong subtree của mình
    otoken = await _login(client, "admin.org@example.gov.vn", "ChangeMe!123")
    r = await client.get("/api/audit", params={"action": "enroll.success"}, headers=_auth(otoken))
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["machine_id"] == str(ma.id)

    # Viewer → 403
    vtoken = await _login(client, "viewer.audit@example.gov.vn", "ChangeMe!123")
    r = await client.get("/api/audit", headers=_auth(vtoken))
    assert r.status_code == 403


async def test_audit_chain_verify_detects_tamper(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])

    # Chuỗi hiện tại hợp lệ
    r = await client.get("/api/audit/verify", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["checked"] >= 1

    # Sửa tay 1 dòng → verify phát hiện đứt chuỗi
    async with session_factory() as s:
        row = (await s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))).scalar_one()
        row.content_hash = "f" * 64
        await s.commit()

    r = await client.get("/api/audit/verify", headers=_auth(token))
    assert r.json()["ok"] is False
    assert r.json()["broken_index"] is not None