# Alert Engine Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign alert subsystem thành 3 trục trực giao — **templates** (nội dung + opt-out controls), **scope** (org_only / org_tree / system), **recipients** (Org Admin của scope + Super Admin luôn nhận, Org Admin tự mute qua prefs) — chỉ hỗ trợ backend notification (in-app bell) + Telegram.

**Architecture:** Bảng `alert_templates` do Super Admin quản lý nội dung (title/body template + `opt_out_controls` + `allowed_vars` whitelist). Bảng `alert_rules` giữ tên cũ nhưng schema mới (template_code + scope_mode + recipient_mode + config). Bảng `user_notification_prefs` lưu opt-out per (user, template). Service mới `alert_engine.trigger_alert()` là pipeline duy nhất: render → resolve recipients → fan-out notification + Telegram. `monitor.py` + `notifications.py` chuyển từ logic inline sang gọi `trigger_alert`.

**Tech Stack:** Python 3.12 + FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL (JSONB), pytest (server); Next.js 16 App Router + TypeScript + Tailwind (portal).

**Spec:** `docs/superpowers/specs/2026-09-01-alert-engine-design.md`

## Global Constraints

Mọi task phải tuân thủ (lấy từ spec):

- **Đặt tên bảng:** giữ tên cũ `alert_rules` + `alert_events` (đổi schema bên trong, KHÔNG rename).
- **Approach:** clean replace — drop bảng cũ, KHÔNG migrate data. Data alert cũ mất.
- **Delivery:** chỉ in-app notification (`notifications` table, đã có) + Telegram (qua `user.telegram_chat_id` + `telegram_runtime.get_bot_config`). KHÔNG email, KHÔNG Zalo, KHÔNG webhook.
- **Recipients:** mặc định = Org Admin của scope (`role IN ('org_admin','admin_org')` — alias legacy) + Super Admin (`role IN ('super_admin','admin_global')`). Super Admin **luôn** nhận, không bị filter prefs. Org Admin bị filter qua `user_notification_prefs`.
- **Opt-out controls do template định nghĩa:** `opt_out_controls` chỉ nhận giá trị trong `{"template", "severity"}`. `muted` chỉ ý nghĩa nếu template có "template"; `min_severity` chỉ ý nghĩa nếu có "severity".
- **Template variables:** chỉ được dùng biến có trong `allowed_vars` của template. Server validate lúc PATCH. Render thiếu biến → substitute `[MISSING: varname]` + log warning (KHÔNG raise).
- **Severity rank:** `SEVERITY_RANK = {"info":0,"success":1,"warning":2,"error":3,"critical":4}`. Filter `min_severity`: chỉ nhận nếu `SEVERITY_RANK[event_severity] >= SEVERITY_RANK[min_severity]`.
- **Idempotency event:** `fingerprint = sha256(f"{rule.id}:{machine_id}:{template_code}:{YYYY-MM-DD}")`. UNIQUE(rule_id, machine_id, fingerprint).
- **Idempotency notification:** `idempotency_key = f"alert-event:{event.id}:user:{user_id}"`.
- **Validation permission:** `scope_mode='system'` chỉ Super Admin được tạo. `org_id` required khi scope != system. Org Admin chỉ được tạo rule cho org trong `visible_org_ids` của mình.
- **Role sets:** dùng `app.api.deps.ADMIN_ROLES` / `SUPER_ADMIN_ROLES` (không hardcode trong service). Alias legacy: `admin_org` tính là org_admin, `admin_global` tính là super_admin.
- **Alembic head hiện tại:** `s7t8u9v0w1x2` — migration mới `down_revision = "s7t8u9v0w1x2"`.
- **File di chuyển:** `portal/app/(portal)/me/telegram/` → `portal/app/(portal)/admin/telegram-bot/` — nội dung file giữ nguyên 100%, chỉ đổi path + cập nhật sidebar link.
- **Format lint:** server dùng `ruff`; portal dùng `npm run typecheck` + `npm run build`. Chạy trước mỗi commit.

---

### Task 1: Migration Alembic — schema mới + seed 7 templates

**Files:**
- Create: `server/alembic/versions/t8u9v0w1x2y3_alert_engine.py`
- Modify: `server/tests/test_migration_graph.py`
- Test: chạy `alembic upgrade head` trên DB test

**Interfaces:**
- Produces bảng: `alert_templates`, `user_notification_prefs`, `alert_rules` (mới), `alert_events` (mới).
- Produces 7 template rows: `machine_new`, `machine_lost`, `machine_offline`, `investigation_completed`, `investigation_failed`, `software_new`, `hardware_changed`.
- Task 2 models phụ thuộc: tên cột + type đúng theo migration này.

- [ ] **Step 1: Viết migration**

```python
# server/alembic/versions/t8u9v0w1x2y3_alert_engine.py
"""Alert engine redesign — templates + scope + recipients (3 trục).

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2

Clean replace: drop alert_rules + alert_events cũ, recreate schema mới.
Thêm alert_templates (Super Admin quản lý nội dung) + user_notification_prefs
(opt-out per user+template). Seed 7 templates ban đầu.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t8u9v0w1x2y3"
down_revision = "s7t8u9v0w1x2"
branch_labels = None
depends_on = None

SEED_TEMPLATES = [
    {
        "code": "machine_new",
        "name": "Máy mới enroll trong tổ chức",
        "description": "Kích hoạt khi 1 máy mới enroll vào tổ chức trong phạm vi rule.",
        "category": "machine",
        "default_severity": "info",
        "title_template": "[{org_name}] Máy mới: {hostname}",
        "body_template": "Hostname: {hostname}\nOS: {os}\nIP: {ip}\nEnrolled: {enrolled_at}",
        "opt_out_controls": ["template"],
        "allowed_vars": ["hostname", "ip", "os", "org_name", "enrolled_at", "machine_id"],
        "default_config": {},
    },
    {
        "code": "machine_lost",
        "name": "Mất liên lạc > N ngày",
        "description": "Kích hoạt khi máy offline liên tục quá threshold_days ngày.",
        "category": "machine",
        "default_severity": "warning",
        "title_template": "[{org_name}] Mất liên lạc > {threshold_days} ngày: {hostname}",
        "body_template": "Hostname: {hostname}\nIP: {ip}\nLast seen: {last_seen_at}",
        "opt_out_controls": ["template"],
        "allowed_vars": ["hostname", "ip", "org_name", "last_seen_at", "threshold_days", "machine_id"],
        "default_config": {"threshold_days": 7},
    },
    {
        "code": "machine_offline",
        "name": "Máy chuyển offline",
        "description": "Kích hoạt khi máy đang online chuyển sang offline (real-time).",
        "category": "machine",
        "default_severity": "warning",
        "title_template": "[{org_name}] Máy offline: {hostname}",
        "body_template": "Hostname: {hostname}\nIP: {ip}\nLast seen: {last_seen_at}",
        "opt_out_controls": ["severity"],
        "allowed_vars": ["hostname", "ip", "org_name", "last_seen_at", "machine_id"],
        "default_config": {},
    },
    {
        "code": "investigation_completed",
        "name": "Điều tra DFIR hoàn thành",
        "description": "Kích hoạt khi cuộc điều tra AI hoàn thành với báo cáo.",
        "category": "investigation",
        "default_severity": "info",
        "title_template": "Điều tra hoàn thành · {severity}",
        "body_template": "**Máy:** {hostname}\n**Phát hiện:** {findings_count}\n**Mức độ:** {severity}\n**Model:** {llm_model}",
        "opt_out_controls": ["severity"],
        "allowed_vars": ["hostname", "findings_count", "severity", "llm_model", "investigation_id", "machine_id"],
        "default_config": {},
    },
    {
        "code": "investigation_failed",
        "name": "Điều tra DFIR thất bại",
        "description": "Kích hoạt khi cuộc điều tra AI thất bại.",
        "category": "investigation",
        "default_severity": "error",
        "title_template": "Điều tra thất bại",
        "body_template": "**Máy:** {hostname}\n**Lỗi:** {error}",
        "opt_out_controls": ["severity"],
        "allowed_vars": ["hostname", "error", "investigation_id", "machine_id"],
        "default_config": {},
    },
    {
        "code": "software_new",
        "name": "Phần mềm lạ xuất hiện",
        "description": "Kích hoạt khi phát hiện phần mềm mới lạ trên máy. (Trigger Phase 3 — chưa có job scan.)",
        "category": "security",
        "default_severity": "warning",
        "title_template": "[{org_name}] Phần mềm lạ: {software_name}",
        "body_template": "**Máy:** {hostname}\n**Phần mềm:** {software_name} {version}\n**Nhà phát hành:** {publisher}",
        "opt_out_controls": ["template", "severity"],
        "allowed_vars": ["hostname", "software_name", "version", "publisher", "machine_id"],
        "default_config": {},
    },
    {
        "code": "hardware_changed",
        "name": "Phần cứng thay đổi",
        "description": "Kích hoạt khi fingerprint phần cứng máy thay đổi. (Trigger Phase 3 — chưa có job scan.)",
        "category": "security",
        "default_severity": "warning",
        "title_template": "[{org_name}] Phần cứng thay đổi: {component}",
        "body_template": "**Máy:** {hostname}\n**Thành phần:** {component}\n**Cũ:** {old_value}\n**Mới:** {new_value}",
        "opt_out_controls": ["template", "severity"],
        "allowed_vars": ["hostname", "component", "old_value", "new_value", "machine_id"],
        "default_config": {},
    },
]


def upgrade() -> None:
    # 1. alert_templates
    op.create_table(
        "alert_templates",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("default_severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("title_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column("opt_out_controls", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("allowed_vars", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_config", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "default_severity IN ('info','success','warning','error','critical')",
            name="ck_alert_templates_severity",
        ),
    )

    # 2. user_notification_prefs
    op.create_table(
        "user_notification_prefs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_code", sa.String(64), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_severity", sa.String(16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "template_code", name="uq_user_notification_prefs_user_template"),
        sa.CheckConstraint(
            "min_severity IS NULL OR min_severity IN ('info','success','warning','error','critical')",
            name="ck_user_notification_prefs_severity",
        ),
    )
    op.create_index("ix_user_notification_prefs_user", "user_notification_prefs", ["user_id"])

    # 3. Drop cũ + recreate alert_rules
    op.drop_table("alert_events")
    op.drop_table("alert_rules")

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("template_code", sa.String(64), nullable=False),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("scope_mode", sa.String(32), nullable=False, server_default="org_only"),
        sa.Column("recipient_mode", sa.String(32), nullable=False, server_default="org_admins_and_super"),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "scope_mode IN ('org_only','org_tree','system')",
            name="ck_alert_rules_scope_mode",
        ),
        sa.CheckConstraint(
            "recipient_mode IN ('org_admins_and_super')",
            name="ck_alert_rules_recipient_mode",
        ),
    )
    op.create_index("ix_alert_rules_org", "alert_rules", ["org_id"])
    op.create_index("ix_alert_rules_template", "alert_rules", ["template_code"])

    # 4. Drop cũ + recreate alert_events
    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_code", sa.String(64), nullable=False),
        sa.Column("machine_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("context", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("recipient_user_ids", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("rule_id", "machine_id", "fingerprint", name="uq_alert_event"),
    )
    op.create_index("ix_alert_events_created", "alert_events", ["created_at"])
    op.create_index("ix_alert_events_org", "alert_events", ["org_id"])

    # 5. Seed 7 templates
    conn = op.get_bind()
    meta = sa.MetaData()
    meta.reflect(bind=conn, only=["alert_templates"])
    tbl = sa.table(
        "alert_templates",
        sa.column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("default_severity", sa.String),
        sa.column("title_template", sa.Text),
        sa.column("body_template", sa.Text),
        sa.column("opt_out_controls", sa.dialects.postgresql.JSONB),
        sa.column("allowed_vars", sa.dialects.postgresql.JSONB),
        sa.column("default_config", sa.dialects.postgresql.JSONB),
        sa.column("enabled", sa.Boolean),
    )
    import uuid as _uuid
    conn.execute(tbl.insert(), [
        {
            "id": _uuid.uuid5(_uuid.NAMESPACE_URL, f"alert-template:{t['code']}"),
            **{k: v for k, v in t.items()},
        }
        for t in SEED_TEMPLATES
    ])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    op.drop_index("ix_user_notification_prefs_user", table_name="user_notification_prefs")
    op.drop_table("user_notification_prefs")
    op.drop_table("alert_templates")
```

- [ ] **Step 2: Thêm test migration graph**

```python
# server/tests/test_migration_graph.py — append
def test_alert_engine_migration_runs_after_telegram_bot_config() -> None:
    """Migration alert engine phải chạy sau telegram_bot_config (head hiện tại)."""
    migrations_dir = Path(__file__).parents[1] / "alembic"
    script = ScriptDirectory(str(migrations_dir))

    rev = script.get_revision("t8u9v0w1x2y3")
    assert rev is not None
    assert "s7t8u9v0w1x2" in rev._normalized_down_revisions
```

- [ ] **Step 3: Chạy migration trên DB test**

