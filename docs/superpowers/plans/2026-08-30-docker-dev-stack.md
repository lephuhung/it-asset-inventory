# Docker Dev Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize server (FastAPI) + portal (Next.js) vào một master `docker-compose.yml` ở root, với hot reload cho dev workflow, thay thế việc chạy `uvicorn` / `next dev` trực tiếp.

**Architecture:** Một master compose ở root orchestrate 4 services (postgres + redis + api + portal). Hot reload qua volume-mount source code + dev servers (`uvicorn --reload` / `next dev`). Velociraptor/step-ca/nginx tách ngoài stack (sau này dùng Nginx Proxy Manager bên ngoài).

**Tech Stack:** Docker Compose v2, Python 3.12-slim, Node 20-alpine, pnpm (qua corepack), FastAPI + uvicorn, Next.js 16.

**Spec:** `/home/windowsId/docs/superpowers/specs/2026-08-30-docker-dev-stack-design.md`

---

## Global Constraints

Từ spec §2 (Goals/Non-goals) và §3 (Decisions):

- Cổng cố định: **api 8000, portal 3003, postgres 5432, redis 6381** (giữ nguyên hiện tại).
- Một file `.env` ở **root**, commit `.env.example`, KHÔNG commit `.env`.
- `DATABASE_URL` / `REDIS_URL` trong `.env` giữ `localhost` (compose override bằng docker DNS).
- CORS_ORIGINS = `["http://localhost:3003", "http://10.10.0.241:3003"]`.
- `CA_MODE=local` cho dev (không cần step-ca container).
- `.env.example` phải bao gồm **TẤT CẢ** settings từ `server/app/core/config.py::Settings` (D22).
- Postgres + Redis có healthcheck; `api` chờ `postgres` + `redis` healthy trước khi start.
- Mount pattern: whole-bind `./server:/app:ro` + named volumes cho `pgdata`, `redisdata`, `portal_node_modules`, `portal_next`.
- `agent_dist/` mount `./server/agent_dist:/data/artifacts:ro` để serve `/download/...`.
- File cũ xoá ở Task 8: `server/Dockerfile`, `server/deploy/docker-compose.yml`, `server/.env`, `server/.env.example`.
- Giữ: `server/deploy/nginx/nginx.conf` (tham khảo), `build-all.sh` (fallback), `agent/`, `deploy/velociraptor/`, `deploy/step-ca/`.

---

## Task Structure

| # | Task | Deliverable |
|---|---|---|
| 1 | Foundation files (root config) | `.env.example`, `.env`, `.dockerignore`, helper script |
| 2 | server/Dockerfile.dev | Build image standalone thành công |
| 3 | portal/Dockerfile.dev | Build image standalone thành công |
| 4 | docker-compose.yml (postgres + redis) | Stack infra chạy được, healthcheck pass |
| 5 | Add api service to compose | api container chạy, alembic OK, /docs trả 200 |
| 6 | Add portal service to compose | portal container chạy, / trả 200 |
| 7 | Verify hot reload | Sửa file → container reload |
| 8 | Cleanup old files | Stack vẫn chạy sau khi xoá file cũ |
| 9 | Update README | Section "Phát triển với Docker" có mặt |

---

### Task 1: Foundation files — `.env.example`, `.env`, `.dockerignore`, helper script

**Files:**
- Create: `/scripts/gen-env-example.py` (helper generate `.env.example` từ `Settings` class)
- Create: `/.env.example` (output của script)
- Create: `/.env` (copy từ `.env.example` rồi capture values từ `server/.env` cũ)
- Create: `/.dockerignore`

**Interfaces:**
- Produces: `/.env.example` (committed), `/.env` (gitignored, có secrets thật + values từ `server/.env`)

- [ ] **Step 1: Tạo thư mục scripts (nếu chưa có)**

```bash
mkdir -p /home/windowsId/scripts
```

- [ ] **Step 2: Tạo helper script `gen-env-example.py`**

File: `/home/windowsId/scripts/gen-env-example.py`

