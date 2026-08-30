# Docker Dev Stack — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-30 |
| Status | Design (awaiting user review) |
| Scope | Containerize `server/` (FastAPI) + `portal/` (Next.js) cho dev workflow |
| Path classification | Architectural |
| Author | Brainstorming session với user |

---

## 1. Bối cảnh & vấn đề

Hệ thống IT Asset Inventory hiện có 2 service chính:

- **`server/`** — FastAPI + uvicorn. Có sẵn `Dockerfile` (bản tối giản) + `server/deploy/docker-compose.yml` (postgres + redis + api + nginx).
- **`portal/`** — Next.js 16 App Router. **Chưa có Dockerfile.** Đang chạy trực tiếp qua `next dev` / `pnpm build`.

User hiện chạy cả 2 service **trực tiếp trên máy** (xem `uvicorn.log`, `portal-dev.log`):

- uvicorn: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- next dev: chạy ở port 3003 (theo `install.ps1` reference)

**Vấn đề:**

1. Phải quản lý 2 terminal riêng + Postgres + Redis + .env files → dễ sai sót khi onboarding.
2. `server/deploy/docker-compose.yml` hiện không dùng thường xuyên (ưu tiên uvicorn trực tiếp), dẫn đến 2 luồng workflow song song.
3. Portal không có Dockerfile → không có cách nào chạy "all-in-one" mà vẫn có hot reload.
4. Phụ thuộc vào host's `.venv` (Python) + `node_modules` (Node) — khác platform giữa các máy dev.

**Mục tiêu:** một file `docker compose up` ở root → khởi động `postgres + redis + server + portal` với hot reload, dùng được cho dev hàng ngày.

---

## 2. Goals & Non-goals

### 2.1. Goals

- **G1.** Một command duy nhất (`docker compose up --build`) chạy đủ 4 service dev-ready.
- **G2.** Hot reload cho cả api (`uvicorn --reload`) và portal (`next dev`) — sửa code → save → thấy ngay.
- **G3.** Một file `.env` ở root chứa toàn bộ config (server + compose).
- **G4.** Cổng giữ nguyên hiện tại: 8000 (api), 3003 (portal), 5432 (postgres), 6381 (redis).
- **G5.** Tương thích ngược với `CA_MODE=local` (CA local trong app, không cần step-ca container).
- **G6.** Repo không chứa nginx — sử dụng Nginx Proxy Manager bên ngoài.

### 2.2. Non-goals (out of scope cho spec này)

- **N1.** Không build/prod-deploy stack. Spec chỉ phục vụ dev. Production sẽ là spec khác.
- **N2.** Không bao gồm Velociraptor. `deploy/velociraptor/` giữ nguyên (sau này user move sang máy khác).
- **N3.** Không bao gồm step-ca container. Dev dùng `CA_MODE=local`; prod/proper mTLS dùng step-ca ngoài (xem `deploy/step-ca/`).
- **N4.** Không thay đổi logic FastAPI / Next.js — chỉ thêm Docker layer.
- **N5.** Không build agent C# trong Docker. Agent build trên Windows (WiX), copy `.msi` vào `server/agent_dist/`.
- **N6.** Không thiết lập CI/CD. Scope chỉ local dev.

---

## 3. Quyết định kiến trúc (decisions log)

