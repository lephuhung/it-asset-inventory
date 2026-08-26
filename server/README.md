# IT Asset Inventory — Server (FastAPI)

Phần server của hệ thống quản lý tài sản máy tính. Bám sát `PLAN_THUC_HIEN.md` (Phase 1 Sprint 1–2).

## Công nghệ

- **FastAPI** (Python 3.12) + uvicorn
- **SQLAlchemy 2.0** (async) + Alembic; **PostgreSQL 16** (JSONB, UUID) — DB duy nhất
- **Redis** — trạng thái online (TTL) + pub/sub realtime (WebSocket)
- **step-ca** — CA nội bộ cho mTLS (client cert); `CA_MODE=local` cho dev/test
- **JWT + RBAC** theo cây tổ chức, **2FA TOTP** (RFC 6238) cho admin
- **AES-256-GCM** — mã hóa số điện thoại / seed TOTP (khóa trong Vault ở prod)
- **Audit log** append-only + hash chain (phát hiện giả mạo)

## Cấu trúc

```
server/
├── app/
│   ├── main.py              # entry point
│   ├── core/                # config, security (JWT/AES/TOTP), audit hash chain
│   ├── db/                  # models, session, base
│   ├── schemas/             # Pydantic (request/response)
│   ├── services/            # ca.py (step-ca/local), fingerprint, phone_encryption
│   ├── api/
│   │   ├── deps.py          # auth JWT, RBAC, mTLS header Depends
│   │   └── routes/          # auth, enroll, heartbeat, inventory, tokens, machines, stats, compliance, install
│   └── templates/           # install.ps1.j2
├── alembic/                 # migrations
├── deploy/
│   ├── docker-compose.yml   # postgres + redis + api + nginx
│   └── nginx/nginx.conf     # 2 server block: agent mTLS / portal TLS
└── tests/                   # pytest (unit + API integration)
```

## Chạy

```bash
# 1. Cài dependency
pip install -e ".[dev]"        # hoặc: pip install -r <(danh sách trong pyproject)

# 2. Tạo .env
cp .env.example .env
#   - sửa DATABASE_URL, SECRET_KEY, DATA_ENCRYPTION_KEY (đừng để mặc định)

# 3. Migration
alembic upgrade head

# 4. Khởi động PostgreSQL + Redis (Docker)
cd deploy && docker compose up -d postgres redis   # PG :5432, Redis :6381

# 5. Migration + chạy dev
alembic upgrade head
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs   (OpenAPI tự sinh)
```

## Test

```bash
.venv/bin/python -m pytest -q
```