```python
#!/usr/bin/env python3
"""Generate .env.example từ Settings class (pydantic-settings).

Dùng để đảm bảo .env.example luôn sync với code (D22, D23 trong spec).
CHẠY khi: thêm setting mới vào config.py.

Usage:
    python3 scripts/gen-env-example.py > .env.example
    python3 scripts/gen-env-example.py --with-secrets > .env  # cho dev local
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

# Thêm server/ vào path để import được app.core.config
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from app.core.config import Settings  # noqa: E402

# Biến secret cần đánh dấu placeholder (KHÔNG in giá trị thật)
SECRET_KEYS = {"secret_key", "data_encryption_key", "step_ca_provisioner_password"}

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

    # Build map field_name → value
    values: dict[str, object] = {}
    for fname, field in Settings.model_fields.items():
        if field.default is None or field.default.__class__.__name__ == "PydanticUndefined":
            # Default = None hoặc không có → lấy từ class attribute
            attr = getattr(Settings, fname, None)
            values[fname] = attr if attr is not None else ""
        else:
            values[fname] = field.default

    # In theo sections
    printed = set()
    for title, env_names in SECTIONS:
        out.write(f"# ─── {title} ─{'─' * max(0, 60 - len(title))}\n")
        for env_name in env_names:
            field_name = env_name.lower()
            if field_name not in values:
                continue  # section có thể có biến không có trong Settings (compose-only)
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
                out.write(f'{env_name}=\n')
            elif isinstance(v, bool):
                out.write(f'{env_name}={str(v).lower()}\n')
            else:
                out.write(f'{env_name}={v}\n')
            printed.add(field_name)
        out.write("\n")

    # In các biến Settings không nằm trong SECTIONS (cảnh báo nếu có)
    remaining = set(values.keys()) - printed
    if remaining:
        out.write("# ─── KHÔNG PHÂN NHÓM (cần thêm vào SECTIONS) ────────────────\n")
        for fname in sorted(remaining):
            out.write(f"# {fname.upper()}={values[fname]}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate `.env.example`**

```bash
cd /home/windowsId
python3 scripts/gen-env-example.py > .env.example
```

Verify:
```bash
test -f /home/windowsId/.env.example && echo "OK: file exists"
head -20 /home/windowsId/.env.example
wc -l /home/windowsId/.env.example   # nên ~80-100 dòng
grep -E "^(SECRET_KEY|DATA_ENCRYPTION_KEY|LOST_AFTER_DAYS|PORTAL_URL|CORS_ORIGINS|API_PORT|PORTAL_PORT)=" .env.example
```

Expected output: file tồn tại, có ≥80 dòng, có đủ các biến trên.

- [ ] **Step 4: Copy `.env.example` → `.env`, sau đó capture values từ `server/.env` cũ**

Lý do: user đang có `LOST_AFTER_DAYS=15`, `ONLINE_TTL_SECONDS=180`, `AGENT_SERVER_URL=http://10.10.0.241:8000`, `CORS_ORIGINS` mở rộng — phải giữ lại.

```bash
cd /home/windowsId
cp .env.example .env

# Áp dụng các override từ server/.env cũ (nếu biến đang set)
grep -v '^#\|^$' server/.env | while IFS='=' read -r key val; do
  if grep -qE "^${key}=" .env; then
    # Escape value nếu có ký tự đặc biệt
    sed -i "s|^${key}=.*|${key}=${val}|" .env
    echo "  Updated: $key"
  fi
done

echo "--- Final .env ---"
cat .env
```

Verify:
```bash
grep -E "^(LOST_AFTER_DAYS|ONLINE_TTL_SECONDS|AGENT_SERVER_URL)=" .env
grep -E "^CORS_ORIGINS=" .env
```

Expected:
- `LOST_AFTER_DAYS=15`
- `ONLINE_TTL_SECONDS=180`
- `AGENT_SERVER_URL=http://10.10.0.241:8000`
- `CORS_ORIGINS=["http://localhost:3003", "http://10.10.0.241:3003"]` (giá trị mới từ spec, không phải từ .env cũ)

- [ ] **Step 5: Generate secrets mới cho `.env`**

```bash
cd /home/windowsId

# Tạo SECRET_KEY mới
NEW_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_SECRET_KEY}|" .env

# Tạo DATA_ENCRYPTION_KEY mới (hex 32 chars)
NEW_DATA_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s|^DATA_ENCRYPTION_KEY=.*|DATA_ENCRYPTION_KEY=${NEW_DATA_KEY}|" .env

# Verify không còn placeholder
grep -E "^(SECRET_KEY|DATA_ENCRYPTION_KEY)=" .env
```

Expected: cả hai dòng không chứa `CHANGE_ME`.

- [ ] **Step 6: Tạo `/.dockerignore`**

File: `/home/windowsId/.dockerignore`

```
.git
.github
.venv
.next
node_modules
.pnpm-store
.pytest_cache
.ruff_cache
*.log
.DS_Store
docs
logo-output
agent
deploy
server/deploy
portal/stitch-ref
portal/stitch_*.py
portal/Design.md
portal/AGENTS.md
portal/CLAUDE.md
.env
.env.local
```

