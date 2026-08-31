"""add dfir_investigation_requests table

Revision ID: 87c54eca9b35
Revises: fc38e39dd494
Create Date: 2026-08-31 04:35:49.561314
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '87c54eca9b35'
down_revision = 'fc38e39dd494'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dfir_investigation_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('machine_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('machines.id'), nullable=False),
        sa.Column('artifact', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('urgency', sa.String(length=16), server_default='normal', nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('requested_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('velociraptor_flow_id', sa.String(length=64), nullable=True),
        sa.Column('velociraptor_url', sa.String(length=512), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_dfir_requests_status_created', 'dfir_investigation_requests', ['status', 'created_at'])
    op.create_index('ix_dfir_investigation_requests_machine_id', 'dfir_investigation_requests', ['machine_id'])
    op.create_index('ix_dfir_investigation_requests_status', 'dfir_investigation_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_dfir_investigation_requests_status', table_name='dfir_investigation_requests')
    op.drop_index('ix_dfir_investigation_requests_machine_id', table_name='dfir_investigation_requests')
    op.drop_index('ix_dfir_requests_status_created', table_name='dfir_investigation_requests')
    op.drop_table('dfir_investigation_requests')
