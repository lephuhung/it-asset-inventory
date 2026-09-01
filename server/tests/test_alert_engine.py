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


# ── org_scope ────────────────────────────────────────────────────


async def test_scope_orgs_org_only_excludes_descendants(db, session_factory):
    from app.db.models import Organization

    root = Organization(name="Root Scope", type="don_vi")
    db.add(root)
    await db.flush()
    child = Organization(name="Child Scope", type="don_vi", parent_id=root.id)
    db.add(child)
    await db.commit()

    from app.services.org_scope import scope_orgs

    ids = await scope_orgs(db, org_id=root.id, scope_mode="org_only")
    assert ids == [root.id]
    assert child.id not in ids


async def test_scope_orgs_org_tree_includes_descendants(db, session_factory):
    from app.db.models import Organization

    root = Organization(name="Root Tree", type="don_vi")
    db.add(root)
    await db.flush()
    child = Organization(name="Child Tree", type="don_vi", parent_id=root.id)
    db.add(child)
    await db.flush()
    grand = Organization(name="Grand Tree", type="don_vi", parent_id=child.id)
    db.add(grand)
    await db.commit()

    from app.services.org_scope import scope_orgs

    ids = await scope_orgs(db, org_id=root.id, scope_mode="org_tree")
    assert set(ids) == {root.id, child.id, grand.id}


async def test_scope_orgs_system_returns_all(db, session_factory):
    from app.db.models import Organization

    org_a = Organization(name="System A", type="don_vi")
    org_b = Organization(name="System B", type="don_vi")
    db.add_all([org_a, org_b])
    await db.commit()

    from app.services.org_scope import all_org_ids

    ids = await all_org_ids(db)
    assert org_a.id in ids and org_b.id in ids


# ── alert_templates render ───────────────────────────────────────


from app.services.alert_templates import render_template, validate_template_vars


def test_render_substitutes_allowed_vars():
    out = render_template(
        "[{org_name}] Máy mới: {hostname}",
        ["org_name", "hostname"],
        {"org_name": "Sở Công an", "hostname": "PC-01"},
    )
    assert out == "[Sở Công an] Máy mới: PC-01"


def test_render_missing_var_substitutes_placeholder():
    out = render_template(
        "{hostname} {ip}",
        ["hostname", "ip"],
        {"hostname": "PC-01"},  # thiếu ip
    )
    assert out == "PC-01 [MISSING: ip]"


def test_validate_template_vars_returns_unknown():
    warnings = validate_template_vars(
        "[{org_name}] {hostname} {unknown_var}",
        None,
        ["org_name", "hostname"],
    )
    assert "unknown_var" in warnings