| # | Câu hỏi | Quyết định | Lý do |
|---|---|---|---|
| D1 | Path classification | Architectural | Nhiều subsystem, thay đổi cách service fit nhau, thay đổi dev workflow |
| D2 | Phạm vi master compose | `postgres + redis + server + portal` | User chọn A; velo/step-ca/nginx tách ngoài |
| D3 | Velociraptor | Tách ngoài stack, ở `deploy/velociraptor/` | User: "sau này chạy veloci ở 1 máy khác" |
| D4 | step-ca | Tách ngoài stack | Dev dùng `CA_MODE=local`; prod/proper mTLS dùng step-ca ngoài |
| D5 | Nginx trong repo | KHÔNG | User dùng Nginx Proxy Manager bên ngoài |
| D6 | Hot reload | CÓ (D — volume-mount source + dev servers) | Dev workflow; prod stack sẽ là spec riêng (xem N1) |
| D7 | Mount pattern | Whole-mount: `./server:/app:ro`, `./portal:/app:ro` | Alembic cần `alembic.ini` (ngoài `app/`), granular mount phức tạp hơn; `--reload-dir /app/app` giới hạn watch scope |
| D8 | Portal `node_modules` | Named volume `portal_node_modules` che host's | Host's `node_modules` có thể build cho OS khác (macOS/Windows); container cần Linux build |
| D9 | Portal `.next` cache | Named volume `portal_next` | Build cache sạch, không conflict với mount |
| D10 | Env file | Một file `.env` ở root | User chọn; gọn hơn so với tách `server/.env` + `portal/.env.local` |
| D11 | `build-all.sh` | Giữ nguyên | Fallback cho ai muốn build native |
| D12 | Dockerfile tên | `Dockerfile.dev` | Chỉ phục vụ dev; prod sẽ là Dockerfile riêng |
| D13 | `server/Dockerfile` cũ | Xoá | Thay bằng `Dockerfile.dev` |
| D14 | `server/deploy/docker-compose.yml` cũ | Xoá | Master compose ở root thay thế |
| D15 | `server/deploy/nginx/nginx.conf` | GIỮ | Tham khảo sau; không mount vào stack |
| D16 | CORS_ORIGINS | `["http://localhost:3003", "http://10.10.0.241:3003"]` | User chọn (c): localhost + LAN IP |
| D17 | DATABASE_URL/REDIS_URL trong `.env` | Giữ `localhost` (Q1.a) | Compose override là behavior chính; giá trị file là fallback/documentation |
| D18 | Compose env override | Có, override `DATABASE_URL` + `REDIS_URL` trong `environment:` | Dùng docker DNS (`postgres:5432`, `redis:6379`) thay vì `localhost` |
| D19 | API `--reload-dir` | `/app/app` | Chỉ watch code dir, bỏ qua `.venv`, `.pytest_cache`, `*.log` |
| D20 | Portal `HOSTNAME` env | `"0.0.0.0"` | `next dev` bind đúng interface trong container |
| D21 | `agent_dist` mount | `./server/agent_dist:/data/artifacts:ro` | Phục vụ `/download/...` endpoint của FastAPI |

---

## 4. Kiến trúc tổng thể

### 4.1. Sơ đồ

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker host (Linux)                    │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  postgres   │  │   redis     │  │   api (FastAPI)     │  │
│  │  :5432      │  │   :6381     │  │   :8000             │  │
│  │             │  │             │  │  - uvicorn --reload │  │
│  │  vol: pgdata│  │ vol: redis  │  │  - vol: ./server    │  │
│  └──────┬──────┘  └──────┬──────┘  │  - vol: agent_dist/ │  │
│         │                │         └──────────┬──────────┘  │
│         │                │                    │              │
│         └───────┬────────┘                    │              │
│                 │       ┌────────────────────┘              │
│                 ▼       ▼                                    │
│           ┌─────────────────────┐                           │
│           │  portal (Next.js)   │                           │
│           │  :3003              │                           │
│           │  - next dev         │                           │
│           │  - vol: ./portal    │                           │
│           │  - API_BASE=        │                           │
│           │     http://api:8000 │                           │
│           └─────────────────────┘                           │
│                                                             │
│  Host port mapping:                                         │
│    localhost:5432 → postgres:5432                           │
│    localhost:6381 → redis:6379                              │
│    localhost:8000 → api:8000                                │
│    localhost:3003 → portal:3003                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2. Network

- Một bridge network `inventory-net`.
- Service gọi nhau qua DNS name: `api`, `portal`, `postgres`, `redis`.
- Host (browser) kết nối qua `localhost:<port>` (port mapping).

### 4.3. Volume strategy

| Source (host) | Target (container) | Loại | Mục đích |
|---|---|---|---|
| `./server` | `/app` | bind mount, `:ro` | Hot reload code Python |
| `./server/agent_dist` | `/data/artifacts` | bind mount, `:ro` | MSI artifacts (served qua `/download`) |
| `pgdata` (named) | `/var/lib/postgresql/data` | docker volume | Postgres data persistence |
| `redisdata` (named) | `/data` | docker volume | Redis data persistence |
| `./portal` | `/app` | bind mount, `:ro` | Hot reload code Next.js |
| `portal_node_modules` (named) | `/app/node_modules` | docker volume | Che host's `node_modules`, container dùng Linux build |
| `portal_next` (named) | `/app/.next` | docker volume | Next.js build cache |

