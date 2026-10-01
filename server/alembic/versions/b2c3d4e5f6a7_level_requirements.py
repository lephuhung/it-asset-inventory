"""Add level_requirements + system_profile_requirements tables (seed catalog).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None

# Catalog yêu cầu mẫu theo cấp độ — đơn vị/Super Admin chỉnh sửa sau.
# Nghĩa chung: cấp càng cao yêu cầu càng khắt khe.
SEED_REQUIREMENTS: list[tuple[int, str, str, str]] = [
    # Cấp 1
    (1, "L1-PHANQUYEN", "Phân quyền truy cập", "Tài khoản sử dụng phân quyền tối thiểu, có danh sách người dùng và quyền hạn."),
    (1, "L1-MATKHAU", "Chính sách mật khẩu", "Mật khẩu tối thiểu 8 ký tự, thay đổi định kỳ, không dùng chung tài khoản."),
    (1, "L1-CAPNHAT", "Cập nhật bản vá", "Hệ điều hành, phần mềm được cập nhật bản vá bảo mật định kỳ."),
    (1, "L1-ANTIVIRUS", "Phần mềm chống mã độc", "Máy tính trong hệ thống cài phần mềm chống mã độc, cập nhật cơ sở dữ liệu."),
    (1, "L1-SAO_LUU", "Sao lưu dữ liệu", "Dữ liệu quan trọng được sao lưu định kỳ và kiểm tra khôi phục."),
    # Cấp 2
    (2, "L2-FIREWALL", "Firewall biên giới", "Triển khai thiết bị lọc biên giới, chỉ mở cổng dịch vụ cần thiết."),
    (2, "L2-GHICHEP", "Ghi log hệ thống", "Ghi log hoạt động của hệ thống và người dùng, lưu trữ tối thiểu 6 tháng."),
    (2, "L2-QUANTRIMANG", "Quản trị tập trung", "Có công cụ quản trị, giám sát tập trung thiết bị trong hệ thống."),
    (2, "L2-PHUCOIKHANCAP", "Phục hồi khẩn cấp", "Có phương án sự cố và phục hồi khẩn cấp đã được phê duyệt, diễn tập định kỳ."),
    (2, "L2-DANHGIADINHKY", "Đánh giá an toàn định kỳ", "Thực hiện đánh giá an toàn hệ thống thông tin định kỳ ít nhất 1 lần/năm."),
    # Cấp 3
    (3, "L3-MTLS", "Xác thực đa yếu tố", "Áp dụng xác thực nhiều yếu tố cho tài khoản quản trị và truy cập từ xa."),
    (3, "L3-MAHOA", "Mã hóa dữ liệu", "Mã hóa dữ liệu quan trọng khi lưu trữ và truyền dẫn."),
    (3, "L3-IDPS", "Giám sát tấn công", "Triển khai hệ thống phát hiện/ngăn chặn xâm nhập, giám sát 24/7."),
    (3, "L3-KIEMTHU_ANTOAN", "Kiểm thử an toàn", "Kiểm thử xâm nhập (pentest) định kỳ và khắc phục kịp thời phát hiện."),
    (3, "L3-VATLY", "Bảo vệ vật lý", "Phòng thiết bị có kiểm soát ra vào, môi trường (điện, nhiệt, cháy nổ) được bảo đảm."),
    (3, "L3-NGUOILUC", "Nhân lực an toàn thông tin", "Có cán bộ chuyên trách an toàn thông tin, được đào tạo nghiệp vụ định kỳ."),
]


def upgrade() -> None:
    op.create_table(
        "level_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("level", sa.Integer(), nullable=False, index=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_level_requirements_level"),
    )
    op.create_table(
        "system_profile_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("system_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("level_requirements.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("profile_id", "requirement_id", name="uq_profile_requirement"),
    )
    # Seed catalog yêu cầu mẫu
    for level, code, title, description in SEED_REQUIREMENTS:
        op.execute(
            sa.text(
                "INSERT INTO level_requirements (id, level, code, title, description, sort_order, is_active) "
                "VALUES (:id, :level, :code, :title, :description, 0, true)"
            ).bindparams(id=uuid.uuid4(), level=level, code=code, title=title, description=description)
        )


def downgrade() -> None:
    op.drop_table("system_profile_requirements")
    op.drop_table("level_requirements")
