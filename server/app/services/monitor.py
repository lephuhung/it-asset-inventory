"""Background monitor — chạy trong lifespan app.

1. Phát hiện máy chuyển offline (last_seen quá hạn) → publish WebSocket event.
2. Định kỳ đảm bảo partition `heartbeats` theo ngày có sẵn.
3. Quét alert rules (Phase 2): máy mới, máy mất liên lạc → ghi AlertEvent + gửi
   qua kênh đã cấu hình (SMTP / Telegram / Zalo — khi có settings).

Không dùng ARQ (Phase 2) — đủ cho Sprint 3 realtime; task đơn giản, 1 instance.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.models import AlertEvent, AlertRule, Machine, MachineStatus
from app.db.session import AsyncSessionLocal
from app.services.partition import ensure_heartbeat_partitions
from app.services.realtime import publish_machine_event

logger = logging.getLogger("monitor")

# Ngưỡng offline = 2× chu kỳ heartbeat tối đa + biên — lấy từ config (operator điều chỉnh
# heartbeat interval qua settings, monitor tự theo)
OFFLINE_THRESHOLD = timedelta(seconds=settings.effective_online_ttl_seconds + 60)
OFFLINE_SCAN_SECONDS = 30
PARTITION_SCAN_SECONDS = 3600  # mỗi giờ rà partition
ALERT_SCAN_SECONDS = 60        # mỗi phút quét alert rules
MACHINE_NEW_WINDOW_MINUTES = 30


async def _sweep_offline() -> None:
    """Máy last_seen quá hạn mà đang online → chuyển offline + publish."""
    cutoff = datetime.now(UTC) - OFFLINE_THRESHOLD
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Machine).where(
                        Machine.status == MachineStatus.ONLINE.value,
                        (Machine.last_seen_at.is_(None)) | (Machine.last_seen_at < cutoff),
                    )
                )
            )
            .scalars()
            .all()
        )
        for m in rows:
            m.status = MachineStatus.OFFLINE.value
            logger.info("Machine %s → offline (last_seen %s)", m.id, m.last_seen_at)
            await publish_machine_event(m.id, MachineStatus.OFFLINE.value, m.hostname)
        if rows:
            await db.commit()


async def _ensure_partitions() -> None:
    try:
        async with AsyncSessionLocal() as db:
            raw = await db.connection()
            from sqlalchemy import text

            rooted = await raw.execute(
                text(
                    "SELECT 1 FROM pg_class c JOIN pg_partitioned_table pt "
                    "ON c.oid = pt.partrelid WHERE c.relname = 'heartbeats'"
                )
            )
            is_rooted = rooted.first() is not None  # lưu kết quả — first() đóng result
            if is_rooted:
                created = await ensure_heartbeat_partitions(raw)
                if created:
                    # ⚠️ DDL partition là transactional — phải COMMIT mới lưu (nếu không
                    # session đóng → rollback → partition biến mất dù log đã in "Created")
                    await db.commit()
                    logger.info("Created heartbeat partitions: %s", created)
    except Exception:  # noqa: BLE001 — môi trường không phải PG partition (test) → bỏ qua
        logger.debug("Heartbeat partition setup skipped (không phải PG partition table)")


async def _deliver_alert(rule: AlertRule, event: AlertEvent) -> bool:
    """Gửi alert qua các kênh đã cấu hình. Trả True nếu gửi được ≥ 1 kênh."""
    delivered = False
    channels = rule.channels or []
    targets = rule.notify_targets or []
    subject = f"[IT Asset] {event.message}"

    if "email" in channels and settings.smtp_host and targets:
        try:
            from email.message import EmailMessage

            import aiosmtplib

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from
            msg["To"] = ", ".join(targets)
            msg.set_content(f"{event.message}\n\nHệ thống quản lý tài sản máy tính")
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_use_tls,
            )
            delivered = True
        except Exception as exc:  # noqa: BLE001 — lỗi gửi không làm chết job
            logger.warning("Alert email failed: %s", exc)

    if "telegram" in channels and settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            import httpx

            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    url,
                    json={"chat_id": settings.telegram_chat_id, "text": subject},
                    timeout=10,
                )
                delivered = delivered or r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alert telegram failed: %s", exc)

    if "zalo" in channels and settings.zalo_oa_token:
        logger.info("Zalo OA chưa được cấu hình đầy đủ — chỉ ghi event")

    return delivered


async def _scan_alerts() -> None:
    """Quét rule → tạo AlertEvent (không trùng lặp) + gửi kênh cấu hình."""
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        rules = (await db.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))).scalars().all()
        if not rules:
            return

        for rule in rules:
            messages: list[tuple[str, str, Machine]] = []  # (machine_id, message, machine)

            if rule.rule_type == "machine_new":
                cutoff = now - timedelta(minutes=MACHINE_NEW_WINDOW_MINUTES)
                machines = (
                    (
                        await db.execute(
                            select(Machine).where(
                                Machine.enrolled_at >= cutoff,
                                *([Machine.org_id == rule.org_id] if rule.org_id else []),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for m in machines:
                    messages.append((str(m.id), f"Máy mới enroll: {m.hostname or m.machine_uuid[:12]}", m))

            elif rule.rule_type == "machine_lost" and rule.threshold_days:
                cutoff = now - timedelta(days=rule.threshold_days)
                machines = (
                    (
                        await db.execute(
                            select(Machine).where(
                                Machine.status == MachineStatus.LOST.value,
                                (Machine.last_seen_at.is_(None)) | (Machine.last_seen_at < cutoff),
                                *([Machine.org_id == rule.org_id] if rule.org_id else []),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for m in machines:
                    messages.append(
                        (str(m.id), f"Mất liên lạc > {rule.threshold_days} ngày: {m.hostname or m.machine_uuid[:12]}", m)
                    )

            # software_new / hardware_changed — cần diff snapshot (Phase 3 khi có cơ chế so sánh)
            if not messages:
                continue

            existing = {
                row[0]
                for row in (
                    await db.execute(
                        select(AlertEvent.fingerprint).where(AlertEvent.rule_id == rule.id)
                    )
                ).all()
            }

            for machine_id, message, machine in messages:
                fingerprint = hashlib.sha256(
                    f"{rule.id}:{machine_id}:{now.strftime('%Y-%m-%d')}".encode()
                ).hexdigest()
                if fingerprint in existing:
                    continue
                event = AlertEvent(
                    rule_id=rule.id,
                    machine_id=machine.id,
                    fingerprint=fingerprint,
                    severity="warning" if rule.rule_type == "machine_lost" else "info",
                    message=message,
                    channels=rule.channels or [],
                )
                event.delivered = await _deliver_alert(rule, event)
                db.add(event)
                logger.info("Alert %s → %s (delivered=%s)", rule.rule_type, machine_id, event.delivered)

        await db.commit()


async def monitor_loop() -> None:
    """Vòng lặp chính — chạy nền suốt vòng đời app."""
    # Chạy partition check NGAY ở vòng đầu (last=-3600 → now-(-3600)>=3600 luôn đúng)
    last_partition_check = -PARTITION_SCAN_SECONDS
    last_alert_check = -ALERT_SCAN_SECONDS
    while True:
        try:
            await _sweep_offline()
            now = asyncio.get_event_loop().time()
            if now - last_partition_check >= PARTITION_SCAN_SECONDS:
                await _ensure_partitions()
                last_partition_check = now
            if now - last_alert_check >= ALERT_SCAN_SECONDS:
                await _scan_alerts()
                last_alert_check = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("Monitor loop error: %s", exc)
        await asyncio.sleep(OFFLINE_SCAN_SECONDS)


async def start_monitor() -> asyncio.Task:
    task = asyncio.create_task(monitor_loop())
    return task
