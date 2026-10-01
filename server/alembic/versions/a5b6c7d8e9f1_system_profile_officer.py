"""Add officer (cán bộ phụ trách / đầu mối SuperAdmin) columns on system_profiles.

Cán bộ phụ trách là đầu mối liên hệ SuperAdmin chỉ định cho 1 hồ sơ cấp độ,
đại diện cho một tổ chức bên ngoài hệ thống (không thuộc cây tổ chức). Mỗi hồ sơ
tối đa 1 cán bộ; chỉ Super Admin mới có quyền thêm/sửa/gỡ.

Revision ID: a5b6c7d8e9f1
Revises: z4a5b6c7d8e9
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a5b6c7d8e9f1"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_profiles",
        sa.Column("officer_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_organization", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_phone", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column("officer_assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_profiles",
        sa.Column(
            "officer_assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("system_profiles", "officer_assigned_by")
    op.drop_column("system_profiles", "officer_assigned_at")
    op.drop_column("system_profiles", "officer_note")
    op.drop_column("system_profiles", "officer_email")
    op.drop_column("system_profiles", "officer_phone")
    op.drop_column("system_profiles", "officer_title")
    op.drop_column("system_profiles", "officer_organization")
    op.drop_column("system_profiles", "officer_name")
