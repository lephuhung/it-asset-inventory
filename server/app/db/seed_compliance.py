"""Seed dữ liệu thông báo tuân thủ quy định bảo vệ dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP).

Gồm 5 nội dung cốt lõi:
1. Phạm vi thu thập và xử lý dữ liệu (Dữ liệu cá nhân cơ bản: SĐT, Nơi công tác)
2. Mục đích và cách thức xử lý (Vận hành danh bạ trên website, cam kết không dùng cho mục đích khác)
3. Thời hạn lưu trữ và bảo mật dữ liệu (Giới hạn theo mục đích, mã hóa và bảo vệ kỹ thuật chống rò rỉ)
4. Quyền và nghĩa vụ của người dùng (Chủ thể dữ liệu: rút lại đồng ý, yêu cầu sửa/xóa dữ liệu)
5. Đầu mối liên hệ giải quyết (Kênh tiếp nhận Email, Hotline)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ComplianceNotice, NoticeStatus, User, UserRole

logger = logging.getLogger(__name__)

INITIAL_COMPLIANCE_TITLE = "Thông báo Tuân thủ Quy định Bảo vệ Dữ liệu Cá nhân"
INITIAL_COMPLIANCE_VERSION = "1.0"

INITIAL_COMPLIANCE_CONTENT = """# THÔNG BÁO TUÂN THỦ QUY ĐỊNH BẢO VỆ DỮ LIỆU CÁ NHÂN
*(Ban hành theo Nghị định số 13/2023/NĐ-CP của Chính phủ về bảo vệ dữ liệu cá nhân)*

Hệ thống Quản lý Tài sản Máy tính & Cổng thông tin nội bộ cam kết bảo vệ dữ liệu cá nhân và tuân thủ các quy định pháp luật hiện hành của Việt Nam, đặc biệt là **Nghị định 13/2023/NĐ-CP**, Luật An toàn thông tin mạng 2015 và Luật An ninh mạng 2018.

---

### 1. Phạm vi thu thập và xử lý dữ liệu
- **Phân loại dữ liệu**: Hệ thống chỉ thu thập và xử lý các **Dữ liệu cá nhân cơ bản** (theo Điều 2 Khoản 3 Nghị định 13/2023/NĐ-CP) thực sự cần thiết phục vụ quản lý, vận hành danh bạ và tài sản công vụ:
  - **Họ và tên**: Định danh cán bộ, nhân sự sử dụng hoặc được bàn giao thiết bị.
  - **Số điện thoại**: Số điện thoại liên hệ công tác của cá nhân.
  - **Nơi công tác của cá nhân**: Đơn vị công tác, cơ quan, phòng ban và chức danh / vị trí công tác.
  - **Thông tin thiết bị công tác liên kết**: Tên máy tính (Hostname), địa chỉ IP, cấu hình kỹ thuật phần cứng (CPU, RAM, Ổ cứng) và trạng thái trực tuyến.
- **Cam kết KHÔNG thu thập**: Tuyệt đối **không thu thập dữ liệu cá nhân nhạy cảm** (vị trí định vị thời gian thực cá nhân, thông tin tài khoản ngân hàng, sinh trắc học cá nhân, nội dung tin nhắn riêng tư, lịch sử duyệt web hay thao tác bàn phím cá nhân).

---

### 2. Mục đích và cách thức xử lý dữ liệu
- **Mục đích xử lý**:
  - Quản trị, hiển thị và vận hành danh bạ cán bộ, nhân sự phụ trách thiết bị công nghệ thông tin trên website / cổng quản trị.
  - Đối soát tài sản máy tính công, hỗ trợ kỹ thuật, kịp thời xử lý sự cố an toàn thông tin và bảo vệ hệ thống công vụ.
- **Cách thức xử lý**:
  - Dữ liệu được tiếp nhận trực tiếp từ người dùng hoặc qua quy trình cấp phát token đăng ký từ ban quản trị đơn vị.
  - Lưu trữ trong cơ sở dữ liệu nội bộ được bảo vệ nghiêm ngặt và chỉ hiển thị trong phạm vi phân quyền công vụ.
- **Cam kết sử dụng đúng mục đích**:
  - Hệ thống **cam kết không sử dụng dữ liệu cho bất kỳ mục đích nào khác** ngoài các mục đích công vụ đã quy định nếu chưa được sự đồng ý của chủ thể dữ liệu.
  - Tuyệt đối không chuyển giao, chia sẻ, mua bán hoặc cung cấp dữ liệu cho bất kỳ bên thứ ba nào vì mục đích thương mại hoặc quảng cáo.

---

### 3. Thời hạn lưu trữ và bảo mật dữ liệu
- **Thời hạn lưu trữ**:
  - Cam kết thời hạn lưu trữ được giới hạn theo mục đích xử lý: Chỉ lưu trữ trong suốt thời gian cá nhân còn công tác tại đơn vị hoặc còn chịu trách nhiệm quản trị/sử dụng tài sản trên hệ thống.
  - Khi cá nhân chuyển công tác, chấm dứt nhiệm vụ hoặc có yêu cầu xóa hợp lệ, dữ liệu sẽ được tiến hành xóa bỏ an toàn hoặc ẩn danh hóa vĩnh viễn.
