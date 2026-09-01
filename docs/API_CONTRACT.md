# API CONTRACT — Hệ thống IT Asset Inventory (Phase 1 MVP)

> Hợp đồng dùng chung cho 3 thành phần: `agent/` (C#), `server/` (FastAPI), `portal/` (Next.js).
> **v1.6 — tối ưu hóa quy trình 1-click nháy đúp chuột cho máy cách ly** (khớp implementation thực tế của server & portal).
> Mọi dev khi code PHẢI bám đúng file này; thay đổi phải sửa contract trước.
>
> **v1.6 (2026-08-27)**: Chuẩn hóa 2 chế độ triển khai của Agent theo phản hồi thực tế:
> 1. **Chế độ 1 (Trực tuyến — Online / Web Link)**: Cài đặt 1 lệnh copy từ trình duyệt Web Portal (`irm .../i/{token} | iex`), tự động enroll và đẩy dữ liệu liên tục qua mTLS.
> 2. **Chế độ 2 (Ngoại tuyến — Offline / Máy cách ly USB)**: Đơn giản hóa tối đa cho người dùng cuối — **chỉ cần nháy đúp chuột vào file `install-offline` trên USB** (không bắt nhập tham số `-Token` hay `-Endpoints`). Kết quả tự động sinh ra **1 file ZIP được mã hóa và ký số** ngay trên USB. Backend thực hiện giải mã, kiểm tra chữ ký số và tự động parse dữ liệu cập nhật hệ thống.

---

## 1. Mô hình 2 chế độ vận hành & Quy ước chung

### 1.1. Bảng so sánh 2 chế độ hoạt động của Agent

| Tiêu chí | Chế độ 1: Trực tuyến (Online / Web Link) | Chế độ 2: Ngoại tuyến (Offline / Máy cách ly USB) |
|---|---|---|
| **Môi trường máy** | Có mạng LAN / VPN / Internet tới Server | Cách ly hoàn toàn (Air-gapped), không có kết nối tới Server |
| **Thao tác cài đặt** | Copy lệnh 1 dòng từ trình duyệt Portal: `irm https://<host>/i/<token> \| iex` | Cắm USB, **chỉ cần nháy đúp chuột** vào `install-offline` (không cần gõ lệnh, không cần tham số) |
| **Cơ chế thu thập** | Tự động chạy nền (Windows Service), gửi định kỳ qua mTLS | Tự động thực thi ngay khi nháy đúp chuột, xuất ra **1 file ZIP mã hóa** trên USB |
| **Cơ chế an ninh 2 lớp** | Kênh truyền bảo mật **mTLS** trực tiếp (Client Cert ECDSA do CA server cấp) | **Lớp 1: Ký số ECDSA P-256** (chống sửa dữ liệu) + **Lớp 2: Mã hóa gói ZIP bằng Server Public Key** (chống lộ dữ liệu trên USB) |
| **Chuyển dữ liệu lên hệ thống**| Tự động gửi qua mTLS: `POST /api/inventory` (24h/lần hoặc khi cấu hình thay đổi) | Admin mang file ZIP về máy có mạng $\rightarrow$ Upload lên Portal (`/offline-import`) $\rightarrow$ Backend tự giải mã, verify chữ ký và parse dữ liệu |
| **Trạng thái máy** | Tự động gửi `POST /api/heartbeat` (30±8s) $\rightarrow$ `online` | Không gửi heartbeat $\rightarrow$ trạng thái `offline`, cập nhật `last_seen_at` theo thời điểm xuất file |

### 1.2. Quy ước chung

- **Định dạng dữ liệu:** JSON UTF-8, `Content-Type: application/json; charset=utf-8` hoặc `multipart/form-data` (khi upload file ZIP mã hóa).
- **Thời gian:** ISO 8601 UTC (`2025-01-01T00:00:00Z`).
- **Mã hóa truyền tải:** TLS 1.2+; với chế độ trực tuyến sau enroll là **mTLS**. Không mã hóa chồng tầng ứng dụng khi đã có mTLS.
- **Quy ước lỗi:** `{ "detail": "..." }` với HTTP status chuẩn (400/401/403/404/409/410/422/429).

---

## 2. mTLS qua nginx → FastAPI (Chế độ Trực tuyến)

nginx verify client cert (`ssl_verify_client optional` + CRL) rồi forward header:

| Header | Ý nghĩa |
|---|---|
| `X-SSL-Client-Verify` | `SUCCESS` — bắt buộc cho /api/heartbeat, /api/inventory, /api/renew, /api/agent/config |
| `X-SSL-Client-CN` | **`machine-<uuid>`** (CN của client cert do server cấp) — FastAPI tách prefix `machine-` |
| `X-SSL-Client-Serial` | serial cert (phục vụ revoke khi renew) |

- FastAPI chỉ bind IP nội bộ, chỉ nhận traffic từ nginx. Setting `require_agent_mtls_header=True` (prod) → app tự chặn verify != SUCCESS.
- Endpoint `/api/enroll`, `/i/{token}`, và `/download/*` KHÔNG cần client cert (dùng HTTPS public + token nếu có).

---

## 3. Chế độ 1 — Agent API Trực tuyến (Online / Web Link)

Dành cho máy trạm có kết nối mạng tới Server. Quản trị viên copy lệnh cài từ trình duyệt Web Portal, dán vào PowerShell trên máy trạm; toàn bộ quá trình cài đặt, đăng ký, báo online và đẩy thông số diễn ra tự động 100%.

### 3.1. POST /api/enroll (không mTLS, rate-limit 30/min theo IP)

Agent tự động gọi ngay sau khi cài đặt thành công bằng script trực tuyến.

**Request:**
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

**Response 200:**
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
- **Cert**: ECDSA P-256, CN=`machine-<machine_id>`, hiệu lực `client_cert_valid_days` (365). Agent phải lưu private key (KHÔNG gửi lên server), cài cert vào Windows Certificate Store (`LocalMachine\My`).
- Agent phải **lưu config** từ response: endpoints (=agent_server_url), heartbeat interval/jitter, inventory interval.

### 3.2. POST /api/heartbeat (mTLS bắt buộc)

Agent gửi định kỳ để duy trì trạng thái `online` trên hệ thống và nhận tín hiệu điều khiển (rescan).

**Request:**
```json
{
  "logged_user": "DOMAIN\\nguyenvana | null",
  "uptime_sec": 12345,
  "ip": "10.0.0.42 | null"
}
```

**Response 200 (v1.7 — Phase 4):**
```json
{
  "ok": true,
  "server_time": "2025-01-01T00:00:05Z",
  "renew_after": "2025-...Z",
  "rescan_requested": false,
  "notice_version": "v1 | null",
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8,
  "server_url": "https://agent.example.gov.vn",
  "agent_server_url": "https://agent.example.gov.vn",
  "inventory_interval_hours": 24,
  "renew_before_percent": 70,
  "agent_config_hash": "a1b2c3d4e5f6...64 hex chars"
}
```

- Agent gửi theo chu kỳ ngẫu nhiên trong `[interval-jitter, interval+jitter]` (mặc định 30±8s ≈ 22–38s).
- Agent đồng bộ interval/jitter/inventory_interval_hours/renew_before_percent/server_url từ response (server điều chỉnh 1 chỗ).
- `rescan_requested=true` → agent chạy inventory ngay (on-demand).
- **`agent_config_hash` (Phase 4)**: SHA-256 hex (64 ký tự) của canonical JSON cấu hình agent server đang áp dụng (5 trường: `agent_server_url`, `heartbeat_interval_seconds`, `heartbeat_jitter_seconds`, `inventory_interval_hours`, `renew_before_percent`). Agent so sánh với hash đã lưu trong `AgentState.LastAgentConfigHash`:
  - **khớp** → heartbeat bình thường, không gọi thêm request (tiết kiệm bandwidth)
  - **khác** → agent gọi ngay `GET /api/agent/config` để đồng bộ cấu hình mới nhất (thay vì đợi tới chu kỳ ConfigSync 6h)
  - **null/rỗng** (server cũ) → fallback: chờ ConfigSync 6h như trước
  - Cho phép admin đổi cấu hình trên portal được áp dụng trong vòng ~30s thay vì 6h.
- **`renew_before_percent` (Phase 4)**: thêm mới (trước đây chỉ sync qua `/api/agent/config`). Agent dùng để quyết định khi nào tự gia hạn client cert.

### 3.3. POST /api/inventory (mTLS bắt buộc)

Request (tất cả trường optional — agent không đọc được trường nào thì bỏ trống). Đây là payload **chuẩn agent Windows đẩy lên** (schema v2/v3 — đầy đủ cpu, disks, partitions, gpu, mainboard, bios, network mở rộng, installed_software, security):

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
    "bitlocker": "off",
    "rdp_enabled": false,
    "firewall_enabled": true,
    "uac_enabled": true,
    "secure_boot_enabled": true,
    "usb_storage_blocked": false,
    "weak_protocols": {
      "smbv1_disabled": true,
      "tls10_disabled": true,
      "tls11_disabled": true,
      "ssl3_disabled": true
    },
    "listening_ports": [
      { "port": 135, "protocol": "TCP", "address": "0.0.0.0" },
      { "port": 445, "protocol": "TCP", "address": "0.0.0.0" }
    ],
    "startup_programs": [
      { "name": "SecurityHealth", "command": "%windir%\\system32\\SecurityHealthSystray.exe", "location": "HKLM_Run" },
      { "name": "UniKey", "command": "\"C:\\Program Files\\UniKey\\UniKeyNT.exe\"", "location": "HKCU_Run" }
    ],
    "local_accounts": [ { "username": "Administrator", "full_name": "Quản trị hệ thống", "disabled": true, "has_password": true, "is_admin": true } ],
    "smarts": [ { "device": "PhysicalDrive0", "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00", "health": "OK" } ]
  }
}
```

**Response 200:** `{ "ok": true, "config_changed": false }`

- Gửi: lần đầu sau enroll, khi cấu hình thay đổi (config_hash mới), định kỳ `inventory_interval_hours` (24h).

### 3.4. Chuẩn hóa dữ liệu phía server khi nhận inventory (v1.4 — agent KHÔNG cần đổi)

Khi nhận inventory (cả qua API mTLS lẫn import gói ZIP offline từ USB), server ghi **thêm** 2 bảng phục vụ thống kê (cùng transaction với `machine_specs` — xem `docs/REFACTOR_SCHEMA_THONG_KE.md`):

| Bảng | Vai trò | Ghi khi |
|---|---|---|
| `machine_current` | Snapshot **mới nhất** của mỗi máy (1:1 với machines), OS/security là **cột có index** | Upsert mỗi lần nhận inventory |
| `machine_software` | Phần mềm đã cài — **1 dòng/app/máy** (unique `machine_id + lower(name)`) | Replace toàn bộ app của máy (delete + insert) |

Chuẩn hóa **phía server** từ payload agent gửi (agent giữ nguyên):
- `os_product` (ProductName thuần, VD "Windows 11 Pro") + `os_release` (DisplayVersion, VD "25H2"): tách từ `os_name` (token `\d{2}H\d` ở đuôi) hoặc fallback `os_version`.
- `os_family` (windows_10 | windows_11 | windows_server_YYYY | linux | other): phân loại theo ProductName — dùng cho thống kê "số máy Win10/Win11" (GROUP BY).
- Security (JSONB) → cột phẳng có kiểu: `firewall_enabled`, `windows_update_status`, `windows_update_enabled`, `antivirus_enabled`, `antivirus_up_to_date`, `bitlocker`, `uac_enabled`, `secure_boot_enabled`, `rdp_enabled`, `usb_storage_blocked`.
- `installed_software` → dòng chuẩn `{name, version, publisher, install_date}` (name ưu tiên `display_name`, fallback `name`).

### 3.5. POST /api/renew (mTLS bắt buộc) — Tự gia hạn client cert

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

### 3.6. GET /api/agent/config (mTLS bắt buộc) — Cấu hình Động & Ký số Chống Thay Đổi (Signed & Tamper-proof)

**Mục đích:** Cung cấp cấu hình hiệu lực cho Agent sau khi cài đặt hoặc định kỳ đồng bộ (mỗi 6h / khi khởi động lại service). Đảm bảo tính toàn vẹn tuyệt đối: chống sửa đổi trái phép (tamper-proof), chống tấn công DNS hijacking, chống proxy giả mạo và chống replay attack.

#### Cấu trúc Response có Ký số (Signed Config Envelope):
```json
{
  "version": 2,
  "issued_at": "2026-08-27T08:00:00Z",
  "payload": {
    "server_url": "https://agent.example.gov.vn",
    "heartbeat_interval_seconds": 30,
    "heartbeat_jitter_seconds": 8,
    "online_ttl_seconds": 76,
    "inventory_interval_hours": 24,
    "renew_before_percent": 70,
    "agent_config_hash": "a1b2c3d4e5f6...64 hex chars",
    "server_time": "2026-08-27T08:00:00Z"
  },
  "signature": "MEUCIQD...",
  "signer_key_id": "server-config-key-v1"
}
```

*(Ghi chú: Để tương thích ngược với client cũ, các trường trong `payload` vẫn được ánh xạ trực tiếp ở root level nếu client yêu cầu schema phẳng).*

- **`agent_config_hash` (Phase 4)**: SHA-256 hex của canonical JSON 5 trường: `agent_server_url`, `heartbeat_interval_seconds`, `heartbeat_jitter_seconds`, `inventory_interval_hours`, `renew_before_percent`. Agent lưu hash này vào `AgentState.LastAgentConfigHash` để so sánh với heartbeat response.

#### Cơ chế Bảo vệ Chống Thay Đổi (Tamper-proofing) & Mã hóa:
1. **Chữ ký số Server (Digital Signature):**
   - Server tính mã băm SHA-256 trên Canonical JSON của `{version, issued_at, payload}`.
   - Ký bằng Server Private Key (ECDSA secp256r1) lưu trong Vault/HSM.
   - Agent xác thực chữ ký bằng Server Public Key được nhúng sẵn trong binary hoặc CA Trust Store trước khi áp dụng. Nếu chữ ký không khớp dù chỉ 1 bit, Agent lập tức hủy bỏ cập nhật và ghi log cảnh báo an ninh.
2. **Chống Replay Attack:**
   - Trường `version` tăng dần đơn điệu (monotonic integer). Agent chỉ chấp nhận cấu hình khi `version > current_config_version`.
3. **Mã hóa truyền tải & Lưu trữ an toàn tại máy trạm:**
   - **Kênh truyền:** Bắt buộc mTLS (TLS 1.3 với client cert định danh máy) mã hóa toàn bộ dữ liệu trên đường truyền.
   - **Lưu trữ trên Disk (`%ProgramData%\OrgInventory\config.json`):**
     - Thiết lập Windows ACL nghiêm ngặt: chỉ `NT AUTHORITY\SYSTEM` và `BUILTIN\Administrators` có quyền Full Control; chặn quyền sửa đổi từ người dùng thông thường (`Users`).
     - Dữ liệu nhạy cảm (token, machine credentials) được mã hóa bằng **Windows DPAPI** (`DataProtectionScope.LocalMachine`) hoặc AES-256-GCM.
4. **Cơ chế Tự động Hoàn nguyên (Rollback):**
   - Agent sao lưu cấu hình hợp lệ trước đó vào `config.json.bak`.
   - Nếu cấu hình mới nhận được hợp lệ nhưng không thể kết nối tới `server_url` mới sau 5 lần thử liên tiếp, Agent tự động rollback về cấu hình cũ và báo cáo lỗi lên server khi có mạng lại.

---

### 3.7. GET /i/{token} — Script cài đặt trực tuyến động (PowerShell)

**Mục đích:** Hỗ trợ người dùng/admin **sao chép link/lệnh trực tiếp từ trình duyệt Web Portal** để dán vào PowerShell cài đặt tự động 1-click.

**Luồng thực thi:**
1. Quản trị viên vào Portal (`/tokens` hoặc trang Self-service link), nhấn **Copy lệnh cài đặt**:
   ```powershell
   powershell -EP Bypass -c "irm https://portal.example.gov.vn/i/t_Ab3xK9mQ2vR8nL4p | iex"
   ```
2. Dán vào PowerShell (Admin) trên máy trạm: gọi `GET /i/{token}` tải script `install.ps1`.
3. Script tự động lấy `agent_server_url` hiệu lực từ Backend, tải MSI từ `GET /download/agent.msi`, verify checksum SHA256 từ `GET /download/agent.msi.sha256` và chữ ký số Authenticode, chạy `msiexec /qn ENROLL_TOKEN=<token> ENDPOINTS=<agent_server_url>`.
4. Windows Service `OrgInventoryAgent` khởi chạy, tự động enroll qua HTTPS và chuyển sang mTLS.

---

### 3.8. GET /download/* — Phục vụ bộ cài MSI & Gói Offline (Công khai)

| Method | Path | Content-Type | Dùng cho | Cơ chế bảo vệ & chống can thiệp |
|---|---|---|---|---|
| GET | `/download/agent.msi` | `application/x-msi` | Cả 2 chế độ: Online & Offline | Ký số EV Authenticode (chống SmartScreen & giả mạo) |
| GET | `/download/agent.msi.sha256` | `text/plain` | Cả 2 chế độ: Verify toàn vẹn | Mã băm SHA-256 đối chiếu trước khi thực thi |
| GET | `/download/install-offline.cmd` | `text/plain` | **Chế độ 2**: Launcher 1-click | Script batch nháy đúp chuột, tự động xin quyền UAC |
| GET | `/download/install-offline.ps1` | `text/plain` | **Chế độ 2**: Bộ điều phối thu thập | Xác thực chữ ký số file config và kiểm tra toàn vẹn MSI |
| GET | `/download/server_public_key.pem` | `text/plain` | **Chế độ 2**: Khóa công khai Server | Dùng để verify chữ ký file config và mã hóa gói kết quả |
| GET | `/download/offline-package.zip` | `application/zip` | **Chế độ 2**: Gói bundle trọn gói USB | **KHÔNG đặt password** — chứa bộ cài, script, khoá công khai và `offline_config.json` mẫu |

> ⚠️ **Quy tắc ZIP**: Cả `offline-package.zip` (do server trả về) và file ZIP mà agent
> sinh ra trên máy cách ly (`INVENTORY_*.zip`) đều **KHÔNG được đặt password**:
> - ZIP tải về: operator copy qua USB dễ dàng, không cần nhớ password; nội dung đã public.
> - ZIP do agent sinh: tính bí mật dựa vào **mã hoá hybrid AES-256-GCM + RSA-OAEP** bên
>   trong từng entry (`encrypted_payload.bin`, `encrypted_key.bin`); ZIP chỉ là vật chứa.
> Test `test_offline_package_zip_is_not_password_protected` chặn regression — nếu dev
> nào gọi `zf.setpassword()` sẽ test fail ngay.

#### Quy cách File cấu hình tải về `offline_config.json`:
Để chống việc can thiệp hoặc sửa đổi tham số cài đặt trên USB (như sửa đổi URL máy chủ, thay đổi tổ chức `org_id` hoặc chèn token giả mạo), file `offline_config.json` trong gói ZIP tải về tuân thủ cấu trúc envelope ký số:
```json
{
  "version": 1,
  "issued_at": "2026-08-27T08:00:00Z",
  "payload": {
    "token": "t_Ab3xK9mQ2vR8nL4p",
    "endpoints": "https://agent.example.gov.vn",
    "note": "Cấu hình offline tạo bởi IT Asset Inventory Portal"
  },
  "signature": "<ECDSA_SHA256_BASE64>",
  "signer": "server_public_key.pem"
}
```
- **Xác thực trước khi cài đặt:** `install-offline.ps1` dùng `server_public_key.pem` kiểm tra chữ ký của `offline_config.json`. Nếu file bị sửa đổi nội dung trên USB $\rightarrow$ dừng ngay lập tức, báo lỗi đỏ và không cho phép tiến hành cài đặt.
- **Tùy chọn mã hóa (`offline_config.enc`):** Trong môi trường bảo mật cao, file cấu hình được mã hóa bằng AES-256-GCM với khóa mã hóa bảo vệ, chống đọc trộm thông tin token hoặc cấu hình mạng nội bộ khi lưu trữ trên USB.

---

---

## 4. Portal API (JWT Bearer, RBAC)

| Method | Path | Mô tả |
|---|---|---|
| POST | /api/auth/login | Đăng nhập `{email, password, totp_code?}` → Token pair |
| POST | /api/auth/refresh | Làm mới token `{refresh_token}` |
| POST | /api/tokens | Sinh token cài đặt cá nhân (hiển thị lệnh 1 click Chế độ 1 và nút tải gói USB Chế độ 2) |
| POST | /api/tokens/bulk | Sinh token hàng loạt qua CSV |
| GET | /api/tokens | Danh sách token & phễu triển khai |
| POST | /api/tokens/revoke | Thu hồi token chưa sử dụng |
| GET | /api/machines | Danh sách máy (lọc theo org, trạng thái online/offline/pending) |
| GET | /api/machines/{id} | Chi tiết máy + snapshot latest_spec |
| POST | /api/machines/{id}/approve | Phê duyệt máy mới / drift |
| POST | /api/machines/{id}/reject | Từ chối máy lạ |
| POST | /api/machines/{id}/rescan | Gửi cờ yêu cầu máy thu thập lại cấu hình |
| PATCH | /api/machines/{id}/lifecycle | Cập nhật vòng đời máy (`in_use`, `in_repair`, `decommissioned`) |
| GET | /api/stats/overview | Tổng quan số lượng máy, online/offline |
| GET | /api/stats/inventory | Thống kê chuyên sâu (OS family, RAM, CPU, Antivirus, BitLocker, Phần mềm) |
| POST | /api/reports/export | Xuất danh sách máy ra Excel |
| GET | /api/self-service/links | Quản lý link tự khai báo |
| POST | /api/self-service/links | Tạo link tự khai báo cho đơn vị |
| GET | /api/ws?token= | WebSocket cập nhật trạng thái máy thời gian thực |

---

## 5. Chế độ 2 — Máy cách ly mạng (Offline USB & Gói ZIP Mã hóa Ký số)

> **Mục tiêu:** Tối ưu hóa trải nghiệm người dùng cuối ở mức cao nhất.
> Người dùng hoặc cán bộ kỹ thuật tại máy cách ly **KHÔNG cần nhớ lệnh, KHÔNG cần nhập tham số `-Token` hay `-Endpoints`**.
>
> **Chỉ cần duy nhất 1 thao tác:** **Nháy đúp chuột vào file `install-offline` trên USB**.
> Kết quả sinh ra là **1 file ZIP được mã hóa và ký số**. Backend sẽ giải mã, kiểm tra tính hợp lệ của chữ ký số và tự động đồng bộ dữ liệu vào hệ thống.

---

### 5.1. Luồng vận hành 1-Click khép kín

```
[BƯỚC 1: TẠI MÁY CÓ MẠNG (ADMIN)]
  Admin vào Portal → Nhấn "Tải bộ cài máy cách ly" (hoặc tải từ /download/offline-package.zip)
  Giải nén vào thư mục gốc của USB. Trên USB gồm có:
    ├── install-offline.cmd          (Launcher nháy đúp chuột)
    ├── install-offline.ps1          (Script tự động hóa)
    ├── OrgInventoryAgent.msi        (Bộ cài Agent đã ký Authenticode)
    ├── OrgInventoryAgent.msi.sha256 (Mã băm SHA-256)
    ├── server_public_key.pem        (Khóa công khai của Server để mã hóa file xuất ra)
    └── offline_config.json          (File chứa org_id do Portal sinh sẵn, không cần gõ tay)
         │
         ▼ (Cắm USB vào máy cách ly)