---

## 5. Cấu trúc file

### 5.1. File MỚI (tạo)

| Đường dẫn | Mô tả |
|---|---|
| `/.dockerignore` | Build context exclusions (root) |
| `/.env` | Env chung — **KHÔNG commit** (đã có trong `.gitignore`) |
| `/.env.example` | Env template — commit vào git |
| `/docker-compose.yml` | Master compose — 4 services + 1 network + 4 named volumes |
| `/server/Dockerfile.dev` | Python 3.12-slim image với deps |
| `/server/.dockerignore` | Server build context exclusions |
| `/portal/Dockerfile.dev` | Node 20-alpine image với pnpm + deps |
| `/portal/.dockerignore` | Portal build context exclusions |

### 5.2. File SỬA

| Đường dẫn | Thay đổi |
|---|---|
| `/README.md` | Thêm section "Phát triển với Docker" (snippet ở §10) |

### 5.3. File XOÁ

| Đường dẫn | Lý do |
|---|---|
| `/server/Dockerfile` | Thay bằng `/server/Dockerfile.dev` |
| `/server/deploy/docker-compose.yml` | Master compose ở root thay thế |
| `/server/.env` | Root `.env` thay thế |
| `/server/.env.example` | Root `.env.example` thay thế |

### 5.4. File KHÔNG đổi

| Đường dẫn | Lý do |
|---|---|
| `/server/deploy/nginx/nginx.conf` | Tham khảo cho tương lai; không mount |
| `/agent/` | Build agent là việc khác (Windows + WiX) |
| `/deploy/velociraptor/` | Tách riêng; sau này move sang máy khác |
| `/deploy/step-ca/` | Dev dùng `CA_MODE=local` |
| `/build-all.sh` | Fallback build native |
| `/portal/.env.local` | Không dùng trong Docker; giữ cho native dev nếu cần |

---

## 6. Nội dung file

### 6.1. `/docker-compose.yml`

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

volumes:
  pgdata:
  redisdata:
  portal_node_modules:
  portal_next:

networks:
  inventory-net:
    driver: bridge
```

### 6.2. `/server/Dockerfile.dev`

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

# Build tools (cho 1 số wheel) + curl (debug/healthcheck từ compose)
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

# Default CMD — compose override bằng "alembic upgrade head && uvicorn --reload"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 6.3. `/portal/Dockerfile.dev`

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

**Lưu ý:** Nếu `pnpm-lock.yaml` thuộc version pnpm cũ mà `pnpm@latest` không đọc được, pin version cụ thể: sửa `pnpm@latest` → `pnpm@9.15.0` (hoặc version tương thích lockfile).

### 6.4. `/.dockerignore`

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
```

### 6.5. `/server/.dockerignore`

```
.venv
.pytest_cache
.ruff_cache
agent_dist
*.log
deploy
tests
README.md
```

### 6.6. `/portal/.dockerignore`

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
```

### 6.7. `/.env.example` (template — commit vào git)

```bash
# ════════════════════════════════════════════════════════════════
# Copy thành .env rồi sửa các CHANGE_ME_*
# ════════════════════════════════════════════════════════════════

# ─── COMPOSE / NETWORK ────────────────────────────────────────
POSTGRES_USER=inventory
POSTGRES_PASSWORD=inventory
POSTGRES_DB=inventory
POSTGRES_PORT=5432

REDIS_PORT=6381

API_PORT=8000
PORTAL_PORT=3003

# ─── SERVER APP (FastAPI) ────────────────────────────────────
APP_ENV=dev
DEBUG=true
HOST=0.0.0.0
PORT=8000

# DATABASE_URL + REDIS_URL bị compose override (docker DNS)
DATABASE_URL=postgresql+asyncpg://inventory:inventory@localhost:5432/inventory
REDIS_URL=redis://localhost:6381/0
DB_ECHO=false
# ONLINE_TTL_SECONDS=180

# Agent heartbeat / inventory
HEARTBEAT_INTERVAL_SECONDS=30
HEARTBEAT_JITTER_SECONDS=8
INVENTORY_INTERVAL_HOURS=24
AGENT_SERVER_URL=https://agent.example.gov.vn

# JWT
SECRET_KEY=CHANGE_ME_generate_with_secrets_token_urlsafe_64
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CA
CA_MODE=local
STEP_CA_URL=https://ca.internal:8443
STEP_CA_PROVISIONER=admin
STEP_CA_PROVISIONER_PASSWORD=CHANGE_ME
CLIENT_CERT_VALID_DAYS=365

