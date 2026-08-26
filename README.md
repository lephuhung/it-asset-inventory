# IT Asset Inventory — Hệ thống quản lý tài sản máy tính (Agent – Server)

Mô hình Agent – Server, dữ liệu sống realtime, định danh đa nguồn, bảo mật mTLS, agent Windows read-only zero-GUI.
Căn cứ thiết kế: [`KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md`](KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md) v1.2 · [`PLAN_THUC_HIEN.md`](PLAN_THUC_HIEN.md) v1.3 · hợp đồng API: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) · vận hành: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Cấu trúc repo (mono)

| Thư mục | Thành phần | Công nghệ | Trạng thái |
|---|---|---|---|
| `server/` | API Server + nginx + step-ca | FastAPI (Python 3.12), PostgreSQL 16, Redis 7 | ✅ Hoàn chỉnh — 68/68 test |
| `portal/` | Portal quản trị | Next.js 16 (App Router, TypeScript, Tailwind), BFF proxy | ✅ Hoàn chỉnh — build xanh |
| `agent/` | Agent Windows | C# .NET 8 Windows Service | ✅ Hoàn chỉnh — build 0 lỗi, e2e với schema server thật |
| `deploy/` | Helper dev (cert, step-ca, env) | — | ✅ |
| `docs/` | API contract, runbook | — | ✅ |

> **Compose canonical nằm ở `server/deploy/docker-compose.yml`** (postgres :5432, redis :6381, api :8000, nginx :443/:9443). Nginx 2 server block: agent mTLS (9443) + portal (443) — xem `server/deploy/nginx/nginx.conf`.

## Chạy nhanh (dev)

```bash
# 1. Khởi động hạ tầng (PostgreSQL + Redis + API)
cd server && cp .env.example .env   # sửa secret trước khi chạy
cd server/deploy && docker compose up -d postgres redis   # DB :5432, Redis :6381

# 2. Migration + chạy API
cd server && .venv/bin/pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload        # → http://127.0.0.1:8000/docs

# 3. Portal
cd portal && pnpm install && pnpm dev   # → http://localhost:3003

# 4. Tạo chứng chỉ dev tạm (nếu cần mTLS demo)
bash deploy/certs/gen-dev-certs.sh
```

Tài khoản seed mặc định: `admin@example.gov.vn` (xem `server/.env` → `SEED_ADMIN_*`).

## Test

```bash
cd server && .venv/bin/pytest -q          # 68 tests (cần PG test trên localhost:5432)
cd portal && pnpm typecheck && pnpm build
cd agent && dotnet build -c Release       # 0 lỗi trên Linux; e2e: python3 tools/mock_server.py + agent --once
```

## Tính năng đã có (Phase 1 + một phần 2/3)

- **Agent kênh:** enroll (token 1 lần → mTLS), heartbeat ~30s±8s jitter, inventory, renew cert tự động, `GET /api/agent/config` (config-driven), on-demand rescan, audit log hash chain.
- **Portal:** login + 2FA TOTP (backup codes), dashboard realtime (WebSocket), quản lý máy/token (phễu triển khai, one-liner), báo cáo Excel (mask SĐT), xác nhận tuân thủ pháp lý, audit, cây tổ chức UBND xã, self-service enroll (`/enroll/[code]`), alerts/drifts/EOL/offline-import.
- **Bảo mật:** mTLS qua nginx (X-SSL-Client-* headers), AES-256-GCM cho SĐT/TOTP seed, JWT httpOnly cookie + auto-refresh, RBAC theo cây org, rate-limit, `install.ps1` verify chữ ký trước khi cài.