[BƯỚC 2: TẠI MÁY CÁCH LY (NGƯỜI DÙNG CUỐI / KTV)]
  Người dùng chỉ cần: NHÁY ĐÚP CHUỘT VÀO `install-offline.cmd`
  Hệ thống tự động thực hiện hoàn toàn ngầm:
    1. Tự xin quyền Administrator (UAC).
    2. Cài đặt Agent vào máy (nếu chưa cài).
    3. Thu thập toàn bộ thông số phần cứng, phần mềm, bảo mật, fingerprint.
    4. Ký số ECDSA P-256 bằng khóa riêng của máy (lưu trong Windows Cert Store, KHÔNG BAO GIỜ rời máy).
    5. Đóng gói và MÃ HÓA toàn bộ dữ liệu bằng Server Public Key (Hybrid Encryption AES-256-GCM).
    6. Tạo ra 1 file ZIP duy nhất ngay trên USB:
       E:\INVENTORY_<HOSTNAME>_<YYYYMMDD_HHMMSS>.zip
    7. Hiện thông báo: "✔ THU THẬP VÀ ĐÓNG GÓI THÀNH CÔNG! Vui lòng chuyển file ZIP cho Quản trị viên."
         │
         ▼ (Rút USB mang về máy quản trị có mạng)
[BƯỚC 3: NẠP LÊN HỆ THỐNG (PORTAL / BACKEND)]
  Admin vào Portal (trang /offline-import) → Kéo thả file ZIP vừa xuất từ USB lên hệ thống
  Endpoint Backend: POST /api/offline/import (hoặc POST /api/offline/import-bundle)
  Backend tự động:
    1. Dùng Server Private Key GIẢI MÃ gói ZIP (AES-256-GCM).
    2. KIỂM TRA CHỮ KÝ SỐ ECDSA: Đối chiếu signature với payload bằng public key của máy trạm.
       → Nếu chữ ký sai hoặc file bị can thiệp trên USB: TỪ CHỐI NGAY (400 Bad Request).
    3. NẾU CHỮ KÝ HỢP LỆ: Parse dữ liệu inventory, chuẩn hóa OS, tự động cập nhật Machine,
       MachineSpec, machine_current, machine_software.
    4. Trả về kết quả xác nhận cho Admin trên giao diện Web.
