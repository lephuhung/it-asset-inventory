# 02 — Settings cấu hình LLM trong hệ thống (Code)

> File này hướng dẫn chính xác vị trí cần sửa / thêm trong codebase hiện tại.

---

## A. Sửa `server/app/core/config.py`

Thêm block cấu hình LLM ngay sau block Velociraptor (cuối class `Settings`):

```python
    # ── LLM (DFIR AI Assistant) ──────────────────────────────
    # Tích hợp Model LLM (Large Language Model) để hỗ trợ phân tích, điều tra
    # sự cố an ninh mạng qua Velociraptor. Mặc định dùng Ollama local (privacy);
    # có thể chuyển sang OpenAI/Qwen/LocalAI/vLLM bằng cách đổi base_url.
    #
    # - enabled: bật/tắt toàn bộ tính năng LLM-DFIR
    # - default_provider: gợi ý khi admin chưa cấu hình (vd 'ollama')
    # - default_base_url: gợi ý URL mặc định
    # - api_timeout_seconds: timeout mỗi request tới LLM (LLaMA-14B chậm ~30s)
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
    llm_daily_token_budget: int | None = None  # None = unlimited
    llm_investigation_interval_seconds: int = 30  # background worker poll job
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
```

Không quên update `model_config` để support list env var cho `llm_default_artifacts` (pydantic-settings mặc định đã hỗ trợ JSON list).

---

## B. Sửa `server/.env.example`

```bash
# ── LLM (DFIR AI Assistant) ──────────────────────────────────
# Tích hợp Model LLM (Ollama / OpenAI / Qwen / vLLM) để phân tích log Velociraptor.
# Mặc định dùng Ollama local — dữ liệu điều tra KHÔNG rời máy (privacy-first).
# Khi muốn dùng cloud (OpenAI/Qwen), đổi base_url + điền api_key trên portal.
#
# - ENABLED: bật toàn bộ tính năng
# - DEFAULT_PROVIDER: ollama|openai|localai|vllm|custom
# - DEFAULT_BASE_URL: OpenAI-compatible endpoint
# - DEFAULT_MODEL: tên model đã pull sẵn (vd qwen2.5:14b-instruct-q4_K_M)
# - API_TIMEOUT_SECONDS=180: LLaMA-14B có thể chậm ~30-60s cho 4K output
# - MAX_CONTEXT_CHARS=200000: giới hạn log đưa vào 1 prompt (tránh OOM)
# - DAILY_TOKEN_BUDGET: chặn chi phí cloud (vd 1000000 = ~$0.50 với GPT-4o-mini)
# - INVESTIGATION_INTERVAL_SECONDS=30: background worker poll job pending
# - COLLECT_POLL_SECONDS=10: poll Velociraptor flow mỗi 10s
# - DEFAULT_ARTIFACTS: JSON list artifact mặc định dùng cho investigation
LLM_ENABLED=false
LLM_DEFAULT_PROVIDER=ollama
LLM_DEFAULT_BASE_URL=http://127.0.0.1:11434/v1
LLM_DEFAULT_MODEL=qwen2.5:14b-instruct-q4_K_M
LLM_API_TIMEOUT_SECONDS=180
LLM_MAX_CONTEXT_CHARS=200000
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.0
LLM_DAILY_TOKEN_BUDGET=
LLM_INVESTIGATION_INTERVAL_SECONDS=30
LLM_COLLECT_POLL_SECONDS=10
LLM_COLLECT_MAX_WAIT_SECONDS=600
LLM_DEFAULT_ARTIFACTS=["Windows.System.Pslist","Windows.System.Services","Windows.Network.Netstat","Windows.Network.Listeners","Windows.EventLogs.LogFile","Windows.ScheduledTasks.Catalog","Windows.Persistence.PermanentWMIBackdoor","Windows.Persistence.PermanentRegistry","Windows.Forensics.Prefetch","Windows.Registry.Recursive"]
```

