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

## 8. DEEPAGENT QUEUE VÀ PROGRESS

### 8.1. Dung lượng đồng thời

| Biến môi trường | Phạm vi | Mặc định | Mô tả |
|---|---|---|---|
| `DEEPAGENT_MAX_CONCURRENT_JOBS` | 1–3 | 2 | Số investigation chạy đồng thời |

Investigation vượt dung lượng được xếp FIFO (`created_at ASC`) và giữ trạng thái `queued` cho đến khi có slot trống.

### 8.2. Thay đổi dung lượng

```bash
# Chỉnh sửa trong .env hoặc docker-compose.yml
DEEPAGENT_MAX_CONCURRENT_JOBS=3

# Rebuild và recreate DeepAgent service
docker compose -p asset-inventory -f server/deploy/docker-compose.yml up -d --build deepagent
```

### 8.3. Giới hạn vận hành DeepAgent

| Giới hạn | Giá trị | Mô tả |
|---|---|---|
| Bước triage tối đa | 6 | Plan ban đầu |
| Bước detail tối đa | 2 | Expansion sau triage |
| Metadata event log | 100 dòng | Kết quả triage đầu tiên |
| Dòng detail/event log | 50 dòng | Mỗi trang expansion |
| Thời gian cửa sổ detail | 60 phút | Giới hạn expansion |
| Ngân sách bằng chứng | 120.000 ký tự | Tổng evidence JSON |
| Timeout tool | 180 giây | MCP bridge deadline |

### 8.4. Progress callback an toàn

DeepAgent gửi callback progress với các trường an toàn:

- `phase`: `running` → `collecting` → `finalizing` → hoàn thành
- `progress_percent`: 0–100
- `current_step` / `total_steps`: số bước (không có event ID thực)
- `message`: mô tả tiến trình (không raw logs/filters/prompts)

**Portal hiển thị**:
- Trạng thái `queued`: "Đang chờ trong hàng đợi FIFO"
- Trạng thái `running`: "Đang khởi động"
- Trạng thái `collecting`: "Thu thập"
- Trạng thái `finalizing`: "Phân tích"

### 8.5. Kiểm tra operational logs an toàn

Logs vận hành của DeepAgent được ghi có kiểm soát:

```bash
# Xem logs DeepAgent container
docker compose -p asset-inventory -f server/deploy/docker-compose.yml logs deepagent

# Xem logs với filter theo job
docker compose -p asset-inventory -f server/deploy/docker-compose.yml logs deepagent --since 1h | grep "job_id="
```

**Lưu ý**: Logs không chứa:
- Raw event IDs, filter criteria, hoặc event log content
- API keys, secrets, hoặc credentials
- LLM prompts hoặc model responses
- Sensitive investigation data (suspicious_activity, etc.)

### 8.6. Timeout interpretation

`DEEPAGENT_MCP_TOOL_TIMEOUT_SECONDS` (mặc định 180 giây) là deadline cho MCP bridge gọi tool. Timeout không đảm bảo flow-level guarantee từ Velociraptor. Đây là caller-side deadline — chỉ chứng minh MCP call không trả về trước deadline.

## 9. TÍCH HỢP VELOCIRAPTOR (DFIR)

### 9.0. Triển khai nhanh bằng Docker (khuyến nghị)

Repo đã có sẵn compose tại `deploy/velociraptor/` — chạy độc lập với Inventory Server:

```bash
cd deploy/velociraptor
mkdir -p data && sudo chown -R 1000:1000 data   # non-root trong container cần quyền ghi
docker compose up -d
docker compose logs -f velociraptor             # chờ "Starting frontend..."
docker compose ps                                # STATUS = healthy
cat data/initial_password.txt                    # password admin lần đầu
bash create-api-key.sh "inventory-portal"        # sinh API key → paste vào /dfir/settings
```

Chi tiết (network, port, backup, troubleshoot): xem `deploy/velociraptor/README.md`.

### 9.1. Kiến trúc

