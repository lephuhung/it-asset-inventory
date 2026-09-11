"""Replace officer_* columns with FK officers.id.

Tách thông tin cán bộ phụ trách ra bảng `officers` riêng (CRUD toàn cục,
Super Admin) để cùng 1 cán bộ có thể phụ trách nhiều hồ sơ — không phải nhập
lại thông tin. Mỗi hồ sơ vẫn chỉ định tối đa 1 cán bộ (FK nullable).

Revision ID: b5c6d7e8f9a0
Revises: bbcbbb152a4b
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "bbcbbb152a4b"
branch_labels = None
depends_on = None


# Các cột legacy được khôi phục khi downgrade — phải khớp với migration
# `a5b6c7d8e9f1_system_profile_officer` (down_revision trước merge).
_LEGACY_OFFICER_COLUMNS = (
    "officer_name",
    "officer_organization",
    "officer_title",
    "officer_phone",
    "officer_email",
    "officer_note",
    "officer_assigned_at",
    "officer_assigned_by",
)


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
        for col in _LEGACY_OFFICER_COLUMNS:
            if col in cols:
                op.drop_column("system_profiles", col)


def downgrade() -> None:
    """Khôi phục schema của revision trước (`bbcbbb152a4b`).

    Alembic invariant: `downgrade()` phải tạo schema tương ứng với revision
    `bbcbbb152a4b` — tức là khôi phục lại các cột `officer_*` đã được
    `a5b6c7d8e9f1` thêm vào (và giữ nguyên qua merge). Nếu bảng `officers`
    còn dữ liệu, cố gắng migrate data trở lại trước khi drop.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    system_profile_cols = (
        {c["name"] for c in inspector.get_columns("system_profiles")}
        if "system_profiles" in inspector.get_table_names()
        else set()
    )
    has_officers_table = "officers" in inspector.get_table_names()

    # 1. Khôi phục các cột legacy trên system_profiles
    if "officer_name" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_name", sa.String(length=255), nullable=True),
        )
    if "officer_organization" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_organization", sa.String(length=255), nullable=True),
        )
    if "officer_title" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_title", sa.String(length=255), nullable=True),
        )
    if "officer_phone" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_phone", sa.String(length=32), nullable=True),
        )
    if "officer_email" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_email", sa.String(length=255), nullable=True),
        )
    if "officer_note" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_note", sa.Text(), nullable=True),
        )
    if "officer_assigned_at" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column("officer_assigned_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "officer_assigned_by" not in system_profile_cols:
        op.add_column(
            "system_profiles",
            sa.Column(
                "officer_assigned_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
        )

    # 2. Best-effort: migrate data từ bảng `officers` về các cột legacy
    # (qua JOIN với officer_id). Nếu thiếu bảng officers / officer_id thì bỏ qua.
    if has_officers_table and "officer_id" in system_profile_cols:
        op.execute(
            """
            UPDATE system_profiles sp
            SET
                officer_name = o.name,
                officer_organization = o.organization,
                officer_title = o.title,
                officer_phone = o.phone,
                officer_email = o.email,
                officer_note = o.note,
                officer_assigned_at = o.created_at,
                officer_assigned_by = o.created_by
            FROM officers o
            WHERE sp.officer_id = o.id
            """
        )

    # 3. Drop FK officer_id + index trên system_profiles
    if "officer_id" in system_profile_cols:
        if "ix_system_profiles_officer_id" in {
            ix["name"] for ix in inspector.get_indexes("system_profiles")
        }:
            op.drop_index("ix_system_profiles_officer_id", table_name="system_profiles")
        op.drop_column("system_profiles", "officer_id")

    # 4. Drop bảng officers + index
    if has_officers_table:
        op.drop_index("ix_officers_name", table_name="officers")
        op.drop_table("officers")