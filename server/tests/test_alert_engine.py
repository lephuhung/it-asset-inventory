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


async def test_upsert_prefs_sets_min_severity_when_allowed(db, session_factory, seeded_env, seeded_templates):
    from app.db.models import User

    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    await upsert_prefs(db, admin, [
        {"template_code": "machine_offline", "muted": False, "min_severity": "error"},
    ])

    pref = await get_pref(db, admin.id, "machine_offline")
    assert pref is not None
    assert pref.min_severity == "error"
    assert pref.muted is False


async def test_get_prefs_with_template_returns_meta(db, session_factory, seeded_env, seeded_templates):
    from app.db.models import User

    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    prefs = await get_prefs_with_template(db, admin.id)
    codes = {p["template_code"] for p in prefs}
    assert "machine_new" in codes
    # machine_new có opt_out_controls=["template"] → metadata đi kèm
    row = next(p for p in prefs if p["template_code"] == "machine_new")
    assert row["opt_out_controls"] == ["template"]


# ── alert_engine ────────────────────────────────────────────────


from app.services.alert_engine import AlertEngine


async def _make_machine(db, *, org_id, hostname="PC-ENGINE", machine_uuid="uuid-engine-1", enrolled=None):
    m = Machine(
        org_id=org_id,
        machine_uuid=machine_uuid,
        hostname=hostname,
        status=MachineStatus.ONLINE.value,
        enrolled_at=enrolled or datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(m)
    await db.flush()
    return m


async def test_trigger_alert_creates_event_with_correct_recipients(
    db, session_factory, seeded_env, seeded_templates
):
    from app.db.models import AlertRule, User

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    # seeded admin role = ? — set org_admin để có recipient
    admin.role = "org_admin"
    await db.commit()

    m = await _make_machine(db, org_id=org_id)

    rule = AlertRule(
        name="Engine test",
        template_code="machine_new",
        org_id=org_id,
        scope_mode="org_only",
        recipient_mode="org_admins_and_super",
        created_by=admin.id,
    )
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    events = await engine.trigger_alert(
        db,
        template_code="machine_new",
        org_id=org_id,
        machine_id=m.id,
        context={"hostname": m.hostname, "org_name": "Test Org"},
    )

    assert len(events) == 1
    assert events[0].rule_id == rule.id
    assert str(admin.id) in events[0].recipient_user_ids
    # Notification đã tạo cho admin
    from app.db.models import Notification
    notifs = (await db.execute(
        select(Notification).where(Notification.recipient_id == admin.id)
    )).scalars().all()
    assert any("Máy mới" in n.title for n in notifs)


async def test_trigger_alert_dedup_same_day(db, session_factory, seeded_env, seeded_templates):
    from app.db.models import AlertRule, User

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(
        name="Dedup", template_code="machine_new", org_id=org_id,
        scope_mode="org_only", created_by=admin.id,
    )
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                               machine_id=m.id, context={"hostname": m.hostname})
    await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                               machine_id=m.id, context={"hostname": m.hostname})

    events = (await db.execute(select(AlertEvent))).scalars().all()
    assert len(events) == 1


async def test_org_admin_opt_out_respected(db, session_factory, seeded_env, seeded_templates):
    from app.db.models import AlertRule, User, UserNotificationPref

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    # Admin mute machine_new
    db.add(UserNotificationPref(user_id=admin.id, template_code="machine_new", muted=True))
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(
        name="Muted", template_code="machine_new", org_id=org_id,
        scope_mode="org_only", created_by=admin.id,
    )
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    events = await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                                        machine_id=m.id, context={"hostname": m.hostname})
    # Admin mute → không nhận → event vẫn tạo nhưng recipient_user_ids rỗng (chỉ có admin)
    assert len(events) == 1
    assert str(admin.id) not in events[0].recipient_user_ids


