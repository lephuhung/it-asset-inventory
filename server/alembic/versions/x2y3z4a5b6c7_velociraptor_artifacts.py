"""Bảng velociraptor_artifacts — artifact Custom.* do Super Admin nạp lên Velociraptor.

DB là source of truth để re-push khi server Velociraptor được dựng lại.
`definition_yaml` không bao giờ xuất hiện trong log/audit.

Revision ID: x2y3z4a5b6c7
Revises: w1x2y3z4a5b6
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "x2y3z4a5b6c7"
down_revision = "w1x2y3z4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "velociraptor_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("definition_yaml", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False, server_default="CLIENT"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_push_status", sa.String(16), nullable=True),
        sa.Column("last_push_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_velociraptor_artifacts_name"),
    )
    op.create_index("ix_velociraptor_artifacts_name", "velociraptor_artifacts", ["name"])


def downgrade() -> None:
    op.drop_index("ix_velociraptor_artifacts_name", table_name="velociraptor_artifacts")
    op.drop_table("velociraptor_artifacts")
