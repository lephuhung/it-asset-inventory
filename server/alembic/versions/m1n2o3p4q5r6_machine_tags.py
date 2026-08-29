"""machine tags — tag linh hoạt + phân loại máy (cá nhân / công vụ / BMNN)

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-08-29 12:00:00.000000

Thiết kế (theo yêu cầu: mỗi máy thuộc 1 trong 3 loại — cá nhân / công vụ / BMNN;
BMNN là tập con của công vụ; tag mục đích mở rộng sau KHÔNG ảnh hưởng thống kê):

- `tags`: bảng tag linh hoạt. `kind='classification'` = 3 tag phân loại hệ thống
  (personal / official / bmnn, is_system=true); `kind='purpose'` = tag mục đích
  (dịch vụ công, soạn thảo văn bản…) thêm sau, nhiều tag / máy.
- `machine_tags`: nhiều–nhiều machines ↔ tags. Partial unique index
  (machine_id) WHERE kind='classification' chặn "1 máy tối đa 1 tag phân loại"
  ngay tại DB.
- `enroll_tokens.classification` + `enroll_tokens.purpose_tags`: loại máy chọn
  lúc sinh token → áp cho máy khi enroll.

Backfill dữ liệu hiện có:
- Máy từng được tạo qua import offline (audit `offline.import*`) → tag `bmnn`
  (đây là nguồn BMNN tin cậy — audit log append-only).
- Mọi máy còn lại → tag `official` (mặc định; máy cá nhân do admin gán thủ công).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "m1n2o3p4q5r6"
down_revision = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. tags
    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="purpose"),
        sa.Column("color", sa.String(length=128), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tags_key", "tags", ["key"], unique=True)

    # 2. machine_tags
    op.create_table(
        "machine_tags",
        sa.Column("machine_id", UUID(as_uuid=True), sa.ForeignKey("machines.id"), primary_key=True),
        sa.Column("tag_id", UUID(as_uuid=True), sa.ForeignKey("tags.id"), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("set_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_machine_tags_classification",
        "machine_tags",
        ["machine_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'classification'"),
    )
    op.create_index("ix_machine_tags_tag", "machine_tags", ["tag_id"])

    # 3. enroll_tokens — loại máy + tag mục đích chọn lúc sinh token
    op.add_column("enroll_tokens", sa.Column("classification", sa.String(length=32), nullable=True))
    op.add_column("enroll_tokens", sa.Column("purpose_tags", JSONB, nullable=True))

    # 4. Seed 3 tag phân loại hệ thống
    def _seed(key: str, label: str, color: str, sort: int) -> None:
        bind.execute(
            sa.text(
                "INSERT INTO tags (id, key, label, kind, color, sort_order, is_system) "
                "VALUES (gen_random_uuid(), :key, :label, 'classification', :color, :sort, true) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "label": label, "color": color, "sort": sort},
        )

    _seed("personal", "Máy cá nhân", "bg-sky-50 text-sky-700 ring-sky-600/20", 1)
    _seed("official", "Máy công vụ", "bg-emerald-50 text-emerald-700 ring-emerald-600/20", 2)
    _seed("bmnn", "Máy BMNN", "bg-amber-50 text-amber-700 ring-amber-600/20", 3)

    # 5. Backfill — máy import offline (audit) → bmnn
    bind.execute(
        sa.text(
            """
            INSERT INTO machine_tags (machine_id, tag_id, kind, created_at)
            SELECT DISTINCT al.machine_id, t.id, 'classification', now()
            FROM audit_log al
            JOIN tags t ON t.key = 'bmnn'
            WHERE al.action LIKE 'offline.import%' AND al.machine_id IS NOT NULL
            ON CONFLICT (machine_id, tag_id) DO NOTHING
            """
        )
    )

    # 6. Backfill — mọi máy chưa có tag phân loại → official (mặc định)
    bind.execute(
        sa.text(
            """
            INSERT INTO machine_tags (machine_id, tag_id, kind, created_at)
            SELECT m.id, t.id, 'classification', now()
            FROM machines m
            JOIN tags t ON t.key = 'official'
            WHERE NOT EXISTS (
                SELECT 1 FROM machine_tags mt
                WHERE mt.machine_id = m.id AND mt.kind = 'classification'
            )
            ON CONFLICT (machine_id, tag_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_machine_tags_tag", table_name="machine_tags")
    op.drop_index("uq_machine_tags_classification", table_name="machine_tags")
    op.drop_table("machine_tags")
    op.drop_index("ix_tags_key", table_name="tags")
    op.drop_table("tags")
    op.drop_column("enroll_tokens", "classification")
    op.drop_column("enroll_tokens", "purpose_tags")
