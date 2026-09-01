"""Unit tests alert engine redesign — models, render, engine, prefs."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import (
    AlertEvent,
    AlertRule,
    AlertTemplate,
    Machine,
    MachineStatus,
    User,
    UserNotificationPref,
)


async def test_alert_template_model_roundtrip(db, session_factory):
    t = AlertTemplate(
        code="unit_test_tpl",
        name="Unit test template",
        category="machine",
        default_severity="info",
        title_template="[{org_name}] {hostname}",
        body_template="{hostname} {ip}",
        opt_out_controls=["template"],
        allowed_vars=["hostname", "ip", "org_name"],
        default_config={},
    )
    db.add(t)
    await db.commit()

    async with session_factory() as s:
        row = (await s.execute(select(AlertTemplate).where(AlertTemplate.code == "unit_test_tpl"))).scalar_one()
        assert row.opt_out_controls == ["template"]
        assert row.allowed_vars == ["hostname", "ip", "org_name"]
        assert row.title_template == "[{org_name}] {hostname}"