```

---

### 5.2. Cấu trúc File ZIP Mã hóa trên USB

File xuất ra có định dạng ZIP bảo mật (ví dụ `INVENTORY_PC-PHONG102_20260827_083000.zip`), bên trong chứa các thành phần đã được mã hóa an toàn:

| Thành phần bên trong ZIP | Ý nghĩa & Chuẩn bảo mật |
|---|---|
| `manifest.json` | Chứa metadata: `machine_uuid`, `hostname`, `fingerprint`, `exported_at`, `org_id` |
| `inventory.json` | Toàn bộ payload cấu hình tài sản (schema v2/v3 chuẩn xác: CPU, RAM, Disk, Software, Security...) |
| `signature.sig` | Chữ ký số **ECDSA-SHA256** (RFC 3279 DER Sequence base64) của máy trạm trên Canonical JSON của `inventory.json` |
| `public_key.pem` | Khóa công khai của máy trạm (`-----BEGIN PUBLIC KEY-----` / SubjectPublicKeyInfo) |
| `encrypted_key.bin` | Khóa đối xứng AES-256 được mã hóa bằng `server_public_key.pem` (Mã hóa lai RSA/ECDH) |

> 🔒 **Cơ chế Mã hóa Lai (Hybrid Encryption):**
> 1. Agent sinh ngẫu nhiên 1 khóa đối xứng dùng 1 lần `session_key` (AES-256-GCM, 256-bit).
> 2. Toàn bộ nội dung dữ liệu tài sản được mã hóa bằng `session_key`.
> 3. `session_key` được mã hóa bất đối xứng bằng `server_public_key.pem`.
> 4. **Chỉ duy nhất Server (sở hữu Server Private Key) mới có thể giải mã gói dữ liệu này**. Ngay cả khi USB bị đánh rơi, người ngoài cũng không thể đọc được thông tin cấu hình máy tính.

---

### 5.3. POST /api/offline/import — Tiếp nhận và Parse file ZIP mã hóa

**Xác thực:** `Authorization: Bearer <admin JWT>` (Admin hoặc Org Admin nạp dữ liệu).  
**Content-Type:** `multipart/form-data`

**Request Parameters:**
- `file`: File nhị phân `.zip` mã hóa do script offline trên USB xuất ra.
- `org_id` *(optional)*: Mã đơn vị tiếp nhận (nếu không truyền, server lấy từ `manifest.json` trong file zip hoặc gán theo `admin.org_id`).

**Luồng xử lý Backend:**
1. **Giải mã (Decryption):**
   - Đọc `encrypted_key.bin`, dùng Server Private Key giải mã ra `session_key`.
   - Dùng `session_key` giải mã gói dữ liệu AES-256-GCM.
   - Nếu giải mã thất bại $\rightarrow$ trả về `400 Bad Request`: `"Gói dữ liệu mã hóa không hợp lệ hoặc không thuộc hệ thống này"`.
2. **Kiểm tra Chữ ký số (Signature Verification):**
   - Trích xuất `inventory.json`, `signature.sig`, và `public_key.pem`.
   - Chuẩn hóa `inventory.json` theo Canonical JSON:
     `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`
   - Tính digest SHA-256 và verify chữ ký ECDSA (secp256r1) bằng `public_key.pem`.
   - Nếu chữ ký không khớp $\rightarrow$ trả về `400 Bad Request`: `"Chữ ký số không hợp lệ — phát hiện dấu hiệu can thiệp dữ liệu trên USB"`.
3. **Parse dữ liệu & Cập nhật cơ sở dữ liệu:**
   - Tìm máy theo `machine_uuid` hoặc fuzzy-match hardware fingerprint (trọng số SMBIOS UUID, MachineGuid, Mainboard Serial).
   - Nếu máy chưa có trong hệ thống $\rightarrow$ tự động tạo máy mới với trạng thái ban đầu `offline` (hoặc `pending` chờ duyệt nếu tổ chức bật chế độ duyệt máy mới).
   - Cập nhật `last_seen_at = exported_at`.
   - Lưu snapshot mới vào bảng `MachineSpec`.
   - Phân loại chuẩn hóa OS (`os_product`, `os_release`, `os_family`) và cập nhật tức thì vào bảng `machine_current` và `machine_software` phục vụ báo cáo thống kê.
4. **Audit Log:** Ghi log hệ thống `action=offline.import_zip`, `actor=admin:<id>`, `machine_id=<uuid>`.

**Response 200:**
```json
{
  "machine_id": "fd0d8278-314e-434b-a884-d858624ca7ca",
  "hostname": "PC-PHONG102",
  "is_new": false,
  "verified": true,
  "decrypted": true,
  "apps_count": 42,
  "collected_at": "2026-08-27T08:30:00Z"
}
```

---

### 5.4. Hỗ trợ dự phòng: POST /api/offline/import (JSON Body)

Để tương thích với các công cụ tự động hóa hoặc script kiểm thử của kỹ sư hệ thống, ngoài việc upload file ZIP, endpoint `/api/offline/import` còn tiếp nhận payload JSON phẳng `{ payload, signature_b64, public_key_pem }` đối với các trường hợp không nén file ZIP.

> **Lưu ý**: Trước đây có endpoint `/api/offline/enroll` để admin proxy CSR cho máy cách ly nhận cert trước khi gửi inventory. Endpoint này **đã được loại bỏ** (Phase 4 cleanup) vì:
> - Agent không có flag `--enroll-offline` để sinh CSR
> - Agent không có flag `--install-cert` để cài cert về
> - Flow 1-Click (`--export-bundle` → upload ZIP) đã đủ — server dùng fingerprint phần cứng làm định danh máy

---

## 6. Trạng thái máy & token

- **Trạng thái máy:** `online` | `offline` | `lost` | `decommissioned` | `pending` (chờ duyệt).
  - Máy Chế độ 1 (Online): Trạng thái `online` khi có heartbeat trong vòng `online_ttl_seconds` (mặc định 76s). Quá hạn tự chuyển `offline`.
  - Máy Chế độ 2 (Offline): Trạng thái mặc định là `offline` (hoặc `pending` lúc mới nhập chờ duyệt), trường `last_seen_at` được gán theo thời gian `exported_at` của lần nạp file gần nhất.
- **Trạng thái token:** `pending` | `used` | `revoked` | `expired`. TTL mặc định 72h, `max_uses=1`, dạng `t_` + base62.
- Online lưu Redis `machine:online:{id}` TTL = `online_ttl_seconds` (mặc định 2×(interval+jitter) = 76s).

---

## 7. Nguyên tắc thiết kế Agent (Áp dụng thống nhất cho cả 2 chế độ)

1. **Vận hành 1-Click cho máy cách ly**: Người dùng tại máy cách ly không phải nhớ lệnh, không gõ tham số. Nháy đúp chuột là tự động thực thi và xuất file kết quả.
2. **An toàn 2 lớp (Ký số máy trạm + Mã hóa máy chủ)**:
   - **Ký số**: Private key ECDSA P-256 nằm an toàn trong Windows Certificate Store của máy trạm, không bao giờ gửi ra ngoài. Chữ ký số đảm bảo chống can thiệp hoặc làm giả dữ liệu tài sản.
   - **Mã hóa**: File kết quả trên USB được mã hóa bằng Server Public Key (AES-256 + RSA/ECDH). Chỉ máy chủ trung tâm mới có khả năng giải mã.
3. **Thống nhất logic thu thập**: Cùng sử dụng chung module thu thập dữ liệu (Fingerprint, Inventory, Software, Security) và schema JSON v2/v3 cho cả 2 chế độ.
4. **Read-only & Zero-GUI**: Không hook process, không đọc dữ liệu người dùng cá nhân, không hiển thị pop-up gây phiền hà.
5. **Khả năng tự phục hồi & Lưu cache cục bộ**: SQLite `%ProgramData%\OrgInventory\cache.db` bảo toàn lịch sử cấu hình máy kể cả khi máy chưa kịp nạp dữ liệu lên server.

---

## 8. Velociraptor (DFIR — Digital Forensics & Incident Response)

> Tích hợp [Velociraptor](https://github.com/velocidex/velociraptor) Server để admin chạy hunt / collect artifact từ xa. **Không can thiệp vào agent inventory** — backend độc lập gọi Velociraptor REST API để đồng bộ hostname ↔ client_id mỗi 5 phút.

### 8.1. Quy trình

1. **Cấu hình (Super Admin, 1 lần)**:
   - Tạo API key ở Velociraptor GUI (Settings → API Keys).
   - Vào portal `/dfir/settings` → nhập Server URL + API Token + bật + chỉnh allowlist.
2. **Sync (background, 5 phút/lần)**:
   - Server gọi `POST {VeloURL}/api/v1/SearchClients` (pagin) → lấy toàn bộ client.
   - Với mỗi client, `normalize(os_info.hostname)` (lowercase + strip FQDN) → tìm `machines.hostname` khớp (cũng đã normalize) → upsert `velociraptor_links(machine_id, client_id, hostname, os_info, last_seen_at)`.
   - Nếu trùng hostname (2 client cùng tên): chọn client có `last_seen_at` mới nhất.
3. **Hunt / Collect (admin, on-demand)**:
   - `POST /api/admin/velociraptor/hunt` với `{artifact, scope, machine_id?}`.
   - Server **validate artifact ∈ allowlist** (403 nếu không). scope=`all` tạo hunt trên toàn bộ Velociraptor client; scope=`single` collect trên 1 client (cần `machine_id` đã có link).
   - Ghi audit log (`action="dfir.hunt.create"`) + `dfir_hunts` table.
   - Trả `velociraptor_url` = deep-link sang Velociraptor GUI (`/#/hunts/{hunt_id}` hoặc `/#/host/{client_id}`).