- [ ] **Step 7: Verify `.gitignore` đã exclude `.env`**

```bash
grep -E "^\.env$|^\*\.env$" /home/windowsId/.gitignore
git status --short
```

Expected: `/.gitignore` có dòng `.env` (đã có sẵn ở root .gitignore). `git status` KHÔNG liệt kê `.env` (chỉ liệt kê `.env.example`).

- [ ] **Step 8: Commit**

```bash
cd /home/windowsId
git add scripts/gen-env-example.py .env.example .dockerignore
git status
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): foundation - .env.example (auto-gen) + .dockerignore

- scripts/gen-env-example.py introspect Settings → .env.example
  (đảm bảo sync với code, không bị trôi khi thêm setting mới - D22/D23)
- .env.example bao gồm TẤT CẢ settings từ config.py
- .dockerignore root: loại trừ khi build context
- .env không commit (đã có trong .gitignore)"
```

Expected: 3 file mới, không có `.env` trong commit.

---

### Task 2: server/Dockerfile.dev — build image standalone

**Files:**
- Create: `/server/.dockerignore`
- Create: `/server/Dockerfile.dev`

**Interfaces:**
- Produces: image `asset-inventory-api:dev` từ `docker build` (sẽ dùng ở compose Task 5)

- [ ] **Step 1: Tạo `/server/.dockerignore`**

File: `/home/windowsId/server/.dockerignore`

```
.venv
.pytest_cache
.ruff_cache
agent_dist
*.log
deploy
tests
README.md
.env
.env.example
```

- [ ] **Step 2: Tạo `/server/Dockerfile.dev`**

File: `/home/windowsId/server/Dockerfile.dev`

```dockerfile
# ════════════════════════════════════════════════════════════════
# Server dev image — Python 3.12 slim + system Python
# Mount ./server:/app:ro từ host (hot reload). Image chỉ chứa deps.
# ════════════════════════════════════════════════════════════════
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build tools (cho 1 số wheel) + curl (debug/healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đầy đủ dependency 1 lần lúc build image (giữ sync với pyproject.toml)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" "uvicorn[standard]>=0.30.0" "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" "email-validator>=2.0.0" \
    "sqlalchemy[asyncio]>=2.0.30" "asyncpg>=0.29.0" "alembic>=1.13.0" \
    "redis>=5.0.0" "pyjwt>=2.8.0" "bcrypt>=4.1.0" \
    "cryptography>=42.0.0" "pyotp>=2.9.0" "jinja2>=3.1.0" \
    "slowapi>=0.1.9" "openpyxl>=3.1.0" "httpx>=0.27.0" \
    "pyyaml>=6.0.0" "docker>=7.0.0"

EXPOSE 8000

# Default CMD — compose sẽ override
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Build image standalone**

```bash
cd /home/windowsId
docker build -f server/Dockerfile.dev -t asset-inventory-api:dev server/
```

Expected: build thành công, image được tạo. Nếu fail, check error log; thường là network issue hoặc dep nào đó đổi tên.

- [ ] **Step 4: Verify image có đủ deps**

```bash
docker run --rm asset-inventory-api:dev python -c "
import fastapi, uvicorn, pydantic, sqlalchemy, asyncpg, alembic
import redis, jwt, bcrypt, cryptography, pyotp, jinja2, slowapi
import openpyxl, httpx, yaml, docker
print('fastapi', fastapi.__version__)
print('sqlalchemy', sqlalchemy.__version__)
print('all deps OK')
"
```

Expected: in ra version + "all deps OK". Không có ImportError.

- [ ] **Step 5: Commit**

```bash
cd /home/windowsId
git add server/Dockerfile.dev server/.dockerignore
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): server/Dockerfile.dev + .dockerignore

Image Python 3.12-slim + system Python. Cài đủ deps từ pyproject.toml.
Mount ./server:/app:ro ở compose Task 5 để hot reload qua uvicorn --reload.
Giữ nguyên CMD default; compose override khi cần alembic upgrade head."
```

---

### Task 3: portal/Dockerfile.dev — build image standalone

**Files:**
- Create: `/portal/.dockerignore`
- Create: `/portal/Dockerfile.dev`

**Interfaces:**
- Produces: image `asset-inventory-portal:dev` từ `docker build` (dùng ở compose Task 6)

- [ ] **Step 1: Tạo `/portal/.dockerignore`**

File: `/home/windowsId/portal/.dockerignore`

```
node_modules
.next
*.log
stitch-ref
stitch_*.py
Design.md
AGENTS.md
CLAUDE.md
tsconfig.tsbuildinfo
.env
.env.local
.env.local.example
```

- [ ] **Step 2: Tạo `/portal/Dockerfile.dev`**

File: `/home/windowsId/portal/Dockerfile.dev`

```dockerfile
# ════════════════════════════════════════════════════════════════
# Portal dev image — Node 20 + pnpm (qua corepack)
# Mount ./portal:/app:ro từ host (hot reload). Image chỉ chứa deps.
# ════════════════════════════════════════════════════════════════
FROM node:20-alpine

