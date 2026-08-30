#!/usr/bin/env python3
"""Generate .env.example từ Settings class (pydantic-settings).

Dùng để đảm bảo .env.example luôn sync với code (D22, D23 trong spec).
CHẠY khi: thêm setting mới vào config.py.

Usage:
    python3 scripts/gen-env-example.py > .env.example
    python3 scripts/gen-env-example.py --with-secrets > .env  # cho dev local
"""
from __future__ import annotations

import sys
from pathlib import Path

# Thêm server/ vào path để import được app.core.config
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from app.core.config import Settings  # noqa: E402

# Biến secret cần đánh dấu placeholder (KHÔNG in giá trị thật)
SECRET_KEYS = {"secret_key", "data_encryption_key", "step_ca_provisioner_password"}

# Defaults chỉ dành cho Docker Compose, không có trong Settings.
COMPOSE_DEFAULTS = {
    "postgres_user": "inventory",
    "postgres_password": "inventory",
    "postgres_db": "inventory",
    "postgres_port": 5432,
    "redis_port": 6381,
    "api_port": 8000,
    "portal_port": 3003,
}

# Sections trong output (group theo comment trong Settings)
SECTIONS = [
    ("COMPOSE / NETWORK (chỉ docker-compose.yml đọc)", [
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT",
        "REDIS_PORT", "API_PORT", "PORTAL_PORT",
    ]),
    ("SERVER APP — Môi trường", ["APP_ENV", "DEBUG", "HOST", "PORT"]),
    ("SERVER APP — Database / Redis", [
        "DATABASE_URL", "REDIS_URL", "DB_ECHO", "ONLINE_TTL_SECONDS",
    ]),
    ("SERVER APP — Agent heartbeat / inventory", [
        "HEARTBEAT_INTERVAL_SECONDS", "HEARTBEAT_JITTER_SECONDS",
        "INVENTORY_INTERVAL_HOURS", "AGENT_SERVER_URL", "LOST_AFTER_DAYS",
    ]),
    ("SERVER APP — JWT", [
        "SECRET_KEY", "JWT_ALGORITHM",
        "ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_DAYS",
    ]),
    ("SERVER APP — Proxy / CA / Encryption", [
        "TRUSTED_PROXY_CIDRS", "CA_MODE", "STEP_CA_URL",
        "STEP_CA_PROVISIONER", "STEP_CA_PROVISIONER_PASSWORD",
        "CLIENT_CERT_VALID_DAYS", "DATA_ENCRYPTION_KEY",
    ]),
    ("SERVER APP — Admin seed", [
        "SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD", "SEED_ADMIN_FULL_NAME",
    ]),
    ("SERVER APP — Rate limit", ["RATE_LIMIT_ENROLL", "RATE_LIMIT_LOGIN"]),
    ("SERVER APP — Portal", ["PORTAL_URL", "CORS_ORIGINS"]),
    ("SERVER APP — Agent MSI + RSA keys", [
        "AGENT_MSI_DIR", "SERVER_PRIVATE_KEY_PATH", "SERVER_PUBLIC_KEY_PATH",
        "REQUIRE_AGENT_MTLS_HEADER",
    ]),
    ("SERVER APP — Velociraptor (DFIR)", [
        "VELOCIRAPTOR_ENABLED", "VELOCIRAPTOR_DEFAULT_URL",
        "VELOCIRAPTOR_DOCKER_CONTAINER", "VELOCIRAPTOR_SYNC_INTERVAL_SECONDS",
        "VELOCIRAPTOR_API_TIMEOUT_SECONDS", "VELOCIRAPTOR_DEFAULT_ALLOWLIST",
    ]),
    ("SERVER APP — LLM (DFIR AI Assistant)", [
        "LLM_ENABLED", "LLM_DEFAULT_PROVIDER", "LLM_DEFAULT_BASE_URL",
        "LLM_DEFAULT_MODEL", "LLM_API_TIMEOUT_SECONDS", "LLM_MAX_CONTEXT_CHARS",
        "LLM_MAX_TOKENS", "LLM_TEMPERATURE", "LLM_DAILY_TOKEN_BUDGET",
        "LLM_INVESTIGATION_INTERVAL_SECONDS", "LLM_EXTERNAL_ORCHESTRATOR",
        "LLM_COLLECT_POLL_SECONDS", "LLM_COLLECT_MAX_WAIT_SECONDS",
        "LLM_DEFAULT_ARTIFACTS",
    ]),
    ("SERVER APP — Alert delivery (SMTP / Telegram / Zalo)", [
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
        "SMTP_FROM", "SMTP_USE_TLS",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_CHAT_ID",
        "TELEGRAM_WEBHOOK_SECRET", "ZALO_OA_TOKEN",
    ]),
]


def main() -> None:
    out = sys.stdout
    out.write("# ════════════════════════════════════════════════════════════════\n")
    out.write("# AUTO-GENERATED từ server/app/core/config.py::Settings\n")
    out.write("# Regenerate: python3 scripts/gen-env-example.py > .env.example\n")
    out.write("# Đừng sửa tay — sửa Settings rồi chạy lại script.\n")
    out.write("# Copy thành .env rồi sửa các CHANGE_ME_*\n")
    out.write("# ════════════════════════════════════════════════════════════════\n\n")

    # Build map field_name → value, seeding compose-only defaults explicitly.
    values: dict[str, object] = dict(COMPOSE_DEFAULTS)
    for fname, field in Settings.model_fields.items():
        if field.default is None:
            values[fname] = None
        elif field.default.__class__.__name__ == "PydanticUndefined":
            # Không có default → lấy từ class attribute nếu có.
            attr = getattr(Settings, fname, None)
            values[fname] = attr if attr is not None else ""
        else:
            values[fname] = field.default

    # In theo sections
    printed = set()
    for section_index, (title, env_names) in enumerate(SECTIONS):
        out.write(f"# ─── {title} ─{'─' * max(0, 60 - len(title))}\n")
        for env_name in env_names:
            field_name = env_name.lower()
            if field_name not in values:
                continue
            v = values[field_name]
            if env_name.lower() in SECRET_KEYS:
                if isinstance(v, str) and not v.startswith("CHANGE_ME"):
                    out.write(f'{env_name}=CHANGE_ME_generate_with_python_secrets_module\n')
                else:
                    out.write(f'{env_name}={v}\n')
            elif isinstance(v, list):
                # Render list dạng JSON-compatible
                items = ", ".join(f'"{x}"' for x in v)
                out.write(f'{env_name}=[{items}]\n')
            elif v is None:
                # Blank strings do not parse as optional numbers in pydantic-settings.
                out.write(f'# {env_name}=\n')
            elif isinstance(v, bool):
                out.write(f'{env_name}={str(v).lower()}\n')
            else:
                out.write(f'{env_name}={v}\n')
            printed.add(field_name)
        if section_index < len(SECTIONS) - 1:
            out.write("\n")

    # In các biến Settings không nằm trong SECTIONS (cảnh báo nếu có)
    remaining = set(values.keys()) - printed
    if remaining:
        out.write("\n# ─── KHÔNG PHÂN NHÓM (cần thêm vào SECTIONS) ────────────────\n")
        for fname in sorted(remaining):
            out.write(f"# {fname.upper()}={values[fname]}\n")


if __name__ == "__main__":
    main()
