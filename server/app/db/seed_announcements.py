"""Seed dữ liệu thông báo ban đầu dạng Modal dành cho người dùng đăng nhập lần đầu."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SystemAnnouncement, User, UserRole

logger = logging.getLogger(__name__)

INITIAL_FIRST_LOGIN_TITLE = "Chào mừng đến với Hệ thống Quản lý Tài sản Máy tính"

INITIAL_FIRST_LOGIN_CONTENT = """# Chào mừng bạn đến với Hệ thống Quản lý Tài sản Máy tính

Hệ thống giúp bạn theo dõi thông tin tài sản máy tính, cấu hình phần cứng, phần mềm và đảm bảo an toàn an ninh thông tin trong toàn cơ quan, đơn vị.

---

### 🌟 Các Tính Năng Cốt Lõi Của Hệ Thống

1. **Quản lý & Giám sát máy tính (`/machines`)**:
   - Tự động kiểm kê phần cứng: CPU, RAM, Dung lượng ổ cứng, Card mạng, Mainboard.
   - Thống kê danh mục phần mềm đã cài đặt trên từng máy tính, phát hiện thay đổi bất thường.
   - Theo dõi trạng thái hoạt động trực tuyến/ngoại tuyến (online/offline) và địa chỉ IP kết nối.

2. **Báo cáo & Thống kê chuyên sâu (`/reports` & `/inventory-stats`)**:
   - Báo cáo tổng hợp số lượng và phân loại máy tính theo từng đơn vị, phòng ban.
   - Xuất dữ liệu kiểm kê phục vụ công tác quản lý tài sản số và thanh quyết toán thiết bị.
   - Cảnh báo các thiết bị chạy hệ điều hành hết hạn hỗ trợ (Windows 10/7 EOL).

3. **Bảo mật & Điều tra sự cố (`/security` & `/dfir`)**:
   - Tự động ghi nhận biến động cấu hình thiết bị (Drift detection).
   - Hỗ trợ công cụ điều tra sự cố số và truy vết mã độc.

4. **Tuân thủ quy định bảo vệ dữ liệu (`/compliance`)**:
   - Minh bạch việc thu thập thông tin kỹ thuật phục vụ quản lý thiết bị công.
   - Tuân thủ quy chuẩn an toàn thông tin và Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.

---

### ⚠️ Lưu Ý Quan Trọng Về Bảo Mật Tài Khoản

> **Khuyến cáo đổi mật khẩu**:
> Nếu bạn vừa đăng nhập bằng mật khẩu mặc định hoặc mật khẩu được cấp ban đầu, vui lòng **thay đổi mật khẩu ngay** tại mục **Bảo mật tài khoản** (`/security`).
> 
> - Mật khẩu mới cần tối thiểu 8 ký tự, bao gồm chữ in hoa, chữ thường, số và ký tự đặc biệt.
> - Tuyệt đối không chia sẻ tài khoản hoặc mật khẩu với người khác.
"""


async def seed_first_login_announcement(db: AsyncSession, *, commit: bool = True) -> None:
    """Tạo 1 thông báo Modal mặc định cho người dùng đăng nhập lần đầu nếu chưa có."""
    # Kiểm tra xem đã có thông báo chào mừng lần đầu nào chưa
    existing = (
        await db.execute(
            select(SystemAnnouncement).where(
                (SystemAnnouncement.target_type == "FIRST_LOGIN")
                | (SystemAnnouncement.title == INITIAL_FIRST_LOGIN_TITLE)
            )
        )
    ).scalars().first()

    if existing:
        logger.info("✓ Initial first-login announcement already exists.")
        return

    # Tìm user SuperAdmin để gắn quyền người tạo
    creator = (
        await db.execute(
            select(User).where(
                (User.email == settings.seed_admin_email)
                | (User.role.in_([UserRole.SUPER_ADMIN.value, UserRole.ADMIN_GLOBAL.value]))
            )
        )
    ).scalars().first()

    if not creator:
        logger.warning("No SuperAdmin user found to seed initial announcement.")
        return

    ann = SystemAnnouncement(
        title=INITIAL_FIRST_LOGIN_TITLE,
        content_md=INITIAL_FIRST_LOGIN_CONTENT.strip(),
        target_type="FIRST_LOGIN",
        target_role=None,
        org_id=None,  # Áp dụng cho tất cả đơn vị
        is_active=True,
        created_by=creator.id,
        created_at=datetime.now(UTC),
    )
    db.add(ann)

    if commit:
        await db.commit()

    logger.info("✓ Successfully seeded initial first-login announcement.")
