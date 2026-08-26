"""drop org_assign_rules

Revision ID: 9b4c5d6e7f8a
Revises: a8b3c9d1e2f4
Create Date: 2026-08-26 12:30:00.000000

Tính năng #13 (rule tự gán tổ chức theo hostname/IP) đã được loại bỏ vì không
thực tế khi triển khai ở cơ quan: hostname/IP không theo tổ chức, token enroll
đã bind org khi admin cấp (Chế độ B / bulk CSV). Drop bảng org_assign_rules.
"""
from __future__ import annotations

from alembic import op

revision = "9b4c5d6e7f8a"
down_revision = "a8b3c9d1e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("org_assign_rules")


def downgrade() -> None:
    op.create_table(
        "org_assign_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("match_field", sa.String(length=16), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )