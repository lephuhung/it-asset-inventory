# KẾ HOẠCH HỆ THỐNG QUẢN LÝ TÀI SẢN MÁY TÍNH (IT ASSET INVENTORY)

> **Mô hình:** Agent – Server
> **Đối tượng:** Máy tính Windows thuộc các cơ quan / tổ chức
> **Mục tiêu cốt lõi:** Tạo "dữ liệu sống" về số lượng máy tính trong phạm vi quản lý, trạng thái online/offline theo thời gian thực, gắn với thông tin người dùng và cơ cấu tổ chức.

---

## MỤC LỤC

1. [Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Agent Windows](#3-agent-windows)
4. [Luồng Enrollment (đánh ID máy)](#4-luồng-enrollment-đánh-id-máy)
5. [Server](#5-server)
6. [Danh sách tính năng chi tiết](#6-danh-sách-tính-năng-chi-tiết)
7. [Bảo mật — vòng đời cert, audit integrity, hardening, tuân thủ](#7-bảo-mật)
8. [Roadmap triển khai](#8-roadmap-triển-khai)
9. [Ước lượng nguồn lực](#9-ước-lượng-nguồn-lực)
10. [Rủi ro & giảm thiểu](#10-rủi-ro--giảm-thiểu)

---

## 1. TỔNG QUAN HỆ THỐNG

### 1.1. Bài toán

- Các cơ quan/tổ chức cần biết **chính xác, theo thời gian thực**: có bao nhiêu máy tính đang quản lý, máy nào đang bật/tắt, cấu hình ra sao, ai đang dùng, thuộc đơn vị nào.
- Phương pháp thủ công (Excel, kiểm kê định kỳ) cho dữ liệu chết, sai lệch, không phát hiện được máy "ma" (đã cấp nhưng không dùng / mất tích).

### 1.2. Giải pháp

- **Agent** cài trên từng máy Windows: tự định danh, thu thập cấu hình, gửi heartbeat định kỳ.
- **Server trung tâm**: tiếp nhận dữ liệu, quản lý theo cây tổ chức, dashboard realtime, báo cáo.
- **Portal web**: quản trị viên cơ quan sinh mã token + lệnh cài đặt cho người dùng; người dùng chỉ cần paste 1 dòng lệnh vào PowerShell — **không cần giao diện cài đặt**.

### 1.3. Nguyên tắc thiết kế xuyên suốt

| Nguyên tắc | Lý do |
|---|---|
| Agent **read-only** (chỉ đọc thông tin, không điều khiển máy) | Dễ qua vòng duyệt an ninh, tránh AV gắn cờ, tránh rủi ro pháp lý |
| Triển khai **zero-GUI** cho người dùng cuối | Cài bằng 1 dòng lệnh, giảm tối đa thao tác |
| Dữ liệu **sống** từ lúc phát token | Kể cả trước khi máy online, hệ thống đã thống kê được phễu triển khai |
| Không giám sát cá nhân | Không screenshot, keylog, lịch sử web — giữ sản phẩm là công cụ quản lý tài sản, không phải công cụ theo dõi |

---

## 2. KIẾN TRÚC TỔNG THỂ

```
┌─────────────┐   HTTPS/mTLS    ┌──────────────────────────────┐
│ Agent Win #1│ ◄─────────────► │                              │
├─────────────┤   Heartbeat     │   SERVER TRUNG TÂM           │
│ Agent Win #2│ ◄─────────────► │  ┌────────────────────────┐  │
├─────────────┤   + Inventory   │  │ API (REST)             │  │
│ Agent Win #N│ ◄─────────────► │  ├────────────────────────┤  │
└─────────────┘                 │  │ PostgreSQL (dữ liệu)   │  │
                                │  │ Redis (online status)  │  │
┌─────────────┐                 │  ├────────────────────────┤  │
│  Portal Web │ ◄── WebSocket ──┤  │ AuthN/Z (RBAC theo tổ  │  │
│  (quản trị) │    realtime     │  │ chức + JWT/OIDC)       │  │
└─────────────┘                 │  └────────────────────────┘  │
                                └──────────────────────────────┘
```

### 2.1. Thành phần

| Thành phần | Công nghệ đề xuất | Vai trò |
|---|---|---|
| Agent | C# / .NET 8 Windows Service, self-contained single-file | Thu thập cấu hình, heartbeat, enroll |
| Installer | MSI (WiX Toolset) + install.ps1 ký số | Cài đặt silent qua one-liner |
| API Server | ASP.NET Core / Node.js / Go (theo team) | REST API cho agent + portal |
| Database | PostgreSQL | Dữ liệu chính, snapshot lịch sử |
| Cache/Queue | Redis | Trạng thái online (TTL), pub/sub realtime |
| Portal Web | React/Vue + WebSocket | Dashboard, quản lý token, báo cáo |

### 2.2. Kênh giao tiếp Agent ↔ Server

- **HTTPS/443 bắt buộc**, mTLS sau khi enroll (mỗi agent 1 client certificate riêng).
- REST API đơn giản: `POST /api/enroll`, `POST /api/heartbeat`, `POST /api/inventory` — payload **JSON UTF-8** (đặc tả chi tiết mục 3.6).
- Heartbeat chu kỳ cơ sở **30 giây**, jitter ±25% (thực tế ~22–38 giây, cấu hình được theo cơ quan) — tránh pattern beaconing giống C2 malware. Chu kỳ có thể điều chỉnh từ xa qua config ký số (mục 3.5).
- User-Agent rõ ràng: `OrgInventoryAgent/x.y`.

---

## 3. AGENT WINDOWS

### 3.1. Lựa chọn nền tảng

**Quyết định: C# / .NET 8, Windows Service, đóng gói self-contained single-file.**

| Tiêu chí | C# (.NET 8) ✅ | Go | Rust |
|---|---|---|---|
| Tỉ lệ bị AV gắn cờ | **Thấp nhất** (cùng hệ sinh thái MS) | Cao (khét tiếng false positive) | Trung bình |
| Đọc WMI/Registry | **Native, đầy đủ** | Qua thư viện OLE, lỗi vặt | Hạn chế |
| Làm Windows Service | `BackgroundService` chuẩn MS | Thư viện ngoài | Thủ công |
| Dung lượng | ~15–25MB | ~10–15MB | ~3–8MB |
| RAM chạy | ~20–40MB | ~10–20MB | ~5–10MB |
| Tốc độ phát triển | **Nhanh** | Nhanh | Chậm |

> Lưu ý: không tối ưu dung lượng bằng packer (UPX...) — đó là con đường nhanh nhất dẫn đến bị AV phát hiện.

### 3.2. Chống Antivirus false positive (checklist bắt buộc)

**Chữ ký số — quan trọng nhất:**
- [ ] Mua **EV Code Signing certificate** → SmartScreen cho qua ngay, không chờ tích lũy reputation.
- [ ] Ký cả 3 thứ: `agent.exe`, `agent.msi`, `install.ps1` (Authenticode).
- [ ] Timestamp khi ký (file cũ vẫn hợp lệ khi cert hết hạn).

**Metadata đầy đủ:**
- [ ] CompanyName (tên thật), FileDescription, ProductName, Version, Copyright, Icon.

**Kiến trúc "hiền":**

| NÊN | KHÔNG NÊN |
|---|---|
| Cài qua MSI chuẩn, service đăng ký qua SCM | Tự copy file + `sc.exe create` thủ công |
| Heartbeat có jitter | Beacon chính xác như đồng hồ |
| HTTPS/443, User-Agent rõ ràng | Port lạ, che giấu traffic |
| Self-update: tải MSI → verify chữ ký → `msiexec` | Tải exe về temp rồi tự chạy |
| Chỉ đọc WMI/Registry | Hook API, inject, đọc process khác |

**Quy trình:**
- [ ] **KHÔNG upload agent lên VirusTotal** (VT phát tán mẫu → ML các vendor học theo → sinh detection lan).
- [ ] Submit trước cho Microsoft: [WDSI file submission](https://www.microsoft.com/en-us/wdsi/filesubmission).
- [ ] Release theo đợt, không đẩy build mới mỗi ngày (mỗi hash mới = reset reputation).
- [ ] Với môi trường cơ quan VN (BKAV Pro, Kaspersky Endpoint...): làm việc với đội an ninh mạng **đẩy hash/cert vào whitelist AV tập trung trước khi triển khai**.

### 3.3. Dữ liệu agent thu thập

**Định danh máy (fingerprint) — kết hợp nhiều nguồn:**
- SMBIOS UUID (`Win32_ComputerSystemProduct.UUID`)
- `MachineGuid` (registry `HKLM\SOFTWARE\Microsoft\Cryptography`)
- Serial mainboard / TPM public key hash
- → Hash có trọng số. Server **fuzzy-match** khi enroll để quyết định máy cũ/mới, tránh đếm trùng khi ghost lại Win hoặc thay linh kiện.

**Cấu hình hệ thống (qua WMI/CIM + Registry):**
- OS: caption, version, build (VD: Windows 10 22H2 build 19045), kiến trúc, ngày cài, trạng thái activation.
- CPU (model, số core), RAM (dung lượng, số khe), ổ cứng (model, serial, dung lượng, SMART cơ bản), GPU, mainboard, BIOS.
- Mạng: hostname, domain/workgroup, IP, MAC — **phát hiện dual-homed** (2 mạng cùng lúc).
- User đang đăng nhập.
- Danh sách phần mềm đã cài (registry Uninstall keys).
- Trạng thái bảo mật: Antivirus (WMI `root\SecurityCenter2`), Windows Update, BitLocker, RDP, tài khoản local.

> **Riêng tư:** agent **không** thu thập số điện thoại, nội dung liên lạc hay dữ liệu cá nhân ngoài user đang đăng nhập. Số điện thoại (nếu có) chỉ do admin/user nhập khi tạo token (mục 4) và được mã hóa AES-256-GCM khi lưu (mục 7.3).

### 3.4. Vòng đời agent

```
Cài đặt (one-liner) → Enroll (token → machine_id + client cert)
→ Heartbeat định kỳ (~30s, jitter ±25%) → Inventory đầy đủ lần đầu
→ Inventory lại khi: hash cấu hình thay đổi / định kỳ 24h / server yêu cầu (on-demand rescan)
```

**Offline cache:** mất mạng → ghi vào SQLite local → gửi bù khi có mạng (kèm timestamp gốc).

**Idempotency:** chạy lại lệnh cài trên máy đã enroll → agent nhận ra cert cũ → chỉ repair/update, không tạo máy trùng.

### 3.5. Đổi endpoint server (IP/domain) từ xa

**Bài toán:** server có thể đổi IP/tên miền (chuyển hạ tầng, đổi nhà cung cấp, tổ chức lại đơn vị). Hàng nghìn agent đã cài phải tự chuyển sang địa chỉ mới — không thể cài lại thủ công từng máy.

**Tầng 1 — Endpoint dự phòng (failover tĩnh, Phase 1):**
- Config agent (ProgramData) lưu danh sách `endpoints[]`: primary + 1–2 backup.
- Primary lỗi N lần liên tiếp (mặc định 5) → tự chuyển sang backup; định kỳ thử lại primary.
- Backup endpoint nên là tên miền dự phòng đăng ký sẵn, trỏ về cùng server (hoặc server dự phòng).

**Tầng 2 — Config ký số đẩy từ server (signed config push, Phase 3):**
- Server đính kèm trong heartbeat response (hoặc endpoint riêng) gói config có version: `{ version, endpoints[], heartbeat_interval_sec, ... }` + **chữ ký ECDSA** bằng khóa ký config (private key trong Vault/HSM).
- **Public key ký config nhúng sẵn trong agent từ lúc build** → DNS hijack hay server giả mạo **không ép được** agent đổi endpoint (đây là lớp bảo vệ quyết định — chỉ TLS thôi không đủ khi đổi domain).
- Agent chỉ áp dụng khi: chữ ký hợp lệ + `version` mới hơn version đang dùng.
- **Rollback tự động:** endpoint mới không kết nối được sau N lần thử → quay lại config cũ, báo lỗi khi kết nối lại được.
- Cùng kênh này dùng để **chỉnh chu kỳ heartbeat từ xa** (tăng khi số máy lớn, giảm khi cần realtime hơn).
- Đổi endpoint là thao tác nhạy cảm: bắt buộc 2FA + audit log; tùy chọn dual-approval (2 admin xác nhận).

**Quy trình đổi domain an toàn (runbook):**
1. Dựng server mới chạy song song với server cũ; giảm DNS TTL trước ít nhất 1 ngày.
2. Push config chứa endpoint mới; theo dõi tỉ lệ agent đã chuyển trên dashboard.
3. Khi ≥ 99% agent đã chuyển → tắt server cũ; giữ DNS cũ redirect thêm một thời gian cho máy offline lâu ngày (khi bật lại sẽ failover theo danh sách endpoint).

### 3.6. Định dạng dữ liệu agent gửi server

**Nguyên tắc config-driven:** binary agent giữ cố định, hành vi điều khiển bằng config tải về sau. Thứ tự ưu tiên: *default biên dịch < config local (ProgramData) < config ký từ server (mục 3.5)*. Config chỉ được ghi đè bởi gói có `version` cao hơn + chữ ký hợp lệ. Chỉ khi cần collector mới mới build lại binary → self-update MSI ký số.

**Định dạng: JSON UTF-8** (`Content-Type: application/json; charset=utf-8`):
- Dễ debug/kiểm thử, khớp OpenAPI/Pydantic phía server, kích thước nhỏ (heartbeat ~0,5KB; inventory ~10–50KB → **gzip** khi > 8KB).
- Mọi gói tin dùng **envelope chung**: `schema_version` (tương thích khi nâng cấp giao thức), `request_id` UUID (idempotency — server xử lý trùng an toàn khi agent retry/gửi bù offline cache), `ts` ISO 8601 UTC.

```json
{
  "schema_version": 1,
  "agent_version": "1.0.0",
  "machine_id": "uuid-sau-enroll",
  "request_id": "uuid-v4",
  "ts": "2025-01-01T00:00:00Z",
  "payload": { }
}
```

- `payload` của **enroll**: token + fingerprint (SMBIOS UUID, MachineGuid hash, serial mainboard hash) + CSR PEM + hostname.
- `payload` của **heartbeat**: uptime, user đăng nhập, IP, `config_hash` hiện tại, số bản ghi offline đang chờ.
- `payload` của **inventory**: specs đầy đủ (OS/CPU/RAM/disk/GPU/mainboard/BIOS), network, software (Phase 2), security posture (Phase 2).
- **Response heartbeat** có thể kèm: `server_time` (đồng bộ clock), `config_update` (gói config ký số — mục 3.5), `command` (VD: rescan — Phase 3) → server điều khiển hành vi agent qua kênh đã xác thực, không cần sửa binary.

**Mã hóa — đúng lớp, đúng việc:**

| Lớp | Cơ chế | Bảo vệ |
|---|---|---|
| Truyền tải (mọi request) | **TLS 1.2+ bắt buộc**; sau enroll là **mTLS** (client cert ECDSA P-256) | Bí mật + toàn vẹn + định danh 2 chiều trên đường truyền |
| Token enroll | Gửi 1 lần qua HTTPS; server chỉ lưu SHA-256 hash | Lộ DB không lộ token |
| File offline USB (Phase 3) | JSON → **ký CMS/PKCS#7** bằng private key agent; tùy chọn mã hóa envelope bằng public key server | Chống sửa file trên USB + bí mật nếu USB thất lạc |

- **Không mã hóa chồng ở tầng ứng dụng** cho request thường: mTLS đã đủ; mã hóa kép chỉ tăng độ phức tạp quản lý khóa mà không thêm an toàn thực tế.
- Dữ liệu nhạy cảm (SĐT, email) được mã hóa AES-256-GCM khi **lưu tại server** (mục 7.3) — agent không thu thập các trường này nên không phải xử lý.

---

## 4. LUỒNG ENROLLMENT (ĐÁNH ID MÁY)

### 4.1. Sơ đồ tổng thể

```
┌──────────────── WEB PORTAL ────────────────┐
│ Admin cơ quan đăng nhập                     │
│   → "Thêm máy mới" → nhập thông tin user:   │
│     (Họ tên, phòng ban, chức vụ, email,    │
│      số điện thoại tùy chọn)               │
│   → [Sinh mã] → token + CÂU LỆNH CÀI ĐẶT    │
│   → Copy gửi cho người dùng                 │
└──────────────────────┬──────────────────────┘
                       │ copy-paste
                       ▼
┌──────────── MÁY NGƯỜI DÙNG ────────────────┐
│ PowerShell (Run as Admin):                  │
│ PS> irm https://server/i/t_Ab3xK9... | iex  │
│   → tải agent.msi → verify chữ ký → cài     │
│   → service enroll bằng token → heartbeat   │
│   → "✔ Cài đặt thành công"                  │
└──────────────────────┬──────────────────────┘
                       │ HTTPS + token
                       ▼
        Server: fuzzy-match fingerprint
          • Khớp máy cũ → cấp lại machine_id
          • Không khớp → tạo mới, gán org + user
        → trả machine_id + client certificate
```

### 4.2. Câu lệnh cài đặt (one-liner)

```powershell
powershell -EP Bypass -c "irm https://server.gov.vn/i/t_Ab3xK9mQ2vR8nL4p | iex"
```

- URL chứa sẵn token → server **render động install.ps1 với token nhúng bên trong**, người dùng không gõ tay.
- install.ps1 (ký Authenticode): kiểm tra quyền Admin → tải MSI → **verify SHA256 + chữ ký** → `msiexec /qn` → service tự enroll → in kết quả.

### 4.3. Thiết kế token

```sql
enroll_tokens (
  id            uuid,
  token_hash    text,          -- chỉ lưu hash, không lưu plaintext
  org_id        uuid,          -- kế thừa từ admin tạo
  created_by    uuid,          -- audit
  full_name     text,          -- thông tin người dùng máy
  department    text,
  position      text,
  email         text,
  phone_encrypted text,       -- số điện thoại (tùy chọn), mã hóa AES-256-GCM
  note          text,
  expires_at    timestamptz,   -- mặc định 72h
  max_uses      int default 1, -- 1 token = 1 máy
  used_at       timestamptz,
  used_by       uuid,
  status        enum(pending, used, revoked, expired)
)
```

**Nguyên tắc:**
- **1 token = 1 máy, dùng 1 lần.** Sau enroll, agent dùng client cert → token vô giá trị ngay cả khi bị lộ.
- TTL ngắn (24–72h), entropy ≥ 128 bit, dạng base62 cho ngắn gọn.
- Thông tin cá nhân đi kèm token (email, số điện thoại) mã hóa AES-256-GCM khi lưu; UI/export mặc định mask.
- Admin có thể revoke token chưa dùng.

### 4.4. Hai chế độ nhập thông tin

| Chế độ | Mô tả | Phù hợp |
|---|---|---|
| **A. Admin nhập hộ** | Admin nhập thông tin user (số điện thoại tùy chọn) → sinh lệnh → gửi | Cơ quan nhỏ, quản lý tập trung |
| **B. Tự khai báo** | Admin tạo link chung của cơ quan → user tự nhập thông tin (số điện thoại tùy chọn) → nhận lệnh riêng | Triển khai hàng trăm máy |
| **Bulk import** | Upload CSV → sinh hàng loạt lệnh + gửi email tự động | Triển khai đợt lớn |

### 4.5. Phễu triển khai trên dashboard (dữ liệu sống từ lúc phát lệnh)

| Người dùng | Phòng | Token | Trạng thái |
|---|---|---|---|
| Nguyễn Văn A | Kế toán | t_Ab3x... | ⏳ Đã gửi, chờ cài |
| Trần Thị B | Nhân sự | t_Qw7z... | ✅ Online (PC-042) |
| Lê Văn C | IT | t_Zx91... | ❌ Hết hạn → [Gửi lại] |

---

## 5. SERVER

### 5.1. Mô hình dữ liệu (PostgreSQL)

```sql
organizations (id, parent_id, name, type)          -- cây tổ chức: Bộ → Sở → Phòng
users         (id, org_id, full_name, email, phone_encrypted, role)
               -- phone_encrypted: số điện thoại, nullable, mã hóa AES-256-GCM (xem 7.3)
machines      (id, org_id, machine_uuid, hostname, fingerprint,
               status, enrolled_at, last_seen_at, assigned_user_id)
machine_specs (machine_id, os_name, os_version, build, cpu, ram_gb,
               disks jsonb, gpu, collected_at)      -- snapshot có lịch sử
heartbeats    (machine_id, ts, ip, logged_user, uptime_sec)  -- partition theo ngày
enroll_tokens (xem mục 4.3)
audit_log     (actor, action, target, ts, ip)
compliance_notices   (id, version, title, content_md, effective_from, status, created_by)
user_acknowledgments (user_id, notice_version, acknowledged_at, ip, source)
```

> **Bảo vệ dữ liệu cá nhân:** `phone_encrypted` lưu số điện thoại (nullable) dưới dạng mã hóa **AES-256-GCM** (IV ngẫu nhiên cho mỗi giá trị); khóa nằm trong KMS/Vault, không bao giờ lưu plaintext. Email/phone chỉ được giải mã ở endpoint có phân quyền; UI và export mặc định **mask** (VD: `0983•••123`) trừ khi có quyền xem đầy đủ. Chi tiết ở mục 7.3.

### 5.2. Trạng thái máy

| Trạng thái | Định nghĩa |
|---|---|
| `online` | Heartbeat trong ≤ 2× chu kỳ |
| `offline` | Quá chu kỳ nhưng < N ngày |
| `lost` ("máy ma") | Mất liên lạc > N ngày (30/60/90) |
| `decommissioned` | Đã thanh lý, loại khỏi thống kê |

- Trạng thái online lưu trong **Redis với TTL** → đọc nhanh, không quét DB.

### 5.3. Phân quyền (RBAC theo cây tổ chức)

| Vai trò | Quyền |
|---|---|
| Admin toàn cục | Xem/quản lý tất cả |
| Admin cơ quan | Chỉ máy + user + token thuộc cây tổ chức của mình |
| Người xem (lãnh đạo) | Dashboard read-only |

> **Xác thực 2 yếu tố (2FA):** bắt buộc cho **Admin toàn cục + Admin cơ quan** (những người sinh token, xem dữ liệu nhạy cảm); vai Người xem có thể bật tùy chính sách từng cơ quan. Dùng chuẩn **TOTP (RFC 6238)** — tương thích Google Authenticator / Authy / Microsoft Authenticator (chi tiết mục 7.3).

### 5.4. API chính

```
POST   /api/enroll                 -- agent đăng ký (token + fingerprint)
POST   /api/heartbeat              -- mTLS, agent heartbeat
POST   /api/inventory              -- mTLS, gửi snapshot cấu hình
GET    /i/{token}                  -- render install.ps1 động
POST   /api/tokens                 -- portal: sinh token
GET    /api/machines?org=&status=  -- portal: danh sách máy
GET    /api/stats/overview         -- portal: thống kê tổng quan
POST   /api/reports/export         -- xuất Excel/PDF
GET    /api/ws                     -- WebSocket realtime dashboard
```

---

## 6. DANH SÁCH TÍNH NĂNG CHI TIẾT

### 6.1. Nhóm dữ liệu sống (core)

| # | Tính năng | Mô tả |
|---|---|---|
| 1 | Timeline bật/tắt | Lịch sử bật máy: giờ dùng/ngày, tần suất → phát hiện máy bỏ không |
| 2 | Phát hiện "máy ma" | Enroll nhưng > 30/60/90 ngày không online → danh sách kiểm tra |
| 3 | Phân biệt máy thật/ảo | Tránh đếm VM sai lệch thống kê tài sản vật lý |
| 4 | Cảnh báo fingerprint drift | Máy đổi mainboard/ghost Win → log cho admin duyệt, chống gian lận định danh |
| 5 | Windows EOL report | Liệt kê máy chạy Windows sắp/đã hết vòng đời → lộ trình nâng cấp |
| 6 | Sức khỏe ổ cứng (SMART) | Cảnh báo ổ sắp hỏng trước khi mất dữ liệu |

### 6.2. Nhóm an ninh & tuân thủ

| # | Tính năng | Mô tả |
|---|---|---|
| 7 | Software inventory | Phát hiện phần mềm không phép / không bản quyền |
| 8 | Trạng thái Antivirus | Máy chưa cài AV / tắt AV / định nghĩa virus cũ |
| 9 | Windows Update status | Máy thiếu patch bảo mật quan trọng |
| 10 | Cấu hình rủi ro | RDP mở, tài khoản không mật khẩu, nhiều local admin, share công khai, BitLocker tắt |
| 11 | Phát hiện dual-homed | Máy cắm đồng thời 2 mạng (vi phạm an ninh mạng cách ly) |

### 6.3. Nhóm đặc thù mạng cơ quan

| # | Tính năng | Mô tả |
|---|---|---|
| 12 | **Chế độ máy cách ly (offline)** | Agent ghi dữ liệu ra file **ký số** → cán bộ copy USB → import vào server. Phủ sóng cả mảng máy mạng nội bộ không ra internet |
| 13 | Tự gán tổ chức theo rule | Theo dải IP, hostname pattern (`KT-*` → phòng Kế toán) → giảm nhập tay khi triển khai lớn |

### 6.4. Nhóm cảnh báo & báo cáo

| # | Tính năng | Mô tả |
|---|---|---|
| 14 | Alert rules | Máy mới xuất hiện, mất liên lạc > N ngày, phần mềm lạ, phần cứng thay đổi |
| 15 | Kênh nhận cảnh báo | Email + **Zalo OA / Telegram bot** (admin nhận trên điện thoại) |
| 16 | Báo cáo định kỳ tự động | Tuần/tháng, xuất **Excel/PDF theo biểu mẫu hành chính** |
| 17 | Dashboard lãnh đạo | View read-only, số to, biểu đồ rõ ràng |

### 6.5. Nhóm vận hành & quản trị

| # | Tính năng | Mô tả |
|---|---|---|
| 18 | Vòng đời tài sản | Mới cài → Đang dùng → Sửa chữa → Thanh lý, kèm ghi chú |
| 19 | Tag + tìm kiếm nâng cao | "Máy Win10, RAM < 8GB, thuộc Sở X" |
| 20 | Diff cấu hình | So sánh 2 máy, hoặc 1 máy ở 2 thời điểm |
| 21 | Tích hợp AD/LDAP | Đồng bộ danh sách người dùng; SSO (OIDC) cho portal |
| 22 | API mở | Cho hệ thống khác lấy dữ liệu tái sử dụng |
| 23 | On-demand rescan | Admin bấm "thu thập lại" → agent quét ngay, không chờ chu kỳ |
| 24 | Thông báo tuân thủ pháp lý | Server lưu bản thông báo tuân thủ (version hóa) → portal bắt buộc xác nhận khi đăng nhập lần đầu / khi có bản mới; install.ps1 in tóm tắt dữ liệu thu thập + link bản đầy đủ (mục 7.4) |
| 25 | Đổi endpoint & chu kỳ heartbeat từ xa | Config ký số (public key nhúng sẵn trong agent): đổi IP/domain server, chỉnh chu kỳ heartbeat; endpoint dự phòng + rollback tự động — không phải cài lại agent khi đổi hạ tầng (mục 3.5) |

### 6.6. Những thứ CỐ TÌNH không làm

| Không làm | Lý do |
|---|---|
| Screenshot, keylog, lịch sử web | Rủi ro pháp lý + AV gắn cờ + người dùng chống đối |
| Remote shell / điều khiển máy | Phình scope, rủi ro bảo mật, kéo theo yêu cầu audit phức tạp |
| Agent có quyền ghi/xóa tùy ý | Giữ read-only → dễ qua vòng duyệt an ninh |

---

## 7. BẢO MẬT

| Rủi ro | Giải pháp |
|---|---|
| Sniffing/giả mạo kênh truyền | HTTPS bắt buộc + mTLS (mỗi agent 1 cert, thu hồi lẻ được) |
| `irm \| iex` chạy script mạng | Script ký Authenticode + verify SHA256/chữ ký MSI trước khi cài |
| Token lộ (lịch sử PS, chat) | Single-use + TTL 24–72h + sau enroll dùng cert |
| Kẻ lạ enroll máy ngoài | Máy lạ hiện trên dashboard của admin; tùy chọn **pending approval** (máy chờ duyệt mới tính chính thức) |
| Brute-force token | Entropy ≥128 bit + rate-limit endpoint enroll theo IP |
| DNS hijack / gói config giả dẫn agent về server lạ | Config update bắt buộc **ký số** (public key nhúng trong agent từ lúc build) + verify TLS + rollback endpoint cũ (mục 3.5) |
| Truy cập trái phép portal | RBAC theo cây tổ chức + JWT/OIDC + **2FA TOTP cho admin** + audit log đầy đủ (ai tạo token, IP nào dùng, máy nào enroll, lúc nào) |
| Dữ liệu cấu hình máy nhạy cảm | Mã hóa at-rest, giới hạn quyền đọc theo org |
| Agent bị sửa/đóng gói lại | Chỉ chạy update có chữ ký hợp lệ; verify cert chain |

### 7.1. Vòng đời client certificate (mTLS)

> **Phân tầng xác thực:** hệ thống dùng **2 cơ chế riêng biệt, không thay thế nhau** —
> - **Agent** (thiết bị chạy tự động lâu dài): dùng **mTLS client cert** — định danh máy bền vững, thu hồi lẻ qua CRL. mTLS phù hợp hơn JWT vì agent hoạt động liên tục (heartbeat 45–75s), cần danh tính ổn định và thu hồi chính xác từng máy, thay vì token ngắn hạn phải refresh lại định kỳ.
> - **Portal quản trị** (con người): dùng **JWT/OIDC** (mục 5.3, 7.3) — phiên ngắn, hợp trình duyệt, thu hồi nhanh khi đăng xuất/đổi quyền.
>
> Tóm lại: **JWT cho người, mTLS cho máy.**

- **CA nội bộ** chuyên cho hệ thống (tự vận hành — VD: step-ca — hoặc PKI quản lý), tách khỏi CA công cộng; root CA lưu offline, issuing CA nằm trong HSM/KMS.
- **Cấp phát**: tại lúc enroll, server sinh client cert (ECDSA P-256), trả kèm `machine_id`; agent giữ private key cục bộ, không gửi lên server.
- **Hiệu lực**: 1 năm (có thể rút ngắn 6 tháng nếu yêu cầu quản lý chặt).
- **Tự gia hạn (renew)**: agent chủ động tạo CSR mới khi cert còn ~70% thời gian sống (server trả `renew_after` khi xác thực) → server ký lại → agent thay cert. Không cần thao tác tay, tránh "lost" oan vì cert hết hạn.
- **Thu hồi**: thanh lý máy, máy mất/đánh cắp, hoặc nghi ngờ bị chiếm dụng → thêm serial vào **CRL** (server mTLS kiểm tra CRL với cache ngắn; tùy chọn OCSP) → agent bị từ chối kết nối và ghi log để xử lý.
- **Server TLS cert**: dùng CA công cộng, tự gia hạn qua ACME (certbot) hoặc quy trình định kỳ; cảnh báo sớm (≥ 30 ngày) trước khi hết hạn.

### 7.2. Audit integrity

- **Append-only**: bảng `audit_log` chỉ được INSERT (role DB tách biệt, thu hồi UPDATE/DELETE); ghi mọi thao tác nhạy cảm: đăng nhập/thoát, sinh/revoke token, enroll, thay đổi quyền, xuất báo cáo, xác nhận tuân thủ.
- **Hash chain**: mỗi dòng chứa `prev_hash` + hash SHA-256 nội dung dòng → phát hiện ngay mọi sửa đổi/xóa ở giữa chuỗi.
- **Anchor ký định kỳ**: định kỳ (hàng ngày/giờ) băm toàn bộ chuỗi → ký bằng khóa riêng (HSM/KMS) → lưu anchor ra ngoài DB (file chỉ-ghi, object storage) → chứng minh log chưa bị sửa kể từ thời điểm anchor.
- **Kiểm soát truy cập**: chỉ dịch vụ nội bộ được ghi; đọc log phân quyền theo vai trò; export dạng bất biến (kèm chữ ký) — không dùng Excel chỉnh sửa cho mục đích đối soát.
- **Truy vết chuỗi sự kiện**: mỗi bản ghi kèm `request_id`/`machine_id` để nối chuỗi: token `t_Ab3x...` → enroll → `machine_id` → heartbeat đầu tiên → thay đổi cấu hình.

### 7.3. Hardening server & hạ tầng

**Hạ tầng & mạng:**
- TLS 1.2+ (tắt 1.0/1.1), HSTS, security headers (CSP, X-Frame-Options, ...).
- Tách lớp: API + Portal ở DMZ; PostgreSQL/Redis ở vùng nội bộ; firewall stateful giữa các lớp; chỉ mở cổng 443 ra ngoài.
- Chạy non-root (container/service user riêng), image tối giản, quét lỗ hổng định kỳ, vá OS + runtime + dependencies.

**Quản lý bí mật (secrets):**
- Mọi bí mật trong Vault/KMS: khóa AES mã hóa dữ liệu nhạy cảm, khóa ký MSI/install.ps1, khóa ký config agent (mục 3.5), khóa CA, DB credentials — không hardcode trong code/config.
- Khóa AES: vòng đời rõ ràng (rotation định kỳ, re-encrypt/key wrapping), quyền giải mã tối thiểu theo endpoint.
- Khóa ký: lưu trong HSM/cloud KMS (EV cert bắt buộc token phần cứng) — server bị xâm nhập cũng không lộ được khóa ký.

**Ứng dụng & dữ liệu:**
- Rate-limit theo IP + theo tài khoản trên mọi endpoint nhạy cảm (enroll, login, token, export).
- JWT ngắn hạn + refresh token có rotation; OIDC khi tích hợp AD (Phase 4).
- **2FA với TOTP cho admin** (bắt buộc — mục 5.3):
  - Kích hoạt: admin quét **QR** chứa TOTP seed → nhập mã 6 số 1 lần để xác nhận → cấp **backup codes** (dùng 1 lần, phòng mất thiết bị).
  - Lưu seed dạng mã hóa **AES-256-GCM** (dùng chung khóa KMS như dữ liệu nhạy cảm, mục 7.3); không lưu plaintext.
  - Verify TOTP với clock-skew dung sai (±1 bước) + chống replay; không dùng chung seed giữa các account.
  - Hỗ trợ nhiều app chuẩn TOTP (Google Authenticator / Authy / Microsoft Authenticator) — không khóa vào một app.
  - Chính sách lockout sau N lần nhập sai + cảnh báo đăng nhập từ thiết bị/IP lạ.
- Giới hạn kích thước payload (inventory có thể lớn), validate schema đầu vào.
- Mã hóa at-rest (disk DB), backup mã hóa + **test restore định kỳ** với RPO/RTO được định nghĩa.

**Giám sát & vận hành:**
- Metric + log tập trung, cảnh báo khi API lỗi / Redis nghẽn / CA–CRL down.
- Cảnh báo sớm: cert sắp hết hạn, tỉ lệ renew thất bại, máy chuyển "lost" bất thường hàng loạt.

### 7.4. Tuân thủ pháp lý & thông báo người dùng

- **Mục đích**: minh bạch việc thu thập dữ liệu, phù hợp **Nghị định 13/2023/NĐ-CP** (bảo vệ dữ liệu cá nhân), Luật An toàn thông tin mạng 2015, Luật An ninh mạng 2018.
- **Bản thông báo tuân thủ** (lưu trên server, version hóa — bảng `compliance_notices`): nêu rõ dữ liệu thu thập (cấu hình máy, online/offline, user đăng nhập, IP, ...), mục đích, thời hạn lưu trữ, ai được truy cập, quyền của người dùng (yêu cầu chỉnh sửa/xóa, kênh liên hệ).
- **Cơ chế hiển thị**:
  - Portal: hiển thị lần đăng nhập đầu + khi có bản mới (so version) → bắt buộc **xác nhận đã đọc** (ghi `user_acknowledgments`: user, version, thời gian, IP) trước khi tiếp tục dùng.
  - Cài đặt: `install.ps1` in tóm tắt dữ liệu thu thập + in link bản đầy đủ; người dùng có thể hủy trước khi cài.
  - Dashboard admin: link thường trực "Thông báo tuân thủ" + lịch sử các bản đã phát hành.
- **Đồng bộ với dữ liệu nhạy cảm**: khi thu thập thêm trường nhạy cảm (VD: số điện thoại — mục 5.1), bản thông báo phải liệt kê đúng trường, mục đích, thời hạn — khớp với thiết kế mã hóa (mục 7.3).

---

## 8. ROADMAP TRIỂN KHAI

```
Phase 1 — MVP (nền tảng + dữ liệu sống tối thiểu)
├── Agent C#: enroll, inventory cơ bản, heartbeat jitter (~30s), offline cache, tự renew client cert, endpoint dự phòng (failover tĩnh)
├── Server: API enroll/heartbeat/inventory, PostgreSQL + Redis, CA nội bộ + CRL
├── Portal: đăng nhập + 2FA (TOTP) cho admin + xác nhận thông báo tuân thủ pháp lý (bản 1), sinh token (chế độ A), danh sách máy on/off
├── Audit log append-only (hash chain) cho admin/token/enroll
└── Báo cáo Excel cơ bản

Phase 2 — Làm giàu dữ liệu
├── Timeline bật/tắt, phát hiện máy ma
├── Software inventory, trạng thái AV, Windows Update
├── Windows EOL report
├── Alert rules + Zalo/email
├── Token chế độ B (tự khai báo) + bulk import CSV
├── Tự gán tổ chức theo rule (IP/hostname)
└── Anchor ký audit log định kỳ + hardening checklist hoàn chỉnh

Phase 3 — Đặc thù & nâng cao
├── Chế độ máy cách ly (offline USB, file ký số)
├── Phát hiện dual-homed
├── SMART ổ cứng, fingerprint drift
├── Vòng đời tài sản, diff cấu hình
├── Pending approval cho máy mới
├── Config ký số từ xa: đổi endpoint IP/domain + chu kỳ heartbeat (có rollback)
└── On-demand rescan

Phase 4 — Tích hợp & mở rộng
├── AD/LDAP sync, SSO OIDC
├── API mở cho hệ thống khác
├── Dashboard lãnh đạo
└── Báo cáo PDF theo biểu mẫu hành chính
```

> **Nguyên tắc:** không ôm quá 3 tính năng ngoài core vào MVP. Hệ thống thắng bằng *độ tin cậy của số liệu*, không phải số lượng tính năng.

---

## 9. ƯỚC LƯỢNG NGUỒN LỰC (tham khảo)

Giả định team: 1 backend, 1 frontend, 1 Windows dev (có thể kiêm), 1 tester bán thời gian.

| Phase | Khối lượng chính | Ước lượng |
|---|---|---|
| Phase 1 | Agent enroll/heartbeat/inventory + API + DB + portal cơ bản + MSI/install.ps1 ký số | 8–10 tuần |
| Phase 2 | 6 tính năng mở rộng + alert + báo cáo | 6–8 tuần |
| Phase 3 | Offline USB + dual-homed + SMART + vòng đời | 6–8 tuần |
| Phase 4 | SSO, API mở, dashboard lãnh đạo | 4–6 tuần |

Các đầu việc cần chuẩn bị song song (không tính vào dev):
- Mua EV Code Signing certificate: 1–3 tuần (xác minh tổ chức).
- Submit Microsoft WDSI + whitelist AV: 1–2 tuần.
- Tên miền + chứng chỉ TLS cho server.
- Đã bao gồm trong ước lượng dev: hạ tầng CA nội bộ + vòng đời cert (~1 tuần), mã hóa số điện thoại + thông báo tuân thủ pháp lý (đầu việc nhỏ, không tách riêng).

---

## 10. RỦI RO & GIẢM THIỂU

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| AV gắn cờ agent | Cao | EV cert + metadata đầy đủ + không packer + submit WDSI trước + whitelist AV tập trung của cơ quan |
| Người dùng không chạy lệnh cài | Trung bình | Lệnh 1 dòng + ảnh/video hướng dẫn + dashboard phễu triển khai để admin đôn đốc + bulk email |
| Máy không ra được internet | Cao | Phase 3: chế độ offline USB (file ký số) |
| Đếm trùng máy (ghost Win, thay phần cứng) | Trung bình | Fingerprint đa nguồn + fuzzy matching + idempotent install |
| Server quá tải khi số máy lớn | Thấp/Trung | Redis cho online status, partition bảng heartbeat, batch insert; chỉnh chu kỳ heartbeat theo quy mô qua config ký số (mục 3.5) |
| Đổi IP/domain server → agent mất liên lạc hàng loạt | Trung bình | Endpoint dự phòng + signed config push (mục 3.5) + runbook chạy song song server cũ/mới khi chuyển đổi |
| Rò rỉ dữ liệu cấu hình | Trung bình | mTLS + RBAC + mã hóa at-rest + audit log |
| Scope creep (biến thành công cụ giám sát) | Trung bình | Danh sách "cố tình không làm" (mục 6.6), giữ agent read-only |
| Cert hết hạn hàng loạt → máy "lost" oan | Trung bình | Agent tự renew trước hạn (~70% vòng đời), CRL/OCSP kịp thời, cảnh báo cert sắp hết hạn |
| Rò rỉ dữ liệu cá nhân (số điện thoại, email) | Trung bình | AES-256-GCM + khóa trong KMS/Vault, mask mặc định, giới hạn quyền giải mã, tuân thủ NĐ 13/2023/NĐ-CP |
| Không minh bạch việc thu thập dữ liệu → khiếu nại/pháp lý | Trung bình | Thông báo tuân thủ version hóa + xác nhận bắt buộc (portal + install.ps1) + audit acknowledgment |

---

*Hết tài liệu kế hoạch. Phiên bản 1.2 — bổ sung: đổi endpoint server từ xa (mục 3.5), heartbeat mặc định ~30s, đặc tả dữ liệu truyền JSON + mã hóa (mục 3.6). Dùng để nghiên cứu và thảo luận nội bộ.*