Run:
```bash
cd server && .venv/bin/alembic upgrade head
.venv/bin/pytest tests/test_migration_graph.py -q
```
Expected: upgrade thành công, test pass.

- [ ] **Step 4: Verify seed 7 templates**

Run:
```bash
cd server && .venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import text
from app.db.session import engine
async def main():
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT code FROM alert_templates ORDER BY code"))).fetchall()
        print([r[0] for r in rows])
asyncio.run(main())
PY
```
Expected: in ra 7 codes theo SEED_TEMPLATES.

- [ ] **Step 5: Commit**

```bash
git add server/alembic/versions/t8u9v0w1x2y3_alert_engine.py server/tests/test_migration_graph.py
git commit -m "feat(alert): migration alert engine — templates + prefs + rules/events schema mới, seed 7 templates"
```

---

### Task 2: SQLAlchemy models — AlertTemplate, UserNotificationPref, AlertRule (mới), AlertEvent (mới)

**Files:**
- Modify: `server/app/db/models.py` (thay thế class AlertRule cũ + AlertEvent cũ; thêm AlertTemplate, UserNotificationPref)

**Interfaces:**
- Consumes: migration Task 1 (tên bảng/cột).
- Produces: `AlertTemplate`, `UserNotificationPref`, `AlertRule`, `AlertEvent` ORM classes — Task 3 schemas và Task 7 alert_engine dùng.

- [ ] **Step 1: Viết test model roundtrip**

```python
# server/tests/test_alert_engine.py — TẠO file mới
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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail (model chưa có)**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_alert_template_model_roundtrip -q`
Expected: FAIL với `ImportError: cannot import name 'AlertTemplate'`.

- [ ] **Step 3: Cài đặt models**

Trong `server/app/db/models.py`, thay 2 class `AlertRule` + `AlertEvent` cũ bằng:

```python
class AlertRule(Base):
    """Subscription alert — bind template + scope + recipient_mode (redesign)."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )  # NULL khi scope_mode='system'
    scope_mode: Mapped[str] = mapped_column(String(32), default="org_only")
    # org_only | org_tree | system
    recipient_mode: Mapped[str] = mapped_column(String(32), default="org_admins_and_super")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # VD {"threshold_days": 3}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AlertEvent(Base):
    """Bản ghi 1 lần alert được kích hoạt (snapshot title/body đã render)."""

    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("rule_id", "machine_id", "fingerprint", name="uq_alert_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recipient_user_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class AlertTemplate(Base):
    """Template nội dung alert — Super Admin quản lý title/body + opt_out_controls."""

    __tablename__ = "alert_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # machine | investigation | security | system
    default_severity: Mapped[str] = mapped_column(String(16), default="info")
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    opt_out_controls: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_vars: Mapped[list] = mapped_column(JSONB, default=list)
    default_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))


class UserNotificationPref(Base):
    """Opt-out per (user, template) — muted / min_severity."""

    __tablename__ = "user_notification_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "template_code", name="uq_user_notification_prefs_user_template"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    min_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_alert_template_model_roundtrip -q`
Expected: PASS.

- [ ] **Step 5: Verify toàn bộ server import được**

Run: `cd server && .venv/bin/python -c "from app.db.models import AlertRule, AlertEvent, AlertTemplate, UserNotificationPref; print('ok')"`
Expected: in `ok`.

- [ ] **Step 6: Commit**

```bash
git add server/app/db/models.py server/tests/test_alert_engine.py
git commit -m "feat(alert): models AlertTemplate + UserNotificationPref + AlertRule/AlertEvent schema mới"
```

---

### Task 3: Pydantic schemas — AlertTemplate, AlertRule, AlertEvent, UserNotificationPref

**Files:**
- Modify: `server/app/schemas/__init__.py`

**Interfaces:**
- Consumes: models Task 2.
- Produces: `AlertTemplateOut`, `AlertTemplateUpdateIn`, `AlertTemplatePreviewOut`, `AlertRuleCreate`, `AlertRuleUpdate`, `AlertRuleOut`, `AlertRuleTestOut`, `AlertEventOut`, `UserNotificationPrefOut`, `UserNotificationPrefUpdateIn` — Task 4-8 routes/service dùng.

- [ ] **Step 1: Thay thế schema Alert cũ**

Trong `server/app/schemas/__init__.py`, thay block `AlertRuleCreate/Update/Out/AlertEventOut` cũ (dòng ~488-530) bằng:

```python
# ── Alert engine redesign (Phase 2 v2) ─────────────────────────


class AlertTemplateOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str
    default_severity: str
    title_template: str
    body_template: str | None
    opt_out_controls: list[str]
    allowed_vars: list[str]
    default_config: dict
    enabled: bool
    updated_at: datetime


class AlertTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    default_severity: str | None = Field(default=None, pattern="^(info|success|warning|error|critical)$")
    title_template: str | None = Field(default=None, min_length=1)
    body_template: str | None = None
    opt_out_controls: list[str] | None = None
    allowed_vars: list[str] | None = None
    default_config: dict | None = None
    enabled: bool | None = None


class AlertTemplatePreviewIn(BaseModel):
    """Context mẫu để render thử template (không lưu)."""

    context: dict = Field(default_factory=dict)


class AlertTemplatePreviewOut(BaseModel):
    title: str
    body: str | None
    warnings: list[str] = Field(default_factory=list)


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    template_code: str = Field(..., min_length=1, max_length=64)
    org_id: uuid.UUID | None = None
    scope_mode: str = Field(default="org_only", pattern="^(org_only|org_tree|system)$")
    recipient_mode: str = Field(default="org_admins_and_super", pattern="^(org_admins_and_super)$")
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_code: str | None = None
    org_id: uuid.UUID | None = None
    scope_mode: str | None = Field(default=None, pattern="^(org_only|org_tree|system)$")
    recipient_mode: str | None = Field(default=None, pattern="^(org_admins_and_super)$")
    config: dict | None = None
    enabled: bool | None = None


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    template_code: str
    template_name: str | None = None
    org_id: uuid.UUID | None
    scope_mode: str
    recipient_mode: str
    config: dict
    enabled: bool
    created_at: datetime


class AlertRuleTestOut(BaseModel):
    """Dry-run: render + resolve recipients, KHÔNG gửi."""

    template_code: str
    title: str
    body: str | None
    recipients: list[dict] = Field(default_factory=list)  # [{user_id, email, full_name, telegram_linked}]
    total_recipients: int
    warnings: list[str] = Field(default_factory=list)


class AlertEventOut(BaseModel):
    id: int
    rule_id: uuid.UUID
    template_code: str
    machine_id: uuid.UUID | None
    org_id: uuid.UUID | None
    severity: str
    title: str
    body: str | None
    recipient_user_ids: list[str]
    created_at: datetime


class UserNotificationPrefOut(BaseModel):
    """Pref của user hiện tại + metadata template (để UI render control)."""

    template_code: str
    template_name: str
    category: str
    default_severity: str
    opt_out_controls: list[str]
    muted: bool
    min_severity: str | None


class UserNotificationPrefItem(BaseModel):
    template_code: str
    muted: bool = False
    min_severity: str | None = None


class UserNotificationPrefUpdateIn(BaseModel):
    prefs: list[UserNotificationPrefItem] = Field(default_factory=list)
```

- [ ] **Step 2: Kiểm tra schema import**

Run: `cd server && .venv/bin/python -c "from app.schemas import AlertRuleCreate, AlertRuleOut, AlertTemplateOut, AlertEventOut, UserNotificationPrefOut; print('ok')"`
Expected: in `ok`.

- [ ] **Step 3: Chạy toàn bộ test cũ (alert rules cũ sẽ fail — ghi nhận, chưa fix)**

Run: `cd server && .venv/bin/pytest tests/test_phase2.py -q 2>&1 | tail -5`
Expected: test_alert_rule_crud + test_alert_job_fires fail vì schema đổi — Task 6 sẽ refactor routes, Task 10 sẽ fix test.

- [ ] **Step 4: Commit**

```bash
git add server/app/schemas/__init__.py
git commit -m "feat(alert): schemas AlertTemplate/AlertRule/AlertEvent/UserNotificationPref redesign"
```

---

### Task 4: Service org_scope — resolve scope orgs (org_only / org_tree / system)

**Files:**
- Create: `server/app/services/org_scope.py`
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: models Organization.
- Produces: `async def scope_orgs(db, *, org_id, scope_mode) -> list[uuid.UUID]`, `async def all_org_ids(db) -> list[uuid.UUID]` — Task 7 alert_engine dùng.
- `visible_org_ids` từ `app.api.deps` ĐÃ có (trả set[str] org + descendants) — dùng lại cho validation route.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
from app.services.org_scope import all_org_ids, scope_orgs


async def test_scope_orgs_org_only_excludes_descendants(db, session_factory, seeded_env):
    from app.db.models import Organization

    root = Organization(name="Root Scope", type="don_vi")
    db.add(root)
    await db.flush()
    child = Organization(name="Child Scope", type="don_vi", parent_id=root.id)
    db.add(child)
    await db.commit()

    ids = await scope_orgs(db, org_id=root.id, scope_mode="org_only")
    assert ids == [root.id]
    assert child.id not in ids


async def test_scope_orgs_org_tree_includes_descendants(db, session_factory, seeded_env):
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

    ids = await scope_orgs(db, org_id=root.id, scope_mode="org_tree")
    assert set(ids) == {root.id, child.id, grand.id}


async def test_scope_orgs_system_returns_all(db, session_factory, seeded_env):
    from app.db.models import Organization

    org_a = Organization(name="System A", type="don_vi")
    org_b = Organization(name="System B", type="don_vi")
    db.add_all([org_a, org_b])
    await db.commit()

    ids = await all_org_ids(db)
    assert org_a.id in ids and org_b.id in ids
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_scope_orgs_org_only_excludes_descendants -q`
Expected: FAIL `ModuleNotFoundError: No module named 'app.services.org_scope'`.

- [ ] **Step 3: Cài đặt service**

```python
# server/app/services/org_scope.py
"""Resolve phạm vi org cho alert rule (scope_mode: org_only | org_tree | system)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organization


async def all_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Toàn bộ org id (cho scope_mode='system')."""
    rows = (await db.execute(select(Organization.id))).scalars().all()
    return list(rows)


async def scope_orgs(
    db: AsyncSession, *, org_id: uuid.UUID | None, scope_mode: str
) -> list[uuid.UUID]:
    """Trả list org_id mà subscription bao phủ.

    - system:  tất cả org
    - org_only: [org_id]
    - org_tree: [org_id] + mọi descendants
    """
    if scope_mode == "system":
        return await all_org_ids(db)
    if org_id is None:
        return []
    if scope_mode == "org_only":
        return [org_id]

    # org_tree — walk cây
    rows = (await db.execute(select(Organization.id, Organization.parent_id))).all()
    by_parent: dict[str, list[uuid.UUID]] = {}
    for oid, parent_id in rows:
        by_parent.setdefault(str(parent_id) if parent_id else "", []).append(oid)

    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    def walk(oid: uuid.UUID) -> None:
        if oid in seen:
            return
        seen.add(oid)
        out.append(oid)
        for child in by_parent.get(str(oid), []):
            walk(child)

    walk(org_id)
    return out
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "scope_orgs or scope_orgs_system" -q`
Expected: PASS cả 3 test.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/org_scope.py server/tests/test_alert_engine.py
git commit -m "feat(alert): org_scope service — resolve scope_mode org_only/org_tree/system"
```

---

### Task 5: Service alert_templates — render + validation + CRUD helpers

**Files:**
- Create: `server/app/services/alert_templates.py`
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: models AlertTemplate, schemas AlertTemplateUpdateIn.
- Produces: `async def list_templates(db, *, enabled_only=False) -> list[AlertTemplate]`, `async def get_template(db, code) -> AlertTemplate | None`, `async def update_template(db, code, body, admin) -> AlertTemplate`, `def render_template(text, allowed_vars, context) -> str`, `def validate_template_vars(title, body, allowed_vars) -> list[str]` — Task 7 engine + Task 8 routes dùng.

- [ ] **Step 1: Viết test render fail**

```python
# server/tests/test_alert_engine.py — append
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
        ["org_name", "hostname"],
    )
    assert "unknown_var" in warnings
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "render or validate_template" -q`
Expected: FAIL `ModuleNotFoundError: No module named 'app.services.alert_templates'`.

- [ ] **Step 3: Cài đặt service**