- [Velociraptor](https://github.com/velocidex/velociraptor) chạy độc lập (cùng host hoặc host riêng) với GUI/API ở port 8889 (hoặc tuỳ cấu hình).
- Velociraptor Client (cài thủ công trên từng máy Windows theo cách admin chọn — không qua agent inventory) tự enroll với Velociraptor Server.
- **Inventory Server** gọi Velociraptor REST API mỗi 5 phút để đối chiếu `os_info.hostname` ↔ `machines.hostname` trong DB, lưu mapping `velociraptor_links(machine_id, client_id)`. KHÔNG cần thay đổi agent.
- **Portal** cho admin chạy hunt / collect artifact qua API `POST /api/admin/velociraptor/hunt`. Kết quả lưu trên Velociraptor Server, portal deep-link sang GUI.

### 9.2. Triển khai lần đầu

1. **Triển khai Velociraptor Server** (tham khảo [docs chính thức](https://docs.velociraptor.app/docs/installation/)):
   - Cấu hình GUI + datastore + filename ở 1 thư mục persistent (vd `/var/lib/velociraptor`).
   - **Mở port 8889 (hoặc tuỳ chọn) ra ngoài** để các client enroll + admin truy cập GUI.
   - Nếu chạy sau nginx: forward WebSocket + path `/api/v1/` + WebSocket upgrade header.
2. **Tạo API key**: trong Velociraptor GUI → **Settings → API Keys** → cấp key với scope `Read + Write (admin)` (cần write để tạo hunt/collect).
3. **Cấu hình trên Inventory Server**:
   - Sửa `.env`:
     ```
     VELOCIRAPTOR_ENABLED=true
     VELOCIRAPTOR_DEFAULT_URL=https://veloci.example.gov.vn:8889
     VELOCIRAPTOR_SYNC_INTERVAL_SECONDS=300
     ```
   - `cd server && alembic upgrade head` (thêm migration `i8j9k0l1m2n3_velociraptor`).
   - Restart server.
4. **Cấu hình trên Portal**:
   - Login Super Admin → `/dfir/settings`:
     - Bật **Velociraptor**.
     - Nhập **Server URL** (đúng URL GUI).
     - Paste **API Token** (đã tạo ở bước 2).
     - Rà lại **Allowlist artifact** (mặc định 13 artifact read-only).
     - Bấm **Lưu** → **Test kết nối** → OK thì sync hostname sẽ tự chạy sau 5 phút.
5. **Cài Velociraptor Client trên máy trạm** (theo cách riêng của đơn vị, VD qua GPO):
   - Client cần biết `client.config.yaml` trỏ tới Velociraptor Server URL.
   - Sau khi enroll xong, client sẽ xuất hiện trong `SearchClients` → sau 5 phút sẽ có mapping trong `/dfir`.
6. **Audit**: mỗi lần admin chạy hunt/collect đều ghi vào `audit_log` (action `dfir.hunt.create`) + bảng `dfir_hunts` (status, hunt_id, deep-link).

### 9.3. Vận hành hằng ngày

- **Sync hostname tự động**: mỗi 5 phút. Xem trạng thái ở `/dfir` (panel "Số máy đã link") hoặc `/dfir/settings` (panel "Trạng thái sync").
- **Sync thủ công**: bấm **Sync thủ công** ở `/dfir` (Super Admin). Có confirm dialog cảnh báo Velociraptor rate-limit ở fleet lớn.
- **Allowlist artifact** (chống lạm quyền):
  - Mặc định chỉ cho phép artifact read-only (`Generic.Client.Info`, `Windows.System.Services`, `Windows.EventLogs.*`, `Windows.Registry.*`, …).
  - Nếu cần thêm `Windows.NTFS.MFT` / `Windows.Persistence.Permanent*` (câu lệnh DFIR chuyên sâu, tốn disk), Super Admin chủ động thêm vào allowlist trên portal.
  - Audit log ghi lại thay đổi allowlist (`action="velociraptor.config.update"`).
- **Test kết nối**: `/dfir/settings` → bấm **Test kết nối** — nếu lỗi, kiểm tra:
  1. URL đúng (đã bao gồm scheme `https://`).
  2. Port 8889 (hoặc tuỳ chọn) đã mở từ Inventory Server.
  3. Token còn hiệu lực (Velociraptor GUI → API Keys).
  4. CA cert nếu Velociraptor dùng self-signed: `verify_ssl=False` trong client wrapper — KHÔNG khuyến nghị cho prod, dùng reverse proxy có TLS hợp lệ.

### 9.4. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `last_sync_error`: "HTTP 401" | Token sai / hết hạn | Tạo token mới ở Velociraptor GUI, cập nhật trên portal |
| `last_sync_error`: "Không kết nối Velociraptor" | Firewall / DNS / port 8889 đóng | Kiểm tra từ server: `curl https://veloci.example.gov.vn:8889/api/v1/SearchClients -H "Authorization: Bearer xxx"` |
| `linked=0, total_clients>0` | Hostname trên Velociraptor khác hostname inventory | Kiểm tra Velociraptor GUI → Host → chọn client → so sánh hostname với portal. Có thể do client install sai config (FQDN vs short name). |
| `linked=N, total_clients=M` với N<<M | Máy Velociraptor chưa enroll vào Inventory (chưa cài agent) — bình thường | Không phải lỗi; chỉ là những client Velociraptor không có trong inventory DB |
| Lỗi `RuntimeError` khi sync | DB engine loop issue (chỉ test) | Báo dev; production code đã chạy ổn |
| Hunt thất bại với 403 | Artifact không trong allowlist | Super Admin vào `/dfir/settings` → thêm artifact vào allowlist |

### 9.5. Bảo mật

- **API Token**: mã hoá AES-256-GCM phía DB; chỉ hiển thị `api_token_set=True/False` ra portal; KHÔNG log giá trị thật.
- **Audit log**: `velociraptor.config.update` (thay đổi URL/token/allowlist) + `dfir.hunt.create` (chạy hunt) — cùng hash chain với các action khác.
- **RBAC**: chỉ Super Admin (hoặc `admin_global` legacy) được cấu hình Velociraptor + chạy hunt; org_admin/viewer chỉ xem được danh sách link + xem kết quả.
- **Allowlist**: chống lạm quyền — nếu Velociraptor token bị lộ, attacker vẫn chỉ chạy được artifact trong allowlist (read-only, không xoá dữ liệu).
- **Không cache payload**: kết quả hunt KHÔNG cache trên Inventory Server — Velociraptor là nguồn gốc. Nếu cần lưu trữ lâu dài → backup Velociraptor datastore (`/var/lib/velociraptor`).

### 9.6. KHÔNG ĐƯỢC LÀM (Velociraptor)

- KHÔNG dùng Velociraptor làm kênh C2 / exfiltration — chỉ dùng cho DFIR khi có sự cố.
- KHÔNG bật allowlist artifact có side-effect xoá dữ liệu (vd `Windows.Kape.Targets` nếu không hiểu rõ) mà chưa review.
- KHÔNG share API token qua kênh không mã hoá (email, chat). Lưu trong Vault/KMS.
- KHÔNG tự ý tắt sync khi "không thấy lỗi" — last_sync_at cũ có thể che giấu sự cố Velociraptor server đã down.

## 11. KHÔNG ĐƯỢC LÀM

- Không upload agent lên VirusTotal (phát tán mẫu → ML vendor học theo).
- Không thay đổi agent thành công cụ giám sát (screenshot/keylog/remote shell) — mục 6.6 tài liệu gốc.
- Không tắt mTLS/verify để "cho nhanh".

## 12. Cài đặt và vận hành agent Linux

### Quick-start (khuyến nghị)

```bash
# 1. Cài package
sudo dpkg -i dist/orginventory-agent_1.1.0_amd64.deb
# hoặc: sudo dnf install dist/orginventory-agent-1.1.0-1.x86_64.rpm

# 2. Chạy postinstall để verify + enable + start service
sudo ORGINV_TOKEN="t_Ab3xK9mQ2vR8nL4p" \
     ORGINV_HOST="https://agent.example.gov.vn" \
     bash installer/linux/postinstall-enable.sh
```

Script `postinstall-enable.sh` thực hiện 3 bước:
1. Ghi `/etc/orginventory/config.json` (mode 0640, group `orginventory`) với token + endpoint.
2. `systemctl enable --now orginventory-agent.service` + reload daemon.
3. In trạng thái + hướng dẫn tiếp theo.

Nếu KHÔNG truyền `ORGINV_TOKEN` / `ORGINV_HOST`, script ghi config mẫu với token rỗng — admin sửa file sau rồi `sudo systemctl restart orginventory-agent`.

### Cài đặt từ package (.deb / .rpm)

```bash
# Debian/Ubuntu
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./orginventory-agent_1.1.0_amd64.deb

# RHEL/Rocky/Alma
sudo dnf install -y ./orginventory-agent-1.1.0-1.x86_64.rpm
```

Package tự động:
- Tạo system user + group `orginventory` (UID/GID từ sysusers.d range 100-999).
- Tạo directories: `/var/lib/orginventory`, `/var/log/orginventory`, `/etc/orginventory`, `/run/orginventory` (mode 0750).
- Copy binary `/opt/orginventory/OrgInventoryAgent` vào `/opt/orginventory/`.
- Cài systemd unit: `orginventory-agent.service`.
- Không start agent service tự động — cần enroll trước.

### One-liner online install (online server)

```bash
curl -fsSL https://agent.example.gov.vn/i/t_Ab3xK9mQ2vR8nL4p | sudo bash
```

Server trả về shell script tự động: phát hiện distro → tải `.deb`/`.rpm` từ `/download/linux/{token}/` → verify SHA256 → cài package → ghi config + enroll token → `systemctl enable --now orginventory-agent.service`.

### One-liner offline (USB bundle cho máy cách ly)

```bash
# Sau khi copy gói offline vào USB
sudo bash installer/linux/install-offline.sh /media/usb
```

Script tự detect package trên USB → verify SHA256 (nếu có `.sha256` kèm theo) → cài package.

### Enroll thủ công (không qua postinstall script)

```bash
sudo /opt/orginventory/OrgInventoryAgent \
  --data-dir /var/lib/orginventory \
  --config /etc/orginventory/config.json \
  --endpoint https://agent.example.gov.vn \
  --enroll-token t_xxx
sudo systemctl enable --now orginventory-agent.service
```

### Kiểm tra agent

```bash
# Trạng thái
systemctl status orginventory-agent
journalctl -u orginventory-agent -f
```

### Pilot checklist

- [ ] 5+ máy Linux cài thành công qua .deb + .rpm
- [ ] `postinstall-enable.sh` chạy thành công, tất cả 5 bước PASS
- [ ] Service `orginventory-agent` chạy bằng user `orginventory` (không root)
- [ ] Helper socket tồn tại, group `orginventory` đọc được
- [ ] Helper self-test trả `ok:true` với dữ liệu thật
- [ ] Inventory gửi về server (kiểm tra `/var/log/orginventory/agent.log`)
- [ ] Portal hiển thị `platform=linux`, badge Linux, SecuritySection thích ứng (Update/SSH/LUKS)
- [ ] Bundle offline Linux → import → server (qua `/api/offline/import`)

### Build package từ source

```bash
cd agent
# Publish self-contained binaries cho cả x64 + arm64
bash installer/linux/build-linux.sh

# Đóng gói .deb (Ubuntu/Debian — cần dpkg-deb)
bash installer/linux/build-deb.sh linux-x64
ls dist/*.deb

# Đóng gói .rpm (RHEL/Rocky — cần rpmbuild, chạy trên RHEL)
bash installer/linux/build-rpm.sh linux-x64
ls dist/rpm/RPMS/x86_64/*.rpm
```

### Troubleshooting

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Service start fail` | Sai token / endpoint trong config.json | Sửa `/etc/orginventory/config.json`, `systemctl restart orginventory-agent` |
| Agent log spam "enroll retry" | Token hết hạn hoặc sai | Sinh token mới từ Portal, cập nhật config, restart |


## 13. VẬN HÀNH ALERT (Telegram)

### 11.1 Cấu hình bot Telegram (Super Admin)

1. Vào `/admin/telegram-bot` (đã move từ `/me/telegram`).
2. Tạo bot qua @BotFather → lấy token.
3. Nhập token + username + webhook secret → **Test kết nối** (gọi `getMe`).
4. Set webhook: chạy snippet `curl` hiển thị trong trang (bắt buộc server có HTTPS public reachable từ Telegram).

### 11.2 User link Telegram

- User vào **Tài khoản → tab Telegram** → bấm link → mở bot → gửi `/start <token>`.
- `telegram_chat_id` lưu ở `users` — Super Admin xem danh sách tại `/admin/telegram-bot` → "Linked users".

### 11.3 Tạo rule alert

1. `/notifications-alerts` → tab **Subscriptions**.
2. Chọn template (Máy mới / Mất liên lạc / Máy offline / Điều tra...) + phạm vi (`org_only` / `org_tree` / `system`).
3. Bấm **Test** để dry-run: xem nội dung render + danh sách người nhận (ai đã link Telegram) — KHÔNG gửi thật.
4. Bật rule. Job scan chạy mỗi phút (machine_new/lost) hoặc real-time (offline).

### 11.4 Org Admin tắt nhận

- Vào `/me/notification-prefs` — UI render theo `opt_out_controls` của từng template:
  - Template có `template` → checkbox "Tắt nhận template này".
  - Template có `severity` → dropdown "Chỉ nhận từ mức X".
- Super Admin không thể tắt — luôn nhận mọi alert.

### 11.5 Debug khi không nhận được alert

1. `/notifications-alerts` → tab **Lịch sử**: kiểm tra event đã tạo chưa (có `recipient_user_ids`).
2. Nếu event có nhưng không nhận Telegram: kiểm tra user có `telegram_chat_id` (trang linked-users) + bot `enabled` tại `/admin/telegram-bot`.
3. Nếu event không tạo: kiểm tra rule enabled + máy trong phạm vi + template enabled.
4. Telegram delivery best-effort — nếu bot lỗi tạm thời, alert vẫn hiển thị qua cổng in-app bell trên portal.

### 11.6 Lưu ý migration

Migration `t8u9v0w1x2y3` **drop bảng alert_rules/alert_events cũ** (clean replace) — cần recreate rule sau upgrade. Không migrate data cũ.
