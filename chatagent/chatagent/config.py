"""Cấu hình ChatAgent — CHỈ đọc biến môi trường `CHATAGENT_*` (spec F5).

**Không** khai `env_file`: container chatagent không được nạp root `.env` (chứa
`DATABASE_URL`, `SECRET_KEY`, `DATA_ENCRYPTION_KEY`). Compose truyền tường minh
các biến `CHATAGENT_*` (T16). Đây là ranh giới cô lập môi trường, không phải
service identity (`inventory-net` chỉ là reachability).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHATAGENT_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8091

    # Service token backend ↔ agent (spec "Ranh giới tin cậy"). Agent không tự
    # khai `actor_id`; actor lấy từ capability backend phát.
    service_token: str = "CHANGE_ME_service_token"
    backend_url: str = "http://127.0.0.1:8000"
    backend_api_key: str = ""

    # Trần thực thi per-turn (spec F11 admission control).
    chat_timeout_seconds: int = Field(default=120, ge=1)
    max_tool_calls: int = Field(default=12, ge=1)
    max_evidence_chars: int = Field(default=120_000, ge=1)
    wall_clock_seconds: int = Field(default=300, ge=1)

    # Egress: mặc định fail-closed cho endpoint LLM private (spec R7).
    egress_allow_cloud: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