- **Biện pháp kỹ thuật bảo vệ chống thất thoát, rò rỉ dữ liệu**:
  - **Mã hóa at-rest**: Số điện thoại và dữ liệu nhạy cảm được mã hóa tự động bằng thuật toán **AES-256-GCM** trước khi ghi vào cơ sở dữ liệu.
  - **Mã hóa đường truyền**: Toàn bộ lưu lượng truy cập web và kết nối máy trạm được bảo vệ bằng HTTPS / TLS 1.3 và xác thực chứng chỉ số (mTLS).
  - **Xác thực đa yếu tố & Phân quyền**: Bắt buộc xác thực hai yếu tố (2FA / TOTP) đối với tài khoản quản trị; kiểm soát quyền truy cập theo vai trò (RBAC) theo nguyên tắc đặc quyền tối thiểu.
  - **Nhật ký kiểm toán chống chối bỏ (Audit Log)**: Ghi nhật ký mọi truy cập, chỉnh sửa dữ liệu vào sổ cái append-only theo chuỗi băm (hash chain) không thể chỉnh sửa hay tẩy xóa.
  - **Phòng chống thất thoát dữ liệu (DLP) & Sao lưu**: Hệ thống tự động phát hiện bất thường, sao lưu dữ liệu mã hóa định kỳ và có kế hoạch ứng phó sự cố an ninh thông tin.

---

### 4. Quyền và nghĩa vụ của người dùng (Chủ thể dữ liệu)
- **Quyền hợp pháp của người dùng theo Nghị định 13/2023/NĐ-CP**:
  - **Quyền được biết**: Được thông báo rõ ràng, minh bạch về mọi hoạt động thu thập và xử lý dữ liệu cá nhân của mình.
  - **Quyền đồng ý & Rút lại sự đồng ý**: Người dùng có quyền đồng ý hoặc rút lại sự đồng ý cho phép xử lý dữ liệu bất kỳ lúc nào.
  - **Quyền truy cập & Xem**: Có quyền tra cứu, xem các thông tin cá nhân của mình đang được hệ thống quản lý.
  - **Quyền yêu cầu chỉnh sửa**: Có quyền yêu cầu ban quản trị cập nhật, sửa đổi khi phát hiện dữ liệu cá nhân bị sai lệch hoặc thay đổi nơi công tác.
  - **Quyền yêu cầu xóa dữ liệu**: Có quyền yêu cầu xóa hoặc hạn chế xử lý dữ liệu cá nhân của mình theo quy định pháp luật.
  - **Quyền khiếu nại, phản ánh**: Có quyền gửi khiếu nại hoặc phản ánh đến cơ quan quản lý khi nghi ngờ có vi phạm an toàn dữ liệu.
- **Nghĩa vụ của người dùng**:
  - Cung cấp thông tin trung thực, chính xác và kịp thời báo cáo khi có thay đổi thông tin liên hệ / nơi công tác.
  - Bảo quản tài khoản đăng nhập cá nhân; nghiêm cấm việc thu thập, khai thác trái phép dữ liệu của cá nhân khác trên hệ thống.

---

### 5. Đầu mối liên hệ giải quyết & Tiếp nhận yêu cầu
Mọi yêu cầu thực hiện quyền bảo vệ dữ liệu cá nhân (rút lại đồng ý, yêu cầu xem, chỉnh sửa hoặc xóa dữ liệu) được tiếp nhận và xử lý qua các kênh chính thức sau:
- **Email tiếp nhận**: `compliance@example.gov.vn` *(hoặc `privacy@gov.vn`)*
- **Hotline hỗ trợ**: `1900 xxxx` / `0239.xxx.xxxx` (Hỗ trợ trong giờ hành chính từ Thứ 2 đến Thứ 6)
- **Đơn vị tiếp nhận**: Bộ phận Quản trị Hệ thống & An toàn thông tin
- **Thời hạn giải quyết**: Cam kết xác nhận tiếp nhận và xử lý yêu cầu hợp lệ của chủ thể dữ liệu trong thời hạn tối đa không quá **72 giờ** làm việc.
"""


async def seed_compliance_notice(db: AsyncSession, *, commit: bool = True) -> None:
    """Tạo bản thông báo tuân thủ mặc định ban đầu nếu chưa có bản nào."""
    # Kiểm tra xem đã có bản thông báo tuân thủ nào chưa
    existing = (
        await db.execute(
            select(ComplianceNotice).where(
                (ComplianceNotice.version == INITIAL_COMPLIANCE_VERSION)
                | (ComplianceNotice.title == INITIAL_COMPLIANCE_TITLE)
            )
        )
    ).scalars().first()

    if existing:
        logger.info("✓ Initial compliance notice already exists.")
        return

    # Tìm user SuperAdmin / Admin để gắn tác giả
    creator = (
        await db.execute(
            select(User).where(
                (User.email == settings.seed_admin_email)
                | (User.role.in_([UserRole.SUPER_ADMIN.value, UserRole.ADMIN_GLOBAL.value]))
            )
        )
    ).scalars().first()

    if not creator:
        logger.warning("No Admin user found to seed initial compliance notice.")
        return

    now = datetime.now(UTC)
    notice = ComplianceNotice(
        version=INITIAL_COMPLIANCE_VERSION,
        title=INITIAL_COMPLIANCE_TITLE,
        content_md=INITIAL_COMPLIANCE_CONTENT.strip(),
        effective_from=now,
        status=NoticeStatus.ACTIVE.value,
        created_by=creator.id,
        created_at=now,
    )
    db.add(notice)

    if commit:
        await db.commit()

    logger.info("✓ Successfully seeded initial compliance notice.")
