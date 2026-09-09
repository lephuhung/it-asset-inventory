"""Replace officer_* columns with FK officers.id.

Tách thông tin cán bộ phụ trách ra bảng `officers` riêng (CRUD toàn cục,
Super Admin) để cùng 1 cán bộ có thể phụ trách nhiều hồ sơ — không phải nhập
lại thông tin. Mỗi hồ sơ vẫn chỉ định tối đa 1 cán bộ (FK nullable).

Revision ID: b5c6d7e8f9a0
Revises: bbcbbb152a4b
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b5c6d7e8f9a0"
down_revision = "bbcbbb152a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "officers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_officers_name", "officers", ["name"])

    op.add_column(
        "system_profiles",
        sa.Column(
            "officer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("officers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_system_profiles_officer_id", "system_profiles", ["officer_id"])

    # Xóa các cột officer_* cũ (nếu migration trước đã chạy thật).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_profiles" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("system_profiles")}
        for col in (
            "officer_name",
            "officer_organization",
            "officer_title",
            "officer_phone",
            "officer_email",
            "officer_note",
            "officer_assigned_at",
            "officer_assigned_by",
        ):
            if col in cols:
                op.drop_column("system_profiles", col)


def downgrade() -> None:
    op.drop_index("ix_system_profiles_officer_id", table_name="system_profiles")
    op.drop_column("system_profiles", "officer_id")
    op.drop_index("ix_officers_name", table_name="officers")
    op.drop_table("officers")
