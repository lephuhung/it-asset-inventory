# RUNBOOK VẬN HÀNH — IT Asset Inventory (Phase 1 MVP)

> Căn cứ: PLAN_THUC_HIEN.md mục 7 (bàn giao vận hành), KE_HOACH mục 3.5 (đổi endpoint), 7.3 (hardening).
> Vai trò: PM / Admin hệ thống / Đội an ninh cơ quan.

---

## 1. TRIỂN KHAI CƠ QUAN MỚI (checklist)

1. ☐ Bàn giao **hash + publisher cert** của `agent.msi`/`agent.exe`/`install.ps1` cho đội an ninh mạng để **whitelist AV tập trung** (BKAV Pro / Kaspersky Security Center / Defender GPO). *Làm trước khi cài đại trà.*
2. ☐ Submit Microsoft WDSI cho mỗi release binary mới.
3. ☐ Đăng ký tên miền + TLS cert (ACME/certbot), VD `inventory.<coquan>.gov.vn`.
4. ☐ Tạo org + admin cơ quan trên portal; bật 2FA TOTP cho admin.
5. ☐ Cập nhật bản thông báo tuân thủ pháp lý (compliance_notice) theo đúng dữ liệu thu thập + mục đích + thời hạn lưu trữ (NĐ 13/2023/NĐ-CP).
6. ☐ Thử nghiệm pilot 5–10 máy thật 1 tuần trước khi mở rộng (tiêu chí Go/No-Go mục 4 PLAN).

## 2. ĐỔI IP/DOMAIN SERVER (mục 3.5 tài liệu gốc)

1. Dựng server mới chạy **song song**; giảm DNS TTL ≥ 1 ngày trước.
2. Đẩy config endpoint mới cho agent (Phase 3: signed config push; trước đó: thay config tay qua MSI repair hoặc cập nhật file config trong ProgramData theo kênh nội bộ).
3. Theo dõi tỉ lệ agent đã chuyển trên dashboard.
4. Khi ≥ 99% agent chuyển → tắt server cũ; giữ DNS cũ redirect thêm thời gian cho máy offline lâu ngày.

## 3. VÒNG ĐỜI CERT

- **Client cert agent**: tự renew ở ~70% vòng đời (RenewService). Cảnh báo sớm 30 ngày nếu tỉ lệ renew thất bại tăng.
- **Server TLS cert**: ACME/certbot tự gia hạn; cảnh báo ≥ 30 ngày trước hết hạn.
- **CA nội bộ (step-ca)**: root CA lưu **offline**; issuing CA trong KMS/HSM; CRL được cron tải về nginx + `nginx -s reload` (không downtime).
- Thanh lý/mất máy: thu hồi cert qua step-ca → CRL → agent bị chặn ở tầng TLS.

## 4. BACKUP & RESTORE

- Backup hàng ngày: PostgreSQL (pg_dump), Redis (rdb), config Vault.
- Backup **mã hóa**; test restore định kỳ với RPO/RTO đã định nghĩa (VD RPO 24h, RTO 4h).
- `audit_log` anchor ký định kỳ (Phase 2) lưu ra ngoài DB (object storage/file chỉ-ghi).

## 5. XỬ LÝ SỰ CỐ

| Sự cố | Triệu chứng | Xử lý |
|---|---|---|
| AV gắn cờ agent | Máy không cài được / agent bị xóa | Kiểm tra whitelist AV đã đẩy hash mới chưa; submit WDSI; liên hệ đội an ninh cơ quan |
| Máy "lost" hàng loạt | Dashboard thấy nhiều máy offline > N ngày | Kiểm tra cert client hết hạn (renew fail), CRL sai, mạng chặn 443, đổi domain chưa hoàn tất |
| Heartbeat trễ | Trạng thái online sai lệch | Kiểm tra Redis, load server, tăng heartbeat_interval_sec qua config |
| Agent không enroll | Token lỗi | Token 1 lần + TTL 72h — sinh token mới; kiểm tra đồng hồ máy (TLS cần clock đúng) |
| Giả header X-SSL-Client | Nghi ngờ request lạ vào thẳng FastAPI | FastAPI chỉ bind IP nội bộ + TRUSTED_PROXIES; kiểm tra firewall giữa nginx và app |
| Quá tải | API chậm, Redis nghẽn | Batch insert heartbeats, tăng chu kỳ heartbeat, scale worker |

## 6. TRIỂN KHAI MÁY CÁCH LY (offline USB)

> Xem chi tiết kỹ thuật + format file trong `docs/OFFLINE_AGENT_SPEC.md`. Mục này tóm
> tắt quy trình vận hành cho admin.
>
> **Lưu ý quan trọng**: trước khi triển khai máy cách ly, cần cài đặt agent trên máy
> đó. Có **2 phương pháp** tuỳ theo máy có mạng ra server hay không — xem bảng so sánh
> trong `OFFLINE_AGENT_SPEC.md` mục 1. Nếu máy cách ly **không có mạng**, dùng
> **Phương pháp B** (tải file qua USB) ở bước 6.1B dưới đây.

### 6.1. Cài đặt agent lên máy cách ly

#### 6.1A. Phương pháp A — Cài bằng lệnh (online, một dòng)

> **Chỉ dùng được nếu máy cách ly CÓ đường mạng tới server** (qua VPN site-to-site,
> hoặc proxy cho phép). Đa số máy cách ly thật sự air-gapped → dùng phương pháp B.

Trên máy cài (Admin PowerShell):
```powershell
irm http://server/i/<enroll_token> | iex
```
Script tự tải MSI + verify chữ ký + cài silent. Sau khi cài xong, agent tự enroll
trong ~30 giây (không cần thao tác tay). Chuyển sang mục 6.4 để lên lịch xuất
inventory.

#### 6.1B. Phương pháp B — Cài bằng tải file (offline, copy qua USB) — **khuyến nghị cho máy cách ly**

**Trên máy admin có mạng** (làm trước):

1. Admin đăng nhập portal, vào **Quản lý Token → Tạo token** với org là đơn vị của máy
   cách ly. Lưu lại token (1 lần, hiển thị ngay khi tạo).
