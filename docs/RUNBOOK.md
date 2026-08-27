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
2. Đẩy config endpoint mới cho agent qua kênh **Signed Config Push**:
   - Gói cấu hình mới bắt buộc được ký số ECDSA (khóa Server) và tăng trường `version`.
   - Khi Agent tải về qua `GET /api/agent/config` hoặc nhận qua `POST /api/heartbeat`, Agent đối chiếu chữ ký với Server Public Key nhúng sẵn trước khi ghi đè `config.json`. Chống kẻ gian giả mạo DNS chuyển hướng Agent.
   - Cơ chế tự phục hồi (Rollback): Nếu endpoint mới không kết nối được sau 5 lần thử liên tiếp, Agent tự động rollback về endpoint cũ và báo cáo sự cố khi kết nối lại được.
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
> **Lưu ý quan trọng**: Agent trên máy cách ly **không enroll qua mạng** (vì không có
> mạng ra server). Toàn bộ quy trình là **1-click qua USB**: tải gói ZIP về USB → nháy
> đúp `install-offline.cmd` trên máy cách ly → file ZIP mã hoá được xuất ra → admin
> upload lên Portal. Server xác thực chữ ký + giải mã + parse dữ liệu.
>
> **Không cần** bất kỳ thao tác CSR / cert / token nào trên máy cách ly.

### 6.1. Chuẩn bị USB trên máy admin (có mạng)

1. Admin đăng nhập Portal → **Quản lý Token → Tạo token** với org là đơn vị của máy
   cách ly. Lưu lại token (chỉ hiện 1 lần khi tạo).
2. Tải gói ZIP **KHÔNG có password** từ:
   - **Cách 1 (khuyến nghị)**: `GET /download/offline-package.zip` (1 file duy nhất).
   - **Cách 2**: tải từng file qua 5 endpoint:
     - `/download/install-offline.cmd` (launcher nháy đúp chuột)
     - `/download/install-offline.ps1` (script điều phối)
     - `/download/server_public_key.pem` (RSA-2048 public key của Server)
     - `/download/agent.msi` (MSI installer)
     - `/download/agent.msi.sha256` (SHA-256 verify MSI)