### 8.2. Endpoints (Super Admin / Admin)

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/admin/velociraptor/config` | Cấu hình hiệu lực (mask token, chỉ trả `api_token_set: bool`) |
| `PUT` | `/api/admin/velociraptor/config` | Cập nhật URL + token (AES-256-GCM) + allowlist. **Super Admin** |
| `POST` | `/api/admin/velociraptor/test` | Test kết nối — trả `ok` + `client_count_sampled` |
| `POST` | `/api/admin/velociraptor/sync` | Trigger sync hostname thủ công (bỏ qua 5p chờ). **Super Admin** |
| `GET` | `/api/admin/velociraptor/links` | List mapping `machine ↔ client_id` (kèm tên máy, org, status) |
| `POST` | `/api/admin/velociraptor/hunt` | Tạo hunt (scope=all) hoặc collect (scope=single) — validate allowlist |
| `GET` | `/api/admin/velociraptor/hunts?limit=50&offset=0` | Lịch sử hunt/collect (audit log local) |
| `GET` | `/api/admin/velociraptor/hunt/{hunt_id}` | Lấy status hunt từ Velociraptor Server (live) |

### 8.3. Schema VelociraptorConfigOut

```json
{
  "enabled": true,
  "server_url": "https://veloci.example.gov.vn:8889",
  "api_token_set": true,
  "allowlist": ["Generic.Client.Info", "Windows.System.Services", "..."],
  "last_sync_at": "2026-08-28T10:30:00Z",
  "last_sync_error": null,
  "last_sync_linked": 142,
  "last_sync_total": 156,
  "updated_at": "2026-08-28T09:00:00Z",
  "updated_by": "uuid",
  "defaults_server_url": "https://veloci.example.gov.vn:8889",
  "defaults_allowlist": ["Generic.Client.Info", "..."]
}
```

### 8.4. Schema DfirHuntOut

```json
{
  "id": "uuid",
  "hunt_id": "H.abc123",  // hoặc flow_id cho collect
  "artifact": "Generic.Client.Info",
  "scope": "all",  // hoặc "single"
  "machine_id": "uuid | null",
  "requested_by": "uuid",
  "status": "completed",  // pending | completed | error
  "velociraptor_url": "https://veloci.example.gov.vn:8889/#/hunts/H.abc123",
  "notes": "Tuỳ chọn",
  "error": null,
  "created_at": "2026-08-28T10:00:00Z",
  "client_count": 156  // số client tham gia (từ Velociraptor)
}
```

### 8.5. Quy ước mapping hostname

Velociraptor trả `os_info.hostname` dạng `DESKTOP-AAA.local` (FQDN); agent inventory trả `DESKTOP-AAA` (short name). Backend chuẩn hoá cả hai về dạng short-name-lowercase để so sánh:

```
normalize("DESKTOP-AAA.local") → "desktop-aaa"
normalize("  PC-DEF  ")       → "pc-def"
normalize("")                  → ""  (bỏ qua, không match)
```

Trường hợp đặc biệt: 1 Velociraptor client chỉ link với 1 máy (client_id UNIQUE). Nếu 2 client cùng hostname → chọn client có `last_seen_at` lớn nhất; client còn lại KHÔNG link (không match với bất kỳ máy nào).

### 8.6. KHÔNG cache payload

Kết quả hunt KHÔNG được lưu trên Inventory Server (chỉ lưu metadata: hunt_id, scope, artifact, client_count, status). Lý do:
1. Dung lượng lớn (notebook Velociraptor có thể > 100MB/máy).
2. Velociraptor là nguồn gốc — nếu cache mà Velociraptor xoá → mất dữ liệu.
3. Audit chain đủ để truy vết (ai chạy, khi nào, artifact gì, bao nhiêu client).

Admin click **Mở Velociraptor GUI** trên portal → mở tab mới sang Velociraptor để xem kết quả trực tiếp.

### 8.7. Lỗi & mã phản hồi

| Mã | Ý nghĩa | Cách xử lý |
|---|---|---|
| 200 | OK | — |
| 400 | Velociraptor chưa cấu hình / scope=single thiếu machine_id | Cấu hình Velociraptor trên `/dfir/settings` trư�c |
| 403 | Artifact không trong allowlist | Super Admin thêm artifact vào allowlist |
| 404 | Machine không tồn tại | Kiểm tra ID |
| 409 | Machine chưa link Velociraptor | Đợi sync (≤5p) hoặc bấm sync thủ công |
| 422 | URL không hợp lệ / scope không đúng | Sửa input |
| 502 | Velociraptor API lỗi (network/auth) | Xem `last_sync_error` ở `/dfir/settings` |

## 9. Alert Engine (redesign — 3 trục: templates / scope / recipients)

Chỉ hỗ trợ 2 delivery channel: **in-app notification** (`notifications` table + WebSocket) và **Telegram** (qua bot do Super Admin cấu hình). KHÔNG email/Zalo/webhook.

### 9.1 Templates (Super Admin)

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/admin/alert-templates` | Danh sách template |
| GET | `/api/admin/alert-templates/{code}` | Chi tiết 1 template |
| PATCH | `/api/admin/alert-templates/{code}` | Sửa name/title/body/opt_out_controls/allowed_vars/severity/enabled |
| POST | `/api/admin/alert-templates/{code}/preview` | Render thử với context mẫu (body `{"context": {...}}`) |

