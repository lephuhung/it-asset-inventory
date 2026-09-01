"""Background monitor — chạy trong lifespan app.

1. Phát hiện máy chuyển offline (last_seen quá hạn) → publish WebSocket event.
2. Định kỳ đảm bảo partition `heartbeats` theo ngày có sẵn.
3. Quét alert rules (Phase 2): máy mới, máy mất liên lạc → ghi AlertEvent + gửi
   qua kênh đã cấu hình (SMTP / Telegram / Zalo — khi có settings).

Không dùng ARQ (Phase 2) — đủ cho Sprint 3 realtime; task đơn giản, 1 instance.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.models import Machine, MachineStatus
from app.db.session import AsyncSessionLocal
from app.services import dfir_investigation
from app.services.partition import ensure_heartbeat_partitions
from app.services.realtime import publish_machine_event

logger = logging.getLogger("monitor")

# Ngưỡng offline = 2× chu kỳ heartbeat tối đa + biên — lấy từ config (operator điều chỉnh
# heartbeat interval qua settings, monitor tự theo)
OFFLINE_THRESHOLD = timedelta(seconds=settings.effective_online_ttl_seconds + 60)
OFFLINE_SCAN_SECONDS = 30
PARTITION_SCAN_SECONDS = 3600  # mỗi giờ rà partition
ALERT_SCAN_SECONDS = 60        # mỗi phút quét alert rules
LOST_SCAN_SECONDS = 3600       # mỗi giờ quét máy mất kết nối lâu ngày
MACHINE_NEW_WINDOW_MINUTES = 30
VELOCIRAPTOR_SYNC_SECONDS = settings.velociraptor_sync_interval_seconds  # 5 phút — sync hostname ↔ client_id
LLM_DFIR_WORKER_SECONDS = settings.llm_investigation_interval_seconds  # 30 giây — poll LLM-DFIR job


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
            # Alert real-time: máy offline (best-effort, không block sweep)
            try:
                from app.db.models import AlertRule as AR
                from app.services.alert_engine import trigger_alert

                has_rule = (await db.execute(
                    select(AR.id).where(
                        AR.template_code == "machine_offline",
                        AR.enabled.is_(True),
                    ).limit(1)
                )).scalar_one_or_none()
                if has_rule:
                    await trigger_alert(
                        db,
                        template_code="machine_offline",
                        org_id=m.org_id,
                        machine_id=m.id,
                        context={"hostname": m.hostname or m.machine_uuid[:12]},
                    )
            except Exception:  # noqa: BLE001 — non-critical
                logger.debug("trigger machine_offline failed")
        if rows:
            await db.commit()


async def _sweep_lost() -> None:
    """Máy offline liên tục quá `lost_after_days` ngày → chuyển `lost` (máy mất kết nối).

    Điều kiện: status=offline AND last_seen_at < now - lost_after_days.
    Hiển thị trong trang /ghost-machines (label: "Máy mất kết nối").

    Không tự động chuyển ngược: máy từng `lost` phải có heartbeat/import mới để
    được admin/webhook chuyển về `online` (qua API).
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.lost_after_days)
    async with AsyncSessionLocal() as db:
        try:
            rows = (
                (
                    await db.execute(
                        select(Machine).where(
                            Machine.status == MachineStatus.OFFLINE.value,
                            (Machine.last_seen_at.is_(None)) | (Machine.last_seen_at < cutoff),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for m in rows:
                m.status = MachineStatus.LOST.value
                logger.info(
                    "Machine %s → lost (last_seen %s, threshold=%d days)",
                    m.id, m.last_seen_at, settings.lost_after_days,
                )
                # Realtime: lỗi Redis không được block sweep
                try:
                    await publish_machine_event(m.id, MachineStatus.LOST.value, m.hostname)
                except Exception:  # noqa: BLE001 — non-critical
                    logger.debug("publish_machine_event failed (Redis down?)")
            if rows:
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — đừng làm vỡ monitor loop
            logger.warning("Sweep lost lỗi: %s", exc)
            await db.rollback()


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


async def _scan_alerts() -> None:
    """Quét rule → tìm máy khớp → gọi alert_engine.trigger_alert.

    machine_new: máy enrolled trong MACHINE_NEW_WINDOW_MINUTES phút.
    machine_lost: máy LOST quá threshold_days (config hoặc default template).
    software_new / hardware_changed: Phase 3 — chưa có trigger.
    """
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        from app.db.models import AlertRule as AR
        from app.services.alert_engine import trigger_alert
        from app.services.alert_templates import get_template
        from app.services.org_scope import scope_orgs

        rules = (await db.execute(select(AR).where(AR.enabled.is_(True)))).scalars().all()
        if not rules:
            return

        for rule in rules:
            tpl = await get_template(db, rule.template_code)
            if tpl is None:
                continue

            scope_ids = await scope_orgs(db, org_id=rule.org_id, scope_mode=rule.scope_mode)
            if not scope_ids:
                continue

            if rule.template_code == "machine_new":
                cutoff = now - timedelta(minutes=MACHINE_NEW_WINDOW_MINUTES)
                machines = (
                    (
                        await db.execute(
                            select(Machine).where(
                                Machine.enrolled_at >= cutoff,
                                Machine.org_id.in_(scope_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for m in machines:
                    await trigger_alert(
                        db,
                        template_code="machine_new",
                        org_id=m.org_id,
                        machine_id=m.id,
                        context={
                            "hostname": m.hostname or m.machine_uuid[:12],
                            "enrolled_at": m.enrolled_at.isoformat() if m.enrolled_at else None,
                        },
                    )

            elif rule.template_code == "machine_lost":
                threshold = int((rule.config or {}).get("threshold_days", 7))
                cutoff = now - timedelta(days=threshold)
                machines = (
                    (
                        await db.execute(
                            select(Machine).where(
                                Machine.status == MachineStatus.LOST.value,
                                (Machine.last_seen_at.is_(None)) | (Machine.last_seen_at < cutoff),
                                Machine.org_id.in_(scope_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for m in machines:
                    await trigger_alert(
                        db,
                        template_code="machine_lost",
                        org_id=m.org_id,
                        machine_id=m.id,
                        context={
                            "hostname": m.hostname or m.machine_uuid[:12],
                            "threshold_days": threshold,
                        },
                    )
        await db.commit()

        await db.commit()


async def monitor_loop() -> None:
    """Vòng lặp chính — chạy nền suốt vòng đời app."""
    # Chạy partition check NGAY ở vòng đầu (last=-3600 → now-(-3600)>=3600 luôn đúng)
    last_partition_check = -PARTITION_SCAN_SECONDS
    last_alert_check = -ALERT_CHECK_SECONDS
    last_schedule_check = -DFIR_SCHEDULE_SCAN_SECONDS
    last_lost_check = -LOST_SCAN_SECONDS
    last_velociraptor_check = -VELOCIRAPTOR_SYNC_SECONDS
    last_llm_dfir_check = -LLM_DFIR_WORKER_SECONDS
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
            if now - last_lost_check >= LOST_SCAN_SECONDS:
                await _sweep_lost()
                last_lost_check = now
            if now - last_velociraptor_check >= VELOCIRAPTOR_SYNC_SECONDS:
                # Đọc trạng thái enabled t� DB (admin toggle qua portal), không dùng
                # settings.velociraptor_enabled (env — chỉ default ban đầu).
                # NOTE: Velociraptor hostname ↔ client_id mapping NO LONGER auto-sync.
                # Full on-demand — admin trigger qua POST /sync (manual).
                # Sync function kept in app.services.velociraptor_sync for manual use.
                last_velociraptor_check = now

            # LLM-DFIR investigation worker — poll job pending/running/collecting/analyzing
            if now - last_llm_dfir_check >= LLM_DFIR_WORKER_SECONDS:
                try:
                    await dfir_investigation.run_pending_investigations()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LLM-DFIR worker error: %s", exc)
                last_llm_dfir_check = now

            # NOTE: DFIR schedules + alerts NO LONGER auto-run on cron.
            # User yêu cầu full on-demand — admin trigger qua portal endpoints:
            # - POST /api/admin/velociraptor/schedules/{id}/run-now  (manual)
            # - POST /api/admin/velociraptor/alerts/scan             (manual)
            # Cron vars (last_alert_check, last_schedule_check) giữ để không
            # break signature, nhưng không còn trigger scan tự động.
        except Exception as exc:  # noqa: BLE001
            logger.warning("Monitor loop error: %s", exc)
        await asyncio.sleep(OFFLINE_SCAN_SECONDS)


async def start_monitor() -> asyncio.Task:
    task = asyncio.create_task(monitor_loop())
    return task


# ── DFIR scheduler + alert detector ─────────────────────────────────

# Sensitive artifacts → trigger alert (admin có thể tùy chỉnh phase 3 qua portal)
SENSITIVE_ARTIFACT_PATTERNS = [
    ("Windows.Persistence.Permanent*", "critical", "Persistence mechanism detected"),
    ("Windows.System.Services", "info", "Service enumeration"),
    ("Windows.EventLogs.Reboot", "info", "Reboot event"),
    ("Windows.EventLogs.Application", "info", "Application log"),
    ("Windows.Network.Netstat", "warning", "Network connections"),
    ("Windows.ScheduledTasks.Catalog", "warning", "Scheduled task"),
    ("Generic.Detection.FIM.High", "warning", "File integrity"),
    ("Generic.Client.Info", "info", "Client baseline"),
    ("Windows.Registry.Recursive", "warning", "Registry scan"),
]

DFIR_SCHEDULE_SCAN_SECONDS = 60  # check schedules mỗi phút
ALERT_CHECK_SECONDS = 600  # scan alerts mỗi 10p


async def _scan_dfir_schedules() -> None:
    """Check dfir_schedules có next_run_at <= now → trigger."""
    from datetime import datetime as dt
    from sqlalchemy import select as sa_select, update
    from app.db.models import DfirSchedule, DfirHunt, VelociraptorLink
    from app.db.session import AsyncSessionLocal
    from app.services.velociraptor import VelociraptorClient, VelociraptorError

    async with AsyncSessionLocal() as db:
        now = dt.now(UTC)
        due = (
            await db.execute(
                sa_select(DfirSchedule)
                .where(DfirSchedule.enabled == True)  # noqa: E712
                .where(DfirSchedule.next_run_at <= now)
            )
        ).scalars().all()

        if not due:
            return

        # Build VelociraptorClient 1 lần (dùng chung cho nhiều schedule)
        cfg = (
            await db.execute(sa_select(type(db)._mapper_registry_ if False else object))  # noop
        ) if False else None
        from app.api.routes.velociraptor import _build_velociraptor_client

        for sch in due:
            built = await _build_velociraptor_client(db)
            if built is None:
                sch.last_status = "error"
                sch.last_error = "Velociraptor chưa cấu hình"
                continue

            client, _ = built
            from datetime import timedelta

            dfir = DfirHunt(
                artifact=sch.artifact,
                scope=sch.scope,
                machine_id=None,
                requested_by=sch.requested_by,
                status="pending",
                notes=f"Auto-run từ schedule '{sch.name}'",
            )
            db.add(dfir)
            client_count = 0
            try:
                async with client as velo:
                    if sch.scope == "multi":
                        machine_ids = sch.machine_ids or []
                        links = (
                            await db.execute(
                                sa_select(VelociraptorLink).where(
                                    VelociraptorLink.machine_id.in_(
                                        [uuid.UUID(m) for m in machine_ids]
                                    )
                                )
                            )
                        ).scalars().all()
                        tasks = [
                            velo.collect_artifact(l.client_id, [sch.artifact])
                            for l in links
                        ]
                        flow_ids = await asyncio.gather(*tasks, return_exceptions=True)
                        successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                        client_count = len(successful)
                        if successful:
                            dfir.hunt_id = successful[0]
                    else:
                        clients = await velo.get_all_clients()
                        client_ids = [c.get("client_id") for c in clients if c.get("client_id")]
                        client_count = len(client_ids)
                        if client_count == 0:
                            continue
                        # Run collect_artifact per client (parallel) — không dùng create_hunt
                        # vì Velociraptor cần artifact definition + org config setup phức tạp
                        tasks = [velo.collect_artifact(cid, [sch.artifact]) for cid in client_ids]
                        flow_ids = await asyncio.gather(*tasks, return_exceptions=True)
                        successful = [fid for fid in flow_ids if isinstance(fid, str) and fid]
                        client_count = len(successful)
                        if successful:
                            dfir.hunt_id = successful[0]

                dfir.status = "completed"
                sch.last_status = "completed"
                sch.last_error = None
                sch.last_run_at = now
                sch.next_run_at = now + timedelta(seconds=sch.interval_seconds)
                logger.info(
                    "Schedule %s chạy: artifact=%s, clients=%d",
                    sch.id, sch.artifact, client_count,
                )
            except VelociraptorError as e:
                dfir.status = "error"
                dfir.error = str(e)
                sch.last_status = "error"
                sch.last_error = str(e)
                sch.last_run_at = now
                sch.next_run_at = now + timedelta(seconds=sch.interval_seconds)
                logger.warning("Schedule %s lỗi: %s", sch.id, e)
            except Exception as e:  # noqa: BLE001
                dfir.status = "error"
                dfir.error = str(e)
                sch.last_status = "error"
                sch.last_error = str(e)
                logger.exception("Schedule %s ngoại lệ", sch.id)
        await db.commit()


async def _scan_sensitive_flows() -> None:
    """Scan recent flows cho sensitive artifacts → tạo alerts (Phase 3 sẽ tích hợp AlertRule)."""
    from datetime import datetime as dt, timedelta
    from sqlalchemy import select as sa_select, func
    from app.db.models import DfirAlert, DfirHunt, VelociraptorLink

    # Lấy các hunt gần đây (24h) có artifact match sensitive patterns
    cutoff = dt.now(UTC) - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        for pattern, severity, description in SENSITIVE_ARTIFACT_PATTERNS:
            # Match artifact name theo glob pattern (vd "Windows.Persistence.Permanent*")
            artifact_prefix = pattern.rstrip("*")
            recent = (
                await db.execute(
                    sa_select(DfirHunt)
                    .where(DfirHunt.created_at >= cutoff)
                    .where(DfirHunt.artifact.like(artifact_prefix + "%"))
                    .where(DfirHunt.hunt_id.is_not(None))  # chỉ hunt có flow_id thật
                )
            ).scalars().all()

            for hunt in recent:
                # Tránh tạo alert trùng cho cùng hunt_id
                existing = (
                    await db.execute(
                        sa_select(DfirAlert).where(DfirAlert.flow_id == hunt.hunt_id)
                    )
                ).scalars().first()
                if existing:
                    continue

                # Resolve machine_id nếu scope=single
                machine_id = hunt.machine_id
                client_id = None
                if hunt.scope == "single" and machine_id:
                    link = (
                        await db.execute(
                            sa_select(VelociraptorLink).where(
                                VelociraptorLink.machine_id == machine_id
                            )
                        )
                    ).scalar_one_or_none()
                    if link:
                        client_id = link.client_id

                alert = DfirAlert(
                    artifact_pattern=pattern,
                    severity=severity,
                    flow_id=hunt.hunt_id,
                    client_id=client_id,
                    machine_id=machine_id,
                    message=(
                        f"{description}: artifact={hunt.artifact}, "
                        f"flow_id={hunt.hunt_id}, scope={hunt.scope}"
                    ),
                )
                db.add(alert)
                logger.info(
                    "DFIR alert: artifact=%s match pattern=%s severity=%s",
                    hunt.artifact, pattern, severity,
                )
        await db.commit()