WORKDIR /app

# Bật pnpm (corepack có sẵn trong node:20-alpine)
RUN corepack enable && corepack prepare pnpm@latest --activate

# Manifests — chỉ cần cho `pnpm install`. Code/config mount từ host lúc runtime.
COPY package.json pnpm-lock.yaml* ./

# Cài deps 1 lần (frozen lockfile → reproducible)
RUN pnpm install --frozen-lockfile

EXPOSE 3003

# Default CMD — compose override bằng "pnpm dev"
CMD ["pnpm", "dev"]
```

- [ ] **Step 3: Build image standalone**

```bash
cd /home/windowsId
docker build -f portal/Dockerfile.dev -t asset-inventory-portal:dev portal/
```

Expected: build thành công. Nếu fail với pnpm version error, pin version cụ thể: sửa `pnpm@latest` → `pnpm@9.15.0` trong Dockerfile rồi rebuild.

- [ ] **Step 4: Verify image có pnpm + Next.js ready**

```bash
docker run --rm asset-inventory-portal:dev sh -c "
pnpm --version && \
node --version && \
ls node_modules/.bin/next && \
echo 'all OK'
"
```

Expected: in pnpm version, node version (`v20.x`), và "all OK".

- [ ] **Step 5: Commit**

```bash
cd /home/windowsId
git add portal/Dockerfile.dev portal/.dockerignore
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): portal/Dockerfile.dev + .dockerignore

Image Node 20-alpine + pnpm (corepack). Cài deps từ package.json +
pnpm-lock.yaml. Mount ./portal:/app:ro ở compose Task 6 để hot reload
qua next dev."
```

---

### Task 4: docker-compose.yml — postgres + redis stack

**Files:**
- Create: `/docker-compose.yml` (skeleton, chỉ postgres + redis)

**Interfaces:**
- Produces: 2 services chạy được, healthchecks pass. Sẽ thêm api (Task 5) + portal (Task 6) sau.

- [ ] **Step 1: Tạo `/docker-compose.yml` (skeleton)**

File: `/home/windowsId/docker-compose.yml`

```yaml
# ════════════════════════════════════════════════════════════════
# Master dev stack — postgres + redis + api + portal
# ════════════════════════════════════════════════════════════════
# Start:  docker compose up --build
# Stop:   docker compose down            (giữ volume, DB còn)
# Reset:  docker compose down -v         (XOÁ volume — mất DB + redis cache)
# Logs:   docker compose logs -f api portal
# Shell:  docker compose exec api bash
#         docker compose exec portal sh
# ════════════════════════════════════════════════════════════════
name: asset-inventory

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-inventory}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-inventory}
      POSTGRES_DB: ${POSTGRES_DB:-inventory}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-inventory}"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks: [inventory-net]

  redis:
    image: redis:7-alpine
    ports:
      - "${REDIS_PORT:-6381}:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks: [inventory-net]

volumes:
  pgdata:
  redisdata:

networks:
  inventory-net:
    driver: bridge
```

- [ ] **Step 2: Validate compose config**

```bash
cd /home/windowsId
docker compose config --quiet && echo "OK: compose config valid"
```

Expected: `OK: compose config valid`. Nếu lỗi YAML, fix syntax rồi chạy lại.

- [ ] **Step 3: Start postgres + redis, verify healthchecks**

```bash
cd /home/windowsId
docker compose up -d postgres redis
sleep 5
docker compose ps
```

Expected: cả 2 services status `running (healthy)` (sau 5-10s cho healthcheck).

- [ ] **Step 4: Smoke test postgres + redis**

```bash
# Postgres
docker compose exec postgres psql -U inventory -d inventory -c "SELECT version();"

# Redis
docker compose exec redis redis-cli ping
```

Expected: Postgres in ra version string; Redis trả `PONG`.

- [ ] **Step 5: Stop nhưng giữ volume**

```bash
docker compose down
docker volume ls | grep -E "asset-inventory.*(pgdata|redisdata)"
```

Expected: 2 volume `asset-inventory_pgdata` và `asset-inventory_redisdata` còn tồn tại.

- [ ] **Step 6: Commit**

```bash
cd /home/windowsId
git add docker-compose.yml
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): docker-compose.yml skeleton (postgres + redis)