---

## C. Thêm models vào `server/app/db/models.py`

Thêm 3 class mới ngay sau class `VelociraptorConfig` (khoảng line 590+):

```python
class LlmConfig(Base):
    """Cấu hình LLM backend — singleton (id=1), Super Admin cấu hình trên portal.

    Mặc định: Ollama local (http://127.0.0.1:11434/v1) — privacy-first.
    Có thể đổi sang OpenAI/Qwen/LocalAI/vLLM bằng cách đổi base_url.

    OpenAI-compatible API → 1 client duy nhất xử lý mọi backend.
    `api_key_encrypted` AES-256-GCM (None nếu Ollama local).
    """

    __tablename__ = "llm_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), default="ollama")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), default=0.0)
    request_timeout: Mapped[int] = mapped_column(Integer, default=120)
    max_context_chars: Mapped[int] = mapped_column(Integer, default=200_000)
    allow_cloud: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used_today: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ok|error|untested
    test_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), onupdate=datetime.now(UTC))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DfirInvestigation(Base):
    """Mỗi lần admin trigger 'Điều tra AI' 1 máy → 1 row.

    Lifecycle:
      pending → running → collecting → analyzing → completed
                                       ↘ failed / timeout

    - `artifacts`: list artifact Velociraptor đã collect
    - `report_markdown`: báo cáo cuối cùng từ LLM (tiếng Việt)
    - `severity`: critical|high|medium|low|info — LLM tự đánh giá
    - `raw_artifacts`: JSON thu thập từ Velociraptor (audit + cho Q&A tiếp)
    """

    __tablename__ = "dfir_investigations"
    __table_args__ = (Index("ix_dfir_investigations_machine_id", "machine_id"),
                      Index("ix_dfir_investigations_status", "status"),
                      Index("ix_dfir_investigations_created_at", "created_at"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    velociraptor_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hunt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifacts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    findings_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_artifacts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class DfirInvestigationMessage(Base):
    """Chat Q&A với LLM về 1 cuộc điều tra.

    System message (chứa raw data + initial prompt) lưu row đầu tiên.
    Mỗi lượt user/assistant lưu 1 row tiếp theo.
    `ON DELETE CASCADE` → xoá investigation là xoá luôn chat history.
    """

    __tablename__ = "dfir_investigation_messages"
    __table_args__ = (Index("ix_dfir_investigation_messages_investigation_id", "investigation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dfir_investigations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system|user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)
```

Cần import thêm: `Numeric` từ `sqlalchemy` (nếu chưa có).

---

## D. Tạo Alembic migration `server/alembic/versions/n2o3p4q5r6s7_llm_dfir.py`

