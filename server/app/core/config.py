"""Cấu hình ứng dụng — pydantic-settings, đọc từ .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Môi trường
    app_env: str = "dev"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # DB — PostgreSQL (asyncpg)
    database_url: str = "postgresql+asyncpg://inventory:inventory@localhost:5432/inventory"
    db_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    # online_ttl: None → tự tính = 2 × (heartbeat_interval + jitter) (mục 5.2: online = heartbeat ≤ 2× chu kỳ)
    online_ttl_seconds: int | None = None

    # ── Agent heartbeat / inventory (server điều chỉnh, agent đồng bộ) ──
    # Agent gửi heartbeat ngẫu nhiên trong [interval-jitter, interval+jitter]
    # (v1.2: chu kỳ cơ sở 30s, jitter ±25% ≈ 22–38s — cập nhật online nhanh hơn).
    heartbeat_interval_seconds: int = 30
    heartbeat_jitter_seconds: int = 8
    # Agent gửi lại inventory đầy đủ định kỳ (mục 3.4: định kỳ 24h)
    inventory_interval_hours: int = 24
    # URL công khai agent dùng cho kênh mTLS (nginx agent block) — khác portal_url
    agent_server_url: str = "https://agent.example.gov.vn"

    # JWT
    secret_key: str = Field(default="CHANGE_ME", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CA / mTLS
    ca_mode: str = "local"  # stepca | local
    step_ca_url: str = "https://ca.internal:8443"
    step_ca_provisioner: str = "admin"
    step_ca_provisioner_password: str = "CHANGE_ME"
    client_cert_valid_days: int = 365

    # Mã hóa dữ liệu nhạy cảm (AES-256-GCM)
    data_encryption_key: str = Field(default="CHANGE_ME", min_length=16)

    # Seed admin
    seed_admin_email: str = "admin@example.gov.vn"
    seed_admin_password: str = "ChangeMe!123"
    seed_admin_full_name: str = "Quản trị viên hệ thống"

    # Rate limit
    rate_limit_enroll: str = "30/minute"
    rate_limit_login: str = "10/minute"

    # Portal
    portal_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Agent installer artifacts (phục vụ /download/agent.msi + /download/agent.msi.sha256).
    # Đặt OrgInventoryAgent.msi + OrgInventoryAgent.msi.sha256 vào thư mục này (cùng cấp).
    # Có thể trỏ tới `agent/publish/win-x64/` sau khi build MSI trên Windows.
    agent_msi_dir: str = "./agent_dist"

    # Server RSA Keypair cho giải mã gói offline (mã hóa lai AES-256-GCM + RSA-OAEP)
    server_private_key_path: str = "./data/server_private_key.pem"
    server_public_key_path: str = "./data/server_public_key.pem"

    # Ký số: agent mode (chặn nếu không phải mTLS header hợp lệ)
    require_agent_mtls_header: bool = False  # True khi chạy sau nginx ở prod

    # ── Alert delivery (Phase 2) ──────────────────────────────
    # Trống = chưa cấu hình → alert chỉ ghi event + log (delivered=False)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.gov.vn"
    smtp_use_tls: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    zalo_oa_token: str = ""

    @property
    def effective_online_ttl_seconds(self) -> int:
        """Online TTL hiệu dụng: explicit override hoặc 2 × (interval + jitter)."""
        if self.online_ttl_seconds is not None:
            return self.online_ttl_seconds
        return 2 * (self.heartbeat_interval_seconds + self.heartbeat_jitter_seconds)

    def agent_config_payload(self) -> dict:
        """Cấu hình agent mà server đang áp dụng — trả về qua heartbeat + /api/agent/config.

        Nhất quán giữa các nơi trả (tránh agent lấy 2 nguồn lệch nhau).
        """
        return {
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "heartbeat_jitter_seconds": self.heartbeat_jitter_seconds,
            "online_ttl_seconds": self.effective_online_ttl_seconds,
            "inventory_interval_hours": self.inventory_interval_hours,
            "renew_before_percent": 70,  # gia hạn cert khi còn 70% vòng đời (mục 7.1)
        }

    @field_validator("data_encryption_key")
    @classmethod
    def _validate_enc_key_hex(cls, v: str) -> str:
        if v.startswith("CHANGE_ME"):
            return v
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
