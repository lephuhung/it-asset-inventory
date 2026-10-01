"""Seed thêm các loại thiết bị/node phổ biến (website, LB, AP, printer...).

Bổ sung catalog device_types ngoài 8 loại chuẩn ban đầu. Idempotent:
ON CONFLICT (code) DO NOTHING — không ghi đè loại Super Admin đã tự tạo/sửa.

Revision ID: d8e9f0a1b2c4
Revises: c7d8e9f0a1b3
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "d8e9f0a1b2c4"
down_revision = "c7d8e9f0a1b3"
branch_labels = None
depends_on = None

EXTRA_DEVICE_TYPES: list[tuple[str, str, str]] = [
    ("website", "Website / Web app", "🌐"),
    ("load_balancer", "Load Balancer", "⚖️"),
    ("access_point", "Access Point (Wi-Fi)", "📶"),
    ("printer", "Máy in", "🖨️"),
    ("camera", "Camera giám sát", "📷"),
    ("ip_phone", "Điện thoại IP", "☎️"),
]


def upgrade() -> None:
    conn = op.get_bind()
    # sort_order tiếp tục sau loại có sort_order lớn nhất hiện có
    max_order = conn.execute(sa.text("SELECT COALESCE(MAX(sort_order), -1) FROM device_types")).scalar() or 0
    for i, (code, label, icon) in enumerate(EXTRA_DEVICE_TYPES):
        conn.execute(
            sa.text(
                "INSERT INTO device_types (id, code, label, icon, sort_order, is_active) "
                "VALUES (:id, :code, :label, :icon, :i, true) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(id=uuid.uuid4(), code=code, label=label, icon=icon, i=max_order + 1 + i)
        )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _, _ in EXTRA_DEVICE_TYPES)
    op.execute(f"DELETE FROM device_types WHERE code IN ({codes})")