## API chính

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/auth/login` | Đăng nhập (JWT + 2FA TOTP) |
| POST | `/api/tokens` | Sinh token enroll (1 token = 1 máy) |
| GET | `/i/{token}` | Render install.ps1 nhúng token |
| POST | `/api/enroll` | Agent enroll (token + fingerprint + CSR → step-ca ký) |
| POST | `/api/heartbeat` | Agent heartbeat (mTLS header từ nginx) |
| POST | `/api/inventory` | Agent gửi snapshot cấu hình |
| GET | `/api/machines` | Danh sách máy (lọc org/status/tìm kiếm) |
| GET | `/api/stats/overview` | Thống kê dashboard |
| GET | `/api/compliance/current` | Thông báo tuân thủ hiện hành |
| POST | `/api/reports/export` | Xuất Excel danh sách máy (lọc org/status/q) |
| GET | `/api/agent/config` | Cấu hình agent (mTLS): heartbeat, online TTL, inventory... |
| WS | `/api/ws?token={jwt}` | Realtime dashboard (Redis pub/sub machine events) |

## Cấu hình agent (IP remote + tần suất heartbeat)

**Nguyên tắc: cấu hình 1 chỗ trên server, agent tự đồng bộ.**

- Operator chỉnh trong `.env`: `AGENT_SERVER_URL` (IP remote mà agent liên hệ cho kênh mTLS),
  `HEARTBEAT_INTERVAL_SECONDS` (mặc định 60), `HEARTBEAT_JITTER_SECONDS` (15),
  `INVENTORY_INTERVAL_HOURS` (24). `ONLINE_TTL_SECONDS` để trống → tự tính
  `2 × (interval + jitter)`, hoặc override nếu muốn.
- **Enroll response** trả `agent_server_url` + config → agent biết liên hệ đâu sau khi enroll.
- **Heartbeat response** trả `heartbeat_interval_seconds`/`heartbeat_jitter_seconds` → agent
  điều chỉnh tần suất theo server (operator đổi config không cần cài lại agent).
- **`GET /api/agent/config`** (mTLS) — agent lấy toàn bộ cấu hình khi cần (sau restart).
- Agent local override (nếu cơ quan muốn khác biệt từng máy): `config.json` trong ProgramData —
  xem contract tại `app/templates/agent_config.example.json`.

> ⚠️ Không chỉnh jitter=0 / interval cố định — bị AV coi là beaconing C2 (mục 3.2 tài liệu gốc).

## Báo cáo Excel (`POST /api/reports/export`)

- Query params: `org_id`, `status` (online/offline/lost/decommissioned/pending), `q` (hostname/uuid), `include_phone_full`.
- Workbook 3 sheet:
  - **Máy tính** — STT, hostname, mã hash, trạng thái, vòng đời, VM?, OS/build, CPU, RAM, ổ đĩa, người dùng, email, **SĐT (mask `0987•••321` mặc định)**, phòng ban, tổ chức, last_seen, enrolled_at, ghi chú.
  - **Thống kê** — tổng máy, phân bổ theo trạng thái & tổ chức.
  - **Thông tin thu thập** — thông báo tuân thủ (mục 7.4) minh bạch dữ liệu thu thập.
- RBAC: admin cơ quan chỉ export máy trong org; SĐT đầy đủ chỉ khi `include_phone_full=true` + vai trò admin.
- Mọi export được ghi vào `audit_log` (action `report.export`).

## Realtime (WebSocket /api/ws)

- Auth bằng JWT qua query param `?token=`; subscriber Redis `machine:events`.
- Sự kiện `{type:"machine_event", machine_id, status, hostname, ts}` được đẩy khi:
  - Máy chuyển **offline→online** (heartbeat đầu sau khi lên).
  - Background monitor phát hiện máy hết hạn → chuyển **online→offline**.
- Subscribe trước khi gửi hello để không mất message.

## Heartbeats partition theo ngày (PostgreSQL)

- Migration tạo `heartbeats` dạng `PARTITION BY RANGE (ts)` + `heartbeats_default`.
- `app/services/partition.py::ensure_heartbeat_partitions` tự tạo daily partition;
  background monitor đảm bảo luôn có partition 7 ngày tới.
- Index trên parent tự áp dụng cho mỗi partition.

## Sprint đã hoàn thành

- [x] Skeleton FastAPI + Docker compose + nginx config
- [x] DB schema v1 + Alembic migration (PostgreSQL, JSONB/UUID)
- [x] **Heartbeats partition theo ngày** + job tự tạo partition
- [x] Auth JWT + RBAC + 2FA TOTP
- [x] Enroll (token + fingerprint fuzzy-match + step-ca ký CSR)
- [x] Heartbeat + online status Redis (TTL)
- [x] Inventory (snapshot, chỉ lưu khi hash đổi)
- [x] Sinh/liệt kê/revoke token, render install.ps1
- [x] Audit log append-only + hash chain
- [x] Compliance notice + xác nhận
- [x] **WebSocket realtime** + background monitor (offline detection)
- [x] **Báo cáo Excel** (3 sheet + mask SĐT + RBAC + audit)
- [x] **Cấu hình agent** (IP remote + heartbeat interval/jitter qua enroll/heartbeat/config)
- [x] Tests (39 cases) + E2E smoke test (REST + WebSocket + Excel)
- [ ] Agent C# + install.ps1 ký số (track riêng)

## Bảo mật lưu ý

- **mTLS**: nginx verify client cert (`ssl_verify_client optional`) → forward `X-SSL-Client-*` header vào FastAPI. App chỉ bind IP nội bộ (chống giả header). Trong prod bật `REQUIRE_AGENT_MTLS_HEADER=true`.
- **Enroll dùng token** (không phải mTLS) — vì agent chưa có cert trước khi enroll.
- **WebSocket** auth bằng JWT query param; nên giới hạn CORS/origin trong prod.
- Các khóa bí mật (AES key, DB password) **không hardcode** — dùng Vault/KMS trong prod.
