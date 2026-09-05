"""Tests: seed thông báo ban đầu cho người dùng đăng nhập lần đầu."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.routes import auth
from app.db.models import SystemAnnouncement
from app.db.seed_announcements import INITIAL_FIRST_LOGIN_TITLE, seed_first_login_announcement


@pytest.mark.asyncio
async def test_seed_first_login_announcement(db):
    # 1. Đảm bảo đã có SuperAdmin user
    await auth.seed_admin(db, commit=False)

    # 2. Chạy seed announcement lần 1
    await seed_first_login_announcement(db, commit=False)

    ann = (
        await db.execute(
            select(SystemAnnouncement).where(SystemAnnouncement.target_type == "FIRST_LOGIN")
        )
    ).scalars().first()

    assert ann is not None
    assert ann.title == INITIAL_FIRST_LOGIN_TITLE
    assert ann.target_type == "FIRST_LOGIN"
    assert ann.is_active is True
    assert ann.org_id is None  # Toàn bộ hệ thống
    assert "Đổi mật khẩu" in ann.content_md or "đổi mật khẩu" in ann.content_md

    # 3. Idempotent: chạy seed lần 2 không bị trùng lặp
    await seed_first_login_announcement(db, commit=False)

    count = (
        await db.execute(
            select(SystemAnnouncement).where(SystemAnnouncement.target_type == "FIRST_LOGIN")
        )
    ).scalars().all()
    assert len(count) == 1