3. **Giải nén** vào thư mục gốc USB (ví dụ `E:\`). Trên USB có tối đa 6 file:
   ```
   E:\install-offline.cmd
   E:\install-offline.ps1
   E:\server_public_key.pem
   E:\offline_config.json     (cấu hình mẫu — admin điền token nếu muốn)
   E:\OrgInventoryAgent.msi   (nếu server có sẵn)
   E:\OrgInventoryAgent.msi.sha256
   ```
4. (Tuỳ chọn) Mở `offline_config.json` bằng notepad, điền `token` và `endpoints` nếu
   muốn agent tự động biết token lúc cài (nếu để trống, agent vẫn hoạt động bình
   thường — fingerprint phần cứng làm định danh).

> **Lưu ý bảo mật**: ZIP tải về **không đặt password** (yêu cầu nghiệp vụ — operator
> copy qua USB dễ dàng). Tính bí mật dựa vào **mã hoá hybrid AES-256-GCM + RSA-OAEP**
> ở file ZIP do agent sinh ra SAU (xem mục 6.3). Test `test_offline_package_zip_is_not_password_protected`
> chặn regression.

### 6.2. Thao tác trên máy cách ly (người dùng cuối)

1. Cắm USB vào máy cách ly.
2. Mở Windows Explorer, **nháy đúp chuột vào `install-offline.cmd`** (hoặc chuột phải
   chọn "Run as Administrator").
3. **Không cần gõ bất kỳ lệnh nào** — script tự động:
   - Xin quyền Administrator (UAC elevation).
   - Đọc cấu hình từ `offline_config.json` (nếu có).
   - Verify SHA-256 toàn vẹn của `OrgInventoryAgent.msi`.
   - Verify Authenticode signature của MSI.
   - Cài Agent qua `msiexec /qn ENROLL_TOKEN=<token> ENDPOINTS=<url>` (chỉ để MSI
     ghi registry bootstrap — KHÔNG gọi server, KHÔNG cấp client cert).
   - Gọi `OrgInventoryAgent.exe --export-bundle <đường dẫn USB>` để:
     - Thu thập fingerprint + inventory (CPU, RAM, disk, software, security...).
     - Sinh cặp khoá ECDSA P-256 (private key **ở lại máy cách ly**, không bao giờ
       thoát ra).
     - Ký số ECDSA-SHA256 trên canonical JSON của inventory.
     - Mã hoá hybrid AES-256-GCM + RSA-OAEP bằng `server_public_key.pem`.
     - Đóng gói thành 1 file ZIP.
4. File ZIP kết quả xuất hiện ngay tại thư mục USB:
   ```
   E:\INVENTORY_<HOSTNAME>_<YYYYMMDD_HHMMSS>.zip
   ```
   Thông báo xanh xuất hiện: *"Vui lòng rút USB và chuyển file cho Quản trị viên để
   cập nhật"*.

### 6.3. Admin upload lên Portal (máy admin có mạng)

1. Cắm USB vào máy admin → vào Portal → **Import máy cách ly** (`/offline-import`).
2. Chọn hoặc kéo thả file `INVENTORY_*.zip` vào khung upload.
3. Nhấn **Xác nhận nạp dữ liệu**:
   - Frontend gọi `POST /api/offline/import` (multipart/form-data).
   - Backend đọc ZIP, RSA-decrypt `encrypted_key.bin` → lấy AES session key.
   - AES-GCM decrypt `encrypted_payload.bin` → inventory JSON.
   - Verify ECDSA signature bằng `public_key.pem` trong ZIP (chống sửa file trên USB).
   - Dùng `fingerprint` (SMBIOS UUID / MachineGuid / Mainboard Serial) để **tự tạo mới**
     máy nếu chưa có, hoặc cập nhật máy đã có (dựa vào `machine_uuid`).
   - Parse inventory → lưu `machine_specs` + cập nhật `machine_current` + replace
     `machine_software`.
4. Kết quả trả về: `{ machine_id, hostname, is_new, verified, apps_count, collected_at }`.

### 6.4. Cập nhật dữ liệu định kỳ (tuần/tháng)

Lặp lại **mục 6.2 + 6.3** mỗi khi cần cập nhật. Mỗi lần upload tạo 1 `MachineSpec`
mới trong DB (lưu lịch sử), cập nhật bảng `machine_current` (mới nhất). Máy vẫn giữ
`status = offline` (không có heartbeat) nhưng có đầy đủ lịch sử cấu hình.

### 6.5. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Script dừng với `[LỖI] Mã băm SHA256 KHÔNG khớp` | MSI bị hỏng trên USB (copy lỗi, virus) | Copy lại từ USB nguồn / share nội bộ |
| Script dừng với `Authenticode signature invalid` | MSI bị sửa hoặc cert hết hạn | Build lại MSI, ký lại Authenticode |
| `Chữ ký không hợp lệ` khi upload | ZIP bị sửa giữa máy cách ly ↔ admin (USB lỗi) | Chạy lại trên máy cách ly (nháy đúp `install-offline.cmd`), upload lại |
| `Không tìm thấy server_public_key.pem` | USB thiếu file | Copy từ gói ZIP gốc, đặt cùng thư mục với `install-offline.ps1` |
| Upload OK nhưng máy không xuất hiện | Token sai org / máy đã tồn tại với org khác | Kiểm tra `visible_org_ids` của admin; xem `audit log` |
| MSI không qua Windows SmartScreen | Chưa ký EV cert / cert hết hạn | Ký lại bằng EV Code Signing cert |

### 6.6. Không được

- Không commit private key của máy cách ly lên bất kỳ repo nào (kể cả portal backup).
  Private key ECDSA chỉ tồn tại trong Windows Certificate Store của máy cách ly, dùng
  để ký inventory; server lưu **public key** để verify.
- Không share token enroll qua email/kênh không mã hoá — token tương đương quyền gán
  máy mới vào tổ chức.
- Không tự ý dùng `--enroll-offline` (CLI flag này **chưa được implement** trong agent
  — chỉ hỗ trợ `--export-bundle`). Flow offline hoàn chỉnh đã được tự động hoá qua
  `install-offline.cmd` + upload ZIP, không cần thao tác CSR thủ công.## 7. BẢO TRÌ ĐỊNH KỲ

- Hàng tuần: xem dashboard, kiểm tra cảnh báo cert, tỉ lệ heartbeat thành công.
- Mỗi release: build agent mới → ký OV cert + timestamp → WDSI → cập nhật hash whitelist AV → release theo đợt.
- Mỗi quý: test restore backup 1 lần, review audit log hash chain, cập nhật runbook.

## 8. KHÔNG ĐƯỢC LÀM

- Không upload agent lên VirusTotal (phát tán mẫu → ML vendor học theo).
- Không thay đổi agent thành công cụ giám sát (screenshot/keylog/remote shell) — mục 6.6 tài liệu gốc.
- Không tắt mTLS/verify để "cho nhanh".
