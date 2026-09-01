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

    # 4. alert_events
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
