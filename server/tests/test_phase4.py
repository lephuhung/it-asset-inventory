"""Test Phase 4: API keys + public endpoint + báo cáo PDF."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import Machine


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_api_key_lifecycle_and_public_endpoint(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    # Tạo máy để public endpoint trả về
    async with session_factory() as s:
        s.add(
            Machine(
                org_id=org_id, machine_uuid="uuid-pub-1", hostname="PC-PUB",
                status="offline", enrolled_at=datetime.now(UTC),
            )
        )
        await s.commit()

    # Tạo key
    r = await client.post(
        "/api/keys", json={"name": "Hệ thống báo cáo", "scope": "read:machines"}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert key.startswith("ai_")
    key_id = r.json()["id"]

    # List keys không lộ plaintext
    r = await client.get("/api/keys", headers=_auth(token))
    assert r.status_code == 200
    assert all("key" not in k for k in r.json())
    assert any(k["id"] == key_id for k in r.json()["items"])

    # Public endpoint dùng X-API-Key
    r = await client.get("/api/public/machines", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    assert any(m["hostname"] == "PC-PUB" for m in r.json())

    # Key sai → 401
    r = await client.get("/api/public/machines", headers={"X-API-Key": "ai_wrong"})
    assert r.status_code == 401

    # Không có key → 401
    r = await client.get("/api/public/machines")
    assert r.status_code == 401

    # Vô hiệu key → 401
    r = await client.patch(f"/api/keys/{key_id}", json={"enabled": False}, headers=_auth(token))
    assert r.status_code == 200
    r = await client.get("/api/public/machines", headers={"X-API-Key": key})
    assert r.status_code == 401

    # Xóa key
    r = await client.delete(f"/api/keys/{key_id}", headers=_auth(token))
    assert r.status_code == 200

    # Viewer không tạo được key
    async with session_factory() as s:
        from app.core.security import hash_password
        from app.db.models import User, UserRole

        s.add(
            User(
                org_id=org_id, full_name="Viewer", email="viewer.api@example.gov.vn",
                role=UserRole.VIEWER.value, password_hash=hash_password("ChangeMe!123"),
            )
        )
        await s.commit()
    vtoken = await _login(client, "viewer.api@example.gov.vn", "ChangeMe!123")
    r = await client.post("/api/keys", json={"name": "X"}, headers=_auth(vtoken))
    assert r.status_code == 403


async def test_report_pdf_export(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])
    async with session_factory() as s:
        s.add(
            Machine(
                org_id=org_id, machine_uuid="uuid-pdf-1", hostname="PC-PDF",
                status="offline", enrolled_at=datetime.now(UTC),
            )
        )
        await s.commit()

    r = await client.post("/api/reports/export-pdf", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"