Template fields: `code` (unique), `category` (`machine`/`investigation`/`security`/`system`), `default_severity`, `title_template`/`body_template` (biến `{var}` whitelist qua `allowed_vars`), `opt_out_controls` (`["template"]`/`["severity"]`/cả hai/`[]`), `default_config`, `enabled`.

Seed 7 templates: `machine_new`, `machine_lost`, `machine_offline`, `investigation_completed`, `investigation_failed`, `software_new`, `hardware_changed`.

### 9.2 Subscriptions (alert rules)

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/alert-rules` | Danh sách rule (theo quyền visible_org_ids) |
| POST | `/api/alert-rules` | Tạo rule: `name`, `template_code`, `org_id`, `scope_mode` (`org_only`/`org_tree`/`system`), `recipient_mode` (`org_admins_and_super`), `config`, `enabled` |
| PATCH | `/api/alert-rules/{id}` | Sửa rule |
| DELETE | `/api/alert-rules/{id}` | Xóa rule |
| POST | `/api/alert-rules/{id}/test` | Dry-run: render + resolve recipients (KHÔNG gửi) |
| GET | `/api/alert-rules/events` | Lịch sử alert events |

Scope semantics:
- `org_only`: chỉ máy thuộc đúng 1 org
- `org_tree`: org + toàn bộ đơn vị trực thuộc (cây con)
- `system`: toàn hệ thống (chỉ Super Admin tạo được)

### 9.3 User notification prefs

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/me/notification-prefs` | Prefs của user + metadata template (`opt_out_controls` để UI render control) |
| PATCH | `/api/me/notification-prefs` | Upsert prefs: `{"prefs": [{"template_code", "muted", "min_severity"}]}` — validate theo template `opt_out_controls` |

