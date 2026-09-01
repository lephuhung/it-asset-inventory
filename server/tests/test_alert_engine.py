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


# ── user_notification_prefs ──────────────────────────────────────


from app.services.user_notification_prefs import (
    get_pref,
    get_prefs_with_template,
    upsert_prefs,
)
from fastapi import HTTPException


async def test_upsert_prefs_respects_opt_out_controls(db, session_factory, seeded_env):
    from app.db.models import User

    # Template với opt_out_controls=["severity"] → không cho muted
    tpl = AlertTemplate(
        code="unit_sev_tpl",
        name="Sev only",
        category="machine",
        default_severity="warning",
        title_template="{hostname}",
        opt_out_controls=["severity"],
        allowed_vars=["hostname"],
    )
    db.add(tpl)
    await db.commit()

    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()

    # muted=true với template chỉ có "severity" → phải raise
    with pytest.raises(HTTPException) as exc:
        await upsert_prefs(db, admin, [
            {"template_code": "unit_sev_tpl", "muted": True, "min_severity": None},
        ])
    assert exc.value.status_code == 422


async def test_upsert_prefs_sets_min_severity_when_allowed(db, session_factory, seeded_env):
    from app.db.models import User

    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    await upsert_prefs(db, admin, [
        {"template_code": "machine_offline", "muted": False, "min_severity": "error"},
    ])

    pref = await get_pref(db, admin.id, "machine_offline")
    assert pref is not None
    assert pref.min_severity == "error"
    assert pref.muted is False


async def test_get_prefs_with_template_returns_meta(db, session_factory, seeded_env):
    from app.db.models import User

    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    prefs = await get_prefs_with_template(db, admin.id)
    codes = {p["template_code"] for p in prefs}
    assert "machine_new" in codes
    # machine_new có opt_out_controls=["template"] → metadata đi kèm
    row = next(p for p in prefs if p["template_code"] == "machine_new")
    assert row["opt_out_controls"] == ["template"]