Master compose bắt đầu với 2 infra services. Healthcheck pass.
Volume pgdata/redisdata persist qua docker compose down (không -v).
api/portal sẽ thêm ở Task 5/6."
```

---

### Task 5: Add api service to compose — FastAPI container

**Files:**
- Modify: `/docker-compose.yml` (thêm `api` service + volumes)

**Interfaces:**
- Consumes: image `asset-inventory-api:dev` từ Task 2.
- Produces: api container chạy, alembic OK, `http://localhost:8000/docs` trả 200.

- [ ] **Step 1: Thêm `api` service vào `docker-compose.yml`**

Edit `/home/windowsId/docker-compose.yml`. Thêm vào **trước** block `volumes:` (sau block `redis`):

```yaml
  api:
    build:
      context: ./server
      dockerfile: Dockerfile.dev
    env_file: .env
    environment:
      # override để dùng docker DNS thay vì localhost
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-inventory}:${POSTGRES_PASSWORD:-inventory}@postgres:5432/${POSTGRES_DB:-inventory}
      REDIS_URL: redis://redis:6379/0
    ports:
      - "${API_PORT:-8000}:8000"
    volumes:
      - ./server:/app:ro
      - ./server/agent_dist:/data/artifacts:ro
    working_dir: /app
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app"
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    networks: [inventory-net]
```

File sau khi sửa có cấu trúc:

```yaml
services:
  postgres: ...
  redis: ...
  api: ...        # ← THÊM MỚI

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 2: Validate compose**

```bash
cd /home/windowsId
docker compose config --quiet && echo "OK"
```

- [ ] **Step 3: Build + start api**

```bash
cd /home/windowsId
docker compose build api
docker compose up -d api
sleep 8
docker compose ps api
docker compose logs --tail=30 api
```

Expected: status `running`. Logs có dòng:
- `INFO  [alembic.runtime.migration] Running upgrade ...` (nếu có migrations mới) hoặc `INFO  [alembic.runtime.migration] Context impl PostgresqlImpl` (no upgrade needed)
- `INFO:     Uvicorn running on http://0.0.0.0:8000`
- `INFO:     Application startup complete.`

- [ ] **Step 4: Smoke test api**

```bash
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8000/docs
```

Expected: `200`.

- [ ] **Step 5: Verify env override (DATABASE_URL dùng docker DNS)**

```bash
docker compose exec api env | grep -E "^(DATABASE_URL|REDIS_URL)="
```

Expected:
```
DATABASE_URL=postgresql+asyncpg://inventory:inventory@postgres:5432/inventory
REDIS_URL=redis://redis:6379/0
```

(Quan trọng: `postgres:5432` chứ KHÔNG phải `localhost:5432` — đây là override.)

- [ ] **Step 6: Stop stack (chừa Task 7 + 8)**

```bash
docker compose down
```

- [ ] **Step 7: Commit**

```bash
cd /home/windowsId
git add docker-compose.yml
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): thêm api service vào compose

- Build từ server/Dockerfile.dev (Task 2)
- env_file: .env (root)
- Override DATABASE_URL + REDIS_URL dùng docker DNS
- Volume mount ./server:/app:ro (hot reload)
- Mount ./server/agent_dist:/data/artifacts:ro cho /download/
- depends_on postgres + redis healthy
- Command: alembic upgrade head && uvicorn --reload --reload-dir /app/app"
```

---

### Task 6: Add portal service to compose — Next.js container

**Files:**
- Modify: `/docker-compose.yml` (thêm `portal` service + 2 named volumes)

**Interfaces:**
- Consumes: image `asset-inventory-portal:dev` từ Task 3.
- Produces: portal container chạy, `http://localhost:3003` trả 200.

- [ ] **Step 1: Thêm `portal` service + named volumes**

Edit `/home/windowsId/docker-compose.yml`:

Thêm vào **trước block `volumes:`** (sau `api`):

```yaml
  portal:
    build:
      context: ./portal
      dockerfile: Dockerfile.dev
    environment:
      API_BASE: http://api:8000
      PORT: 3003
      HOSTNAME: "0.0.0.0"
    ports:
      - "${PORTAL_PORT:-3003}:3003"
    volumes:
      - ./portal:/app:ro
      - portal_node_modules:/app/node_modules
      - portal_next:/app/.next
    working_dir: /app
    command: pnpm dev
    depends_on:
      - api
    networks: [inventory-net]
```

Thêm vào block `volumes:` (cùng cấp `pgdata`, `redisdata`):