# Encryption
DATA_ENCRYPTION_KEY=CHANGE_ME_32_byte_hex_key_00000000000000

# Admin seed (chạy 1 lần lúc khởi tạo DB)
SEED_ADMIN_EMAIL=admin@example.gov.vn
SEED_ADMIN_PASSWORD=ChangeMe!123
SEED_ADMIN_FULL_NAME=Quản trị viên hệ thống

# Rate limit
RATE_LIMIT_ENROLL=30/minute
RATE_LIMIT_LOGIN=10/minute

# Portal
PORTAL_URL=http://localhost:3003
CORS_ORIGINS=["http://localhost:3003", "http://10.10.0.241:3003"]

# ─── VELOCIRAPTOR (DFIR) ─────────────────────────────────────
VELOCIRAPTOR_ENABLED=false
VELOCIRAPTOR_DEFAULT_URL=https://velociraptor.example.gov.vn:8889
VELOCIRAPTOR_DOCKER_CONTAINER=velociraptor
VELOCIRAPTOR_SYNC_INTERVAL_SECONDS=300
VELOCIRAPTOR_API_TIMEOUT_SECONDS=30
VELOCIRAPTOR_DEFAULT_ALLOWLIST=["Generic.Client.Info","Windows.System.Services","Windows.System.Pslist","Windows.Network.Netstat","Windows.Network.NetstatEnriched","Windows.Network.Listeners","Windows.Forensics.Prefetch","Windows.EventLogs.Reboot","Windows.EventLogs.LogFile","Windows.ScheduledTasks.Catalog","Windows.StartupItems.Persist","Windows.Registry.Recursive","Windows.Registry.System","Windows.Registry.User"]

# ─── LLM (DFIR AI Assistant) ────────────────────────────────
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

### 6.8. `/.env` (file thật — không commit)

User tạo bằng `cp .env.example .env` rồi generate secrets:

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('DATA_ENCRYPTION_KEY=' + secrets.token_hex(32))"
```

---

## 7. Workflow sử dụng

### 7.1. Lần đầu setup

```bash
cd /home/windowsId
cp .env.example .env
# Generate + paste secrets vào .env
docker compose up -d --build
docker compose logs -f api portal
```

Truy cập:
- Portal: http://localhost:3003
- API docs: http://localhost:8000/docs

### 7.2. Daily dev

| Tác vụ | Lệnh |
|---|---|
| Khởi động | `docker compose up -d` |
| Dừng (giữ data) | `docker compose down` |
| Dừng + **xoá DB** | `docker compose down -v` |
| Xem log tất cả | `docker compose logs -f` |
| Xem log riêng api | `docker compose logs -f api` |
| Restart 1 service | `docker compose restart api` |
| Rebuild image (sau khi đổi Dockerfile/pyproject) | `docker compose build api && docker compose up -d api` |
| Rebuild tất cả | `docker compose build && docker compose up -d` |

### 7.3. Debug

```bash
docker compose exec api bash                  # shell api
docker compose exec portal sh                 # shell portal
docker compose exec postgres psql -U inventory -d inventory
docker compose exec redis redis-cli
docker compose exec api alembic current       # check migration
docker compose exec api alembic upgrade head  # apply migration
docker compose exec api env | grep -E "DATABASE|REDIS|SECRET|PORTAL"
```

### 7.4. Thêm dependency

**Python:**
```bash
# Cách 1 (khuyến nghị): edit pyproject.toml → rebuild
$EDITOR server/pyproject.toml
docker compose build api && docker compose up -d api

# Cách 2 (quick, mất khi restart container): pip install
docker compose exec api pip install <package>
```

**Node:**
```bash
# Cách 1 (khuyến nghị): edit package.json → rebuild
$EDITOR portal/package.json
docker compose build portal && docker compose up -d portal

