"""Telegram bot runtime — đọc cấu hình từ DB (do Super Admin cấu hình) với fallback env.

Trước đây các giá trị `telegram_bot_token`, `telegram_bot_username`,
`telegram_webhook_secret` chỉ được đọc từ `Settings` (env). Nay Super Admin
có thể set trên portal tại `/admin/telegram-bot`. Service layer dưới đây
cung cấp:

- `get_bot_config(db)`: trả về dict gồm `bot_token`, `bot_username`,
  `webhook_secret`, `enabled`, `source` ("db" | "env" | "none"). DB được ưu tiên,
  fallback env. Cache trong process để không truy vấn mỗi lần gửi notification.
- `invalidate_bot_cache()`: xoá cache (gọi sau khi Super Admin update).
- `BotConfigView`: dataclass trả cho caller, đã giải mã `bot_token` /
  `webhook_secret` từ AES-256-GCM (chỉ tồn tại trong memory).

Token KHÔNG được log ra ngoài để tránh lộ. Các hàm gửi notification (trong
`services/notifications.py`) và xử lý webhook (trong `api/routes/notifications.py`)
gọi qua module này thay vì đọc `settings.telegram_*` trực tiếp.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_aes_gcm
from app.db.models import TelegramBotConfig

logger = logging.getLogger("telegram_runtime")

# Cache trong process: { mtime: float, snapshot: BotConfigView }
_CACHE: dict[str, Any] = {}
_CACHE_TTL_SECONDS = 5.0  # cache 5s — vừa giảm query, vừa không "delay" update lâu


@dataclass(frozen=True)
class BotConfigView:
    bot_token: str | None
    bot_username: str | None
    webhook_secret: str | None
    enabled: bool
    source: str  # "db" | "env" | "none"

    @property
    def is_configured(self) -> bool:
        """Bot đã sẵn sàng gửi message + nhận webhook."""
        return bool(self.bot_token and self.bot_username)

    @property
    def can_send(self) -> bool:
        """Bot có thể gửi notification đi (cần token + enabled)."""
        return self.enabled and bool(self.bot_token)

    @property
    def bot_username_clean(self) -> str:
        """Username bot không có ký tự '@' ở đầu (dùng cho deep-link)."""
        if not self.bot_username:
            return ""
        return self.bot_username.lstrip("@")


def invalidate_bot_cache() -> None:
    """Xoá cache — gọi ngay sau khi Super Admin PUT config mới."""
    _CACHE.clear()


def _decrypt_or_none(value: str | None) -> str | None:
    """Giải mã AES-GCM. Trả None nếu input None hoặc lỗi (log warning)."""
    if value is None:
        return None
    try:
        return decrypt_aes_gcm(value)
    except Exception as e:  # noqa: BLE001
        logger.warning("Không giải mã được telegram bot config: %s", e)
        return None


async def get_bot_config(db: AsyncSession) -> BotConfigView:
    """Đọc config từ DB với cache 5s; fallback env nếu DB chưa có row.

    Bot token KHÔNG bao giờ log ra ngoài (chỉ trả về cho caller).
    """
    now = time.monotonic()
    snap = _CACHE.get("snapshot")
    mtime = _CACHE.get("mtime", 0.0)
    if snap is not None and (now - mtime) < _CACHE_TTL_SECONDS:
        return snap  # type: ignore[return-value]

    db_row: TelegramBotConfig | None = None
    try:
        db_row = (await db.execute(
            select(TelegramBotConfig).where(TelegramBotConfig.id == 1)
        )).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001
        logger.debug("Không đọc được telegram_bot_config (bảng chưa migrate?): %s", e)

    if db_row is not None:
        bot_token = _decrypt_or_none(db_row.bot_token_encrypted)
        bot_username = db_row.bot_username
        webhook_secret = db_row.webhook_secret  # dùng đối chiếu, không cần mã hoá
        enabled = db_row.enabled
        source = "db"
    else:
        bot_token = settings.telegram_bot_token or None
        bot_username = settings.telegram_bot_username or None
        webhook_secret = settings.telegram_webhook_secret or None
        enabled = True
        source = "env" if (bot_token or bot_username or webhook_secret) else "none"

    snap = BotConfigView(
        bot_token=bot_token,
        bot_username=bot_username,
        webhook_secret=webhook_secret,
        enabled=enabled,
        source=source,
    )
    _CACHE["snapshot"] = snap
    _CACHE["mtime"] = now
    return snap