async def test_super_admin_always_receives_even_if_pref_muted(
    db, session_factory, seeded_env, seeded_templates
):
    from app.db.models import AlertRule, User, UserNotificationPref

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "super_admin"
    await db.commit()

    # Super admin cũng mute (nhưng hệ thống phải bỏ qua)
    db.add(UserNotificationPref(user_id=admin.id, template_code="machine_new", muted=True))
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(
        name="Super", template_code="machine_new", org_id=org_id,
        scope_mode="org_only", created_by=admin.id,
    )
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    events = await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                                        machine_id=m.id, context={"hostname": m.hostname})
    assert len(events) == 1
    assert str(admin.id) in events[0].recipient_user_ids


async def test_min_severity_filters_lower_severity(db, session_factory, seeded_env, seeded_templates):
    from app.db.models import AlertRule, User, UserNotificationPref

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    # machine_offline default_severity=warning; admin chỉ nhận từ error trở lên
    db.add(UserNotificationPref(
        user_id=admin.id, template_code="machine_offline",
        muted=False, min_severity="error",
    ))
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(
        name="Offline", template_code="machine_offline", org_id=org_id,
        scope_mode="org_only", created_by=admin.id,
    )
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    events = await engine.trigger_alert(db, template_code="machine_offline", org_id=org_id,
                                        machine_id=m.id, context={"hostname": m.hostname})
    assert len(events) == 1
    assert str(admin.id) not in events[0].recipient_user_ids


async def test_disabled_template_and_disabled_rule_no_trigger(
    db, session_factory, seeded_env, seeded_templates
):
    from app.db.models import AlertRule, User

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(
        name="Disabled rule", template_code="machine_new", org_id=org_id,
        scope_mode="org_only", enabled=False, created_by=admin.id,
    )
    db.add(rule)
    await db.commit()

    engine = AlertEngine()
    events = await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                                        machine_id=m.id, context={"hostname": m.hostname})
    assert events == []