2. Tải 3 file về cùng thư mục trên USB (ví dụ `E:\agent\`):
   - `OrgInventoryAgent.msi` — file đã ký Authenticode, lấy từ portal/releases hoặc
     share nội bộ (`\\fileserver\Releases\OrgInventory\OrgInventoryAgent.msi`).
   - `OrgInventoryAgent.msi.sha256` — cùng SHA256 build script sinh ra, copy cùng MSI.
   - `install-offline.ps1` — wrapper cài cho máy cách ly, tải từ server:
     ```powershell
     Invoke-WebRequest http://server/download/install-offline.ps1 -OutFile E:\agent\install-offline.ps1
     ```
     (Hoặc copy file `app/templates/install-offline.ps1` từ source server.)
3. Ghi lại token + URL endpoint ra giấy / file `.txt` trên USB. KHÔNG gửi token qua
   email/kênh không mã hóa.

**Trên máy cách ly** (Admin PowerShell):

1. Cắm USB vào máy cách ly.
2. Chạy:
   ```powershell
   E:\agent\install-offline.ps1 -Token "<enroll_token>" -Endpoints "https://agent.example.gov.vn"
   ```
   Script tự động:
   - Kiểm tra quyền Administrator.
   - Verify SHA256 + Authenticode của MSI.
   - Hiển thị thông báo tuân thủ, chờ user nhấn Enter.
   - Chạy `msiexec /i ... /qn ENROLL_TOKEN=<token> ENDPOINTS=<url>`.
3. Sau khi cài xong, **service agent đã chạy** nhưng **chưa enroll được** (vì không có
   mạng). Tiếp tục bước 6.2 bên dưới để sinh CSR và lấy cert.

### 6.2. Sinh CSR trên máy cách ly (sau khi cài agent)

Trên máy cách ly (Admin PowerShell), chạy:
```powershell
"C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --enroll-offline E:\agent\enroll.json
```
File `enroll.json` chứa CSR + fingerprint + token, ghi ra USB.

### 6.3. Admin proxy CSR qua API (máy admin có mạng)

1. Rút USB, cắm vào máy admin nối mạng.
2. Mở PowerShell, gọi API:
   ```powershell
   $body = Get-Content D:\usb\enroll.json -Raw | ConvertFrom-Json
   $token = (curl -X POST http://server/api/auth/login -d '{"email":"...","password":"..."}' `
             -ContentType application/json | ConvertFrom-Json).access_token

   $payload = @{
     token       = $body.token
     hostname    = $body.hostname
     fingerprint = $body.fingerprint
     csr_pem     = $body.csr_pem
   } | ConvertTo-Json -Depth 10

   Invoke-RestMethod -Uri "http://server/api/offline/enroll" `
     -Method POST -ContentType "application/json" `
     -Headers @{Authorization="Bearer $token"} `
     -Body $payload | ConvertTo-Json -Depth 10 | Out-File D:\usb\cert.json -Encoding UTF8
   ```
3. Hoặc dùng curl (Linux/macOS):
   ```bash
   ADMIN_TOKEN=$(curl -s -X POST http://server/api/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"admin@…","password":"…"}' | jq -r .access_token)

   curl -s -X POST http://server/api/offline/enroll \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' \
     --data-binary @D:/usb/enroll.json > D:/usb/cert.json
   ```
   **Kiểm tra response**: phải có `client_cert_pem` (bắt đầu bằng
   `-----BEGIN CERTIFICATE-----`), `is_new_machine`, `status`. Lỗi 401/403/422 → xem
   chi tiết trong RUNBOOK mục 5 (Xử lý sự cố).

### 6.4. Cài cert trên máy cách ly

1. Cắm USB vào máy cách ly → chạy:
   ```powershell
   "C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --install-cert D:\usb\cert.json
   ```
   Cert được import vào Windows Cert Store; `state.json` lưu `machine_id` + config.
2. Service agent từ giờ cache mọi inventory/heartbeat. Không cần làm gì thêm trên máy.

### 6.5. Xuất inventory định kỳ (hàng tuần/tháng)

1. Trên máy cách ly:
   ```powershell
   "C:\Program Files\OrgInventory\OrgInventoryAgent.exe" --export-inventory D:\usb\inv-2026-08-26.json
   ```
2. Copy USB sang máy admin → nhập vào server:
   ```bash
   curl -s -X POST http://server/api/offline/import \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' \
     --data-binary @D:/usb/inv-2026-08-26.json | jq .
   ```
   Kết quả mong đợi: `{"machine_id":"...","hostname":"...","is_new":false,"verified":true}`.
3. **Audit log** sẽ ghi `action=offline.import`, `actor=admin:<id>` → truy vết được.

### 6.6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `401 Token không tồn tại` khi gọi `/api/offline/enroll` | Token đã dùng/hết hạn/sai | Tạo token mới, copy lại USB, chạy lại `--enroll-offline` trên máy cách ly |
| `Chữ ký không hợp lệ` khi `/api/offline/import` | File JSON bị sửa giữa máy cách ly ↔ admin | Chạy lại `--export-inventory`; so SHA-256 file (agent CLI in ra) |
| Cert CN không khớp `machine-<id>` | Cài nhầm cert của máy khác | Dùng đúng file `cert.json` tương ứng với token; kiểm tra `machine_id` trong response |
| Agent không thấy trong `/api/machines` | Nhầm org | Kiểm tra org của token trùng org của đơn vị trên portal; dùng `visible_org_ids` |
| Service không chạy | Chưa cài MSI hoặc cert chưa import | Kiểm tra Event Viewer → Application → `OrgInventoryAgent` |

### 6.7. Không được

- Không commit private key của máy cách ly lên bất kỳ repo nào (kể cả portal backup).
- Không share token enroll qua email/kênh không mã hóa — token tương đương quyền enroll máy
  mới vào tổ chức.
- Không chạy `/api/offline/enroll` mà không kiểm tra file USB trước (xác nhận SHA-256 in
  bởi `--enroll-offline`).

## 7. BẢO TRÌ ĐỊNH KỲ

- Hàng tuần: xem dashboard, kiểm tra cảnh báo cert, tỉ lệ heartbeat thành công.
- Mỗi release: build agent mới → ký OV cert + timestamp → WDSI → cập nhật hash whitelist AV → release theo đợt.
- Mỗi quý: test restore backup 1 lần, review audit log hash chain, cập nhật runbook.

## 8. KHÔNG ĐƯỢC LÀM

- Không upload agent lên VirusTotal (phát tán mẫu → ML vendor học theo).
- Không thay đổi agent thành công cụ giám sát (screenshot/keylog/remote shell) — mục 6.6 tài liệu gốc.
- Không tắt mTLS/verify để "cho nhanh".
