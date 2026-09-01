"""E2E: machine enroll → alert → Org Admin nhận in-app + Telegram (nếu link)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.db.models import Machine, MachineStatus, User, UserNotificationPref
from app.services.monitor import _scan_alerts


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_machine_enroll_triggers_notification_to_org_admin(
    client, session_factory, seeded_env, seeded_templates,
):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    # Seeded admin → org_admin
    async with session_factory() as s:
        admin = (await s.execute(
            select(User).where(User.email == seeded_env["email"])
        )).scalar_one()
        admin.role = "org_admin"
        await s.commit()

    # Tạo rule machine_new cho org
    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Máy mới E2E",
            "template_code": "machine_new",
            "org_id": str(org_id),
            "scope_mode": "org_only",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # Enroll máy mới (giả lập trực tiếp DB — window 30 phút)
    async with session_factory() as s:
        m = Machine(
            org_id=org_id, machine_uuid="uuid-e2e-1", hostname="PC-E2E",
            status=MachineStatus.ONLINE.value,
            enrolled_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()
        mid = m.id

    # Scan alerts
    await _scan_alerts()

    # Org Admin nhận notification (in-app bell)
    async with session_factory() as s:
        from app.db.models import Notification
        notifs = (await s.execute(
            select(Notification).where(Notification.recipient_id == admin.id)
        )).scalars().all()
        assert any("Máy mới" in n.title and n.category == "alert" for n in notifs)
        assert mid is not None


async def test_machine_enroll_sends_telegram_to_linked_admin(
    client, session_factory, seeded_env, seeded_templates, seeded_telegram_bot,
):
    from app.services.telegram_runtime import invalidate_bot_cache

    invalidate_bot_cache()  # test trước có thể đã cache trạng thái "none"
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    async with session_factory() as s:
        admin = (await s.execute(
            select(User).where(User.email == seeded_env["email"])
        )).scalar_one()
        admin.role = "org_admin"
        admin.telegram_chat_id = "123456789"  # đã link Telegram
        await s.commit()

    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Máy mới TG",
            "template_code": "machine_new",
            "org_id": str(org_id),
            "scope_mode": "org_only",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    async with session_factory() as s:
        m = Machine(
            org_id=org_id, machine_uuid="uuid-e2e-2", hostname="PC-E2E-TG",
            status=MachineStatus.ONLINE.value,
            enrolled_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()

    # Mock telegram sendMessage → 200
    with patch("app.services.notifications.httpx.AsyncClient") as MockClient:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        MockClient.return_value.__aenter__.return_value.post.return_value = mock_resp

        await _scan_alerts()

    # NotificationDelivery telegram = delivered
    async with session_factory() as s:
        from app.db.models import Notification, NotificationDelivery
        notif = (await s.execute(
            select(Notification).where(Notification.recipient_id == admin.id)
        )).scalars().first()
        assert notif is not None
        delivery = (await s.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notif.id,
                NotificationDelivery.channel == "telegram",
            )
        )).scalar_one_or_none()
        assert delivery is not None
        assert delivery.status == "delivered"


async def test_org_admin_mute_stops_notification(client, session_factory, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    async with session_factory() as s:
        admin = (await s.execute(
            select(User).where(User.email == seeded_env["email"])
        )).scalar_one()
        admin.role = "org_admin"
        # Mute machine_new
        s.add(UserNotificationPref(user_id=admin.id, template_code="machine_new", muted=True))
        await s.commit()

    r = await client.post(
        "/api/alert-rules",
        json={"name": "Muted", "template_code": "machine_new", "org_id": str(org_id), "scope_mode": "org_only"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    async with session_factory() as s:
        m = Machine(
            org_id=org_id, machine_uuid="uuid-e2e-3", hostname="PC-MUTED",
            status=MachineStatus.ONLINE.value,
            enrolled_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()

    await _scan_alerts()

    async with session_factory() as s:
        from app.db.models import Notification
        notifs = (await s.execute(
            select(Notification).where(Notification.recipient_id == admin.id)
        )).scalars().all()
        assert not any("Máy mới" in n.title for n in notifs)
