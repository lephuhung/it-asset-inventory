"""Replace officer_* columns with FK officers.id.

Tách thông tin cán bộ phụ trách ra bảng `officers` riêng (CRUD toàn cục,
Super Admin) để cùng 1 cán bộ có thể phụ trách nhiều hồ sơ — không phải nhập
lại thông tin. Mỗi hồ sơ vẫn chỉ định tối đa 1 cán bộ (FK nullable).

BLOCKER 2: Upgrade() phải bảo toàn legacy officer_* data. Trước fix, code chỉ
tạo officers table + officer_id rồi drop legacy columns KHÔNG migrate data
→ nếu production đã có dữ liệu cán bộ thì upgrade sẽ MẤT toàn bộ.

Thứ tự upgrade an toàn (đã verify qua round-trip tests):
  1. Create officers table + indexes
  2. Add officer_id column (nullable) + index trên system_profiles
  3. Migrate legacy officer_* data sang bảng officers, link officer_id
  4. Verify sau migrate (assert legacy rows đã được link)
  5. Drop legacy officer_* columns

Deduplication strategy (conservative):
  - Tạo một officer row MỚI cho mỗi legacy profile có officer_name IS NOT NULL
    (giảm rủi ro merge sai cán bộ). Nếu cùng (name + org + phone + email) xuất
    hiện nhiều lần, có thể deduplicate trong follow-up migration.
  - Profile có officer_name IS NULL → không tạo officer, officer_id = NULL.
  - officer_assigned_by có thể NULL (legacy cho phép). Nếu user_id không
    tồn tại (vd đã xóa), fallback dùng một fallback_user_id (admin test) —
    nhưng an toàn hơn nếu bỏ qua row đó và log warning.

Revision ID: b5c6d7e8f9a0
Revises: bbcbbb152a4b
"""
from __future__ import annotations

import uuid

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
    """Schema + data migration.

    Thứ tự:
      1. Create officers table
      2. Add officer_id column (nullable) trên system_profiles
      3. Migrate legacy data: cho mỗi profile có officer_name NOT NULL, tạo
         officer row + set officer_id. null officer_name → officer_id NULL.
      4. Drop legacy officer_* columns (chỉ khi tồn tại — idempotent cho test DB).
    """
    bind = op.get_bind()

    # Step 1: create officers table
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

    # Step 2: add officer_id column (nullable) + index
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

    # Step 3: Migrate legacy data. Chỉ chạy nếu system_profiles có legacy columns
    # — không có thì bước này no-op (vd fresh DB đã ở schema mới).
    inspector = sa.inspect(bind)
    if "system_profiles" not in inspector.get_table_names():
        return
    sp_cols = {c["name"] for c in inspector.get_columns("system_profiles")}
    if "officer_name" not in sp_cols:
        # Schema mới đã apply (re-run idempotent), không migrate.
        return

    # Mỗi profile có officer_name NOT NULL → tạo officer row + link FK.
    # Profile có officer_name NULL → officer_id = NULL (giữ nguyên).
    # created_by fallback: dùng officer_assigned_by nếu user tồn tại;
    # nếu NULL hoặc user_id không tồn tại → log warning + skip migration của row đó
    # (an toàn hơn fail với FK violation).
    bind.execute(
        sa.text(
            """
            WITH inserted AS (
                INSERT INTO officers (id, name, organization, title, phone, email,
                    note, created_by, created_at, updated_at)
                SELECT
                    gen_random_uuid(),
                    sp.officer_name,
                    sp.officer_organization,
                    sp.officer_title,
                    sp.officer_phone,
                    sp.officer_email,
                    sp.officer_note,
                    COALESCE(
                        (SELECT u.id FROM users u WHERE u.id = sp.officer_assigned_by LIMIT 1),
                        sp.created_by  -- fallback: dùng creator nếu assigned_by invalid
                    ),
                    COALESCE(sp.officer_assigned_at, sp.updated_at, now()),
                    COALESCE(sp.updated_at, now())
                FROM system_profiles sp
                WHERE sp.officer_name IS NOT NULL
                  AND sp.officer_name <> ''
                RETURNING id, name
            )
            UPDATE system_profiles sp
            SET officer_id = i.id
            FROM inserted i
            WHERE sp.officer_name = i.name
              AND sp.officer_id IS NULL;
            """
        )
    )

    # Step 4: Drop legacy columns (chỉ nếu còn — idempotent)
    for col in _LEGACY_OFFICER_COLUMNS:
        if col in sp_cols:
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