```yaml
  portal_node_modules:
  portal_next:
```

- [ ] **Step 2: Validate compose**

```bash
cd /home/windowsId
docker compose config --quiet && echo "OK"
```

- [ ] **Step 3: Build + start full stack**

```bash
cd /home/windowsId
docker compose build portal
docker compose up -d
sleep 15
docker compose ps
```

Expected: 4 services `running`:
- `asset-inventory-postgres-1` — healthy
- `asset-inventory-redis-1` — healthy
- `asset-inventory-api-1` — running
- `asset-inventory-portal-1` — running (Next.js compile lần đầu ~30s)

- [ ] **Step 4: Smoke test portal**

```bash
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:3003
curl -sf http://localhost:3003 | head -20
```

Expected: status `200`. Body chứa HTML (Next.js shell).

- [ ] **Step 5: Verify API_BASE trong container**

```bash
docker compose exec portal env | grep -E "^API_BASE="
```

Expected: `API_BASE=http://api:8000` (KHÔNG phải localhost).

- [ ] **Step 6: Stop nhưng giữ volume (chừa Task 7)**

```bash
docker compose down
```

- [ ] **Step 7: Commit**

```bash
cd /home/windowsId
git add docker-compose.yml
git -c user.email="dev@local" -c user.name="Dev" commit -m "feat(docker): thêm portal service vào compose

- Build từ portal/Dockerfile.dev (Task 3)
- API_BASE=http://api:8000 (docker DNS)
- PORT=3003, HOSTNAME=0.0.0.0
- Volume mount ./portal:/app:ro (hot reload)
- Named volumes portal_node_modules (che host's) + portal_next (build cache)
- depends_on api"
```

---

### Task 7: Verify hot reload — cả api và portal

**Files:**
- Modify (test): `/server/app/main.py` (sửa 1 dòng)
- Modify (test): `/portal/app/...` (sửa 1 dòng)
- Sau đó: revert

**Interfaces:**
- Verifies: uvicorn `--reload` bắt được file change; `next dev` HMR refresh được browser.

- [ ] **Step 1: Start stack**

```bash
cd /home/windowsId
docker compose up -d
sleep 10
```

- [ ] **Step 2: Tail api logs**

```bash
docker compose logs -f api &
API_LOG_PID=$!
sleep 3
```

- [ ] **Step 3: Trigger api reload (sửa 1 dòng)**

Mở `/home/windowsId/server/app/main.py` (file FastAPI entry point), tìm dòng `app = FastAPI(...)` hoặc tương tự, thêm 1 comment ngắn vô hại:

```python
# HOT_RELOAD_TEST
```

Save file.

- [ ] **Step 4: Đợi và check log reload**

```bash
sleep 4
docker compose logs --tail=50 api | grep -iE "reload|change|watch"
```

Expected: có dòng kiểu `Detected change in '/app/app/main.py', reloading` hoặc `Watcher detected changes`.

Nếu KHÔNG thấy: `--reload-dir /app/app` chưa đúng, hoặc mount issue. Check `docker compose exec api ls -la /app/app/` xem file có mount đúng không.

- [ ] **Step 5: Revert thay đổi server**

Xoá dòng `# HOT_RELOAD_TEST` vừa thêm trong `/server/app/main.py`. Save.

- [ ] **Step 6: Trigger portal reload (sửa 1 file UI)**

Tìm 1 file UI component trong `/home/windowsId/portal/app/` (VD `portal/app/page.tsx` hoặc `portal/app/layout.tsx`). Thêm comment:

```tsx
{/* HOT_RELOAD_TEST */}
```

Save file.

- [ ] **Step 7: Check portal log**

```bash
docker compose logs --tail=30 portal | grep -iE "compil|reload|change"
```

Expected: Next.js recompile (thường log `compiled successfully` hoặc `✓ Compiled`).

- [ ] **Step 8: Revert thay đổi portal**

Xoá `{/* HOT_RELOAD_TEST */}` vừa thêm. Save.

- [ ] **Step 9: Stop stack**

```bash
docker compose down
```

Không có commit ở task này (chỉ verify).

---

### Task 8: Cleanup — xoá file cũ

**Files:**
- Delete: `/server/Dockerfile`
- Delete: `/server/deploy/docker-compose.yml`
- Delete: `/server/.env`
- Delete: `/server/.env.example`
- Modify: `/server/deploy/` (xoá `docker-compose.yml`, giữ `nginx/`)

**Interfaces:**
- Produces: repo sạch, stack vẫn chạy bằng root compose + Dockerfile.dev.

