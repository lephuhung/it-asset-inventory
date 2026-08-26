"""alert rules, events, self-service links, org assign rules

Revision ID: 70786f173f6e
Revises: b3e1a2c4d5f6
Create Date: 2026-08-25 13:28:13.526940

Chỉ tạo 4 bảng mới (Phase 2: alert rules + events, self-service links, org assign rules).
KHÔNG đụng vào bảng heartbeats (partition) — autogenerate nhầm lẫn partition
nên phần heartbeat đã được loại bỏ thủ công.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '70786f173f6e'
down_revision = 'b3e1a2c4d5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('alert_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('rule_type', sa.String(length=32), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('threshold_days', sa.Integer(), nullable=True),
    sa.Column('channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notify_targets', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('org_assign_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('match_field', sa.String(length=16), nullable=False),
    sa.Column('pattern', sa.String(length=255), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('self_service_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_self_service_links_code'), 'self_service_links', ['code'], unique=True)
    op.create_table('alert_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('rule_id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=True),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('delivered', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], ),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rule_id', 'machine_id', 'fingerprint', name='uq_alert_event')
    )


def downgrade() -> None:
    op.drop_table('alert_events')
    op.drop_index(op.f('ix_self_service_links_code'), table_name='self_service_links')
    op.drop_table('self_service_links')
    op.drop_table('org_assign_rules')
    op.drop_table('alert_rules')
