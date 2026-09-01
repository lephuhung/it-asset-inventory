# ══════════════════════════════════════════════════════════════════════════
# Server image — build agent Linux TỰ ĐỘNG trong lúc build Docker
# (không cần upload binary lên GitHub / agent_dist).
#
# Stage 1: build OrgInventoryAgent (Linux) — cần .NET 8 SDK
# Stage 2: Python runtime + copy binary đã build
#
# Windows MSI vẫn phải build trên máy Windows (agent/installer/build-msi.ps1)
# — Docker Linux không build được MSI. Copy MSI vào server/agent_dist/ khi
# chuẩn bị deploy Windows.
# ══════════════════════════════════════════════════════════════════════════

# ── Stage 1: build agent Linux ──────────────────────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS agent-builder

WORKDIR /build

# Copy source agent (Core + Linux)
COPY agent/src/OrgInventoryAgent.Core/ ./src/OrgInventoryAgent.Core/
COPY agent/linux/src/OrgInventoryAgent.Linux/ ./linux/src/OrgInventoryAgent.Linux/
COPY agent/Assets/ ./Assets/
COPY agent/Assets/ ./linux/Assets/

# Restore + build Linux agent (linux-x64)
RUN dotnet publish ./linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj \
      -c Release -r linux-x64 --self-contained true \
      -p:PublishSingleFile=true \
      -p:EnableCompressionInSingleFile=false \
      -p:IncludeNativeLibrariesForSelfExtract=false \
      -p:InvariantGlobalization=true \
      -o /build/out/linux-x64

# (tùy chọn) build arm64 nếu cần:
# RUN dotnet publish ./linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj \
#       -c Release -r linux-arm64 --self-contained true \
#       -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=false \
#       -o /build/out/linux-arm64

# ── Stage 2: Python runtime ─────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Agent .NET binary chạy trên python:3.12-slim (không có libicu) → invariant mode
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

# Cài dependency runtime (bám sát pyproject.toml dependencies)
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "email-validator>=2.0.0" \
    "sqlalchemy[asyncio]>=2.0.30" \
    "asyncpg>=0.29.0" \
    "alembic>=1.13.0" \
    "redis>=5.0.0" \
    "pyjwt>=2.8.0" \
    "bcrypt>=4.1.0" \
    "cryptography>=42.0.0" \
    "pyotp>=2.9.0" \
    "jinja2>=3.1.0" \
    "slowapi>=0.1.9" \
    "httpx>=0.27.0" \
    "openpyxl>=3.1.0" \
    "pyyaml>=6.0.0" \
    "grpcio>=1.66.0" \
    "pyvelociraptor>=0.1.11" \
    "python-multipart>=0.0.20"

# Copy toàn bộ server source
COPY server/ ./

# Copy agent binary đã build từ stage 1 vào agent_dist
RUN mkdir -p agent_dist
COPY --from=agent-builder /build/out/linux-x64/OrgInventoryAgent ./agent_dist/OrgInventoryAgent-linux-x64
RUN chmod 0755 agent_dist/OrgInventoryAgent-linux-x64

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]