"""Alert engine — pipeline trigger_alert: template → scope → recipients → render → notify."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SUPER_ADMIN_ROLES
from app.db.models import AlertEvent, AlertRule, AlertTemplate, Machine, User
from app.services.alert_templates import get_template, render_template
from app.services.notifications import create_notification
from app.services.org_scope import scope_orgs
from app.services.user_notification_prefs import get_pref

logger = logging.getLogger("alert_engine")

# Role "org_admin" gồm alias legacy admin_org
ORG_ADMIN_ROLES = ("org_admin", "admin_org")

SEVERITY_RANK = {"info": 0, "success": 1, "warning": 2, "error": 3, "critical": 4}


class AlertEngine:
    """Pipeline render → scope → recipients → notify."""

    async def trigger_alert(
        self,
        db: AsyncSession,
        *,
        template_code: str,
        org_id: uuid.UUID | None,
        machine_id: uuid.UUID | None = None,
        context: dict | None = None,
    ) -> list[AlertEvent]:
        """Điểm vào duy nhất cho mọi trigger (monitor, DFIR, future).

        Trả list AlertEvent đã tạo (1 / subscription match).
        KHÔNG raise vì template lỗi — log + skip.
        """
        template = await get_template(db, template_code)
        if template is None or not template.enabled:
            logger.warning("trigger_alert: template %s không tồn tại hoặc disabled", template_code)
            return []

        # ── 1. Build context ─────────────────────────────────
        ctx = dict(context or {})
        ctx.setdefault("org_id", str(org_id) if org_id else None)
        if org_id:
            org_name = await self._org_name(db, org_id)
            if org_name:
                ctx.setdefault("org_name", org_name)
        if machine_id:
            machine = await db.get(Machine, machine_id)
            if machine:
                ctx.setdefault("hostname", machine.hostname)
                ctx.setdefault("ip", machine.public_ip)
                ctx.setdefault("machine_id", str(machine.id))
                if machine.last_seen_at:
                    ctx.setdefault("last_seen_at", machine.last_seen_at.isoformat())

        title = render_template(template.title_template, template.allowed_vars or [], ctx)
        body = render_template(template.body_template or "", template.allowed_vars or [], ctx) or None

        # ── 2. Find subscriptions match ──────────────────────
        rules = (await db.execute(
            select(AlertRule).where(
                AlertRule.template_code == template_code,
                AlertRule.enabled.is_(True),
            )
        )).scalars().all()
        if not rules:
            return []

        events: list[AlertEvent] = []
        for rule in rules:
            # Rule org scope — rule có org_id khác org trigger thì bỏ qua
            if rule.scope_mode != "system":
                if rule.org_id is None:
                    continue
                scope_ids = await scope_orgs(db, org_id=rule.org_id, scope_mode=rule.scope_mode)
                if org_id not in scope_ids:
                    continue
            else:
                scope_ids = await scope_orgs(db, org_id=None, scope_mode="system")

            fingerprint = self._fingerprint(rule.id, machine_id, template_code)
            dup = (await db.execute(
                select(AlertEvent).where(
                    AlertEvent.rule_id == rule.id,
                    AlertEvent.machine_id == machine_id,
                    AlertEvent.fingerprint == fingerprint,
                )
            )).scalar_one_or_none()
            if dup:
                continue

            recipients = await self._resolve_recipients(db, rule, template, scope_ids)
            if not recipients:
                logger.debug("trigger_alert: rule %s không có recipient", rule.id)

            event = AlertEvent(
                rule_id=rule.id,
                template_code=template_code,
                machine_id=machine_id,
                org_id=org_id,
                fingerprint=fingerprint,
                severity=template.default_severity,
                title=title,
                body=body,
                context=ctx,
                recipient_user_ids=[str(u.id) for u in recipients],
            )
            db.add(event)
            await db.flush()  # lấy event.id

            # ── 3. Fan-out notification ───────────────────────
            await self._deliver(db, event, recipients)
            events.append(event)

        await db.commit()
        return events

    # ── helpers ──────────────────────────────────────────────

    def _fingerprint(
        self, rule_id: uuid.UUID, machine_id: uuid.UUID | None, template_code: str
    ) -> str:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        raw = f"{rule_id}:{machine_id}:{template_code}:{day}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _org_name(self, db: AsyncSession, org_id: uuid.UUID) -> str | None:
        from app.db.models import Organization
        row = await db.get(Organization, org_id)
        return row.name if row else None

    async def _resolve_recipients(
        self,
        db: AsyncSession,
        rule: AlertRule,
        template: AlertTemplate,
        scope_ids: list[uuid.UUID],
    ) -> list[User]:
        """Org Admin của scope + Super Admin. Super Admin bỏ qua prefs."""
        if not scope_ids:
            return []

        org_admins = (await db.execute(
            select(User).where(
                User.is_active.is_(True),
                User.role.in_(ORG_ADMIN_ROLES),
                User.org_id.in_(scope_ids),
            )
        )).scalars().all()

        supers = (await db.execute(
            select(User).where(
                User.is_active.is_(True),
                User.role.in_(SUPER_ADMIN_ROLES),
            )
        )).scalars().all()

        severity = template.default_severity
        severity_rank = SEVERITY_RANK.get(severity, 0)
        controls = set(template.opt_out_controls or [])

        accepted: list[User] = []
        for u in org_admins:
            pref = await get_pref(db, u.id, template.code)
            if pref:
                if pref.muted:
                    continue
                if "severity" in controls and pref.min_severity and SEVERITY_RANK.get(pref.min_severity, 0) > severity_rank:
                    continue
            accepted.append(u)

        # Super Admin luôn nhận — KHÔNG filter prefs
        accepted.extend(supers)

        # Dedup
        seen: set[uuid.UUID] = set()
        out: list[User] = []
        for u in accepted:
            if u.id in seen:
                continue
            seen.add(u.id)
            out.append(u)
        return out

    async def _deliver(
        self, db: AsyncSession, event: AlertEvent, recipients: list[User]
    ) -> None:
        """Fan-out create_notification cho từng recipient + Telegram (qua create_notification)."""
        if not recipients:
            return
        ids = [u.id for u in recipients]
        await create_notification(
            db,
            recipient_ids=ids,
            source="system",
            category="alert",
            severity=event.severity,
            title=event.title,
            body=event.body,
            link=f"/machines/{event.machine_id}" if event.machine_id else None,
            entity_type="alert",
            entity_id=str(event.id),
            idempotency_key=f"alert-event:{event.id}:all",
        )


async def trigger_alert(
    db: AsyncSession,
    *,
    template_code: str,
    org_id: uuid.UUID | None,
    machine_id: uuid.UUID | None = None,
    context: dict | None = None,
) -> list[AlertEvent]:
    """Singleton helper — gọi từ monitor / dfir / future."""
    return await AlertEngine().trigger_alert(
        db,
        template_code=template_code,
        org_id=org_id,
        machine_id=machine_id,
        context=context,
    )