# ── routes: alert_templates_admin ──────────────────────────────


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_alert_templates_admin_crud(client, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/admin/alert-templates", headers=h)
    assert r.status_code == 200
    codes = [t["code"] for t in r.json()]
    assert "machine_new" in codes

    r = await client.get("/api/admin/alert-templates/machine_new", headers=h)
    assert r.status_code == 200
    assert r.json()["title_template"].startswith("[{org_name}]")

    r = await client.patch(
        "/api/admin/alert-templates/machine_new",
        json={"title_template": "[{org_name}] ⚠ MÁY MỚI: {hostname}"},
        headers=h,
    )
    assert r.status_code == 200
    assert "MÁY MỚI" in r.json()["title_template"]

    # Validate: opt_out_controls không hợp lệ → 422
    r = await client.patch(
        "/api/admin/alert-templates/machine_new",
        json={"opt_out_controls": ["slack"]},
        headers=h,
    )
    assert r.status_code == 422

    # Validate: biến không khai báo → 422
    r = await client.patch(
        "/api/admin/alert-templates/machine_new",
        json={"title_template": "[{org_name}] {not_allowed_var}"},
        headers=h,
    )
    assert r.status_code == 422


async def test_alert_templates_preview(client, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/admin/alert-templates/machine_new/preview",
        json={"context": {"hostname": "PC-X", "org_name": "Sở"}},
        headers=h,
    )
    assert r.status_code == 200
    assert "PC-X" in r.json()["title"]
    assert r.json()["body"] is not None


# ── routes: alert_rules ────────────────────────────────────────


async def test_alert_rules_crud_new_schema(client, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    org_id = seeded_env["org_id"]

    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Máy mới Sở Công an",
            "template_code": "machine_new",
            "org_id": org_id,
            "scope_mode": "org_tree",
            "recipient_mode": "org_admins_and_super",
            "config": {},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    rule_id = r.json()["id"]
    assert r.json()["template_name"] == "Máy mới enroll trong tổ chức"

    r = await client.get("/api/alert-rules", headers=h)
    assert r.status_code == 200
    assert any(x["id"] == rule_id for x in r.json()["items"])

    r = await client.patch(
        f"/api/alert-rules/{rule_id}", json={"enabled": False}, headers=h
    )
    assert r.status_code == 200 and r.json()["enabled"] is False

    # scope_mode system với template không tồn tại → 422
    r = await client.post(
        "/api/alert-rules",
        json={"name": "Bad", "template_code": "nope", "org_id": None, "scope_mode": "system"},
        headers=h,
    )
    assert r.status_code == 422

    r = await client.delete(f"/api/alert-rules/{rule_id}", headers=h)
    assert r.status_code == 200


async def test_alert_rules_dry_run_test(client, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}
    org_id = seeded_env["org_id"]

    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Dry run",
            "template_code": "machine_new",
            "org_id": org_id,
            "scope_mode": "org_only",
        },
        headers=h,
    )
    rule_id = r.json()["id"]

    r = await client.post(
        f"/api/alert-rules/{rule_id}/test",
        json={"context": {"hostname": "PC-DRY"}},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()
    assert "PC-DRY" in data["title"]
    assert isinstance(data["total_recipients"], int)


# ── routes: alert_events ────────────────────────────────────────


async def test_alert_events_list(client, seeded_env, db, session_factory, seeded_templates):
    from app.db.models import AlertRule, User

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(name="Events", template_code="machine_new", org_id=org_id,
                     scope_mode="org_only", created_by=admin.id)
    db.add(rule)
    await db.flush()
    await db.commit()

    engine = AlertEngine()
    await engine.trigger_alert(db, template_code="machine_new", org_id=org_id,
                               machine_id=m.id, context={"hostname": m.hostname})

    token = await _login(client, seeded_env["email"], seeded_env["password"])
    r = await client.get("/api/alert-rules/events", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1
    item = r.json()["items"][0]
    assert "title" in item
    assert "recipient_user_ids" in item


# ── routes: user_notification_prefs ─────────────────────────────


async def test_me_notification_prefs_get_and_patch(client, seeded_env, seeded_templates):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/me/notification-prefs", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    codes = {p["template_code"] for p in items}
    assert "machine_new" in codes

    # machine_offline (opt_out_controls=["severity"]) — set min_severity=error
    r = await client.patch(
        "/api/me/notification-prefs",
        json={"prefs": [{"template_code": "machine_offline", "muted": False, "min_severity": "error"}]},
        headers=h,
    )
    assert r.status_code == 200
    row = next(p for p in r.json()["items"] if p["template_code"] == "machine_offline")
    assert row["min_severity"] == "error"

    # machine_new (opt_out_controls=["template"]) — set muted=true
    r = await client.patch(
        "/api/me/notification-prefs",
        json={"prefs": [{"template_code": "machine_new", "muted": True, "min_severity": None}]},
        headers=h,
    )
    assert r.status_code == 200
    row = next(p for p in r.json()["items"] if p["template_code"] == "machine_new")
    assert row["muted"] is True

    # machine_new muted — nhưng không được set min_severity (chỉ có "template")
    r = await client.patch(
        "/api/me/notification-prefs",
        json={"prefs": [{"template_code": "machine_new", "muted": False, "min_severity": "critical"}]},
        headers=h,
    )
    assert r.status_code == 422


# ── DFIR trigger via engine ────────────────────────────────────


async def test_dfir_trigger_alert_via_engine(db, session_factory, seeded_env, seeded_templates):
    """Trigger trực tiếp qua engine (không cần LLM) — investigation_completed."""
    from app.db.models import AlertRule, User

    org_id = uuid.UUID(seeded_env["org_id"])
    admin = (await db.execute(select(User).where(User.email == seeded_env["email"]))).scalar_one()
    admin.role = "org_admin"
    await db.commit()

    m = await _make_machine(db, org_id=org_id)
    rule = AlertRule(name="Inv", template_code="investigation_completed", org_id=org_id,
                     scope_mode="org_only", created_by=admin.id)
    db.add(rule)
    await db.flush()

    engine = AlertEngine()
    events = await engine.trigger_alert(
        db,
        template_code="investigation_completed",
        org_id=org_id,
        machine_id=m.id,
        context={
            "hostname": m.hostname,
            "findings_count": 3,
            "severity": "high",
            "llm_model": "qwen",
            "investigation_id": str(uuid.uuid4()),
        },
    )
    assert len(events) == 1
    assert "Điều tra hoàn thành" in events[0].title
    assert str(admin.id) in events[0].recipient_user_ids
