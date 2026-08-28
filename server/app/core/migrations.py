"""Kiểm tra migration đã áp dụng đầy đủ chưa — fail-fast khi khởi động.

Lý do: nếu code mới query cột mới (vd `portal_url`) mà migration chưa chạy
→ mọi request trả 500 với `UndefinedColumnError` từ Postgres. Khó debug + downtime
lâu vì lỗi chỉ xuất hiện ở runtime, sau khi server đã nhận traffic.

Check ngay lúc startup → phát hiện sớm, thông báo rõ cách fix, server từ chối
phục vụ request cho đến khi admin chạy `alembic upgrade head`.

Bỏ qua trong APP_ENV=test (conftest tự tạo schema bằng `Base.metadata.create_all`,
không qua alembic nên revision trong `alembic_version` không tồn tại).
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Tên file alembic.ini cùng thư mục với source — không phụ thuộc CWD khi deploy.
_ALEMBIC_INI = str(Path(__file__).resolve().parents[2] / "alembic.ini")


async def assert_schema_at_head(engine: AsyncEngine) -> None:
    """So sánh revision hiện tại trong DB với `head` trong alembic/versions/.

    Raise `RuntimeError` với thông báo rõ nếu DB thiếu migration → lifespan sẽ
    fail-fast, server không start được (không phục vụ request).

    Args: `engine` — async engine đã cấu hình (vd `app.db.session.engine`).
    """
    cfg = Config(_ALEMBIC_INI)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    def _read_current(sync_conn) -> str | None:
        """Chạy trong sync context (run_sync bên dưới)."""
        ctx = MigrationContext.configure(sync_conn)
        return ctx.get_current_revision()

    async with engine.connect() as conn:
        current = await conn.run_sync(_read_current)

    if current == head:
        logger.info("✓ DB schema at head (revision=%s)", head)
        return

    # Không đụng tới bảng `alembic_version` → migration thực sự chưa chạy.
    # (Không liệt kê chi tiết revision vì merge heads làm phả hệ tuyến tính —
    # chỉ cần gợi ý chạy `alembic upgrade head` là đủ.)
    raise RuntimeError(
        "\n[DB MIGRATION] Schema chưa được cập nhật — server từ chối khởi động.\n"
        f"  Revision hiện tại: {current or '(trống — chưa chạy migration lần nào)'}\n"
        f"  Revision cần đến:  {head}\n"
        f"  → Chạy:\n"
        f"      cd server && alembic upgrade head\n"
        f"  → Sau đó restart server.\n"
        f"  → Trong môi trường test, đặt APP_ENV=test để bỏ qua check."
    )