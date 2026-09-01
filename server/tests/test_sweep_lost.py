"""Test monitor._sweep_lost — auto transition OFFLINE → LOST sau lost_after_days.

Vì `_sweep_lost` dùng `AsyncSessionLocal` toàn cục (engine riêng của monitor
service), test phải chạy trong cùng event loop với engine. Để tránh issue
asyncpg cross-loop, ta dùng 1 test duy nhất kiểm tra đầy đủ các case.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import Machine
from app.services.monitor import _sweep_lost


async def _create_machine(session, org_id, *, last_seen_at, status, hostname):
    m = Machine(
        org_id=org_id,
        machine_uuid=f"uuid-{hostname}-{status}",
        hostname=hostname,
        fingerprint={},
        status=status,
        last_seen_at=last_seen_at,
    )
    session.add(m)
    await session.flush()
    return m


async def test_sweep_lost_full_workflow(session_factory, seeded_env, monkeypatch):
    """Verify đầy đủ logic sweep_lost: transition + threshold + ignore online + None last_seen."""
    from app.core.config import settings

    # Setup: tạo 4 máy với các trạng thái khác nhau
    from app.db.models import MachineStatus
    old_offline = datetime.now(UTC) - timedelta(days=settings.lost_after_days + 5)
    recent_offline = datetime.now(UTC) - timedelta(days=1)
    very_old_online = datetime.now(UTC) - timedelta(days=settings.lost_after_days + 10)

    m_old_offline = None
    m_recent_offline = None
    m_old_online = None
    m_no_lastseen = None
    async with session_factory() as session:
        m_old_offline = await _create_machine(
            session, seeded_env["org_id"], last_seen_at=old_offline, status="offline", hostname="old-off"
        )
        m_recent_offline = await _create_machine(
            session, seeded_env["org_id"], last_seen_at=recent_offline, status="offline", hostname="recent-off"
        )
        m_old_online = await _create_machine(
            session, seeded_env["org_id"], last_seen_at=very_old_online, status="online", hostname="old-on"
        )
        m_no_lastseen = await _create_machine(
            session, seeded_env["org_id"], last_seen_at=None, status="offline", hostname="no-lastseen"
        )
        await session.commit()
        ids = (m_old_offline.id, m_recent_offline.id, m_old_online.id, m_no_lastseen.id)

    # Run sweep with the test session factory.  The production module owns a
    # long-lived engine, which belongs to a different event loop in pytest.
    monkeypatch.setattr("app.services.monitor.AsyncSessionLocal", session_factory)
    await _sweep_lost()

    # Verify
    from sqlalchemy import select

    async with session_factory() as session:
        rows = (await session.execute(select(Machine).where(Machine.id.in_(ids)))).scalars().all()
        statuses = {m.hostname: m.status for m in rows}
        assert statuses["old-off"] == MachineStatus.LOST.value, (
            f"Máy offline >{settings.lost_after_days} ngày phải chuyển sang lost, "
            f"hiện tại: {statuses}"
        )
        assert statuses["recent-off"] == MachineStatus.OFFLINE.value, (
            f"Máy offline gần đây phải giữ nguyên, hiện tại: {statuses}"
        )
        assert statuses["old-on"] == MachineStatus.ONLINE.value, (
            f"Máy online KHÔNG bị đụng, hiện tại: {statuses}"
        )
        assert statuses["no-lastseen"] == MachineStatus.LOST.value, (
            f"Máy last_seen=None + offline phải chuyển sang lost, hiện tại: {statuses}"
        )


async def test_lost_after_days_default_is_15():
    """Default config = 15 ngày (operator có thể override .env)."""
    from app.core.config import settings

    assert settings.lost_after_days == 15, (
        f"Expected default 15 days, got {settings.lost_after_days}"
    )
