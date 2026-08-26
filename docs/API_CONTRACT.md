# API CONTRACT — Hệ thống IT Asset Inventory (Phase 1 MVP)

> Hợp đồng dùng chung cho 3 thành phần: `agent/` (C#), `server/` (FastAPI), `portal/` (Next.js).
> **v1.3 — khớp implementation thực tế của server** (đã verify 67/67 test). Mọi dev khi code PHẢI bám đúng file này; thay đổi phải sửa contract trước.

---

## 1. Quy ước chung

- **Định dạng:** JSON UTF-8, `Content-Type: application/json; charset=utf-8`.
- **Thời gian:** ISO 8601 UTC (`2025-01-01T00:00:00Z`).
- **Mã hóa truyền tải:** TLS 1.2+; sau enroll là **mTLS**. Không mã hóa chồng tầng ứng dụng.
- **Payload flat** (không envelope) trong Phase 1: agent gửi trực tiếp schema của từng endpoint. Envelope `{schema_version, request_id, ts}` dự kiến Phase 2.
- Lỗi: `{ "detail": "..." }` với HTTP status chuẩn (400/401/403/404/409/410/422/429).

## 2. mTLS qua nginx → FastAPI

nginx verify client cert (`ssl_verify_client optional` + CRL) rồi forward header:

| Header | Ý nghĩa |
|---|---|
| `X-SSL-Client-Verify` | `SUCCESS` — bắt buộc cho /api/heartbeat, /api/inventory, /api/renew, /api/agent/config |
| `X-SSL-Client-CN` | **`machine-<uuid>`** (CN của client cert do server cấp) — FastAPI tách prefix `machine-` |
| `X-SSL-Client-Serial` | serial cert (phục vụ revoke khi renew) |

- FastAPI chỉ bind IP nội bộ, chỉ nhận traffic từ nginx. Setting `require_agent_mtls_header=True` (prod) → app tự chặn verify != SUCCESS.
- Endpoint `/api/enroll` và `/i/{token}` KHÔNG cần client cert (dùng HTTPS + token).

## 3. Agent API (đã khớp server)

### 3.1. POST /api/enroll (không mTLS, rate-limit 30/min theo IP)

Request:
```json
{
  "token": "t_Ab3xK9mQ2vR8nL4p...",
  "hostname": "PC-042",
  "fingerprint": {
    "smbios_uuid": "4C4C4544-... | null",
    "machine_guid": "hash-sha256-hex | null",
    "mainboard_serial": "hash-sha256-hex | null"
  },
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----... (ECDSA P-256, CN=machine-<uuid> bất kỳ)"
}
```

Response 200:
```json
{
  "machine_id": "uuid",
  "client_cert_pem": "-----BEGIN CERTIFICATE-----...",
  "ca_cert_pem": null,
  "renew_after": "2025-...Z",
  "is_new_machine": true,
  "status": "online",
  "agent_server_url": "https://agent.example.gov.vn",
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8,
  "inventory_interval_hours": 24
}
```

- Token sai → 401; hết hạn → 401 (server tự đổi status expired); đã dùng → 401; revoked → 401.
- Fuzzy-match: máy cũ (ghost Win/thay linh kiện) → cấp lại machine_id cũ, `is_new_machine=false`; drift → server ghi `fingerprint_drifts` chờ duyệt.
- **Cert**: ECDSA P-256, CN=`machine-<machine_id>`, hiệu lực `client_cert_valid_days` (365). Agent phải lưu private key (KHÔNG gửi lên server), cài cert vào Windows Certificate Store.
- Agent phải **lưu config** từ response: endpoints (=agent_server_url), heartbeat interval/jitter, inventory interval.

### 3.2. POST /api/heartbeat (mTLS bắt buộc)

Request:
```json
{
  "logged_user": "DOMAIN\\nguyenvana | null",
  "uptime_sec": 12345,
  "ip": "10.0.0.42 | null"
}
```

Response 200:
```json
{
  "ok": true,
  "server_time": "2025-01-01T00:00:05Z",
  "renew_after": "2025-...Z",
  "rescan_requested": false,
  "notice_version": "v1 | null",
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8
}
```

- Agent gửi theo chu kỳ ngẫu nhiên trong `[interval-jitter, interval+jitter]` (mặc định 30±8s ≈ 22–38s).
- Agent đồng bộ interval/jitter từ response (server điều chỉnh 1 chỗ).
- `rescan_requested=true` → agent chạy inventory ngay (Phase 3 on-demand).

### 3.3. POST /api/inventory (mTLS bắt buộc)

Request (flat, tất cả trường optional):
```json
{
  "os_name": "Windows 11 Pro",
  "os_version": "10.0.22631",
  "os_build": "22631",
  "os_arch": "x64",
  "os_installed_at": "2024-...Z",
  "activation_status": "licensed",
  "cpu": { "model": "...", "cores": 8 },
  "ram_gb": 16.0,
  "disks": [ { "model": "...", "serial": "...", "size_gb": 512, "type": "SSD" } ],
  "gpu": { "model": "..." },
  "mainboard": { "model": "...", "serial": "..." },
  "bios": { "version": "..." },
  "network": [ { "name": "Ethernet", "ip": "10.0.0.42", "mac": "AA-BB-...", "is_dual_homed": false } ],
  "logged_user": "DOMAIN\\nguyenvana",
  "installed_software": [ { "name": "...", "version": "..." } ],
  "security": {
    "antivirus": [ { "name": "...", "status": "enabled" } ],
    "windows_update_status": "up-to-date",
    "bitlocker": "on",
    "rdp_enabled": false,
    "local_accounts": [ { "name": "...", "has_password": true } ],
    "smarts": [ { "disk": "C:", "health": "ok" } ]
  },
  "is_vm": false,
  "config_hash": "sha256-của-payload"
}
```

Response 200: `{ "ok": true, "config_changed": false }`

- Gửi: lần đầu sau enroll, khi cấu hình thay đổi (config_hash mới), định kỳ `inventory_interval_hours` (24h).

### 3.4. POST /api/renew (mTLS bắt buộc) — tự gia hạn client cert

Request: `{ "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----..." }`

Response 200:
```json
{
  "client_cert_pem": "-----BEGIN CERTIFICATE-----...",
  "ca_cert_pem": null,
  "cert_serial": null,
  "renew_after": "2025-...Z"
}
```

- Agent gọi khi cert còn < `renew_before_percent` (70%) vòng đời — lấy từ `GET /api/agent/config` hoặc tự tính theo `renew_after`.
- Server thu hồi cert cũ (serial từ X-SSL-Client-Serial) rồi ký cert mới cùng CN=`machine-<uuid>`.

### 3.5. GET /api/agent/config (mTLS bắt buộc) — config-driven

Response 200:
```json
{
  "server_url": "https://agent.example.gov.vn",
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8,
  "online_ttl_seconds": 76,
  "inventory_interval_hours": 24,
  "renew_before_percent": 70,
  "server_time": "2025-...Z"
}
```

- Agent gọi định kỳ (VD mỗi 6h) để đồng bộ cấu hình — **binary agent không đổi, hành vi do server điều chỉnh**.

### 3.6. GET /i/{token} — render install.ps1 động (không auth)

- Trả `text/plain` PowerShell: kiểm tra Admin → tải MSI → verify SHA256 + chữ ký Authenticode → `msiexec /qn ENROLL_TOKEN=...` → in "✔ Cài đặt thành công".
- Token hết hạn/đã dùng/revoked → 401/404.

## 4. Portal API (JWT Bearer, RBAC)

Roles: `super_admin` (toàn quyền), `org_admin` (cây org của mình + cấp dưới), `viewer` (read-only).

| Method | Path | Mô tả |
|---|---|---|
| POST | /api/auth/login | `{email, password, totp_code?}` → `{access_token, refresh_token, token_type, requires_2fa}` |
| POST | /api/auth/refresh | `{refresh_token}` → LoginResponse |
| POST | /api/auth/logout | thu hồi refresh |
| GET | /api/auth/me | thông tin user hiện tại |
| POST | /api/auth/totp/setup | → `{secret, uri, backup_codes}` |
| POST | /api/auth/totp/confirm | `{code}` → bật 2FA, trả LoginResponse |
| GET | /api/compliance/current | bản tuân thủ hiện hành (hoặc null) |
| GET | /api/compliance/pending | `bool` — user còn phải xác nhận? |
| POST | /api/compliance/acknowledge | ghi xác nhận |
| POST | /api/tokens | `{org_id, full_name, department, position, email?, phone?, note?, ttl_hours=72}` → `{token, install_command, expires_at}` — **token hiện 1 lần** |
| POST | /api/tokens/bulk | CSV hàng loạt → `{created, errors}` |
| GET | /api/tokens?status= | phễu triển khai |
| POST | /api/tokens/revoke | `{token_id}` |
| GET | /api/machines?org_id=&status=&q= | danh sách máy |
| GET | /api/machines/{id} | chi tiết + latest_spec |
| GET | /api/machines/stats | thống kê |
| POST | /api/machines/{id}/approve · /reject · /rescan · PATCH /lifecycle | vận hành |
| GET | /api/machines/{id}/timeline | lịch sử bật/tắt |
| GET | /api/stats/overview | `{total_machines, online, ...}` |
| POST | /api/reports/export | Excel (mask SĐT mặc định) |
| POST | /api/reports/export-pdf | PDF (Phase 4) |
| GET | /api/orgs | cây tổ chức |
| GET | /api/audit? | audit read-only (super_admin) |
| GET | /api/audit/verify | kiểm tra hash chain |
| GET | /api/ws?token= | WebSocket: `{type:"machine_status", machine_id, status, ts}` + `{type:"stats", ...}` |

## 5. Trạng thái máy & token

- Máy: `online` | `offline` | `lost` | `decommissioned` | `pending` (chờ duyệt).
- Token: `pending` | `used` | `revoked` | `expired`. TTL mặc định 72h, `max_uses=1`, entropy ≥ 128 bit, dạng `t_` + base62.
- Online lưu Redis `machine:online:{id}` TTL = `online_ttl_seconds` (mặc định 2×(interval+jitter) = 76s).

## 6. Nguyên tắc agent (bắt buộc — mục 7 API_CONTRACT cũ, giữ nguyên)

- **Read-only**: chỉ đọc WMI/Registry; không hook/inject/đọc process khác; không ghi ngoài ProgramData + cert store.
- **Zero-GUI**: không window/notification. Config `%ProgramData%\OrgInventory\config.json`; log xoay vòng `%ProgramData%\OrgInventory\logs\`.
- **Fingerprint**: SMBIOS UUID (WMI Win32_ComputerSystemProduct / fallback registry), MachineGuid (HKLM\SOFTWARE\Microsoft\Cryptography), serial mainboard — gửi 3 nguồn riêng, server tính hash trọng số.
- **Heartbeat**: chu kỳ `[interval-jitter, interval+jitter]` (mặc định 30±8s), ngẫu nhiên mỗi lần — tránh pattern C2.
- **Failover endpoint**: `endpoints[]` (server_url + backup); primary lỗi 5 lần liên tiếp → chuyển backup; thử lại primary định kỳ.
- **Idempotent install**: có cert + machine_id trong config → bỏ qua enroll, chỉ repair/update.
- **Offline cache**: SQLite `%ProgramData%\OrgInventory\cache.db`; gửi bù khi có mạng (giữ nguyên dữ liệu).
- **Private key client cert**: sinh local (ECDSA P-256), lưu Windows Certificate Store, KHÔNG gửi lên server.
- User-Agent: `OrgInventoryAgent/x.y.z`.