```python
# server/app/services/alert_templates.py
"""CRUD + render cho alert templates (Super Admin quản lý)."""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertTemplate, User

logger = logging.getLogger("alert_templates")

_VAR_RE = re.compile(r"\{(\w+)\}")

ALLOWED_OPT_OUT_CONTROLS = {"template", "severity"}


def render_template(text: str, allowed_vars: list[str], context: dict) -> str:
    """Render template string. Biến thiếu → substitute `[MISSING: varname]`.

    Không raise — gọi từ alert_engine (delivery không được chết vì template lỗi).
    """
    if not text:
        return ""
    allowed = set(allowed_vars or [])

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in allowed:
            return f"[MISSING: {name}]"
        val = context.get(name)
        if val is None:
            return f"[MISSING: {name}]"
        return str(val)

    return _VAR_RE.sub(_sub, text)


def validate_template_vars(title: str, body: str | None, allowed_vars: list[str]) -> list[str]:
    """Trả list biến xuất hiện trong template nhưng KHÔNG có trong allowed_vars."""
    allowed = set(allowed_vars or [])
    found: set[str] = set()
    found.update(_VAR_RE.findall(title))
    if body:
        found.update(_VAR_RE.findall(body))
    return sorted(found - allowed)


async def list_templates(
    db: AsyncSession, *, enabled_only: bool = False
) -> list[AlertTemplate]:
    stmt = select(AlertTemplate).order_by(AlertTemplate.category, AlertTemplate.code)
    if enabled_only:
        stmt = stmt.where(AlertTemplate.enabled.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_template(db: AsyncSession, code: str) -> AlertTemplate | None:
    return (await db.execute(
        select(AlertTemplate).where(AlertTemplate.code == code)
    )).scalar_one_or_none()


async def update_template(
    db: AsyncSession, code: str, body, admin: User
) -> AlertTemplate | None:
    """Cập nhật template theo `body` (Pydantic AlertTemplateUpdateIn).

    Validate: opt_out_controls ⊆ {"template","severity"}; biến trong title/body
    phải nằm trong allowed_vars (chỉ chặn nếu allowed_vars được cung cấp).
    """
    row = (await db.execute(
        select(AlertTemplate).where(AlertTemplate.code == code)
    )).scalar_one_or_none()
    if row is None:
        return None

    # Validate opt_out_controls
    if body.opt_out_controls is not None:
        bad = set(body.opt_out_controls) - ALLOWED_OPT_OUT_CONTROLS
        if bad:
            from fastapi import HTTPException, status
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"opt_out_controls không hợp lệ: {sorted(bad)} (chỉ chấp nhận template/severity)",
            )

    # Validate vars nếu cả title/body lẫn allowed_vars cùng được cung cấp
    new_allowed = body.allowed_vars if body.allowed_vars is not None else (row.allowed_vars or [])
    new_title = body.title_template if body.title_template is not None else row.title_template
    new_body = body.body_template if body.body_template is not None else row.body_template
    warnings = validate_template_vars(new_title, new_body, new_allowed)
    if warnings:
        from fastapi import HTTPException, status
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template dùng biến không khai báo trong allowed_vars: {warnings}",
        )

    for field in ("name", "description", "category", "default_severity",
                  "title_template", "body_template", "opt_out_controls",
                  "allowed_vars", "default_config", "enabled"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)

    row.updated_by = admin.id
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    logger.info("Super Admin %s updated template %s", admin.email, code)
    return row
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "render or validate_template" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/alert_templates.py server/tests/test_alert_engine.py
git commit -m "feat(alert): alert_templates service — render whitelist vars + validate + CRUD"
```

---

### Task 6: Service user_notification_prefs — get/upsert prefs + validate theo template

**Files:**
- Create: `server/app/services/user_notification_prefs.py`
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: models UserNotificationPref, AlertTemplate; schemas UserNotificationPrefUpdateIn.
- Produces: `async def get_prefs_with_template(db, user_id) -> list[dict]` (join template meta), `async def get_pref(db, user_id, template_code) -> UserNotificationPref | None`, `async def upsert_prefs(db, user, items) -> list[dict]` — Task 7 engine + Task 9 routes dùng.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
from app.services.user_notification_prefs import (
    get_pref,
    get_prefs_with_template,
    upsert_prefs,
)
from fastapi import HTTPException


async def test_upsert_prefs_respects_opt_out_controls(db, session_factory, seeded_env):
    from app.db.models import AlertTemplate, User

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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "prefs" -q`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Cài đặt service**

```python
# server/app/services/user_notification_prefs.py
"""Opt-out per (user, template) — muted / min_severity."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertTemplate, User, UserNotificationPref


async def get_pref(
    db: AsyncSession, user_id: uuid.UUID, template_code: str
) -> UserNotificationPref | None:
    return (await db.execute(
        select(UserNotificationPref).where(
            UserNotificationPref.user_id == user_id,
            UserNotificationPref.template_code == template_code,
        )
    )).scalar_one_or_none()


async def get_prefs_with_template(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Prefs của user + metadata template (để UI render control theo opt_out_controls)."""
    templates = (await db.execute(
        select(AlertTemplate).where(AlertTemplate.enabled.is_(True))
        .order_by(AlertTemplate.category, AlertTemplate.code)
    )).scalars().all()
    prefs = (await db.execute(
        select(UserNotificationPref).where(UserNotificationPref.user_id == user_id)
    )).scalars().all()
    by_code = {p.template_code: p for p in prefs}

    out = []
    for t in templates:
        p = by_code.get(t.code)
        out.append({
            "template_code": t.code,
            "template_name": t.name,
            "category": t.category,
            "default_severity": t.default_severity,
            "opt_out_controls": t.opt_out_controls or [],
            "muted": bool(p.muted) if p else False,
            "min_severity": p.min_severity if p else None,
        })
    return out


async def upsert_prefs(
    db: AsyncSession, user: User, items: list[dict]
) -> list[dict]:
    """Upsert prefs. Validate từng item theo template.opt_out_controls.

    - muted=true chỉ được nếu template có "template" trong opt_out_controls
    - min_severity chỉ được nếu template có "severity" trong opt_out_controls
    """
    for item in items:
        code = item.get("template_code")
        template = (await db.execute(
            select(AlertTemplate).where(AlertTemplate.code == code)
        )).scalar_one_or_none()
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Template không tồn tại: {code}")

        controls = set(template.opt_out_controls or [])
        if item.get("muted") and "template" not in controls:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Template '{code}' không cho phép mute (opt_out_controls={sorted(controls)})",
            )
        if item.get("min_severity") and "severity" not in controls:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Template '{code}' không cho phép chọn min_severity (opt_out_controls={sorted(controls)})",
            )

        row = await get_pref(db, user.id, code)
        if row is None:
            row = UserNotificationPref(
                user_id=user.id,
                template_code=code,
                muted=bool(item.get("muted", False)),
                min_severity=item.get("min_severity"),
            )
            db.add(row)
        else:
            row.muted = bool(item.get("muted", row.muted))
            row.min_severity = item.get("min_severity", row.min_severity)
        row.updated_at = datetime.now(UTC)
    await db.commit()
    return await get_prefs_with_template(db, user.id)
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "prefs" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/user_notification_prefs.py server/tests/test_alert_engine.py
git commit -m "feat(alert): user_notification_prefs service — upsert + validate theo opt_out_controls"
```

---

### Task 7: Service alert_engine — trigger_alert pipeline (core)

**Files:**
- Create: `server/app/services/alert_engine.py`
- Test: `server/tests/test_alert_engine.py` (append — đây là test lõi)

**Interfaces:**
- Consumes: `scope_orgs` (Task 4), `get_template` + `render_template` (Task 5), `get_pref` (Task 6), `create_notification` từ `app.services.notifications`, models.
- Produces: `class AlertEngine` với `async def trigger_alert(db, *, template_code, org_id, machine_id=None, context=None) -> list[AlertEvent]`; singleton helper `async def trigger_alert(...)` — Task 10 monitor + Task 11 dfir dùng.

- [ ] **Step 1: Viết test fail (các case lõi)**

```python
# server/tests/test_alert_engine.py — append
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
    db, session_factory, seeded_env
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
    assert admin.id in events[0].recipient_user_ids
    # Notification đã tạo cho admin
    from app.db.models import Notification
    notifs = (await db.execute(
        select(Notification).where(Notification.recipient_id == admin.id)
    )).scalars().all()
    assert any("Máy mới" in n.title for n in notifs)


async def test_trigger_alert_dedup_same_day(db, session_factory, seeded_env):
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


async def test_org_admin_opt_out_respected(db, session_factory, seeded_env):
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
    assert admin.id not in events[0].recipient_user_ids


