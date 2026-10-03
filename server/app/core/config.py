"""Cấu hình ứng dụng — pydantic-settings, đọc từ .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Role read-only inventory của Chat Assistant (T3) — tên cố định, dùng chung
# migration role + suy ra URL pool.
CHAT_RO_DB_USERNAME = "inventory_chat_ro"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def effective_chat_ro_database_url(self) -> str:
        """URL pool chat_ro — override tường minh hoặc suy ra từ `database_url`.

        Dùng SQLAlchemy `make_url` để thay user/password, giữ nguyên mọi thành phần
        khác (kể cả host IPv6 dạng `[::1]`) và percent-encode password an toàn.
        """
        if self.chat_ro_database_url:
            return self.chat_ro_database_url
        from sqlalchemy.engine import make_url

        return (
            make_url(self.database_url)
            .set(username=CHAT_RO_DB_USERNAME, password=self.chat_ro_password)
            .render_as_string(hide_password=False)
        )

    # Môi trường
    app_env: str = "dev"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # DB — PostgreSQL (asyncpg)
    database_url: str = "postgresql+asyncpg://inventory:inventory@localhost:5432/inventory"
    db_echo: bool = False

    # Chat Assistant — pool read-only inventory (T3). Role `inventory_chat_ro`
    # chỉ có SELECT trên view `chat_ro_views`. Nếu `chat_ro_database_url` trống,
    # suy ra từ `database_url` (thay user/password). Password dùng cho migration
    # tạo role (không truyền vào app runtime nếu đã có URL đầy đủ).
    chat_ro_database_url: str | None = None
    chat_ro_password: str = "CHANGE_ME_CHAT_RO"

    # Chat Assistant — capability HS256 ký bởi backend (T4). TÁCH BIỆT với
    # `secret_key` (JWT người dùng): lộ một khoá không kéo theo khoá kia. Chỉ
    # backend giữ; agent chỉ mang token, không bao giờ thấy secret này.
    chat_context_secret: str = Field(
        default="CHANGE_ME_CHAT_CONTEXT_SECRET_000000", min_length=32
    )
    # Service token backend ↔ ChatAgent (T10). Chỉ backend và container chatagent
    # biết; agent gửi qua header `X-Service-Token` cho mọi endpoint nội bộ.
    chat_service_token: str = Field(
        default="CHANGE_ME_CHAT_SERVICE_TOKEN_0000", min_length=16
    )
    # Intent audit chưa có outcome quá ngưỡng này (giây) → reconciler ghi `unknown`.
    audit_outcome_deadline: int = 600
    # Cửa sổ ân hạn cho completion đến muộn sau khi turn đã terminal (T8).
    chat_completion_grace_seconds: int = 120
    # Turn `pending` quá hạn này (không được dispatch) → failed(chat_dispatch_stuck) (T8, F7).
    turn_pending_timeout_seconds: int = 60
    # Khoảng retry bounded khi resolve client_id từ Velociraptor (T7).
    resolver_consistency_window_seconds: int = 5

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

    # Máy offline liên tục quá N ngày (không heartbeat / không upload ZIP mới)
    # → chuyển sang `lost` (máy mất kết nối). Hiển thị trong trang /ghost-machines.
    lost_after_days: int = 15

    # JWT
    secret_key: str = Field(default="CHANGE_ME_PLEASE_OVERRIDE_32_CHARS", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Trusted proxy CIDRs — chỉ tin X-Forwarded-For / X-Real-IP từ các IP này.
    # CSV. Mặc định = các dải private + loopback (an toàn cho dev).
    # Production: thêm IP của nginx/ALB/CDN trước FastAPI.
    trusted_proxy_cidrs: str = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

    # CA / mTLS
    ca_mode: str = "local"  # stepca | local
    step_ca_url: str = "https://ca.internal:8443"
    step_ca_provisioner: str = "admin"
    step_ca_provisioner_password: str = "CHANGE_ME"
    client_cert_valid_days: int = 365

    # Mã hóa dữ liệu nhạy cảm (AES-256-GCM)
    data_encryption_key: str = Field(default="CHANGE_ME_32_CHARS_HEX_VALUE", min_length=16)

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
    # Source agent đã tách repo riêng — build MSI ở repo đó rồi copy vào đây,
    # hoặc set AGENT_RELEASES_BASE để redirect sang GitHub Releases.
    agent_msi_dir: str = "./agent_dist"

    # GitHub Releases của repo agent (org-inventory-agent) — khi set, các route
    # /download/agent* và script cài redirect sang `…/releases/latest/download/<asset>`
    # thay vì đọc file local trong agent_msi_dir. Vd:
    #   https://github.com/lephuhung/org-inventory-agent/releases
    agent_releases_base: str = ""

    # MSI OrgInventory Agent đã được ký Authenticode chưa. False (mặc định) →
    # install command tự nướng `$env:ORGINV_ALLOW_UNSIGNED="1"` để script cài
    # bỏ qua check chữ ký (giai đoạn test). True → command KHÔNG bypass,
    # install script sẽ bắt buộc verify chữ ký Authenticode hợp lệ.
    # Set true sau khi CI release đã cấu hình cert ký MSI.
    agent_msi_signed: bool = False

    # Server RSA Keypair cho giải mã gói offline (mã hóa lai AES-256-GCM + RSA-OAEP)
    server_private_key_path: str = "./data/server_private_key.pem"
    server_public_key_path: str = "./data/server_public_key.pem"

    # ── Dấu thời gian tin cậy cho báo cáo PDF (RFC 3161 / TSA) ──
    # Nhúng Document Timestamp (DocTS) vào PDF khi export → chứng minh báo cáo
    # tồn tại tại thời điểm TSA cấp dấu. Chỉ gửi SHA-256 của file lên TSA,
    # không gửi nội dung báo cáo.
    # - tsa_url: endpoint RFC 3161. Mặc định FreeTSA (dev).
    #   Prod: trỏ về TSA của nhà cung cấp dịch vụ cấp dấu thời gian tin cậy
    #   được cấp phép theo NĐ 23/2025/NĐ-CP (VNPT-CA, BKAV-CA, FPT-CA...)
    #   hoặc TSA nội bộ nếu chỉ cần bằng chứng kỹ thuật.
    # - tsa_username/password: để trống cho TSA public không xác thực.
    report_timestamp_enabled: bool = True
    tsa_url: str = "https://freetsa.org/tsr"
    tsa_timeout_seconds: int = 20
    tsa_username: str = ""
    tsa_password: str = ""

    # Ký số: agent mode (chặn nếu không phải mTLS header hợp lệ)
    require_agent_mtls_header: bool = False  # True khi chạy sau nginx ở prod

    # ── Velociraptor (DFIR) ─────────────────────────────────────
    # Tích hợp Velociraptor Server (https://github.com/velocidex/velociraptor)
    # phục vụ DFIR (Digital Forensics & Incident Response). Backend sync hostname
    # ↔ client_id mỗi VELOCIRAPTOR_SYNC_INTERVAL_SECONDS; portal deep-link sang
    # Velociraptor GUI để admin chạy hunt/collect artifact.
    # - enabled=True: bật toàn bộ (sync + API)
    # - default_url: gợi ý khi admin chưa cấu hình trên portal (vd "https://veloci.example.gov.vn:8889")
    # - sync_interval_seconds: 5 phút (300s) — đủ để theo kịp máy mới enroll
    # - api_timeout_seconds: timeout cho mỗi request HTTP sang Velociraptor
    # - default_allowlist: các artifact Velociraptor MẶC ĐỊNH CHO PHÉP chạy (chống lạm quyền);
    #   admin có thể chỉnh trên portal. Tất cả là artifact read-only, không tốn disk.
    velociraptor_enabled: bool = False
    velociraptor_default_url: str = ""
    velociraptor_sync_interval_seconds: int = 300
    velociraptor_api_timeout_seconds: int = 30
    velociraptor_default_allowlist: list[str] = [
        # Read-only system info (an toàn, thông tin OS/CPU/RAM/disk/network)
        "Generic.Client.Info",
        "Windows.System.Services",
        "Windows.System.Pslist",
        "Windows.Network.Netstat",
        "Windows.Network.NetstatEnriched",
        "Windows.Network.Listeners",
        # Forensics (read-only — dùng cho tính năng Top 10 sự kiện DFIR)
        "Windows.Forensics.Prefetch",
        # Event logs (chỉ đọc, không xoá)
        "Windows.EventLogs.Reboot",
        "Windows.EventLogs.LogFile",
        # Scheduled tasks / startup (read-only)
        "Windows.ScheduledTasks.Catalog",
        "Windows.StartupItems.Persist",
        # Registry (chỉ đọc các key an toàn)
        "Windows.Registry.Recursive",
        "Windows.Registry.System",
        "Windows.Registry.User",
        # Linux (read-only — dùng cho tính năng Top 10 sự kiện DFIR trên Linux)
        "Linux.Sys.Pslist",
        "Linux.Network.NetstatEnriched",
        "Linux.Sys.LastUserLogin",
        # macOS (read-only)
        "MacOS.Sys.Pslist",
        "MacOS.Network.Netstat",
    ]

    # ── LLM (DFIR AI Assistant) ──────────────────────────────
    # Tích hợp Model LLM (Large Language Model) để hỗ trợ phân tích, điều tra
    # sự cố an ninh mạng qua Velociraptor. Mặc định dùng Ollama local (privacy);
    # có thể chuyển sang OpenAI/Qwen/LocalAI/vLLM bằng cách đổi base_url.
    #
    # - enabled: bật/tắt toàn bộ tính năng LLM-DFIR
    # - default_provider: gợi ý khi admin chưa cấu hình (vd 'ollama')
    # - default_base_url: gợi ý URL mặc định
    # - api_timeout_seconds: timeout mỗi request tới LLM
    # - max_context_chars: giới hạn dung lượng log đưa vào prompt (tránh OOM LLM)
    # - daily_token_budget: chặn chi phí cloud (None = unlimited)
    llm_enabled: bool = False
    llm_default_provider: str = "ollama"
    llm_default_base_url: str = "http://127.0.0.1:11434/v1"
    llm_default_model: str = "qwen2.5:14b-instruct-q4_K_M"
    llm_api_timeout_seconds: int = 180
    llm_max_context_chars: int = 200_000
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0
    llm_daily_token_budget: int | None = None
    llm_investigation_interval_seconds: int = 30  # background worker poll job
    # External orchestrator: nếu set, khi investigation collect xong sẽ KHÔNG gọi LLM local,
    # mà chờ external service (Hermes) push kết quả về.
    # Giá trị: "" (mặc định, local LLM) | "hermes" (đợi Hermes callback)
    # API key cần scope `investigation:write` để gọi POST /api/external/llm-dfir/investigations/{id}/result
    llm_external_orchestrator: str = ""
    llm_collect_poll_seconds: int = 10  # poll Velociraptor flow mỗi 10s
    llm_collect_max_wait_seconds: int = 600  # timeout 10 phút cho 1 lần collect
    llm_default_artifacts: list[str] = [
        # Read-only forensics artifacts mặc định cho investigation
        "Windows.System.Pslist",
        "Windows.System.Services",
        "Windows.Network.Netstat",
        "Windows.Network.Listeners",
        "Windows.EventLogs.LogFile",
        "Windows.ScheduledTasks.Catalog",
        "Windows.Persistence.PermanentWMIBackdoor",
        "Windows.Persistence.PermanentRegistry",
        "Windows.Forensics.Prefetch",
        "Windows.Registry.Recursive",
    ]

    # ── DeepAgent LangGraph (external DFIR orchestrator) ───────
    # Khi LlmConfig.external_orchestrator="deepagent", backend dispatch một
    # job có client_id + time range sang service độc lập. Service này tự gọi
    # Velociraptor MCP và callback report Markdown về endpoint external.
    deepagent_enabled: bool = False
    deepagent_url: str = "http://127.0.0.1:8090"
    deepagent_api_key: str = ""
    deepagent_request_timeout_seconds: int = 30
    deepagent_default_lookback_hours: int = 24
    deepagent_max_concurrent_jobs: int = Field(default=12, ge=1, le=12)
    # Age bound cho `dispatch_uncertain`: nếu GET /v1/jobs vẫn transient
    # (5xx/408/429/timeout) sau khoảng này tính từ `started_at` → terminal
    # `reconcile_timeout` để giải phóng capacity slot (không giữ slot vô hạn
    # khi backend unhealthy kéo dài).
    deepagent_reconcile_max_uncertain_seconds: int = Field(default=1800, ge=60)

    # ── Alert delivery (Phase 2) ──────────────────────────────
    # Trống = chưa cấu hình → alert chỉ ghi event + log (delivered=False)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.gov.vn"
    smtp_use_tls: bool = True
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""  # cho deep-link (vd "MyInventoryBot")
    telegram_chat_id: str = ""  # legacy broadcast, dùng notifications thay thế
    telegram_webhook_secret: str = ""  # secret để verify webhook từ Telegram
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