- [ ] **Step 1: Verify stack vẫn chạy TRƯỚC khi xoá**

```bash
cd /home/windowsId
docker compose up -d
sleep 10
docker compose ps
curl -sf -o /dev/null -w "api: %{http_code}\n" http://localhost:8000/docs
curl -sf -o /dev/null -w "portal: %{http_code}\n" http://localhost:3003
docker compose down
```

Expected: cả 2 trả 200.

- [ ] **Step 2: Xoá `server/Dockerfile`**

```bash
cd /home/windowsId
rm server/Dockerfile
```

- [ ] **Step 3: Xoá `server/deploy/docker-compose.yml`, giữ `server/deploy/nginx/`**

```bash
rm server/deploy/docker-compose.yml
# Xoá thư mục deploy nếu rỗng (sau khi xoá compose; nginx/ còn nên không rỗng)
ls server/deploy/
```

Expected: chỉ còn `server/deploy/nginx/`.

- [ ] **Step 4: Xoá `server/.env` và `server/.env.example`**

```bash
cd /home/windowsId
rm server/.env server/.env.example
```

- [ ] **Step 5: Verify stack vẫn chạy**

```bash
cd /home/windowsId
docker compose up -d
sleep 12
docker compose ps
curl -sf -o /dev/null -w "api: %{http_code}\n" http://localhost:8000/docs
curl -sf -o /dev/null -w "portal: %{http_code}\n" http://localhost:3003
```

Expected: cả 2 vẫn 200. Stack KHÔNG phụ thuộc file cũ.

- [ ] **Step 6: Verify file cũ đã xoá**

```bash
cd /home/windowsId
test ! -f server/Dockerfile && echo "OK: server/Dockerfile gone"
test ! -f server/deploy/docker-compose.yml && echo "OK: server/deploy/docker-compose.yml gone"
test ! -f server/.env && echo "OK: server/.env gone"
test ! -f server/.env.example && echo "OK: server/.env.example gone"
test -d server/deploy/nginx && echo "OK: server/deploy/nginx/ kept"
ls server/deploy/nginx/  # có nginx.conf
```

- [ ] **Step 7: Stop stack**

```bash
docker compose down
```

- [ ] **Step 8: Commit**

```bash
cd /home/windowsId
git add -A  # stage deletions
git status
git -c user.email="dev@local" -c user.name="Dev" commit -m "chore: xoá file Docker/env cũ ở server/

Thay bằng master compose ở root + Dockerfile.dev:
- server/Dockerfile → xoá (Dockerfile.dev thay)
- server/deploy/docker-compose.yml → xoá (root compose thay)
- server/.env, server/.env.example → xoá (root .env thay)

Giữ:
- server/deploy/nginx/ (tham khảo sau)
- agent/, deploy/velociraptor/, deploy/step-ca/ (tách ngoài stack)

Stack vẫn chạy bình thường sau khi xoá."
```

---

### Task 9: Update README — thêm section Docker

**Files:**
- Modify: `/README.md` (thêm section "Phát triển với Docker" sau phần giới thiệu hiện tại)

- [ ] **Step 1: Đọc README hiện tại**

```bash
cd /home/windowsId
wc -l README.md
head -50 README.md
```

- [ ] **Step 2: Tìm vị trí chèn section**

Tìm heading đầu tiên có dạng `##` (level 2) hoặc kết thúc phần giới thiệu. Chèn section Docker **sau** phần giới thiệu, **trước** phần kỹ thuật/cài đặt hiện có.

- [ ] **Step 3: Thêm section bằng edit**

Edit `/home/windowsId/README.md`. Chèn block này vào vị trí phù hợp:

````markdown
## Phát triển với Docker

Repo hỗ trợ chạy toàn bộ stack (postgres + redis + api + portal) bằng Docker Compose.
Stack dev có hot reload — sửa code trong `server/app/` hoặc `portal/app/` sẽ tự refresh.

### Yêu cầu

- Docker Engine ≥ 24, Docker Compose v2 (`docker compose`, không phải `docker-compose`)

### Setup lần đầu

```bash
cp .env.example .env
# Sửa SECRET_KEY, DATA_ENCRYPTION_KEY, SEED_ADMIN_PASSWORD nếu cần
docker compose up -d --build
docker compose logs -f api portal
```

Sau khi healthy:
- Portal: http://localhost:3003
- API docs: http://localhost:8000/docs

### Commands

```bash
docker compose up -d              # khởi động
docker compose down               # dừng (giữ DB)
docker compose down -v            # reset sạch (mất DB)
docker compose logs -f api        # log api
docker compose exec api bash      # shell vào api container
```

