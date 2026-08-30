# IT Asset Inventory — Hệ thống quản lý tài sản máy tính (Agent – Server)

> **Đơn vị phát triển:** Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh  
> **Mục đích:** Quản lý tài sản CNTT, kiểm kê cấu hình phần cứng, danh mục phần mềm và đánh giá an toàn thông tin (Security Posture) phục vụ công tác bảo đảm an ninh mạng và an toàn thông tin trong các cơ quan, đơn vị.  

Mô hình Agent – Server, dữ liệu sống realtime, định danh đa nguồn, bảo mật mTLS, agent Windows read-only zero-GUI.
Căn cứ thiết kế: [`KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md`](KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md) v1.2 · [`PLAN_THUC_HIEN.md`](PLAN_THUC_HIEN.md) v1.3 · hợp đồng API: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) · vận hành: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Cấu trúc repo (mono)

| Thư mục | Thành phần | Công nghệ | Trạng thái |
|---|---|---|---|
| `server/` | API Server + nginx + step-ca | FastAPI (Python 3.12), PostgreSQL 16, Redis 7 | ✅ Hoàn chỉnh — 68/68 test |
| `portal/` | Portal quản trị | Next.js 16 (App Router, TypeScript, Tailwind), BFF proxy | ✅ Hoàn chỉnh — build xanh |
| `agent/` | Agent Windows + Linux | C# .NET 8 Windows Service / Linux systemd | ✅ Hoàn chỉnh — build 0 lỗi, e2e với schema server thật; .deb/.rpm packaging cho Ubuntu/RHEL |
| `deploy/` | Helper dev (cert, step-ca, env, velociraptor) | — | ✅ |
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

## Đồng bộ GitHub & CI

Repo git đã khởi tạo (nhánh `main`, đã loại cache: node_modules/.next/.venv/bin/obj/.nuget-packages/.env).

```bash
# 1. Tạo repo trên GitHub (khuyến nghị Private), rồi:
git remote add origin git@github.com:<USER>/<REPO>.git
git push -u origin main

# 2. CI chạy tự động mỗi push/PR (xem .github/workflows/ci.yml):
#    - Server: pytest (68 tests, có Postgres service) + ruff
#    - Agent:  dotnet build trên Ubuntu + Windows
#    - Portal: npm run typecheck + build
```

**Phát triển agent trên Windows (theo yêu cầu):**
1. Clone repo trên máy Windows: `git clone <repo> && cd agent`
2. Mở `agent/OrgInventoryAgent.sln` (cần .NET 8 SDK) hoặc `dotnet build -c Release`
3. Build MSI: `.\installer\build-msi.ps1 -Sign -CertificateThumbprint <thumb>` (cần WiX v4: `dotnet tool install --global wix`)
4. Cài thử: `msiexec /i OrgInventoryAgent.msi /qn ENROLL_TOKEN="t_..." ENDPOINTS="https://agent.gov.vn"` (admin)
5. Debug không cần MSI: `OrgInventoryAgent.exe --data-dir C:\temp\at --endpoint https://... --enroll-token ... --once`
6. Log: `%ProgramData%\OrgInventory\logs\agent.log` · config: `%ProgramData%\OrgInventory\config.json`
7. Mỗi commit agent → push → job CI "Agent C# (dotnet build)" chạy trên cả Ubuntu lẫn Windows tự xác nhận build xanh.

**Phát triển agent trên Linux (Ubuntu/Debian + RHEL/Rocky):**

1. Clone repo trên máy Linux: `git clone <repo> && cd agent`
2. Mở `OrgInventoryAgent.sln` (cần .NET 8 SDK) hoặc `dotnet build -c Release`
3. Build package: `bash installer/linux/build-deb.sh linux-x64` (cần `dpkg-deb`) hoặc `bash installer/linux/build-rpm.sh linux-x64` (cần `rpmbuild`)
4. Cài thử: `sudo dpkg -i dist/orginventory-agent_1.1.0_amd64.deb` rồi `sudo bash installer/linux/postinstall-enable.sh` (tự verify helper + enable service)
5. Debug không cần package: `dotnet run --project linux/src/OrgInventoryAgent.Linux -- --data-dir /tmp/at --print-inventory` (xem v4 envelope JSON)
6. Log: `/var/log/orginventory/agent.log` · config: `/etc/orginventory/config.json` (mode 0640, group `orginventory`)
7. Mỗi commit agent → push → job CI build cả Windows lẫn Linux tự xác nhận build xanh.

## Test

```bash
cd server && .venv/bin/pytest -q          # 68 tests (cần PG test trên localhost:5432)
cd portal && pnpm typecheck && pnpm build
cd agent && dotnet build -c Release       # 0 lỗi trên Linux; e2e: python3 tools/mock_server.py + agent --once
```

## Tính năng đã có (Phase 1 + một phần 2/3)

- **Agent kênh:** enroll (token 1 lần → mTLS), heartbeat ~30s±8s jitter, inventory, renew cert tự động, `GET /api/agent/config` (config-driven), on-demand rescan, audit log hash chain.
- **Portal:** login + 2FA TOTP (backup codes), dashboard realtime (WebSocket), quản lý máy/token (phễu triển khai, one-liner), báo cáo Excel (mask SĐT), xác nhận tuân thủ pháp lý, audit, cây tổ chức UBND xã, self-service enroll (`/enroll/[code]`), alerts/drifts/EOL/offline-import.
- **DFIR (Velociraptor):** backend tích hợp [Velociraptor](https://github.com/velocidex/velociraptor) — Super Admin cấu hình Velociraptor Server URL + API Token (AES-256-GCM) + **allowlist artifact** (chống lạm quyền) trên portal. Background task **5 phút/lần** tự động gọi Velociraptor `SearchClients` để đồng bộ `machine.hostname ↔ Velociraptor client_id` — **không phụ thuộc agent**. Admin chạy hunt/collect artifact từ `/dfir` hoặc từ trang máy; kết quả lưu trên Velociraptor Server, portal deep-link sang GUI. Cho phép điều tra số từ xa khi xảy ra sự cố an ninh mạng.
- **Bảo mật:** mTLS qua nginx (X-SSL-Client-* headers), AES-256-GCM cho SĐT/TOTP seed + Velociraptor API Token, JWT httpOnly cookie + auto-refresh, RBAC theo cây org, rate-limit, `install.ps1` verify chữ ký trước khi cài.