```python
"""LLM-DFIR — bảng cấu hình LLM + investigation + chat messages.

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-08-29 16:00:00.000000

Tạo 3 bảng mới phục vụ tích hợp Model LLM (Ollama/OpenAI-compatible) để
phân tích, điều tra sự cố an ninh mạng qua Velociraptor:

- `llm_config` (singleton, id=1): URL + provider + model + API key (mã hoá).
- `dfir_investigations`: mỗi lần admin trigger điều tra 1 máy → 1 row.
- `dfir_investigation_messages`: chat Q&A với LLM về cuộc điều tra.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. llm_config — singleton
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(32), nullable=False, server_default="ollama"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("fallback_model", sa.String(128), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="4096"),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=False, server_default="0.0"),
        sa.Column("request_timeout", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("max_context_chars", sa.Integer(), nullable=False, server_default="200000"),
        sa.Column("allow_cloud", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("daily_token_budget", sa.Integer(), nullable=True),
        sa.Column("tokens_used_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_status", sa.String(32), nullable=True),
        sa.Column("test_error", sa.Text(), nullable=True),
        sa.Column("test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )

    # Seed default row (id=1) — disabled, pointing to local Ollama
    op.execute(
        """
        INSERT INTO llm_config (id, enabled, provider, base_url, model)
        VALUES (1, false, 'ollama', 'http://127.0.0.1:11434/v1', 'qwen2.5:14b-instruct-q4_K_M')
        ON CONFLICT (id) DO NOTHING
        """
    )

    # 2. dfir_investigations
    op.create_table(
        "dfir_investigations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("machine_id", UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("velociraptor_client_id", sa.String(64), nullable=True),
        sa.Column("hunt_id", sa.String(64), nullable=True),
        sa.Column("flow_id", sa.String(64), nullable=True),
        sa.Column("artifacts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("llm_provider", sa.String(32), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("findings_count", sa.Integer(), nullable=True),
        sa.Column("raw_artifacts", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_dfir_investigations_machine_id", "dfir_investigations", ["machine_id"])
    op.create_index("ix_dfir_investigations_velociraptor_client_id", "dfir_investigations", ["velociraptor_client_id"])
    op.create_index("ix_dfir_investigations_status", "dfir_investigations", ["status"])
    op.create_index("ix_dfir_investigations_created_at", "dfir_investigations", ["created_at"])

    # 3. dfir_investigation_messages
    op.create_table(
        "dfir_investigation_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "investigation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dfir_investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_dfir_investigation_messages_investigation_id",
        "dfir_investigation_messages",
        ["investigation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dfir_investigation_messages_investigation_id", table_name="dfir_investigation_messages")
    op.drop_table("dfir_investigation_messages")

    op.drop_index("ix_dfir_investigations_created_at", table_name="dfir_investigations")
    op.drop_index("ix_dfir_investigations_status", table_name="dfir_investigations")
    op.drop_index("ix_dfir_investigations_velociraptor_client_id", table_name="dfir_investigations")
    op.drop_index("ix_dfir_investigations_machine_id", table_name="dfir_investigations")
    op.drop_table("dfir_investigations")

    op.drop_table("llm_config")
```

Sau khi tạo file:
```bash
cd server && alembic upgrade head
```

---

## E. Thêm Pydantic schemas vào `server/app/schemas/__init__.py`

Thêm vào cuối file:

```python
# ── LLM-DFIR ──────────────────────────────────────────────────────


class LlmConfigOut(BaseModel):
    enabled: bool
    provider: str
    base_url: str
    api_key_masked: str  # "oll-***xyz" hoặc "(không đặt)"
    model: str
    fallback_model: str | None
    system_prompt: str | None
    max_tokens: int
    temperature: float
    request_timeout: int
    max_context_chars: int
    allow_cloud: bool
    daily_token_budget: int | None
    tokens_used_today: int
    test_status: str | None
    test_error: str | None
    test_at: datetime | None
    updated_at: datetime
    available_models: list[str] = []  # trả thêm từ /models endpoint


class LlmConfigUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # null = giữ nguyên; "" = xoá
    model: str | None = None
    fallback_model: str | None = None
    system_prompt: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    request_timeout: int | None = None
    max_context_chars: int | None = None
    allow_cloud: bool | None = None
    daily_token_budget: int | None = None


class LlmTestConnectionOut(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str]
    error: str | None = None


class DfirInvestigationCreate(BaseModel):
    machine_id: uuid.UUID
    artifacts: list[str] | None = None  # None = dùng default
    custom_instructions: str | None = None  # tuỳ chọn, ví dụ "Tập trung vào ransomware"


class DfirInvestigationOut(BaseModel):
    id: uuid.UUID
    machine_id: uuid.UUID
    machine_hostname: str | None = None
    status: str
    artifacts: list[str]
    llm_provider: str | None
    llm_model: str | None
    severity: str | None
    findings_count: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    error: str | None
    report_markdown: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    requested_by: uuid.UUID
    requested_by_name: str | None = None


class DfirInvestigationMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tokens: int | None
    created_at: datetime


class DfirInvestigationChatIn(BaseModel):
    message: str
```

---
