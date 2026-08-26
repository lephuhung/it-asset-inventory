# API CONTRACT — Hệ thống IT Asset Inventory (Phase 1 MVP)

> Hợp đồng dùng chung cho 3 thành phần: `agent/` (C#), `server/` (FastAPI), `portal/` (Next.js).
> **v1.4 — khớp implementation thực tế của server** (đã verify 78/78 test). Mọi dev khi code PHẢI bám đúng file này; thay đổi phải sửa contract trước.
>
> **v1.4 (2026-08-26)**: refactor schema thống kê phía server — bảng `machine_current` +
> `machine_software` (xem mục 3.7). **Agent KHÔNG đổi**: payload v1/v2/v3 vẫn được chấp nhận
> nguyên vẹn; mọi chuẩn hóa (os_product/os_release/os_family, security → cột) do server tính.

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

Request (tất cả trường optional — agent không đọc được trường nào thì bỏ trống). Đây là
payload **chuẩn agent Windows đẩy lên** (schema v2 — đầy đủ cpu/disks+partitions/gpu/
mainboard/bios/network mở rộng/installed_software/security):
```json
{
  "os_name": "Windows 11 Pro 25H2",
  "os_version": "10.0.26200",
  "os_build": "26200",
  "os_arch": "X64",
  "os_installed_at": "2024-05-15T08:30:00Z",
  "activation_status": "Licensed",
  "is_vm": false,
  "logged_user": "DESKTOP-EATRCNQ\\LPH",
  "config_hash": "a1b2c3d4e5f6...",
  "cpu": { "model": "13th Gen Intel(R) Core(TM) i7-13700H", "cores": 14, "threads": 20, "clock_mhz": 2400, "virtualization_enabled": true },
  "ram_gb": 31.7,
  "disks": [
    {
      "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00",
      "size_bytes": 1024209543168,
      "bus_type": "NVMe",
      "media_type": "SSD",
      "smart_health": "OK",
      "partitions": [ { "drive_letter": "C:", "total_bytes": 511000000000, "free_bytes": 320000000000, "file_system": "NTFS" } ]
    }
  ],
  "gpu": { "model": "NVIDIA GeForce RTX 4060 Laptop GPU", "driver_version": "31.0.15.5123", "memory_mb": 8192 },
  "mainboard": { "manufacturer": "Dell Inc.", "product": "0K5R1T", "serial": "/ABC1234/CN123456789/", "version": "A00" },
  "bios": { "vendor": "Dell Inc.", "version": "1.14.0", "release_date": "2024-01-10", "smbios_version": "3.5" },
  "network": [
    {
      "name": "Wi-Fi (Intel(R) Wi-Fi 6E AX211 160MHz)",
      "ip": "10.10.0.253",
      "mac": "00:1A:2B:3C:4D:5E",
      "is_dual_homed": false,
      "gateway": "10.10.0.1",
      "dhcp_enabled": true,
      "dns_servers": ["10.10.0.1", "8.8.8.8"],
      "speed_mbps": 1200
    }
  ],
  "installed_software": [
    {
      "display_name": "Google Chrome",
      "version": "127.0.6533.100",
      "publisher": "Google LLC",
      "install_date": "2024-08-10",
      "uninstall_string": "\"C:\\Program Files\\Google\\Chrome\\...\"",
      "is_per_user": false
    }
  ],
  "security": {
    "antivirus": [ { "displayName": "Windows Defender", "enabled": true, "upToDate": true } ],
    "windows_update_status": "up-to-date",
    "bitlocker": "on",
    "rdp_enabled": false,
    "local_accounts": [ { "username": "Administrator", "full_name": "Quản trị hệ thống", "disabled": true, "has_password": true, "is_admin": true } ],
    "smarts": [ { "device": "PhysicalDrive0", "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00", "health": "OK" } ]
  }
}
```

Ghi chú:
- **Backward-compat**: payload cũ (v1 — `cpu.{model,cores}`, `disks[].{serial,size_gb,type}`,
  `security.antivirus[].{name,status}`…) vẫn được chấp nhận; trường lạ bị bỏ qua (không 422).
- **Alias/legacy fields**: agent gửi song song cả hai tên (vd `installed_software[].{display_name,name}`,
  `security.antivirus[].{displayName,name,status,enabled}`, `security.local_accounts[].{username,name}`,
  `disks[].{size_bytes,size,size_gb}`, `mainboard.{model,manufacturer,product}`) — server giữ nguyên
  tất cả, front-end ưu tiên đọc tên chuẩn v2 rồi fallback v1.
- **Security mở rộng (v3)**: `firewall_enabled`, `uac_enabled`, `secure_boot_enabled`,
  `usb_storage_blocked`, `weak_protocols.{smbv1_disabled,tls10_disabled,tls11_disabled,ssl3_disabled}`,
  `listening_ports[].{port,protocol,address}`, `startup_programs[].{name,command,location}` — lưu
  trong JSONB `security`, portal hiển thị ở thẻ "Trạng thái bảo mật".
- `config_hash` do agent tính (sha256 của payload trừ chính `config_hash`) — server không nhận
  thì tự tính. Gửi lại cùng hash → `config_changed=false`, không lưu snapshot trùng.
- Trường sai kiểu (vd `cpu.threads` là chuỗi) → **422**, không lưu dữ liệu hỏng.

Response 200: `{ "ok": true, "config_changed": false }`

- Gửi: lần đầu sau enroll, khi cấu hình thay đổi (config_hash mới), định kỳ `inventory_interval_hours` (24h).
- Máy lưu đủ: os (kể cả `os_installed_at`, `activation_status`), cpu, ram, disks+partitions,
  gpu, mainboard, bios, network (kể cả `gateway`/`dhcp_enabled`/`dns_servers`/`speed_mbps`),
  logged_user, installed_software, security (kể cả nhóm mở rộng v3), config_hash — trả về qua
  `GET /api/machines/{id}` → `latest_spec`.

### 3.7. Chuẩn hóa dữ liệu phía server (v1.4 — agent KHÔNG cần đổi)

Kể từ v1.4, khi nhận inventory server ghi **thêm** 2 bảng phục vụ thống kê (cùng transaction
với `machine_specs` — xem `docs/REFACTOR_SCHEMA_THONG_KE.md`):

| Bảng | Vai trò | Ghi khi |
|---|---|---|
| `machine_current` | Snapshot **mới nhất** của mỗi máy (1:1 với machines), OS/security là **cột có index** | Upsert mỗi lần nhận inventory |
| `machine_software` | Phần mềm đã cài — **1 dòng/app/máy** (unique `machine_id + lower(name)`) | Replace toàn bộ app của máy (delete + insert) |

Chuẩn hóa **phía server** từ payload agent gửi (agent giữ nguyên):

- `os_product` (ProductName thuần, VD "Windows 11 Pro") + `os_release` (DisplayVersion, VD "25H2"):
  tách từ `os_name` (token `\d{2}H\d` ở đuôi) hoặc fallback `os_version`. Lý do: `os_version`
  luôn là `10.0.<build>` cho CẢ Win10 lẫn Win11 → không phân biệt được.
- `os_family` (windows_10 | windows_11 | windows_server_YYYY | linux | other): phân loại theo
  ProductName — dùng cho thống kê "số máy Win10/Win11" (GROUP BY).
- Security (JSONB) → cột phẳng có kiểu: `firewall_enabled`, `windows_update_status`,
  `windows_update_enabled` (suy từ status: up-to-date/pending/checking/enabled → true;
  disabled/off/never/paused → false), `antivirus_enabled`, `antivirus_up_to_date`,
  `bitlocker`, `uac_enabled`, `secure_boot_enabled`, `rdp_enabled`, `usb_storage_blocked`.
- `installed_software` → dòng chuẩn `{name, version, publisher, install_date}` (name ưu tiên
  `display_name`, fallback `name`).

> ⚠️ Agent hiện tại **chưa gửi** `firewall_enabled`/`windows_update_status` (chỉ có trong schema
> v3 và payload test) — các thống kê tương ứng trả `unknown` cho tới khi agent release mới
> bổ sung collector. Đây là giới hạn dữ liệu, không phải lỗi schema.

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
| GET | /api/stats/inventory | thống kê cấu hình **hiện tại**: `total_machines`, `by_os_family` (Win10/Win11…), `by_os_arch`, `by_is_vm`, `by_ram_gb` (`<4/4–8/8–16/16–32/32+ GB` + `unknown`), `by_firewall`, `by_windows_update_status/enabled`, `by_antivirus`, `by_bitlocker`, `top_software` (query: `org_id`?, `top_software_limit`=20, max 100) |
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
