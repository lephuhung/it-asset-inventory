"""Test Phase 2: alert rules + job, self-service chế độ B, bulk import, org assign rules."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import (
    AlertEvent,
    Machine,
    MachineStatus,
)


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Alert rules ────────────────────────────────────────────────


async def test_alert_rule_crud(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Mất liên lạc 7 ngày",
            "rule_type": "machine_lost",
            "org_id": org_id,
            "threshold_days": 7,
            "channels": ["email", "telegram"],
            "notify_targets": ["it@example.gov.vn"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    rule_id = r.json()["id"]

    r = await client.get("/api/alert-rules", headers=_auth(token))
    assert r.status_code == 200
    assert any(x["id"] == rule_id for x in r.json())

    r = await client.patch(
        f"/api/alert-rules/{rule_id}", json={"enabled": False}, headers=_auth(token)
    )
    assert r.status_code == 200 and r.json()["enabled"] is False

    r = await client.delete(f"/api/alert-rules/{rule_id}", headers=_auth(token))
    assert r.status_code == 200

    # type không hợp lệ → 422
    r = await client.post(
        "/api/alert-rules",
        json={"name": "X", "rule_type": "whatever", "org_id": org_id},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_alert_job_fires_and_no_duplicate(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    r = await client.post(
        "/api/alert-rules",
        json={"name": "Máy mới", "rule_type": "machine_new", "org_id": str(org_id), "channels": []},
        headers=_auth(token),
    )
    rule_id = uuid.UUID(r.json()["id"])

    async with session_factory() as s:
        m = Machine(
            org_id=org_id, machine_uuid="uuid-alert-1", hostname="PC-NEW",
            status=MachineStatus.PENDING.value, enrolled_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()

    from app.services.monitor import _scan_alerts

    await _scan_alerts()
    await _scan_alerts()  # chạy lần 2 → không trùng

    async with session_factory() as s:
        events = (await s.execute(select(AlertEvent).where(AlertEvent.rule_id == rule_id))).scalars().all()
        assert len(events) == 1
        assert events[0].message.startswith("Máy mới enroll")
        r = await client.get("/api/alert-rules/events", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()) >= 1


# ── Self-service (chế độ B) ────────────────────────────────────


async def test_self_service_claim_flow(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    r = await client.post(
        "/api/self-service/links", json={"org_id": org_id}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    link_id = r.json()["id"]
    code = r.json()["code"]
    assert "/enroll/" in r.json()["url"]

    # Thông tin công khai — không cần auth
    info = await client.get(f"/api/self-service/{code}")
    assert info.status_code == 200
    assert info.json()["org_name"]

    # Claim — không cần auth, rate-limit riêng
    claim = await client.post(
        f"/api/self-service/{code}/claim",
        json={"full_name": "Trần Thị B", "department": "Nhân sự", "phone": "0983", "email": "b@example.gov.vn"},
    )
    assert claim.status_code == 200, claim.text
    data = claim.json()
    assert data["token"].startswith("t_")
    assert "irm" in data["install_command"]

    # Token xuất hiện trong phễu triển khai
    r = await client.get("/api/tokens", headers=_auth(token))
    assert any(t["full_name"] == "Trần Thị B" for t in r.json())

    # Link đã tắt → claim bị từ chối
    await client.patch(f"/api/self-service/links/{link_id}", json={"enabled": False}, headers=_auth(token))
    claim2 = await client.post(
        f"/api/self-service/{code}/claim", json={"full_name": "X"}
    )
    assert claim2.status_code == 404


# ── Bulk import ────────────────────────────────────────────────


async def test_bulk_tokens(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.post(
        "/api/tokens/bulk",
        json={
            "org_id": seeded_env["org_id"],
            "ttl_hours": 72,
            "items": [
                {"full_name": "Người 1", "department": "Kế toán", "email": "n1@example.gov.vn"},
                {"full_name": "Người 2", "phone": "0983111222"},
            ],
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 2
    assert all(t["token"].startswith("t_") for t in data["tokens"])

    # Ngoài phạm vi quyền → 403 (org lạ)
    r = await client.post(
        "/api/tokens/bulk",
        json={"org_id": str(uuid.uuid4()), "items": [{"full_name": "X"}]},
        headers=_auth(token),
    )
    assert r.status_code == 403