### 9.4 Recipients & delivery

- Mặc định: **Org Admin** của scope (`role IN ('org_admin','admin_org')`) + **Super Admin** (`role IN ('super_admin','admin_global')`).
- Org Admin có thể mute per template (`muted=true` khi template có control `template`) hoặc đặt ngưỡng `min_severity` (khi template có control `severity`).
- **Super Admin luôn nhận** — không bị filter bởi prefs.
- In-app notification luôn tạo; Telegram gửi qua `telegram_runtime.get_bot_config` tới `user.telegram_chat_id` nếu user đã link (best-effort, không retry).
- Idempotency: event dedup theo `sha256(rule_id:machine_id:template_code:YYYY-MM-DD)` — cùng rule + máy + ngày chỉ 1 event.

### 9.5 Trigger points

| Sự kiện | template_code | Nguồn |
|---|---|---|
| Máy enroll mới (window 30 phút) | `machine_new` | `monitor._scan_alerts` (60s) |
| Máy LOST quá threshold_days | `machine_lost` | `monitor._scan_alerts` (60s) |
| Máy chuyển offline (real-time) | `machine_offline` | `monitor._sweep_offline` (30s) |
| Điều tra DFIR hoàn thành | `investigation_completed` | `dfir_investigation` |
| Điều tra DFIR thất bại | `investigation_failed` | `dfir_investigation` |
| Phần mềm lạ / phần cứng đổi | `software_new` / `hardware_changed` | Phase 3 (chưa có job scan) |
