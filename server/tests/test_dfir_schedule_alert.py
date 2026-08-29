"""Tests cho Velociraptor schedules + alerts (Phase 2)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import DfirAlert, DfirSchedule, VelociraptorConfig


# ── DfirSchedule CRUD ────────────────────────────────────


async def test_create_schedule_requires_super_admin(client, seeded_env):
    """Tạo schedule cần super_admin — org_admin bị 403."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    # Setup Velociraptor enabled + allowlist
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "enabled": True,
            "server_url": "https://localhost:8889",
            "allowlist": ["Generic.Client.Info"],
        },
    )

    # super_admin OK
    r = await client.post(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "name": "Test schedule",
            "artifact": "Generic.Client.Info",
            "interval_seconds": 3600,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["enabled"] is True
    assert r.json()["artifact"] == "Generic.Client.Info"
    assert r.json()["interval_seconds"] == 3600


async def test_list_schedules_empty(client, seeded_env):
    """GET /schedules trả list rỗng khi chưa tạo."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    r = await client.get(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_patch_schedule_toggle_enabled(client, seeded_env):
    """PATCH schedule đ�i enabled=false → enabled toggle."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    # Create
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": True, "server_url": "https://localhost:8889", "allowlist": ["Generic.Client.Info"]},
    )
    cr = await client.post(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": "S1", "artifact": "Generic.Client.Info", "interval_seconds": 3600},
    )
    sched_id = cr.json()["id"]
    assert cr.json()["enabled"] is True

    # Disable
    r = await client.patch(
        f"/api/admin/velociraptor/schedules/{sched_id}",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_delete_schedule(client, seeded_env):
    """DELETE schedule xoá row."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": True, "server_url": "https://localhost:8889", "allowlist": ["Generic.Client.Info"]},
    )
    cr = await client.post(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": "ToDelete", "artifact": "Generic.Client.Info", "interval_seconds": 3600},
    )
    sid = cr.json()["id"]

    r = await client.delete(
        f"/api/admin/velociraptor/schedules/{sid}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 204

    # Verify gone
    r = await client.get(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert all(s["id"] != sid for s in r.json())


async def test_create_schedule_validates_interval(client, seeded_env):
    """Interval phải trong [60, 604800]."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": True, "server_url": "https://localhost:8889", "allowlist": ["Generic.Client.Info"]},
    )
    r = await client.post(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": "Bad", "artifact": "Generic.Client.Info", "interval_seconds": 30},  # too low
    )
    assert r.status_code == 422


async def test_create_schedule_validates_artifact_allowlist(client, seeded_env):
    """Artifact phải trong allowlist."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    await client.put(
        "/api/admin/velociraptor/config",
        headers={"Authorization": f"Bearer {tok}"},
        json={"enabled": True, "server_url": "https://localhost:8889", "allowlist": ["Generic.Client.Info"]},
    )
    r = await client.post(
        "/api/admin/velociraptor/schedules",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": "X", "artifact": "Windows.Persistence.Permanent", "interval_seconds": 3600},
    )
    assert r.status_code == 403
    assert "allowlist" in r.json()["detail"].lower()


# ── DfirAlert ──────────────────────────────────────────────


async def test_list_alerts_empty(client, seeded_env):
    """GET /alerts trả list rỗng ban đầu."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]
    r = await client.get(
        "/api/admin/velociraptor/alerts",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_resolve_alert(client, seeded_env):
    """PATCH /alerts/{id}/resolve đánh dấu resolved=true."""
    sa = await client.post(
        "/api/auth/login",
        json={"email": seeded_env["email"], "password": seeded_env["password"]},
    )
    tok = sa.json()["access_token"]

    # Insert alert directly via DB
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        alert = DfirAlert(
            artifact_pattern="Windows.Persistence.*",
            severity="critical",
            flow_id="F.test123",
            client_id="C.test",
            message="Test alert",
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        alert_id = str(alert.id)

    # Resolve
    r = await client.patch(
        f"/api/admin/velociraptor/alerts/{alert_id}/resolve",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["resolved"] is True

    # Verify DB
    async with AsyncSessionLocal() as db:
        a = (await db.execute(select(DfirAlert).where(DfirAlert.id == alert.id))).scalar_one_or_none()
        assert a is not None
        assert a.resolved is True