# Cách 2 (quick): pnpm add — ghi vào named volume `portal_node_modules`,
# KHÔNG update host's package.json. Sau khi rebuild image, package mất (trừ khi đã update package.json).
docker compose exec portal pnpm add <package>
```

> ⚠️ **Lưu ý quan trọng:** Cách 2 chỉ để debug nhanh. Trước khi commit/merge, **phải update file manifest tương ứng** (`server/pyproject.toml` hoặc `portal/package.json` + `pnpm-lock.yaml`) để khi rebuild image, package được cài lại đúng cách.

---

## 8. Troubleshooting

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `port is already allocated` | Port 8000/3003/5432/6381 đã bị chiếm | `lsof -i :<port>` tìm process; kill hoặc đổi `*_PORT` trong `.env` |
| `alembic upgrade head` fail | DB chưa healthy / URL sai | `docker compose logs api`; kiểm tra `DATABASE_URL` compose override |
| Portal không gọi được API | `API_BASE` sai | `docker compose exec portal env \| grep API_BASE` phải là `http://api:8000` |
| `node_modules` lỗi / Next.js fail | Mount che mất container's `node_modules` | Check `portal_node_modules` declared; `docker compose down -v && docker compose up -d --build` |
| Hot reload không bắt | Uvicorn cache / mount issue | Sửa file trong `./server/app/` save lại; `docker compose logs api` xem reload message |
| Reset triệt để | DB + image cache cũ | `docker compose down -v && docker compose up -d --build` |
| Image cũ / volume rác | Docker cache đầy | `docker system prune -a` (cẩn thận) |
| pnpm version mismatch | Lockfile cũ, `pnpm@latest` không đọc được | Pin pnpm version trong `Dockerfile.dev` |

---

## 9. Self-review

### 9.1. Placeholder scan

- Không có "TBD" / "TODO" trong spec.
- Tất cả giá trị placeholder (CHANGE_ME_*) đã được giải thích cách generate.

### 9.2. Internal consistency

- `docker-compose.yml` §6.1 dùng đúng các biến từ `.env.example` §6.7 (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, *_PORT, DATABASE_URL override, REDIS_URL override, CORS_ORIGINS).
- `server/Dockerfile.dev` §6.2 cài đúng các deps liệt kê trong `server/pyproject.toml` (verified qua danh sách đã chốt).
- `portal/Dockerfile.dev` §6.3 dùng `pnpm` để khớp với `portal/pnpm-lock.yaml`.
- Cổng đã chốt (8000/3003/5432/6381) consistent xuyên suốt spec.
- Volume names (`pgdata`, `redisdata`, `portal_node_modules`, `portal_next`) consistent giữa `volumes:` section và `services:` mount.

### 9.3. Scope check

- Single implementation plan: tạo 8 file + sửa 1 file + xoá 4 file. Đủ nhỏ cho 1 plan.
- Không cần decompose thành nhiều sub-projects.

### 9.4. Ambiguity check

- Tất cả config có default rõ ràng (qua `${VAR:-default}`).
- Lệnh copy-paste-able — không có bước "tuỳ ý interpret".
- Trong container `api`, `DATABASE_URL` được compose override — không có rủi ro hiểu nhầm là dùng `localhost`.
- Hot reload giới hạn bằng `--reload-dir /app/app` — không ambiguity về scope watch.

---

## 10. README.md snippet (cần thêm vào `/README.md`)

````markdown
## Phát triển với Docker

Repo hỗ trợ chạy toàn bộ stack (postgres + redis + api + portal) bằng Docker Compose.
Stack dev có hot reload — sửa code trong `server/app/` hoặc `portal/app/` sẽ tự refresh.

### Yêu cầu

- Docker Engine ≥ 24, Docker Compose v2 (`docker compose`, không phải `docker-compose`)

### Setup lần đầu

```bash
cp .env.example .env
# Sửa SECRET_KEY, DATA_ENCRYPTION_KEY, SEED_ADMIN_PASSWORD (xem comment trong file)

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

---

## 11. Open questions / Future work

- **F1.** Production stack riêng (multi-stage Dockerfile, secrets từ Vault, TLS qua Nginx Proxy Manager) — sẽ là spec khác.
- **F2.** Khi user move Velociraptor sang máy khác, cần đảm bảo `VELOCIRAPTOR_DEFAULT_URL` trỏ đúng LAN IP của máy mới.
- **F3.** step-ca container có cần không nếu user muốn test mTLS end-to-end locally? Hiện `CA_MODE=local` đủ cho dev; nếu cần test mTLS qua nginx, sẽ cần step-ca container.
- **F4.** CI/CD — build images trên CI, push registry, deploy qua compose/swarm/k8s. Ngoài scope spec này.
