"""velociraptor client_config — thêm cột lưu YAML mTLS client cert

Revision ID: j9k0l1m2n3o4
Revises: i8j9k0l1m2n3
Create Date: 2026-08-28 12:00:00.000000

Đổi cơ chế auth Inventory Server ↔ Velociraptor Server từ Bearer API key
sang mTLS với client cert (Velociraptor-native, CA-pinned). Admin chạy
`velociraptor config client --name inventory-portal --role administrator`
trong container Velociraptor → được YAML chứa ca_cert + client_cert +
client_private_key → paste vào portal /dfir/settings.

Migration:
- Thêm cột client_config_encrypted (TEXT, AES-256-GCM) vào velociraptor_config.
- GIỮ cột api_token_encrypted (Bearer fallback cho cấu hình cũ — v�n hoạt
  động nếu chưa nâng cấp lên mTLS).
- Thêm cột client_cert_info (JSONB) — metadata cert (subject, expiry, fingerprint)
  để hiển thị trên portal mà KHÔNG lộ private key.

Sau migration, code đọc mTLS trước (client_config_encrypted), fallback Bearer
(api_token_encrypted). Có thể drop cột Bearer sau khi mọi deploy nâng cấp xong.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "j9k0l1m2n3o4"
down_revision = "i8j9k0l1m2n3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "velociraptor_config",
        sa.Column(
            "client_config_encrypted",
            sa.Text(),
            nullable=True,
            comment=(
                "YAML từ `velociraptor config client` (ca_cert + client_cert + "
                "client_private_key) — mã hoá AES-256-GCM. Dùng để mTLS khi gọi "
                "Velociraptor REST API (đối tượng đáng tin = Velociraptor CA)."
            ),
        ),
    )
    op.add_column(
        "velociraptor_config",
        sa.Column(
            "client_cert_info",
            JSONB,
            nullable=True,
            comment=(
                "Metadata client cert (subject, issuer, not_valid_before/after, "
                "sha256_fingerprint). Hiển thị trên portal để admin xác nhận — "
                "KHÔNG chứa private key. NULL nếu chưa cấu hình."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("velociraptor_config", "client_cert_info")
    op.drop_column("velociraptor_config", "client_config_encrypted")