async def test_super_admin_always_receives_even_if_pref_muted(
    db, session_factory, seeded_env
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
    assert admin.id in events[0].recipient_user_ids


async def test_min_severity_filters_lower_severity(db, session_factory, seeded_env):
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
    assert admin.id not in events[0].recipient_user_ids


async def test_disabled_template_and_disabled_rule_no_trigger(
    db, session_factory, seeded_env
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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "trigger_alert" -q`
Expected: FAIL `ModuleNotFoundError: No module named 'app.services.alert_engine'`.

- [ ] **Step 3: Cài đặt alert_engine**

```python
# server/app/services/alert_engine.py
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
from app.services.org_scope import scope_orgs
from app.services.user_notification_prefs import get_pref
from app.services.notifications import create_notification

logger = logging.getLogger("alert_engine")

# Role "org_admin" gồm alias legacy admin_org
ORG_ADMIN_ROLES = ("org_admin", "admin_org")

SEVERITY_RANK = {"info": 0, "success": 1, "warning": 2, "error": 3, "critical": 4}

# Cache machine snapshot field cho context — tránh N+1 query lặp
_MACHINE_CTX_FIELDS = {
    "hostname": "hostname",
    "ip": "public_ip",
    "os": "os_family",
    "enrolled_at": "enrolled_at",
    "last_seen_at": "last_seen_at",
    "machine_id": "id",
}


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
                ctx.setdefault("last_seen_at", machine.last_seen_at)
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

            fingerprint = self._fingerprint(rule.id, machine_id, template_code, ctx)
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
        self, rule_id: uuid.UUID, machine_id: uuid.UUID | None,
        template_code: str, ctx: dict,
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
                if "severity" in controls and pref.min_severity:
                    if SEVERITY_RANK.get(pref.min_severity, 0) > severity_rank:
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
```

> **Lưu ý:** `create_notification` hiện nhận `recipient_ids` + tạo 1 row / recipient. Idempotency key `f"alert-event:{event.id}:all"` — nếu engine chạy lại cùng event (không xảy ra do dedup fingerprint), notification không duplicate.

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "trigger_alert" -q`
Expected: PASS toàn bộ 6 test.

- [ ] **Step 5: Chạy ruff**

Run: `cd server && .venv/bin/ruff check app/services/alert_engine.py app/services/org_scope.py app/services/alert_templates.py app/services/user_notification_prefs.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add server/app/services/alert_engine.py server/tests/test_alert_engine.py
git commit -m "feat(alert): alert_engine — trigger_alert pipeline (template → scope → recipients → notify)"
```

---

### Task 8: Routes alert_templates_admin — Super Admin CRUD + preview

**Files:**
- Create: `server/app/api/routes/alert_templates_admin.py`
- Modify: `server/app/main.py` (include router)
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: `list_templates`, `get_template`, `update_template` (Task 5).
- Produces: `GET /api/admin/alert-templates`, `GET /{code}`, `PATCH /{code}`, `POST /{code}/preview` — Task 13 portal dùng.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_alert_templates_admin_crud(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/admin/alert-templates", headers=h)
    assert r.status_code == 200
    codes = [t["code"] for t in r.json()["items"]]
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


async def test_alert_templates_preview(client, seeded_env):
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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "alert_templates_admin or alert_templates_preview" -q`
Expected: FAIL 404 (route chưa có).

- [ ] **Step 3: Cài đặt routes**

```python
# server/app/api/routes/alert_templates_admin.py
"""Alert templates CRUD — Super Admin only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.db.models import User
from app.schemas import (
    AlertTemplateOut,
    AlertTemplatePreviewIn,
    AlertTemplatePreviewOut,
    AlertTemplateUpdateIn,
)
from app.services.alert_templates import (
    get_template,
    list_templates,
    render_template,
    update_template,
    validate_template_vars,
)

router = APIRouter(prefix="/api/admin/alert-templates", tags=["admin-alert-templates"])


async def _to_out(t) -> AlertTemplateOut:
    return AlertTemplateOut(
        id=t.id, code=t.code, name=t.name, description=t.description,
        category=t.category, default_severity=t.default_severity,
        title_template=t.title_template, body_template=t.body_template,
        opt_out_controls=t.opt_out_controls or [],
        allowed_vars=t.allowed_vars or [],
        default_config=t.default_config or {},
        enabled=t.enabled, updated_at=t.updated_at,
    )


@router.get("", response_model=list[AlertTemplateOut])
async def list_templates_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    rows = await list_templates(db)
    return [_to_out(t) for t in rows]


@router.get("/{code}", response_model=AlertTemplateOut)
async def get_template_endpoint(
    code: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    row = await get_template(db, code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    return _to_out(row)


@router.patch("/{code}", response_model=AlertTemplateOut)
async def update_template_endpoint(
    code: str,
    body: AlertTemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    row = await update_template(db, code, body, admin)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    return _to_out(row)


@router.post("/{code}/preview", response_model=AlertTemplatePreviewOut)
async def preview_template(
    code: str,
    body: AlertTemplatePreviewIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    row = await get_template(db, code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    ctx = body.context or {}
    title = render_template(row.title_template, row.allowed_vars or [], ctx)
    body_text = render_template(row.body_template or "", row.allowed_vars or [], ctx) or None
    warnings = validate_template_vars(row.title_template, row.body_template, row.allowed_vars or [])
    return AlertTemplatePreviewOut(title=title, body=body_text, warnings=warnings)
```

Trong `server/app/main.py`, thêm import + include:

```python
# main.py — thêm vào import block
    alert_templates_admin,
# main.py — thêm vào include block (sau telegram_bot_admin)
app.include_router(alert_templates_admin.router)
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "alert_templates_admin or alert_templates_preview" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/api/routes/alert_templates_admin.py server/app/main.py server/tests/test_alert_engine.py
git commit -m "feat(alert): routes /api/admin/alert-templates — Super Admin CRUD + preview"
```

---

### Task 9: Routes alert_rules — refactor CRUD theo schema mới + dry-run test

**Files:**
- Rewrite: `server/app/api/routes/alert_rules.py` (bỏ events route — Task 9b tách riêng)
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: schemas AlertRuleCreate/Update/Out (Task 3), `visible_org_ids` (deps), `get_template` (Task 5), `AlertEngine._resolve_recipients` (Task 7).
- Produces: `GET /api/alert-rules`, `POST /api/alert-rules`, `PATCH /api/alert-rules/{id}`, `DELETE /api/alert-rules/{id}`, `POST /api/alert-rules/{id}/test` — Task 12 portal dùng.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
async def test_alert_rules_crud_new_schema(client, seeded_env):
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


async def test_alert_rules_dry_run_test(client, seeded_env):
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
    assert "Máy mới" in data["title"] or "PC-DRY" in data["title"]
    assert isinstance(data["total_recipients"], int)
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "alert_rules_crud_new_schema or alert_rules_dry_run" -q`
Expected: FAIL (routes cũ chưa handle template_code/scope_mode).

- [ ] **Step 3: Rewrite route**

```python
# server/app/api/routes/alert_rules.py — REWRITE toàn bộ
"""Alert rules (subscriptions) — schema mới: template_code + scope_mode + recipient_mode.

- List/create/update/delete theo quyền (visible_org_ids).
- POST /{id}/test: dry-run render + resolve recipients — KHÔNG gửi notification thật.
- History events nằm ở route riêng (alert_events.py).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, is_super_admin, require_admin, visible_org_ids
from app.db.models import AlertEvent, AlertRule, User
from app.schemas import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleTestOut,
    AlertRuleUpdate,
    Page,
)
from app.services.alert_templates import get_template, render_template, validate_template_vars
from app.services.org_scope import scope_orgs

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


async def _rule_to_out(db: AsyncSession, r: AlertRule) -> AlertRuleOut:
    tpl = await get_template(db, r.template_code)
    return AlertRuleOut(
        id=r.id,
        name=r.name,
        template_code=r.template_code,
        template_name=tpl.name if tpl else None,
        org_id=r.org_id,
        scope_mode=r.scope_mode,
        recipient_mode=r.recipient_mode,
        config=r.config or {},
        enabled=r.enabled,
        created_at=r.created_at,
    )


async def _can_access(db: AsyncSession, admin: User, rule: AlertRule) -> bool:
    """Admin được phép xem/sửa rule nếu rule org nằm trong cây con của họ."""
    if is_super_admin(admin):
        return True
    visible = await visible_org_ids(db, admin)
    return rule.org_id is None or str(rule.org_id) in visible


@router.get("", response_model=Page[AlertRuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin()),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    visible = await visible_org_ids(db, admin)
    all_rows = (
        (await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))).scalars().all()
    )
    filtered = [r for r in all_rows if _can_access(db, admin, r) or await _can_access(db, admin, r)]
    # simplify: filter bằng visible set
    filtered = [r for r in all_rows if r.org_id is None or str(r.org_id) in visible]
    total = len(filtered)
    items = [await _rule_to_out(db, r) for r in filtered[offset : offset + limit]]
    return Page[AlertRuleOut](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=AlertRuleOut)
async def create_rule(
    body: AlertRuleCreate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    # Validate template tồn tại
    tpl = await get_template(db, body.template_code)
    if tpl is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")

    # scope_mode=system chỉ Super Admin
    if body.scope_mode == "system" and not is_super_admin(admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin tạo rule phạm vi hệ thống")
    if body.scope_mode != "system" and body.org_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scope_mode != system cần org_id")

    visible = await visible_org_ids(db, admin)
    if body.org_id and str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo rule cho tổ chức này")

    # Merge config với default_config template
    config = {**(tpl.default_config or {}), **(body.config or {})}

    rule = AlertRule(
        name=body.name,
        template_code=body.template_code,
        org_id=body.org_id,
        scope_mode=body.scope_mode,
        recipient_mode=body.recipient_mode,
        config=config,
        enabled=body.enabled,
        created_by=admin.id,
    )
    db.add(rule)
    await db.commit()
    return await _rule_to_out(db, rule)


@router.patch("/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền sửa rule này")

    if body.name is not None:
        rule.name = body.name
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.template_code is not None:
        tpl = await get_template(db, body.template_code)
        if tpl is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")
        rule.template_code = body.template_code
        rule.config = {**(tpl.default_config or {}), **(rule.config or {})}
    if body.org_id is not None:
        visible = await visible_org_ids(db, admin)
        if str(body.org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền gán org này")
        rule.org_id = body.org_id
    if body.scope_mode is not None:
        if body.scope_mode == "system" and not is_super_admin(admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ Super Admin set scope system")
        rule.scope_mode = body.scope_mode
    if body.recipient_mode is not None:
        rule.recipient_mode = body.recipient_mode
    if body.config is not None:
        rule.config = body.config
    await db.commit()
    return await _rule_to_out(db, rule)


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xóa rule này")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


@router.post("/{rule_id}/test", response_model=AlertRuleTestOut)
async def test_rule(
    rule_id: uuid.UUID,
    body: dict | None = None,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run: render title/body + resolve recipients. KHÔNG gửi."""
    body = body or {}
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rule không tồn tại")
    if not await _can_access(db, admin, rule):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền test rule này")

    tpl = await get_template(db, rule.template_code)
    if tpl is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Template không tồn tại")

    ctx = dict(body.get("context") or {})
    ctx.setdefault("hostname", "[test]")
    ctx.setdefault("org_name", "[org test]")
    ctx.setdefault("threshold_days", (rule.config or {}).get("threshold_days", 7))

    title = render_template(tpl.title_template, tpl.allowed_vars or [], ctx)
    body_text = render_template(tpl.body_template or "", tpl.allowed_vars or [], ctx) or None
    warnings = validate_template_vars(tpl.title_template, tpl.body_template, tpl.allowed_vars or [])

    scope_ids = await scope_orgs(db, org_id=rule.org_id, scope_mode=rule.scope_mode)
    from app.services.alert_engine import AlertEngine
    recipients = await AlertEngine()._resolve_recipients(db, rule, tpl, scope_ids)

    return AlertRuleTestOut(
        template_code=rule.template_code,
        title=title,
        body=body_text,
        recipients=[
            {"user_id": str(u.id), "email": u.email, "full_name": u.full_name,
             "telegram_linked": bool(u.telegram_chat_id)}
            for u in recipients
        ],
        total_recipients=len(recipients),
        warnings=warnings,
    )
```

> **Lưu ý:** đoạn `filtered` trong `list_rules` có dòng thừa `_can_access` — xoá khi implement, chỉ giữ filter bằng visible set (dòng sau).

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py -k "alert_rules_crud_new_schema or alert_rules_dry_run" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/api/routes/alert_rules.py server/tests/test_alert_engine.py
git commit -m "feat(alert): alert_rules routes — schema mới + dry-run test endpoint"
```

---

### Task 9b: Route alert_events — tách history ra file riêng

**Files:**
- Create: `server/app/api/routes/alert_events.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: schema AlertEventOut (Task 3).
- Produces: `GET /api/alert-rules/events` (giữ path cũ cho tương thích portal) — Task 12 portal dùng.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
async def test_alert_events_list(client, seeded_env, db, session_factory):
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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_alert_events_list -q`
Expected: FAIL (route /events không còn trả title/recipient_user_ids — hoặc 500 vì alert_events schema cũ).

- [ ] **Step 3: Cài đặt route**

```python
# server/app/api/routes/alert_events.py
"""Lịch sử alert events (read-only) — giữ path cũ /api/alert-rules/events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.db.models import AlertEvent, AlertRule
from app.schemas import AlertEventOut, Page

router = APIRouter(prefix="/api/alert-rules", tags=["alert-rules"])


@router.get("/events", response_model=Page[AlertEventOut])
async def list_events(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin()),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Lịch sử alert đã kích hoạt (mới nhất trước)."""
    base = select(AlertEvent)
    total = (await db.execute(select(sa_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(AlertEvent.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return Page[AlertEventOut](
        items=[
            AlertEventOut(
                id=e.id,
                rule_id=e.rule_id,
                template_code=e.template_code,
                machine_id=e.machine_id,
                org_id=e.org_id,
                severity=e.severity,
                title=e.title,
                body=e.body,
                recipient_user_ids=[str(x) for x in (e.recipient_user_ids or [])],
                created_at=e.created_at,
            )
            for e in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
```

Trong `server/app/main.py`:

```python
    alert_events,
# include sau alert_rules
app.include_router(alert_events.router)
```

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_alert_events_list -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/api/routes/alert_events.py server/app/main.py server/tests/test_alert_engine.py
git commit -m "feat(alert): alert_events route — history read-only tại /api/alert-rules/events"
```

---

### Task 10: Routes user_notification_prefs — /api/me/notification-prefs

**Files:**
- Create: `server/app/api/routes/user_notification_prefs.py`
- Modify: `server/app/main.py`
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: `get_prefs_with_template`, `upsert_prefs` (Task 6).
- Produces: `GET /api/me/notification-prefs`, `PATCH /api/me/notification-prefs` — Task 14 portal dùng.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
async def test_me_notification_prefs_get_and_patch(client, seeded_env):
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
```

- [ ] **Step 2: Chạy test — kỳ vọng fail**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_me_notification_prefs_get_and_patch -q`
Expected: FAIL 404.

- [ ] **Step 3: Cài đặt route**

```python
# server/app/api/routes/user_notification_prefs.py
"""User notification preferences — /api/me/notification-prefs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas import UserNotificationPrefOut, UserNotificationPrefUpdateIn
from app.services.user_notification_prefs import (
    get_prefs_with_template,
    upsert_prefs,
)

router = APIRouter(prefix="/api/me/notification-prefs", tags=["me-notification-prefs"])


class PrefsOut(BaseModel):
    items: list[UserNotificationPrefOut]


@router.get("", response_model=PrefsOut)
async def get_my_prefs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await get_prefs_with_template(db, user.id)
    return PrefsOut(items=[UserNotificationPrefOut(**r) for r in rows])


@router.patch("", response_model=PrefsOut)
async def patch_my_prefs(
    body: UserNotificationPrefUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await upsert_prefs(db, user, [p.model_dump() for p in body.prefs])
    return PrefsOut(items=[UserNotificationPrefOut(**r) for r in rows])
```

Trong `server/app/main.py`:

```python
    user_notification_prefs,
app.include_router(user_notification_prefs.router)
```

> **Chú ý:** import `get_current_user` từ `app.api.deps` (đã có).

- [ ] **Step 4: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_me_notification_prefs_get_and_patch -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/api/routes/user_notification_prefs.py server/app/main.py server/tests/test_alert_engine.py
git commit -m "feat(alert): /api/me/notification-prefs — get + patch prefs theo template controls"
```

---

### Task 11: Monitor — migrate machine_new / machine_lost / machine_offline sang alert_engine

**Files:**
- Modify: `server/app/services/monitor.py` (xoá `_deliver_alert`, sửa `_scan_alerts`, sửa `_sweep_offline`)
- Test: `server/tests/test_phase2.py` (fix alert tests)

**Interfaces:**
- Consumes: `trigger_alert` (Task 7), `scope_orgs` (Task 4).
- Produces: machine_new + machine_lost trigger từ scan; machine_offline trigger từ sweep — test E2E.

- [ ] **Step 1: Fix test Phase 2 alert theo schema mới**

```python
# server/tests/test_phase2.py — thay 2 test alert đầu bằng:

async def test_alert_rule_crud(client, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = seeded_env["org_id"]

    r = await client.post(
        "/api/alert-rules",
        json={
            "name": "Mất liên lạc 7 ngày",
            "template_code": "machine_lost",
            "org_id": org_id,
            "scope_mode": "org_only",
            "config": {"threshold_days": 7},
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    rule_id = r.json()["id"]

    r = await client.get("/api/alert-rules", headers=_auth(token))
    assert r.status_code == 200
    assert any(x["id"] == rule_id for x in r.json()["items"])

    r = await client.patch(
        f"/api/alert-rules/{rule_id}", json={"enabled": False}, headers=_auth(token)
    )
    assert r.status_code == 200 and r.json()["enabled"] is False

    r = await client.delete(f"/api/alert-rules/{rule_id}", headers=_auth(token))
    assert r.status_code == 200

    # template không tồn tại → 422
    r = await client.post(
        "/api/alert-rules",
        json={"name": "X", "template_code": "whatever", "org_id": org_id},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_alert_job_fires_and_no_duplicate(client, session_factory, seeded_env):
    token = await _login(client, seeded_env["email"], seeded_env["password"])
    org_id = uuid.UUID(seeded_env["org_id"])

    r = await client.post(
        "/api/alert-rules",
        json={"name": "Máy mới", "template_code": "machine_new", "org_id": str(org_id), "scope_mode": "org_only"},
        headers=_auth(token),
    )
    rule_id = uuid.UUID(r.json()["id"])

    async with session_factory() as s:
        m = Machine(
            org_id=org_id, machine_uuid="uuid-alert-1", hostname="PC-NEW",
            status=MachineStatus.PENDING.value, enrolled_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()

    from app.services.monitor import _scan_alerts

    await _scan_alerts()
    await _scan_alerts()  # chạy lần 2 → không trùng

    async with session_factory() as s:
        events = (await s.execute(select(AlertEvent).where(AlertEvent.rule_id == rule_id))).scalars().all()
        assert len(events) == 1
        assert events[0].title.startswith("[")  # đã render template
        r = await client.get("/api/alert-rules/events", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1
```

- [ ] **Step 2: Chạy test — kỳ vọng fail (monitor chưa migrate)**

Run: `cd server && .venv/bin/pytest tests/test_phase2.py -k "alert" -q`
Expected: FAIL — monitor vẫn dùng cột cũ (rule_type, channels).

- [ ] **Step 3: Sửa monitor.py**

Xoá hàm `_deliver_alert` (toàn bộ). Sửa `_scan_alerts`:

```python
# monitor.py — thay _scan_alerts bằng:

MACHINE_NEW_WINDOW_MINUTES = 30


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
```

Sửa `_sweep_offline` — sau khi set status + publish, thêm trigger:

```python
        for m in rows:
            m.status = MachineStatus.OFFLINE.value
            logger.info("Machine %s → offline (last_seen %s)", m.id, m.last_seen_at)
            await publish_machine_event(m.id, MachineStatus.OFFLINE.value, m.hostname)
            # Alert real-time: máy offline (best-effort, không block sweep)
            try:
                from app.services.alert_engine import trigger_alert
                from app.services.org_scope import scope_orgs
                from app.services.alert_templates import get_template

                tpl = await get_template(db, "machine_offline")
                if tpl and tpl.enabled:
                    scope_ids = await scope_orgs(db, org_id=m.org_id, scope_mode="org_only")
                    # m.org_id phải nằm trong scope của ít nhất 1 rule machine_offline —
                    # trigger_alert tự lọc rule theo org; chỉ cần gọi khi có rule enabled
                    from app.db.models import AlertRule as AR
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
                logger.debug("trigger machine_offline failed (Redis down?)")
```

- [ ] **Step 4: Chạy test Phase 2 alert — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_phase2.py -k "alert" tests/test_alert_engine.py -q`
Expected: PASS cả 2.

- [ ] **Step 5: Chạy ruff + toàn bộ test**

Run:
```bash
cd server && .venv/bin/ruff check app/services/monitor.py
.venv/bin/pytest -q 2>&1 | tail -15
```
Expected: ruff clean; các test fail chỉ còn là những chỗ chưa migrate (Task 11b fix).

- [ ] **Step 6: Commit**

```bash
git add server/app/services/monitor.py server/tests/test_phase2.py
git commit -m "feat(alert): monitor migrate machine_new/lost/offline sang alert_engine"
```

---

### Task 11b: DFIR — migrate notify_investigation_* sang trigger_alert

**Files:**
- Modify: `server/app/services/dfir_investigation.py` (4 call sites)
- Modify: `server/app/services/notifications.py` (xoá notify_investigation_completed/failed + from_dict variants + _resolve_investigation_recipients_from_dict)
- Test: `server/tests/test_alert_engine.py` (append)

**Interfaces:**
- Consumes: `trigger_alert` (Task 7).
- Produces: investigation_completed/failed trigger qua engine; xoá 4 helper cũ.

- [ ] **Step 1: Viết test fail**

```python
# server/tests/test_alert_engine.py — append
async def test_dfir_trigger_alert_via_engine(db, session_factory, seeded_env):
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
    assert admin.id in events[0].recipient_user_ids
```

- [ ] **Step 2: Chạy test — kỳ vọng fail (engine chưa đúng hoặc context thiếu)**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_dfir_trigger_alert_via_engine -q`
Expected: FAIL (hostname chưa render vì context override — sẽ pass sau khi engine set hostname từ machine nếu context thiếu).

- [ ] **Step 3: Sửa engine — machine context setdefault (đã có) — chỉ cần đảm bảo `investigation_id`/`findings_count`/`severity`/`llm_model` lấy từ context**

Kiểm tra: engine Task 7 đã `ctx.setdefault("hostname", machine.hostname)` — test này context cung cấp hostname nên OK. Chạy lại sẽ pass nếu `create_notification` chạy được. Nếu test fail vì `severity` chưa chuẩn hoá (high → error): thêm mapping trong dfir migrate (Step 4).

- [ ] **Step 4: Migrate 4 call sites trong dfir_investigation.py**

Tại 4 chỗ gọi cũ (dòng ~545, ~558, ~755, ~801), thay bằng helper chung:

```python
# dfir_investigation.py — thêm helper ở đầu file (sau import):

async def _notify_investigation_result(
    db: AsyncSession,
    *,
    investigation_id: uuid.UUID,
    machine_id: uuid.UUID,
    status: str,  # "completed" | "failed"
    severity: str | None = None,
    findings_count: int | None = None,
    llm_model: str | None = None,
    error: str | None = None,
) -> None:
    """Gọi alert_engine.trigger_alert — recipients = Org Admin của máy + Super Admin."""
    from app.services.alert_engine import trigger_alert
    from app.db.models import Machine as _M

    machine = await db.get(_M, machine_id)
    org_id = machine.org_id if machine else None

    context = {
        "hostname": machine.hostname if machine else None,
        "investigation_id": str(investigation_id),
    }
    if status == "completed":
        context.update({
            "findings_count": findings_count or 0,
            "severity": severity or "info",
            "llm_model": llm_model or "—",
        })
    else:
        context["error"] = (error or "")[:300]

    try:
        await trigger_alert(
            db,
            template_code=(
                "investigation_completed" if status == "completed"
                else "investigation_failed"
            ),
            org_id=org_id,
            machine_id=machine_id,
            context=context,
        )
    except Exception as e:  # noqa: BLE001 — không làm chết pipeline investigation
        logger.warning("notify investigation %s failed: %s", status, e)
```

Thay 4 call sites:

```python
# Dòng ~545 (completed, inv object)
await _notify_investigation_result(
    db, investigation_id=inv.id, machine_id=inv.machine_id,
    status="completed", severity=inv.severity,
    findings_count=inv.findings_count, llm_model=inv.llm_model,
)

# Dòng ~558 (failed, inv object)
await _notify_investigation_result(
    db, investigation_id=inv.id, machine_id=inv.machine_id,
    status="failed", error=str(e),
)

# Dòng ~755 (failed, snapshot dict)
await _notify_investigation_result(
    db, investigation_id=snapshot["id"], machine_id=snapshot["machine_id"],
    status="failed", error=error,
)

# Dòng ~801 (completed, snapshot dict)
await _notify_investigation_result(
    db, investigation_id=snapshot["id"], machine_id=snapshot["machine_id"],
    status="completed", severity=snapshot.get("severity"),
    findings_count=snapshot.get("findings_count"),
    llm_model=snapshot.get("llm_model"),
)
```

Xoá trong `notifications.py`: `notify_investigation_completed`, `notify_investigation_failed`, `notify_investigation_completed_from_dict`, `notify_investigation_failed_from_dict`, `get_investigation_recipients`, `_resolve_investigation_recipients_from_dict` (nếu không còn dùng).

- [ ] **Step 5: Chạy test — kỳ vọng pass**

Run: `cd server && .venv/bin/pytest tests/test_alert_engine.py::test_dfir_trigger_alert_via_engine -q`
Expected: PASS.

- [ ] **Step 6: Chạy ruff + toàn bộ test**

Run:
```bash
cd server && .venv/bin/ruff check app/services/dfir_investigation.py app/services/notifications.py
.venv/bin/pytest -q 2>&1 | tail -15
```
Expected: ruff clean; không còn import lỗi (nếu notifications.py có export bị test khác dùng → kiểm tra `grep -rn "notify_investigation" tests/`).

- [ ] **Step 7: Commit**

```bash
git add server/app/services/dfir_investigation.py server/app/services/notifications.py server/tests/test_alert_engine.py
git commit -m "feat(alert): DFIR migrate investigation_completed/failed sang alert_engine"
```

---

### Task 12: Portal — move /me/telegram → /admin/telegram-bot + sidebar

**Files:**
- Move: `portal/app/(portal)/me/telegram/page.tsx` → `portal/app/(portal)/admin/telegram-bot/page.tsx`
- Modify: `portal/components/sidebar.tsx` (đổi link `/me/telegram` → `/admin/telegram-bot`)

**Interfaces:**
- Produces: trang Super Admin bot config tại `/admin/telegram-bot` — KHÔNG đổi code.
- Task 15 portal typecheck phụ thuộc: path mới không gãy import (`@/lib/api` dùng absolute, an toàn).

- [ ] **Step 1: git mv**

```bash
cd /home/windowsId/.worktrees/alert-engine/portal
mkdir -p "app/(portal)/admin/telegram-bot"
git mv "app/(portal)/me/telegram/page.tsx" "app/(portal)/admin/telegram-bot/page.tsx"
rmdir "app/(portal)/me/telegram" 2>/dev/null || true
```

- [ ] **Step 2: Sửa sidebar link**

```tsx
// portal/components/sidebar.tsx — đổi href "/me/telegram" → "/admin/telegram-bot"
      {
        href: "/admin/telegram-bot",
        label: "Cấu hình bot Telegram",
        icon: MessageCircle,
        roles: SUPER_ADMIN_ROLES,
      },
```

- [ ] **Step 3: Verify typecheck + build**

Run:
```bash
cd portal && npm run typecheck
npm run build 2>&1 | tail -5
```
Expected: build pass, không còn tham chiếu `/me/telegram`.

- [ ] **Step 4: Commit**

```bash
git add -A portal
git commit -m "feat(portal): move /me/telegram → /admin/telegram-bot + cập nhật sidebar"
```

---

### Task 13: Portal — types + format helpers cho alert engine

**Files:**
- Modify: `portal/lib/types.ts`
- Modify: `portal/lib/format.ts`

**Interfaces:**
- Produces: `AlertTemplate`, `AlertRule` (mới), `AlertEvent` (mới), `UserNotificationPrefItem` interfaces + `ALERT_TEMPLATE_META`, `OPT_OUT_LABELS` — Task 14-16 UI dùng.

- [ ] **Step 1: Thêm types**

```ts
// portal/lib/types.ts — append

export interface AlertTemplate {
  id: string;
  code: string;
  name: string;
  description: string | null;
  category: string; // machine | investigation | security | system
  default_severity: string;
  title_template: string;
  body_template: string | null;
  opt_out_controls: string[]; // ["template"] | ["severity"] | [...]
  allowed_vars: string[];
  default_config: Record<string, unknown>;
  enabled: boolean;
  updated_at: string;
}

export interface AlertTemplatePreview {
  title: string;
  body: string | null;
  warnings: string[];
}

export interface AlertRule {
  id: string;
  name: string;
  template_code: string;
  template_name: string | null;
  org_id: string | null;
  scope_mode: "org_only" | "org_tree" | "system";
  recipient_mode: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

export interface AlertRuleTestResult {
  template_code: string;
  title: string;
  body: string | null;
  recipients: Array<{
    user_id: string;
    email: string;
    full_name: string;
    telegram_linked: boolean;
  }>;
  total_recipients: number;
  warnings: string[];
}

export interface AlertEvent {
  id: number;
  rule_id: string;
  template_code: string;
  machine_id: string | null;
  org_id: string | null;
  severity: string;
  title: string;
  body: string | null;
  recipient_user_ids: string[];
  created_at: string;
}

export interface UserNotificationPref {
  template_code: string;
  template_name: string;
  category: string;
  default_severity: string;
  opt_out_controls: string[];
  muted: boolean;
  min_severity: string | null;
}
```

- [ ] **Step 2: Thêm format helpers**

```ts
// portal/lib/format.ts — append

export const ALERT_CATEGORY_META: Record<string, { label: string; badge: string }> = {
  machine: { label: "Máy", badge: "bg-blue-50 text-blue-700 ring-blue-600/20" },
  investigation: { label: "Điều tra", badge: "bg-violet-50 text-violet-700 ring-violet-600/20" },
  security: { label: "Bảo mật", badge: "bg-rose-50 text-rose-700 ring-rose-600/20" },
  system: { label: "Hệ thống", badge: "bg-slate-100 text-slate-600 ring-slate-500/20" },
};

export const OPT_OUT_LABELS: Record<string, string> = {
  template: "Tắt nhận template này",
  severity: "Chọn mức severity tối thiểu",
};
```

- [ ] **Step 3: Verify typecheck**

Run: `cd portal && npm run typecheck`
Expected: pass (chưa dùng type mới → không lỗi).

- [ ] **Step 4: Commit**

```bash
git add portal/lib/types.ts portal/lib/format.ts
git commit -m "feat(portal): types + format helpers alert engine redesign"
```

---

### Task 14: Portal — notifications-alerts refactor thành 3 tab + SubscriptionsTab

**Files:**
- Rewrite: `portal/app/(portal)/notifications-alerts/page.tsx` (layout 3 tab)
- Create: `portal/app/(portal)/notifications-alerts/SubscriptionsTab.tsx`
- Modify: `portal/lib/format.ts` (ALERT_RULE_TYPE_META giữ cho template badges)

**Interfaces:**
- Consumes: `AlertRule`, `AlertTemplate`, `Organization`, `flattenOrgTree` (types/format Task 13).
- Produces: tab Subscriptions (list + create form: template dropdown + scope radio + org tree + config threshold + dry-run test).

- [ ] **Step 1: Viết SubscriptionsTab.tsx**

```tsx
// portal/app/(portal)/notifications-alerts/SubscriptionsTab.tsx
"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BellRing, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertRule, AlertTemplate, AlertRuleTestResult, Organization } from "@/lib/types";
import { ALERT_CATEGORY_META, flattenOrgTree, ORG_TYPE_META } from "@/lib/format";
import {
  Badge, Button, Card, ConfirmDialog, EmptyState, ErrorBanner,
  Field, IconButton, Input, PageResponse, Select, Spinner, Pagination,
} from "@/components/ui";

const SCOPE_OPTIONS = [
  { value: "org_only", label: "Một tổ chức (không gồm đơn vị con)" },
  { value: "org_tree", label: "Tổ chức + đơn vị trực thuộc" },
  { value: "system", label: "Toàn hệ thống (chỉ Super Admin)" },
];

export default function SubscriptionsTab({
  isSuperAdmin, templates, orgs,
}: {
  isSuperAdmin: boolean;
  templates: AlertTemplate[];
  orgs: Organization[];
}) {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [page, setPage] = useState<PageResponse<AlertRule>>({ items: [], total: 0, limit: 50, offset: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // form
  const [name, setName] = useState("");
  const [templateCode, setTemplateCode] = useState("machine_new");
  const [scopeMode, setScopeMode] = useState<"org_only" | "org_tree" | "system">("org_only");
  const [orgId, setOrgId] = useState("");
  const [thresholdDays, setThresholdDays] = useState(7);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AlertRule | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [testResult, setTestResult] = useState<AlertRuleTestResult | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const r = await api.get<PageResponse<AlertRule>>("/alert-rules", { limit: 50, offset });
      setRules(r.items);
      setPage(r);
      setError(null);
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : "Không tải được rule");
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { void load(); }, [load]);

  const selectedTemplate = templates.find((t) => t.code === templateCode);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const config: Record<string, unknown> = {};
      if (selectedTemplate?.code === "machine_lost") config.threshold_days = thresholdDays;
      await api.post<AlertRule>("/alert-rules", {
        name,
        template_code: templateCode,
        org_id: scopeMode === "system" ? null : orgId || null,
        scope_mode: scopeMode,
        recipient_mode: "org_admins_and_super",
        config,
      });
      setName("");
      setTestResult(null);
      await load(true);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.detail : "Không tạo được rule");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleRule = async (rule: AlertRule) => {
    try {
      await api.patch(`/alert-rules/${rule.id}`, { enabled: !rule.enabled });
      await load(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Cập nhật thất bại"); }
  };

  const removeRule = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.delete(`/alert-rules/${removing.id}`);
      setRemoving(null);
      await load(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Xóa thất bại"); }
    finally { setRemoveBusy(false); }
  };

  const runTest = async (rule: AlertRule) => {
    setTestingId(rule.id);
    setTestResult(null);
    try {
      const r = await api.post<AlertRuleTestResult>(`/alert-rules/${rule.id}/test`, { context: {} });
      setTestResult(r);
    } catch (e) { setError(e instanceof Error ? e.message : "Test thất bại"); }
    finally { setTestingId(null); }
  };

  const canSystem = isSuperAdmin;
  const effectiveScopeOptions = SCOPE_OPTIONS.filter((o) => o.value !== "system" || canSystem);

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="Subscriptions" subtitle="Mỗi rule bind 1 template + phạm vi + người nhận mặc định (Org Admin + Super Admin)" padded={false}>
        {loading && rules.length === 0 ? <Spinner /> : rules.length === 0 ? (
          <EmptyState icon={<BellRing className="size-10" />} title="Chưa có rule nào" description="Tạo rule đầu tiên ở form bên phải." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {rules.map((r) => {
              const tpl = templates.find((t) => t.code === r.template_code);
              const cat = ALERT_CATEGORY_META[tpl?.category ?? "system"] ?? ALERT_CATEGORY_META.system;
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <span className={`flex size-9 items-center justify-center rounded-lg ${r.enabled ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-400"}`}>
                    <BellRing className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">{r.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge className={cat.badge}>{tpl?.name ?? r.template_code}</Badge>
                      <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">
                        {SCOPE_OPTIONS.find((o) => o.value === r.scope_mode)?.label ?? r.scope_mode}
                      </Badge>
                      {r.config?.threshold_days != null && (
                        <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">&gt; {r.config.threshold_days} ngày</Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button variant="outline" size="sm" onClick={() => void runTest(r)} disabled={testingId === r.id}>
                      {testingId === r.id ? "Đang test…" : "Test"}
                    </Button>
                    <button role="switch" aria-checked={r.enabled} aria-label={r.enabled ? `Tắt rule ${r.name}` : `Bật rule ${r.name}`}
                      onClick={() => void toggleRule(r)}
                      className={`relative h-6 w-10 cursor-pointer rounded-full transition-colors ${r.enabled ? "bg-emerald-500" : "bg-slate-300"}`}>
                      <span className={`absolute top-1 size-4 rounded-full bg-white transition-all ${r.enabled ? "left-5" : "left-1"}`} />
                    </button>
                    <IconButton label={`Xóa rule ${r.name}`} onClick={() => setRemoving(r)} className="hover:bg-rose-50 hover:text-rose-600">
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <Pagination page={page} onChange={(o) => { setOffset(o); void load(true); }} />
      </Card>

      <Card title="Tạo rule mới">
        <form onSubmit={create} className="space-y-3">
          <Field label="Tên rule" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Máy mới ở Sở Công an" required />
          </Field>
          <Field label="Mẫu alert" required>
            <Select value={templateCode} onChange={(e) => { setTemplateCode(e.target.value); setTestResult(null); }}>
              {templates.map((t) => (
                <option key={t.code} value={t.code}>{t.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Phạm vi" required hint={scopeMode === "system" ? "Chỉ Super Admin" : undefined}>
            <Select value={scopeMode} onChange={(e) => setScopeMode(e.target.value as typeof scopeMode)}>
              {effectiveScopeOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          </Field>
          {scopeMode !== "system" && (
            <Field label="Tổ chức" required hint="Bỏ trống = toàn hệ thống (nếu được phép)">
              <Select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                <option value="">— Chọn tổ chức —</option>
                {flattenOrgTree(orgs).map(({ org, depth }) => {
                  const meta = ORG_TYPE_META[org.type];
                  return (
                    <option key={org.id} value={org.id}>{"— ".repeat(depth)}{org.name} ({meta?.label ?? org.type})</option>
                  );
                })}
              </Select>
            </Field>
          )}
          {selectedTemplate?.code === "machine_lost" && (
            <Field label="Ngưỡng mất liên lạc (ngày)" required>
              <Input type="number" min={1} max={365} value={thresholdDays} onChange={(e) => setThresholdDays(Number(e.target.value))} />
            </Field>
          )}
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Người nhận: <b>Org Admin của phạm vi + Super Admin</b> (Org Admin tự tắt nhận qua Cài đặt thông báo)
          </div>
          {formError && <p className="text-sm text-rose-600">{formError}</p>}
          <Button type="submit" loading={submitting} className="w-full" disabled={!name || (scopeMode !== "system" && !orgId)}>
            <Plus className="size-4" /> Tạo rule
          </Button>
        </form>
      </Card>

      {testResult && (
        <Card className="xl:col-span-3" title="Kết quả test (dry-run — không gửi)">
          <div className="space-y-2 text-sm">
            <p className="font-medium">{testResult.title}</p>
            {testResult.body && <pre className="whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">{testResult.body}</pre>}
            <p className="text-xs text-slate-500">{testResult.total_recipients} người nhận</p>
            {testResult.recipients.length > 0 && (
              <ul className="max-h-40 overflow-y-auto rounded border border-slate-200 divide-y divide-slate-100 text-xs">
                {testResult.recipients.map((u) => (
                  <li key={u.user_id} className="flex items-center justify-between px-3 py-1.5">
                    <span>{u.full_name || u.email}</span>
                    <Badge className={u.telegram_linked ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-slate-100 text-slate-500 ring-slate-500/20"}>
                      {u.telegram_linked ? "Telegram ✓" : "Chưa link TG"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {testResult.warnings.length > 0 && (
              <p className="text-xs text-amber-600">Warning: {testResult.warnings.join(", ")}</p>
            )}
          </div>
        </Card>
      )}

      <ConfirmDialog open={removing !== null} onClose={() => setRemoving(null)} title="Xóa alert rule" danger
        loading={removeBusy} confirmLabel="Xóa rule" onConfirm={() => void removeRule()}
        message={<>Rule <b>{removing?.name}</b> sẽ bị xóa vĩnh viễn.</>} />
    </div>
  );
}
```

- [ ] **Step 2: Rewrite page.tsx thành layout 3 tab**

```tsx
// portal/app/(portal)/notifications-alerts/page.tsx — REWRITE
"use client";

import { useEffect, useState } from "react";
import { Bell, BellRing, History, Plus, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { AlertTemplate, Organization } from "@/lib/types";
import { Badge, Button, PageHeader } from "@/components/ui";
import { useAuth } from "@/components/auth-context";
import { useNotifications } from "@/components/notification-bell";
import SubscriptionsTab from "./SubscriptionsTab";
import TemplatesTab from "./TemplatesTab";
import HistoryTab from "./HistoryTab";

type Tab = "subscriptions" | "templates" | "history";

export default function NotificationsAlertsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";
  const [tab, setTab] = useState<Tab>("subscriptions");
  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const { unreadCount, refresh } = useNotifications();
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    api.get<AlertTemplate[]>("/admin/alert-templates")
      .then((list) => setTemplates(Array.isArray(list) ? list : []))
      .catch(() => setTemplates([]));
    api.get<Organization[]>("/orgs")
      .then((list) => setOrgs(Array.isArray(list) ? list : []))
      .catch(() => setOrgs([]));
    void refresh();
  }, [refresh]);

  const tabs: Array<{ key: Tab; label: string; icon: React.ReactNode; show: boolean }> = [
    { key: "subscriptions", label: "Subscriptions", icon: <BellRing className="size-3.5" />, show: true },
    { key: "templates", label: "Templates", icon: <Bell className="size-3.5" />, show: isSuperAdmin },
    { key: "history", label: "Lịch sử", icon: <History className="size-3.5" />, show: true },
  ];

  return (
    <div>
      <PageHeader
        title="Thông báo & Cảnh báo"
        description="Mẫu alert · Phạm vi · Người nhận — quản lý theo 3 trục"
        actions={
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)}>
              <History className="size-3.5" /> Lịch sử thông báo
              {unreadCount > 0 && <Badge className="ml-1 bg-brand-50 text-brand-700 ring-brand-600/20">{unreadCount} mới</Badge>}
            </Button>
          </div>
        }
      />

      <div className="mb-6 flex items-center gap-1 rounded-lg bg-slate-100 p-1 w-fit">
        {tabs.filter((t) => t.show).map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t.key ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white/60"
            }`}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      {tab === "subscriptions" && <SubscriptionsTab isSuperAdmin={isSuperAdmin} templates={templates} orgs={orgs} />}
      {tab === "templates" && <TemplatesTab templates={templates} onReload={() => {
        api.get<AlertTemplate[]>("/admin/alert-templates")
          .then((list) => setTemplates(Array.isArray(list) ? list : []))
          .catch(() => setTemplates([]));
      }} />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}
```

- [ ] **Step 3: Tạo placeholder TemplatesTab + HistoryTab (task sau sẽ fill)**

```tsx
// portal/app/(portal)/notifications-alerts/TemplatesTab.tsx — placeholder (Task 15 fill)
"use client";
export default function TemplatesTab({ templates, onReload }: { templates: unknown[]; onReload: () => void }) {
  return <div className="text-sm text-slate-500">Tab Templates — sẽ được cài đặt ở bước tiếp theo.</div>;
}

// portal/app/(portal)/notifications-alerts/HistoryTab.tsx — placeholder (Task 16 fill)
"use client";
export default function HistoryTab() {
  return <div className="text-sm text-slate-500">Tab Lịch sử — sẽ được cài đặt ở bước tiếp theo.</div>;
}
```

- [ ] **Step 4: Xoá imports cũ trong format.ts nếu không dùng**

Kiểm tra `ALERT_RULE_TYPE_META`, `ALERT_CHANNEL_META` còn được dùng ở đâu khác: `grep -rn "ALERT_RULE_TYPE_META\|ALERT_CHANNEL_META" portal/app portal/components` — nếu chỉ dùng trong notifications-alerts cũ → xoá khỏi format.ts (Task này). Nếu dùng nơi khác → giữ.

- [ ] **Step 5: Verify typecheck + build**

Run: `cd portal && npm run typecheck && npm run build 2>&1 | tail -5`
Expected: build pass.

- [ ] **Step 6: Commit**

```bash
git add portal/app/\(portal\)/notifications-alerts/ portal/lib/format.ts
git commit -m "feat(portal): notifications-alerts 3 tab layout + SubscriptionsTab"
```

---

### Task 15: Portal — TemplatesTab (Super Admin) với editor + live preview

**Files:**
- Rewrite: `portal/app/(portal)/notifications-alerts/TemplatesTab.tsx`

**Interfaces:**
- Consumes: `AlertTemplate`, `AlertTemplatePreview`, api helpers (Task 13).
- Produces: list template + edit modal (title/body/opt_out_controls/allowed_vars/default_severity) + live preview gọi `POST /api/admin/alert-templates/{code}/preview`.

- [ ] **Step 1: Viết TemplatesTab.tsx**

```tsx
// portal/app/(portal)/notifications-alerts/TemplatesTab.tsx
"use client";

import { useState } from "react";
import { Bell, Check, Save, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AlertTemplate, AlertTemplatePreview } from "@/lib/types";
import { ALERT_CATEGORY_META, ALERT_SEVERITY_META, OPT_OUT_LABELS } from "@/lib/format";
import {
  Badge, Button, Card, ErrorBanner, Field, Input, Modal, Select, Textarea, Toggle,
} from "@/components/ui";

export default function TemplatesTab({
  templates, onReload,
}: {
  templates: AlertTemplate[];
  onReload: () => void;
}) {
  const [editing, setEditing] = useState<AlertTemplate | null>(null);
  const [titleTemplate, setTitleTemplate] = useState("");
  const [bodyTemplate, setBodyTemplate] = useState("");
  const [optOut, setOptOut] = useState<string[]>([]);
  const [defaultSeverity, setDefaultSeverity] = useState("info");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [preview, setPreview] = useState<AlertTemplatePreview | null>(null);
  const [previewCtx, setPreviewCtx] = useState("{}");

  const openEdit = (t: AlertTemplate) => {
    setEditing(t);
    setTitleTemplate(t.title_template);
    setBodyTemplate(t.body_template ?? "");
    setOptOut(t.opt_out_controls ?? []);
    setDefaultSeverity(t.default_severity);
    setEnabled(t.enabled);
    setError(null);
    setInfo(null);
    setPreview(null);
    setPreviewCtx("{}");
  };

  const toggleOptOut = (c: string) => {
    setOptOut((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const updated = await api.patch<AlertTemplate>(`/admin/alert-templates/${editing.code}`, {
        title_template: titleTemplate,
        body_template: bodyTemplate || null,
        opt_out_controls: optOut,
        default_severity: defaultSeverity,
        enabled,
      });
      setEditing(updated);
      setInfo("Đã lưu template. Thay đổi áp dụng cho mọi rule dùng template này.");
      onReload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    if (!editing) return;
    try {
      let ctx: Record<string, unknown> = {};
      try { ctx = JSON.parse(previewCtx || "{}"); } catch { setError("Context preview phải là JSON hợp lệ"); return; }
      const r = await api.post<AlertTemplatePreview>(`/admin/alert-templates/${editing.code}/preview`, { context: ctx });
      setPreview(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview thất bại");
    }
  };

  return (
    <div className="space-y-6">
      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {info && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" />{info}
        </div>
      )}

      <Card title="Templates" subtitle="Super Admin quản lý nội dung + opt-out controls cho từng loại alert" padded={false}>
        <ul className="divide-y divide-slate-100">
          {templates.map((t) => {
            const cat = ALERT_CATEGORY_META[t.category] ?? ALERT_CATEGORY_META.system;
            const sev = ALERT_SEVERITY_META[t.default_severity] ?? ALERT_SEVERITY_META.info;
            return (
              <li key={t.code} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <span className="flex size-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <Bell className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800">{t.name}</p>
                  <p className="text-xs text-slate-500">{t.code}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge className={cat.badge}>{cat.label}</Badge>
                    <Badge className={sev.badge}>{sev.label}</Badge>
                    {(t.opt_out_controls ?? []).map((c) => (
                      <Badge key={c} className="bg-slate-100 text-slate-600 ring-slate-500/20">{OPT_OUT_LABELS[c] ?? c}</Badge>
                    ))}
                    {!t.enabled && <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">Disabled</Badge>}
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => openEdit(t)}>Sửa template</Button>
              </li>
            );
          })}
        </ul>
      </Card>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={`Sửa template · ${editing?.code ?? ""}`}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>Hủy</Button>
            <Button onClick={() => void save()} disabled={saving} loading={saving}>
              <Save className="size-3.5" /> Lưu template
            </Button>
          </div>
        }>
        {editing && (
          <div className="space-y-4">
            <Field label="Tên" required>
              <Input value={editing.name} disabled />
            </Field>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Category">
                <Badge className={ALERT_CATEGORY_META[editing.category]?.badge ?? ""}>
                  {ALERT_CATEGORY_META[editing.category]?.label ?? editing.category}
                </Badge>
              </Field>
              <Field label="Severity mặc định">
                <Select value={defaultSeverity} onChange={(e) => setDefaultSeverity(e.target.value)}>
                  {Object.entries(ALERT_SEVERITY_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </Select>
              </Field>
            </div>

            <Field label="Title template" required hint={`Biến cho phép: ${(editing.allowed_vars ?? []).join(", ")}`}>
              <Input value={titleTemplate} onChange={(e) => setTitleTemplate(e.target.value)} />
            </Field>
            <Field label="Body template" hint={`Biến cho phép: ${(editing.allowed_vars ?? []).join(", ")}`}>
              <Textarea rows={4} value={bodyTemplate} onChange={(e) => setBodyTemplate(e.target.value)} />
            </Field>

            <Field label="Opt-out controls" hint="Template quyết định admin được mute theo cách nào">
              <div className="flex flex-wrap gap-3">
                {["template", "severity"].map((c) => (
                  <label key={c} className="flex items-center gap-1.5 text-sm text-slate-700">
                    <input type="checkbox" checked={optOut.includes(c)} onChange={() => toggleOptOut(c)}
                      className="size-4 rounded border-slate-300 text-blue-600 focus:ring-brand-600" />
                    {OPT_OUT_LABELS[c]}
                  </label>
                ))}
              </div>
            </Field>

            <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
              <span className="text-sm text-slate-700">Template enabled</span>
              <Toggle on={enabled} onChange={setEnabled} label="Template enabled" />
            </div>

            {/* Live preview */}
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
                <Sparkles className="size-3.5" /> Live preview
              </p>
              <Field label="Context JSON (sample)">
                <Input value={previewCtx} onChange={(e) => setPreviewCtx(e.target.value)} placeholder='{"hostname": "PC-01"}' />
              </Field>
              <Button variant="outline" size="sm" onClick={() => void runPreview()}>Render preview</Button>
              {preview && (
                <div className="rounded bg-white p-2 text-xs space-y-1 ring-1 ring-slate-200">
                  <p className="font-medium text-slate-800">{preview.title}</p>
                  {preview.body && <pre className="whitespace-pre-wrap text-slate-600">{preview.body}</pre>}
                  {preview.warnings.length > 0 && (
                    <p className="text-amber-600">Warning: {preview.warnings.join(", ")}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
```

> **Chú ý:** `Toggle` trong `components/ui.tsx` — kiểm tra signature: `export function Toggle({ on, onChange, label, ... })`. Nếu props khác (vd `checked`, `setChecked`), điều chỉnh cho khớp. Xem `notification-bell.tsx` / `settings/page.tsx` cách dùng.

- [ ] **Step 2: Verify typecheck + build**

Run: `cd portal && npm run typecheck && npm run build 2>&1 | tail -5`
Expected: build pass (nếu lỗi Toggle props → sửa cho khớp ui.tsx).

- [ ] **Step 3: Commit**

```bash
git add portal/app/\(portal\)/notifications-alerts/TemplatesTab.tsx
git commit -m "feat(portal): TemplatesTab — editor template + live preview"
```

---

### Task 16: Portal — HistoryTab (alert events)

**Files:**
- Rewrite: `portal/app/(portal)/notifications-alerts/HistoryTab.tsx`

**Interfaces:**
- Consumes: `AlertEvent` type (Task 13), `api.get("/alert-rules/events")`.
- Produces: bảng lịch sử events (time, template, severity, title, recipients count).

- [ ] **Step 1: Viết HistoryTab.tsx**

```tsx
// portal/app/(portal)/notifications-alerts/HistoryTab.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { BellRing } from "lucide-react";
import { api } from "@/lib/api";
import type { AlertEvent } from "@/lib/types";
import { ALERT_SEVERITY_META, formatDateTime, timeAgo } from "@/lib/format";
import {
  Badge, Card, EmptyState, PageResponse, Pagination, Spinner,
  TABLE, TABLE_WRAP, TD, TH, THEAD, TR_HOVER,
} from "@/components/ui";

export default function HistoryTab() {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [page, setPage] = useState<PageResponse<AlertEvent>>({ items: [], total: 0, limit: 50, offset: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (silent = false) => {
    try {
      const r = await api.get<PageResponse<AlertEvent>>("/alert-rules/events", { limit: 50, offset });
      setEvents(r.items);
      setPage(r);
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { void load(); }, [load]);

  return (
    <Card title="Lịch sử cảnh báo" subtitle={`${page.total} sự kiện — content đã render lúc trigger`} padded={false}>
      {loading && events.length === 0 ? <Spinner /> : events.length === 0 ? (
        <EmptyState icon={<BellRing className="size-10" />} title="Chưa có cảnh báo nào" description="Cảnh báo sẽ xuất hiện khi rule kích hoạt." />
      ) : (
        <div className={TABLE_WRAP}>
          <table className={TABLE}>
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={TH}>Thời gian</th>
                <th scope="col" className={TH}>Template</th>
                <th scope="col" className={TH}>Mức độ</th>
                <th scope="col" className={TH}>Nội dung</th>
                <th scope="col" className={TH}>Người nhận</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const sev = ALERT_SEVERITY_META[ev.severity] ?? ALERT_SEVERITY_META.info;
                return (
                  <tr key={ev.id} className={TR_HOVER}>
                    <td className={`${TD} text-xs`} title={formatDateTime(ev.created_at)}>{timeAgo(ev.created_at)}</td>
                    <td className={`${TD} text-xs text-slate-500`}>{ev.template_code}</td>
                    <td className={TD}><Badge className={sev.badge}>{sev.label}</Badge></td>
                    <td className={`${TD} text-sm text-slate-700`}>{ev.title}</td>
                    <td className={`${TD} text-xs text-slate-500`}>{ev.recipient_user_ids?.length ?? 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={page} onChange={(o) => { setOffset(o); void load(true); }} />
        </div>
      )}
    </Card>
  );
}
```

- [ ] **Step 2: Verify typecheck + build**

Run: `cd portal && npm run typecheck && npm run build 2>&1 | tail -5`
Expected: build pass.

- [ ] **Step 3: Commit**

```bash
git add portal/app/\(portal\)/notifications-alerts/HistoryTab.tsx
git commit -m "feat(portal): HistoryTab — lịch sử alert events"
```

---

### Task 17: Portal — /me/notification-prefs trang cấu hình nhận thông báo

**Files:**
- Create: `portal/app/(portal)/me/notification-prefs/page.tsx`
- Modify: `portal/components/sidebar.tsx` (thêm link cho ADMIN_ROLES)
- Modify: `portal/components/user-info.tsx` (nếu có menu cá nhân — kiểm tra)

**Interfaces:**
- Consumes: `UserNotificationPref` type (Task 13), `api.get/patch("/api/me/notification-prefs")`.
- Produces: trang render động theo `opt_out_controls`; Super Admin thấy banner + disabled.

- [ ] **Step 1: Viết page**

```tsx
// portal/app/(portal)/me/notification-prefs/page.tsx
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BellOff, Check, Save, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { UserNotificationPref } from "@/lib/types";
import { ALERT_CATEGORY_META, ALERT_SEVERITY_META, OPT_OUT_LABELS } from "@/lib/format";
import { useAuth } from "@/components/auth-context";
import { Badge, Button, Card, ErrorBanner, Select, Spinner, Toggle } from "@/components/ui";

const SEVERITY_OPTIONS = ["info", "success", "warning", "error", "critical"];

export default function NotificationPrefsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin_global";

  const [items, setItems] = useState<UserNotificationPref[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: UserNotificationPref[] }>("/me/notification-prefs");
      setItems(r.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tải được cấu hình");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const g: Record<string, UserNotificationPref[]> = {};
    for (const it of items) (g[it.category] ??= []).push(it);
    return g;
  }, [items]);

  const update = (code: string, patch: Partial<UserNotificationPref>) => {
    setItems((prev) => prev.map((it) => (it.template_code === code ? { ...it, ...patch } : it)));
    setSaved(false);
  };

  const saveAll = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.patch("/me/notification-prefs", {
        prefs: items.map((it) => ({
          template_code: it.template_code,
          muted: it.muted,
          min_severity: it.min_severity,
        })),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 5000);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner label="Đang tải cài đặt thông báo..." />;

  const enabledItems = items.filter((it) => it.opt_out_controls.length > 0);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="flex items-center gap-3">
        <BellOff className="size-7 text-brand-600" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Cài đặt nhận thông báo</h1>
          <p className="text-sm text-slate-500">
            Tùy chỉnh loại alert bạn muốn nhận. Thay đổi áp dụng cho cả cổng thông báo trên portal và Telegram.
          </p>
        </div>
      </header>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {saved && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200">
          <Check className="size-4 shrink-0 text-emerald-600" /> Đã lưu cài đặt.
        </div>
      )}

      {isSuperAdmin && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-slate-400" />
          <div>
            <p className="font-semibold">Bạn là Super Admin.</p>
            <p className="mt-1 text-xs">Super Admin luôn nhận mọi alert trong hệ thống và không thể tắt. Các control bên dưới không áp dụng cho bạn.</p>
          </div>
        </div>
      )}

      {enabledItems.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">Không có alert nào có tùy chọn nhận. Bạn nhận toàn bộ alert hệ thống.</p>
        </Card>
      ) : (
        Object.entries(grouped).map(([category, list]) => (
          <Card key={category} title={ALERT_CATEGORY_META[category]?.label ?? category}>
            <div className="divide-y divide-slate-100">
              {list.map((it) => (
                <div key={it.template_code} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-800">{it.template_name}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        Mức mặc định: <Badge className={ALERT_SEVERITY_META[it.default_severity]?.badge ?? ""}>{ALERT_SEVERITY_META[it.default_severity]?.label ?? it.default_severity}</Badge>
                      </p>
                    </div>
                    <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">{it.template_code}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-4">
                    {it.opt_out_controls.includes("template") && (
                      <label className="flex items-center gap-2 text-sm text-slate-700">
                        <Toggle on={!it.muted} onChange={(v: boolean) => update(it.template_code, { muted: !v })} label={`Nhận ${it.template_name}`} />
                        <span className={it.muted ? "text-slate-400" : "text-slate-700"}>
                          {it.muted ? "Đang tắt" : "Đang nhận"}
                        </span>
                      </label>
                    )}
                    {it.opt_out_controls.includes("severity") && (
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <span className="text-xs text-slate-500">Chỉ nhận từ mức:</span>
                        <Select
                          value={it.min_severity ?? it.default_severity}
                          onChange={(e) => update(it.template_code, { min_severity: e.target.value })}
                          disabled={isSuperAdmin}
                          className="w-36"
                        >
                          {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{ALERT_SEVERITY_META[s]?.label ?? s}</option>)}
                        </Select>
                      </div>
                    )}
                    {it.opt_out_controls.length === 0 && (
                      <p className="text-xs text-slate-400">Luôn nhận (không có tùy chọn tắt) — {OPT_OUT_LABELS.template}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      {!isSuperAdmin && enabledItems.length > 0 && (
        <div className="sticky bottom-4 flex justify-end">
          <Button onClick={() => void saveAll()} loading={saving}>
            <Save className="size-3.5" /> Lưu cài đặt
          </Button>
        </div>
      )}
    </div>
  );
}
```

> **Chú ý:** kiểm tra `Toggle` props trong `components/ui.tsx` — nếu signature là `({ on, onChange, label })` thì OK; nếu là `checked/setChecked` thì đổi. Xem cách `settings/page.tsx` dùng.

- [ ] **Step 2: Thêm sidebar link**

```tsx
// portal/components/sidebar.tsx — thêm vào group ADMIN (sau "Cấu hình Agent" hoặc gần /notifications-alerts)
      {
        href: "/me/notification-prefs",
        label: "Cài đặt nhận thông báo",
        icon: BellOff,
        roles: ADMIN_ROLES,
      },
```
Import `BellOff` từ lucide-react nếu chưa có.

- [ ] **Step 3: Verify typecheck + build**

Run: `cd portal && npm run typecheck && npm run build 2>&1 | tail -5`
Expected: build pass.

- [ ] **Step 4: Commit**

```bash
git add portal/app/\(portal\)/me/notification-prefs/ portal/components/sidebar.tsx
git commit -m "feat(portal): /me/notification-prefs — opt-out per template theo opt_out_controls"
```

---

### Task 18: Integration test — luồng E2E machine_new → Org Admin nhận + Telegram

**Files:**
- Create: `server/tests/integration/test_alert_flow.py`
- Test: chạy `pytest -q tests/integration/`

**Interfaces:**
- Consumes: toàn bộ alert engine đã build (Task 1-11b).
- Produces: chứng minh E2E: enroll máy mới → notification cho Org Admin + Telegram cho admin đã link.

- [ ] **Step 1: Viết integration test**

```python
# server/tests/integration/test_alert_flow.py
"""E2E: machine enroll → alert → Org Admin nhận in-app + Telegram (nếu link)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.db.models import AlertEvent, AlertRule, Machine, MachineStatus, User, UserNotificationPref
from app.services.monitor import _scan_alerts


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_machine_enroll_triggers_notification_to_org_admin(
    client, session_factory, seeded_env,
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


async def test_machine_enroll_sends_telegram_to_linked_admin(
    client, session_factory, seeded_env,
):
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


async def test_org_admin_mute_stops_notification(client, session_factory, seeded_env):
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
```

- [ ] **Step 2: Chạy test**

Run: `cd server && .venv/bin/pytest tests/integration/test_alert_flow.py -q`
Expected: PASS cả 3 (nếu telegram mock chưa khớp → xem `_maybe_deliver_telegram` trong notifications.py để sửa mock).

- [ ] **Step 3: Commit**

```bash
git add server/tests/integration/test_alert_flow.py
git commit -m "test(alert): integration E2E — enroll → org admin notified + telegram + mute"
```

---

### Task 19: Docs — API_CONTRACT.md + RUNBOOK.md

**Files:**
- Modify: `docs/API_CONTRACT.md`
- Modify: `docs/RUNBOOK.md`

**Interfaces:**
- Consumes: toàn bộ API mới (Task 8-10).
- Produces: tài liệu alert engine cho người vận hành.

- [ ] **Step 1: API_CONTRACT.md — thêm section alert engine**

```markdown
## Alert Engine (redesign — 3 trục)

### Templates (Super Admin)
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/admin/alert-templates` | Danh sách template |
| GET | `/api/admin/alert-templates/{code}` | Chi tiết 1 template |
| PATCH | `/api/admin/alert-templates/{code}` | Sửa name/title/body/opt_out_controls/allowed_vars/severity |
| POST | `/api/admin/alert-templates/{code}/preview` | Render thử với context mẫu |

### Subscriptions
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/alert-rules` | Danh sách rule (theo quyền) |
| POST | `/api/alert-rules` | Tạo rule (template_code + org_id + scope_mode + recipient_mode) |
| PATCH | `/api/alert-rules/{id}` | Sửa rule |
| DELETE | `/api/alert-rules/{id}` | Xóa rule |
| POST | `/api/alert-rules/{id}/test` | Dry-run: render + resolve recipients (không gửi) |
| GET | `/api/alert-rules/events` | Lịch sử alert events |

### User prefs
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/me/notification-prefs` | Prefs của user + metadata template |
| PATCH | `/api/me/notification-prefs` | Upsert prefs (validate theo opt_out_controls) |

### Delivery
- In-app notification: luôn gửi qua `notifications` table + WebSocket.
- Telegram: gửi qua bot (`telegram_runtime`) tới `user.telegram_chat_id` nếu user đã link.
- Super Admin luôn nhận; Org Admin có thể mute/ngưỡng severity qua prefs.
```

- [ ] **Step 2: RUNBOOK.md — thêm section vận hành**

```markdown
## Vận hành Alert (Telegram)

1. **Cấu hình bot**: Super Admin vào `/admin/telegram-bot` → nhập token từ @BotFather → Test kết nối → Set webhook (curl snippet trong trang).
2. **User link Telegram**: user vào Tài khoản → tab Telegram → bấm link → mở bot → /start <token>.
3. **Tạo rule**: `/notifications-alerts` → tab Subscriptions → chọn template + phạm vi + ngưỡng → Test dry-run trước khi bật.
4. **Org Admin tắt nhận**: `/me/notification-prefs` — mute per template hoặc chọn ngưỡng severity.
5. **Debug**: `/notifications-alerts` → tab Lịch sử — event có `recipient_user_ids`; nếu Telegram không gửi, kiểm tra user có `telegram_chat_id` (trang /admin/telegram-bot → linked-users).
6. **Mất dữ liệu alert cũ**: migration t8u9v0w1x2y3 drop bảng alert_rules/alert_events cũ — cần recreate rule sau upgrade.
```

- [ ] **Step 3: Kiểm tra docs render**

Run: `grep -n "Alert Engine" docs/API_CONTRACT.md && grep -n "Vận hành Alert" docs/RUNBOOK.md`
Expected: cả 2 đều xuất hiện.

- [ ] **Step 4: Commit**

```bash
git add docs/API_CONTRACT.md docs/RUNBOOK.md
git commit -m "docs: alert engine API contract + runbook vận hành Telegram"
```

---

## Self-Review

### 1. Spec coverage

| Spec section | Task |
|---|---|
| §4.2 Schema (alert_templates, user_notification_prefs, alert_rules, alert_events) | Task 1 (migration), Task 2 (models) |
| §4.3 Service alert_engine.trigger_alert | Task 7 |
| §4.4 File mới server | Task 4-9b |
| §6 Seed 7 templates | Task 1 |
| §7 API endpoints (templates admin, rules, prefs) | Task 8, 9, 9b, 10 |
| §8.1 notifications-alerts 3 tab | Task 14-16 |
| §8.2 /me/notification-prefs | Task 17 |
| §8.3 /admin/telegram-bot move | Task 12 |
| §9 Trigger points migrate (monitor + dfir) | Task 11, 11b |
| §10 Validation & error handling | Task 5 (validate vars), Task 6 (prefs validate), Task 9 (permission) |
| §11 Testing (unit + integration) | Task 2-11b tests + Task 18 integration |
| §12 Migration plan | Task 1 |
| §15 Workflow | Task 1-19 |

### 2. Placeholder scan

- Task 14 Step 3 placeholder TemplatesTab/HistoryTab — **có chủ đích** (fill ở Task 15/16), không phải TBD.
- Không có "add appropriate error handling" hay "similar to Task N" — mọi code đều hiện đầy đủ.

### 3. Type consistency

- `AlertRuleCreate` schema: `template_code`, `org_id`, `scope_mode`, `recipient_mode`, `config` — khớp model Task 2 + route Task 9.
- `AlertRuleOut.template_name` — route Task 9 populate từ `get_template`.
- `AlertEventOut` fields: `id, rule_id, template_code, machine_id, org_id, severity, title, body, recipient_user_ids, created_at` — khớp model Task 2 + route Task 9b + portal type Task 13.
- `UserNotificationPrefOut` — khớp `get_prefs_with_template` dict keys (template_code, template_name, category, default_severity, opt_out_controls, muted, min_severity).
- `trigger_alert(db, *, template_code, org_id, machine_id, context)` — khớp Task 7, 11, 11b.
- Portal `Toggle` props cần kiểm tra tại thời điểm implement (ghi chú trong Task 15/17) — nếu signature khác, điều chỉnh local, không ảnh hưởng type consistency giữa task.

### 4. Rủi ro còn lại cần lưu ý khi execute

- `create_notification` hiện tạo 1 notification / recipient — alert_engine gọi 1 lần với `recipient_ids` list → đúng.
- `_maybe_deliver_telegram` chạy trong `create_notification` (background) — Task 18 mock `httpx.AsyncClient` cần khớp.
- `visible_org_ids` trả `set[str]` — Task 9 so sánh `str(rule.org_id) in visible` — đúng.
- Test Phase 2 cũ sẽ fail sau Task 3 cho tới Task 11 fix — ghi chú đã có trong Task 3 Step 3.