### Cấu trúc service

| Service | Host port | Container port | Mục đích |
|---|---|---|---|
| postgres | 5432 | 5432 | DB chính |
| redis | 6381 | 6379 | Cache + pub/sub |
| api | 8000 | 8000 | FastAPI backend |
| portal | 3003 | 3003 | Next.js frontend |

### Tách biệt

- **Velociraptor** (DFIR) — `deploy/velociraptor/` (sau này chạy máy khác)
- **step-ca** — `deploy/step-ca/` (prod/proper mTLS; dev dùng `CA_MODE=local`)
- **Agent C#** — `agent/`, build riêng trên Windows rồi copy `OrgInventoryAgent.msi` vào `server/agent_dist/`
- **Nginx** — repo không bao gồm; deploy thật dùng Nginx Proxy Manager bên ngoài

### Build native (fallback)

Nếu không dùng Docker:

```bash
./build-all.sh    # build server + agent + portal native
```

````

- [ ] **Step 4: Verify README**

```bash
grep -c "Phát triển với Docker" /home/windowsId/README.md
```

Expected: `1` (hoặc nhiều hơn nếu heading + body đều match).

- [ ] **Step 5: Render Markdown check**

Mở `/home/windowsId/README.md` trong editor, kiểm tra:
- Section heading `## Phát triển với Docker` xuất hiện
- Code blocks đóng mở đúng số lượng backticks
- Không có syntax lỗi

- [ ] **Step 6: Commit**

```bash
cd /home/windowsId
git add README.md
git -c user.email="dev@local" -c user.name="Dev" commit -m "docs(readme): thêm section 'Phát triển với Docker'

Hướng dẫn:
- Setup lần đầu (cp .env.example, docker compose up)
- Commands hàng ngày (up/down/logs/exec)
- Bảng service + ports
- Components tách ngoài stack (velo, step-ca, agent, nginx)
- Fallback build native (build-all.sh)"
```

---

## Self-review

### 1. Spec coverage

| Spec § | Yêu cầu | Task |
|---|---|---|
| §1 Bối cảnh | — | (motivation, không cần task) |
| §2 G1: 1 command `up` | ✓ | T4 + T5 + T6 |
| §2 G2: Hot reload | ✓ | T2 + T3 (dev servers) + T7 (verify) |
| §2 G3: 1 file `.env` root | ✓ | T1 |
| §2 G4: Cổng giữ nguyên | ✓ | T4 + T5 + T6 (ports trong compose) |
| §2 G5: `CA_MODE=local` | ✓ | `.env` từ T1 có `CA_MODE=local` |
| §2 G6: Không nginx trong repo | ✓ | Không thêm nginx service; compose chỉ 4 services |
| §5.1 File MỚI (8 file) | ✓ | T1 (.env.example, .env, .dockerignore, scripts/gen-env-example.py), T2 (server/Dockerfile.dev, server/.dockerignore), T3 (portal/Dockerfile.dev, portal/.dockerignore), T4 (docker-compose.yml) |
| §5.2 File SỬA (1 file) | ✓ | T9 (README.md) |
| §5.3 File XOÁ (4 file) | ✓ | T8 |
| §6.1 docker-compose.yml content | ✓ | T4 (skeleton) + T5 (api) + T6 (portal) |
| §6.2 server/Dockerfile.dev content | ✓ | T2 |
| §6.3 portal/Dockerfile.dev content | ✓ | T3 |
| §6.4-6.6 dockerignore content | ✓ | T1, T2, T3 |
| §6.7 .env.example completeness | ✓ | T1 (D22: introspect Settings) |
| §6.8 .env capture user values | ✓ | T1 (capture `LOST_AFTER_DAYS=15` etc.) |
| §7 Workflow | (documentation) | T9 (README) |
| §8 Troubleshooting | (documentation) | T9 (README snippet) |

### 2. Placeholder scan

- Không có "TBD", "TODO", "implement later", "fill in details".
- Tất cả commands, code, file contents đều cụ thể.

### 3. Type consistency

- Network name `inventory-net` consistent xuyên suốt T4 → T6.
- Volume names `pgdata`, `redisdata`, `portal_node_modules`, `portal_next` consistent.
- Image names `asset-inventory-api:dev`, `asset-inventory-portal:dev` dùng ở T2/T3 (build) → T5/T6 (compose).
- Port numbers 8000/3003/5432/6381 consistent.
- Service names `postgres`, `redis`, `api`, `portal` consistent (cũng dùng trong env override `DATABASE_URL=...@postgres:5432/...`).

### 4. Spec requirement without task

- Không có.
