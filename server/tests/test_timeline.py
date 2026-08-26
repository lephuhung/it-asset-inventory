"""Test timeline bật/tắt máy (tính năng #1 Phase 2)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import hash_password
from app.db.models import Heartbeat, Machine, Organization, OrgType, User, UserRole


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_timeline_groups_heartbeats_into_sessions(client, session_factory, seeded_env):
    org_id = uuid.UUID(seeded_env["org_id"])
    async with session_factory() as s:
        m = Machine(org_id=org_id, machine_uuid="uuid-tl-1", hostname="PC-TL", status="offline")
        s.add(m)
        await s.flush()
        now = datetime.now(UTC)
        # Phiên 1: heartbeat liên tục mỗi 2 phút (gap < 300s → 1 phiên)
        for i in range(5):
            s.add(Heartbeat(machine_id=m.id, ts=now - timedelta(minutes=2 * i)))
        # Phiên 2: cách phiên 1 là 40 phút (gap > 300s → phiên mới)
        s.add(Heartbeat(machine_id=m.id, ts=now - timedelta(minutes=40)))
        s.add(Heartbeat(machine_id=m.id, ts=now - timedelta(minutes=38)))
        await s.commit()
        machine_id = str(m.id)

    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get(
        f"/api/machines/{machine_id}/timeline", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sessions_count"] == 2
    assert data["total_online_sec"] > 0
    assert len(data["daily"]) >= 1
    assert data["daily"][0]["boots"] == 2
    # Phiên bật máy dài nhất ≈ 8 phút (5 heartbeat × 2 phút)
    assert max(s["duration_sec"] for s in data["sessions"]) >= 420


async def test_timeline_org_scoped(client, session_factory, seeded_env):
    """User ngoài phạm vi org không xem được timeline."""
    async with session_factory() as s:
        other = Organization(name="Sở khác", type=OrgType.SO_BAN_NGANH.value)
        s.add(other)
        await s.flush()
        m = Machine(org_id=other.id, machine_uuid="uuid-tl-2", hostname="PC-X", status="offline")
        s.add(m)
        await s.flush()
        s.add(Heartbeat(machine_id=m.id, ts=datetime.now(UTC)))
        viewer = User(
            org_id=uuid.UUID(seeded_env["org_id"]),
            full_name="Viewer khác org",
            email="viewer.other@example.gov.vn",
            role=UserRole.VIEWER.value,
            password_hash=hash_password("ChangeMe!123"),
        )
        s.add(viewer)
        await s.commit()
        machine_id = str(m.id)

    token = await _login(client, "viewer.other@example.gov.vn", "ChangeMe!123")
    r = await client.get(
        f"/api/machines/{machine_id}/timeline", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403