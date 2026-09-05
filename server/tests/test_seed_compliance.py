"""Tests: seed thông báo tuân thủ quy định bảo vệ dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.routes import auth
from app.db.models import ComplianceNotice
from app.db.seed_compliance import (
    INITIAL_COMPLIANCE_TITLE,
    INITIAL_COMPLIANCE_VERSION,
    seed_compliance_notice,
)


@pytest.mark.asyncio
async def test_seed_compliance_notice(db):
    # 1. Đảm bảo đã có SuperAdmin user
    await auth.seed_admin(db, commit=False)

    # 2. Chạy seed compliance notice lần 1
    await seed_compliance_notice(db, commit=False)

    notice = (
        await db.execute(
            select(ComplianceNotice).where(ComplianceNotice.version == INITIAL_COMPLIANCE_VERSION)
        )
    ).scalars().first()

    assert notice is not None
    assert notice.title == INITIAL_COMPLIANCE_TITLE
    assert notice.version == "1.0"
    assert notice.status == "active"
    
    # 5 nội dung cốt lõi:
    # 1. Phạm vi thu thập và xử lý dữ liệu (Số điện thoại, Nơi công tác)
    assert "Phạm vi thu thập và xử lý dữ liệu" in notice.content_md
    assert "Số điện thoại" in notice.content_md
    assert "Nơi công tác của cá nhân" in notice.content_md

    # 2. Mục đích và cách thức xử lý (hiển thị/vận hành danh bạ, cam kết không sử dụng cho mục đích khác)
    assert "Mục đích và cách thức xử lý dữ liệu" in notice.content_md
    assert "danh bạ" in notice.content_md
    assert "cam kết không sử dụng dữ liệu cho bất kỳ mục đích nào khác" in notice.content_md

    # 3. Thời hạn lưu trữ và bảo mật dữ liệu (giới hạn theo mục đích, bảo vệ kỹ thuật chống thất thoát/rò rỉ)
    assert "Thời hạn lưu trữ và bảo mật dữ liệu" in notice.content_md
    assert "giới hạn theo mục đích" in notice.content_md
    assert "AES-256" in notice.content_md

    # 4. Quyền và nghĩa vụ của người dùng (rút lại sự đồng ý, yêu cầu chỉnh sửa hoặc xóa dữ liệu)
    assert "Quyền và nghĩa vụ của người dùng" in notice.content_md
    assert "Rút lại sự đồng ý" in notice.content_md
    assert "yêu cầu chỉnh sửa" in notice.content_md
    assert "yêu cầu xóa dữ liệu" in notice.content_md

    # 5. Đầu mối liên hệ giải quyết (Email, Hotline)
    assert "Đầu mối liên hệ giải quyết" in notice.content_md
    assert "Email tiếp nhận" in notice.content_md
    assert "Hotline" in notice.content_md

    # 3. Idempotent: chạy seed lần 2 không bị trùng lặp
    await seed_compliance_notice(db, commit=False)

    count = (
        await db.execute(
            select(ComplianceNotice).where(ComplianceNotice.version == INITIAL_COMPLIANCE_VERSION)
        )
    ).scalars().all()
    assert len(count) == 1
