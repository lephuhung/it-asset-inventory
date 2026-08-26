# PLAN THỰC HIỆN — HỆ THỐNG QUẢN LÝ TÀI SẢN MÁY TÍNH (IT ASSET INVENTORY)

> Căn cứ: `KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md` v1.0
> **v1.1 — điều chỉnh:** (1) bỏ EV Code Signing cert (chi phí cao) → dùng OV cert + chiến lược whitelist AV tập trung; (2) Server dùng **FastAPI (Python)** thay vì ASP.NET Core.
> **v1.2 — bổ sung:** (3) phương án đổi IP/domain server từ xa — endpoint dự phòng tĩnh (Phase 1) + signed config push (Phase 3); (4) chu kỳ heartbeat mặc định rút từ 45–75s xuống **~30s (jitter ±25%)** để cập nhật online/offline nhanh hơn.
> **v1.3 — làm rõ:** định dạng dữ liệu agent gửi server — **JSON UTF-8** + envelope chung (`schema_version`, `request_id` idempotency); mã hóa bằng TLS/mTLS ở tầng truyền tải, **không mã hóa chồng tầng ứng dụng**; file offline USB ký CMS/PKCS#7 (đặc tả: mục 3.6 tài liệu gốc).
> Giả định team: 1 Backend Python (BE), 1 Frontend (FE), 1 Windows dev C# (WIN, có thể kiêm), 1 Tester bán thời gian (QA)
> Tổng thời gian dự kiến: **24–32 tuần** (Phase 1: 8–10 tuần, Phase 2: 6–8, Phase 3: 6–8, Phase 4: 4–6)

---

## 0. NGUYÊN TẮC ĐIỀU HÀNH DỰ ÁN

1. **MVP trước, không ôm tính năng** — Phase 1 chỉ làm đúng core: enroll → heartbeat → inventory → dashboard on/off. Hệ thống thắng bằng độ tin cậy số liệu.
2. **Chống AV false positive là critical path** — không có EV cert nên phải bù bằng: OV cert ký nhất quán (tích lũy reputation), submit WDSI sớm, và **whitelist hash/cert trong AV tập trung của cơ quan** (đây mới là cơ chế chính khi triển khai nội bộ).
3. **Demo mỗi 2 tuần** (cuối mỗi sprint) — kể cả khi chỉ demo được "agent gửi heartbeat vào DB".
4. **Mọi thứ có checklist nghiệm thu** (Definition of Done — mục 9).
5. **Agent read-only, zero-GUI** — mọi thiết kế đi chệch nguyên tắc này phải qua review kiến trúc.

---

## 1. KIẾN TRÚC CÔNG NGHỆ (đã chốt)

### 1.1. Bảng công nghệ

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| **Agent** | C# / .NET 8 Windows Service, self-contained single-file | Không đổi — lý do giữ C#: ít bị AV gắn cờ nhất, WMI/Registry native, làm Windows Service chuẩn |
| **Installer** | MSI (WiX Toolset) + install.ps1 ký Authenticode | Cài silent qua one-liner |
| **API Server** | **FastAPI (Python 3.12+)**, uvicorn/gunicorn | Async, tự sinh OpenAPI docs, đủ cho REST + WebSocket |
| **Reverse proxy / TLS termination** | **nginx** | ⚠️ Quan trọng: mTLS verify client cert ở nginx (`ssl_verify_client optional`), truyền thông tin cert vào FastAPI qua header (`X-SSL-Client-CN`, `X-SSL-Client-Serial`, `X-SSL-Client-Verify`) — FastAPI/uvicorn không nên tự terminate mTLS |
| **ORM / Migration** | SQLAlchemy 2.0 (async) + Alembic | |
| **Validation** | Pydantic v2 | Validate schema đầu vào mọi endpoint |
| **Database** | PostgreSQL 16 | Bảng `heartbeats` partition theo ngày |
| **Cache/Queue** | Redis 7 | Online status (TTL), pub/sub cho WebSocket, rate-limit counter |
| **CA nội bộ (mTLS)** | step-ca (Smallstep) | Root offline + issuing CA; cấp/renew/revoke qua API; CRL phục vụ nginx (`ssl_crl`) |
| **Portal Web** | React + Vite + WebSocket client | |
| **AuthN/Z portal** | JWT (pyjwt) + RBAC theo cây tổ chức; 2FA TOTP (pyotp) | OIDC tích hợp AD ở Phase 4 (thư viện `authlib`) |
| **Mã hóa dữ liệu nhạy cảm** | AES-256-GCM — thư viện `cryptography` | Khóa trong Vault/KMS |
| **Báo cáo** | openpyxl (Excel); WeasyPrint (PDF, Phase 4) | |
| **Background jobs** | ARQ (async task queue, chạy trên Redis) | Anchor ký audit log định kỳ, gửi email/Zalo, báo cáo định kỳ |
| **Email/Alert** | SMTP (aiosmtplib); Zalo OA API / Telegram Bot API | |
| **Secrets** | HashiCorp Vault (hoặc KMS sẵn có của đơn vị) | Khóa AES, DB credentials, khóa CA, khóa ký config agent |
| **Ký số** | **OV Code Signing certificate** (thay EV) + timestamp | Chi tiết mục 2 |

### 1.2. Sơ đồ triển khai server

```
Internet                    DMZ                         Vùng nội bộ
─────────                   ────                        ────────────
Agent ──443──► nginx ──► FastAPI (uvicorn) ──► PostgreSQL
(mTLS cert)    │ verify      │                          Redis
               │ client cert │── ARQ workers             Vault/KMS
Portal ──443─► │ (TLS thường)│── WebSocket /api/ws
(JWT)          │             step-ca (issuing CA + CRL)
```

- nginx làm **2 server block**: block agent (bắt buộc mTLS + kiểm CRL) và block portal (TLS thường + JWT ở tầng app).
- CRL từ step-ca được cron refresh vào nginx, reload không downtime.

### 1.3. Điểm cần lưu ý khi đổi sang FastAPI

| Vấn đề | Cách xử lý |
|---|---|
| mTLS không phải sở trường của uvicorn | Verify ở nginx, app chỉ đọc header — **bắt buộc** khóa IP nội bộ (app chỉ nhận traffic từ nginx) để tránh giả header |
| Cấp client cert lúc enroll | FastAPI gọi **step-ca API** (`/1.0/sign`) với CSR agent gửi lên → trả cert. Không tự ký bằng `cryptography` trừ khi step-ca không đáp ứng |
| Fuzzy-match fingerprint | PL/Python: dùng pg_trgm (Postgres) hoặc tính điểm trọng số trong code — giữ logic ở service layer |
| Hash chain audit_log | Trigger DB hoặc service layer — chọn **service layer** để dễ test; quyền DB vẫn revoke UPDATE/DELETE |
| Throughput heartbeat | FastAPI async + Redis pipeline + batch insert heartbeats → mục tiêu 1.000+ máy không vấn đề |

---

## 2. PHƯƠNG ÁN KÝ SỐ KHÔNG EV CERT

**Bối cảnh:** EV cert đắt (~triệu đến vài chục triệu VND/năm kèm token phần cứng). Hệ thống triển khai **nội bộ các cơ quan** — không phải phần mềm phát hành công khai — nên cơ chế chống AV chính là **whitelist tập trung**, không phải SmartScreen reputation.

### 2.1. Phương án thay thế (theo thứ tự ưu tiên)

| # | Phương án | Chi phí | Hiệu quả |
|---|---|---|---|
| 1 | **OV Code Signing cert** (Sectigo/DigiCert OV, ~3–8 triệu VND/năm) | Thấp | Ký Authenticode đầy đủ, timestamp. SmartScreen không cho qua ngay nhưng **tích lũy reputation theo cert** — ký nhất quán 1 cert, không đổi cert mỗi năm |
| 2 | **Whitelist hash/cert trong AV tập trung của cơ quan** (BKAV Pro Endpoint, Kaspersky Security Center, Windows Defender qua GPO/Intune) | Miễn phí | ⚠️ **Đây là cơ chế chính.** Triển khai nội bộ = đội an ninh cơ quan kiểm soát AV → đẩy hash/publisher cert vào whitelist trước khi cài |
| 3 | **Submit Microsoft WDSI** trước mỗi release | Miễn phí | Defender không gắn cờ → giảm 80% rủi ro (Defender là AV phổ biến nhất) |
| 4 | Phát hành qua kênh nội bộ (file server/GPO/SCCM nếu cơ quan có) | Miễn phí | Bỏ qua SmartScreen hoàn toàn khi triển khai bằng GPO — SmartScreen chỉ chặn file tải từ internet |
| 5 | Nếu cơ quan có **PKI/CA nội bộ được tin cậy**: ký bằng CA nội bộ và push root vào Trusted Publishers qua GPO | Miễn phí | Mạnh trong môi trường domain |

### 2.2. Checklist bắt buộc (không đổi so với tài liệu gốc, chỉ bỏ EV)

- [ ] Mua **OV code signing cert**, ký cả 3: `agent.exe`, `agent.msi`, `install.ps1` + **timestamp**
- [ ] Metadata đầy đủ: CompanyName (tên thật), FileDescription, ProductName, Version, Copyright, Icon
- [ ] **KHÔNG upload agent lên VirusTotal**; submit WDSI trước mỗi release
- [ ] Release theo đợt (mỗi hash mới = reset reputation)
- [ ] Kiến trúc "hiền": MSI chuẩn, heartbeat jitter, HTTPS/443, User-Agent rõ ràng, chỉ đọc WMI/Registry
- [ ] Quy trình vận hành: **trước khi triển khai tại cơ quan mới, bàn giao hash + publisher cert cho đội an ninh mạng whitelist** — đưa bước này vào runbook triển khai

### 2.3. Rủi ro còn lại & chấp nhận

- SmartScreen có thể cảnh báo vàng ("Windows protected your PC") trong 1–2 tháng đầu với máy cài từ internet → giảm thiểu: hướng dẫn kèm ảnh chụp bước "More info → Run anyway", ưu tiên kênh GPO/file server nội bộ, cài theo đợt lớn tập trung sau khi whitelist.
- **Không chấp nhận**: dùng cert self-signed không kiểm soát, hoặc bỏ ký hoàn toàn — install.ps1 vẫn bắt buộc verify chữ ký MSI trước khi cài.

---

## 3. TUẦN 0 — CHUẨN BỊ (chạy song song, trước khi code)

| # | Việc | Người | Lead time | Ghi chú |
|---|---|---|---|---|
| 0.1 | **Đặt mua OV Code Signing certificate** | PM/Admin | 3–7 ngày | Rẻ và nhanh hơn EV nhiều; chuẩn bị hồ sơ pháp lý tổ chức |
| 0.2 | Đăng ký tên miền + TLS cert cho server (ACME/certbot) | BE | 1–2 ngày | VD: `inventory.server.gov.vn` |
| 0.3 | Dựng môi trường: repo mono (`agent/` C#, `server/` FastAPI, `portal/` React), CI (GitHub Actions/GitLab CI), docker-compose dev | BE | 3 ngày | CI server: pytest + ruff/mypy; CI agent: build + ký (khi có cert) |
| 0.4 | Dựng step-ca: root offline + issuing CA + CRL endpoint | BE | 2–3 ngày | Test cấp/revoke/renew từ tuần 0 |
| 0.5 | Dựng nginx config mẫu: 2 server block (agent mTLS / portal TLS), đọc CRL | BE | 2 ngày | Đây là mảng dễ sai nhất của stack FastAPI — làm sớm |
| 0.6 | Thiết kế DB schema v1 + Alembic migration đầu tiên | BE | 2 ngày | Theo mục 5.1 tài liệu gốc |
| 0.7 | Tài khoản submit Microsoft WDSI + liên hệ sẵn đội an ninh cơ quan pilot | PM | 1 ngày | Chuẩn bị whitelist AV tập trung |

**Output tuần 0:** repo + CI chạy được; step-ca cấp/revoke được cert thử; nginx verify mTLS + forward header vào FastAPI "hello world"; schema v1; OV cert đã đặt hàng.

---

## 4. PHASE 1 — MVP (Tuần 1 → 8/10)

> Mục tiêu: cài 1 dòng lệnh → máy enroll → heartbeat realtime → dashboard thấy online/offline. Demo nội bộ cuối phase với 5–10 máy thật.

### Sprint 1 (Tuần 1–2): Nền móng Agent + API skeleton

**WIN (Agent C#):**
- [ ] Project .NET 8 Windows Service (`BackgroundService`), build self-contained single-file
- [ ] Thu thập fingerprint đa nguồn: SMBIOS UUID + MachineGuid + serial mainboard → hash có trọng số
- [ ] Thu thập inventory cơ bản: OS/CPU/RAM/disk/hostname/IP/MAC/logged user
- [ ] Cấu hình agent từ file local (ProgramData), logging file xoay vòng
- [ ] Sinh keypair ECDSA P-256 + CSR, gửi kèm khi enroll (private key không rời máy)
- [ ] Serialize payload **JSON UTF-8** theo envelope chung (`schema_version`, `request_id`, `ts` UTC); gzip khi payload > 8KB

**BE (FastAPI):**
- [ ] Project skeleton: FastAPI + SQLAlchemy async + Alembic + Pydantic settings; docker-compose (Postgres + Redis + step-ca + nginx)
- [ ] `POST /api/enroll`: nhận token + fingerprint + CSR → fuzzy-match (pg_trgm) → step-ca ký CSR → trả `machine_id` + client cert
- [ ] `POST /api/heartbeat` + `POST /api/inventory`: đọc identity từ header nginx forward (`X-SSL-Client-*`), từ chối nếu `VERIFY != SUCCESS`
- [ ] Online status vào Redis với TTL = 2× chu kỳ heartbeat
- [ ] `audit_log` append-only + hash chain (service layer) — ghi sự kiện enroll
- [ ] Auth portal: JWT login/logout, RBAC seed (admin toàn cục / admin cơ quan / người xem)
- [ ] Pydantic schema cho 3 payload (enroll/heartbeat/inventory) theo envelope chung; xử lý idempotent theo `request_id` (retry/gửi bù không tạo bản ghi trùng)

**FE (React):**
- [ ] Khung React + Vite + layout + trang login JWT
- [ ] Trang danh sách máy (đọc API, chưa realtime)

**QA:** test plan tổng thể; test fingerprint trên 5–10 máy/VM (kể cả ghost lại Win → fuzzy-match).

**Demo S1:** agent cài tay → enroll thành công → record trong DB; nginx từ chối request không có client cert.

### Sprint 2 (Tuần 3–4): Heartbeat + Token + Offline cache

**WIN:**
- [ ] Vòng lặp heartbeat chu kỳ cơ sở 30s, jitter ±25% (thực tế ~22–38s), chu kỳ đọc từ config local, User-Agent `OrgInventoryAgent/x.y`
- [ ] Config local (ProgramData) hỗ trợ danh sách endpoint dự phòng: primary lỗi N lần liên tiếp (mặc định 5) → tự chuyển backup, định kỳ thử lại primary
- [ ] Inventory đầy đủ lần đầu sau enroll; gửi lại khi hash cấu hình đổi
- [ ] Offline cache SQLite local + gửi bù khi có mạng (kèm timestamp gốc)
- [ ] Idempotency: chạy lại cài đặt → nhận cert cũ, không tạo máy trùng

**BE:**
- [ ] `POST /api/tokens`: 1 token = 1 máy, TTL 72h, chỉ lưu hash (SHA-256), entropy ≥128 bit base62
- [ ] Thông tin user kèm token; số điện thoại mã hóa **AES-256-GCM** (`cryptography`), khóa lấy từ Vault (dev dùng env, staging/prod bắt buộc Vault)
- [ ] Trạng thái máy `online/offline` từ Redis TTL
- [ ] `GET /i/{token}` render động `install.ps1` nhúng token (Jinja2 template)
- [ ] Rate-limit (slowapi hoặc middleware Redis) trên enroll/login/tokens

**FE:**
- [ ] Màn "Thêm máy mới" (chế độ A) → sinh token + hiển thị one-liner copy
- [ ] Bảng phễu triển khai: trạng thái token (đã gửi/đã dùng/hết hạn)

**Demo S2:** sinh token trên portal → paste one-liner (install.ps1 thô, chưa MSI) → máy online trên dashboard.

### Sprint 3 (Tuần 5–6): Đóng gói + ký số + Realtime + 2FA

**WIN:**
- [ ] Đóng gói MSI bằng WiX Toolset (service đăng ký qua SCM chuẩn)
- [ ] Hoàn thiện `install.ps1`: kiểm tra Admin → tải MSI → **verify SHA256 + chữ ký Authenticode** → `msiexec /qn` → in "✔ Cài đặt thành công"
- [ ] Metadata đầy đủ (CompanyName thật, FileDescription, ProductName, Version, Icon)
- [ ] Tự renew client cert khi còn ~70% vòng đời (đọc `renew_after` server trả về)

**BE:**
- [ ] WebSocket `GET /api/ws`: push online/offline realtime qua Redis pub/sub
- [ ] `GET /api/stats/overview`: tổng máy, online, offline, token chờ
- [ ] CRL: step-ca phục vụ CRL → cron refresh vào nginx → agent bị thu hồi bị chặn ở tầng TLS
- [ ] 2FA TOTP (pyotp): QR enroll (otpauth URI), verify ±1 bước, backup codes 1 lần, seed mã hóa AES-256-GCM
- [ ] Thông báo tuân thủ: bảng `compliance_notices` + `user_acknowledgments`, API lấy bản hiện hành + xác nhận

**FE:**
- [ ] Dashboard realtime: số máy on/off tự cập nhật qua WebSocket
- [ ] Màn bật 2FA (quét QR, nhập mã, hiển thị backup codes)
- [ ] Xác nhận thông báo tuân thủ (bản 1) khi đăng nhập đầu

**QA:**
- [ ] Test one-liner end-to-end Windows 10/11 sạch
- [ ] Test revoke cert → agent bị từ chối ở nginx; test renew tự động
- [ ] Test hash chain: sửa tay 1 dòng audit_log → phải phát hiện đứt chuỗi
- [ ] Test giả header `X-SSL-Client-*` trực tiếp vào FastAPI (bypass nginx) → phải bị chặn

**⚠️ Checkpoint tuần 6:** OV cert phải có. Ký `agent.exe` + MSI + `install.ps1` (có timestamp). **Submit WDSI**. Bàn giao hash/cert cho đội an ninh cơ quan pilot để whitelist.

### Sprint 4 (Tuần 7–8): Báo cáo + Hardening + Pilot nội bộ

**BE:**
- [ ] `POST /api/reports/export`: Excel (openpyxl), mask số ĐT mặc định (`0983•••123`)
- [ ] Hardening: TLS 1.2+ tại nginx, HSTS, security headers, giới hạn payload, backup mã hóa + test restore 1 lần
- [ ] Metric + log tập trung; cảnh báo cert sắp hết hạn / Redis nghẽn / CRL refresh lỗi
- [ ] Load test sơ bộ: 200 máy giả lập heartbeat đồng thời (chu kỳ 30s)

**WIN:**
- [ ] Fix lỗi từ QA; log agent đủ để debug từ xa
- [ ] Self-update khung: tải MSI → verify chữ ký → `msiexec` (có thể dời Phase 2 nếu kịp)

**FE:**
- [ ] Màn xuất báo cáo, lọc theo org/trạng thái
- [ ] Trang audit log read-only cho admin toàn cục

**QA + cả team:**
- [ ] **Pilot nội bộ 5–10 máy thật 1 tuần**: tỉ lệ heartbeat thành công, RAM/CPU agent, false positive AV (Defender + AV của cơ quan nếu có)
- [ ] Test failover endpoint: tắt endpoint primary → agent tự chuyển backup trong ≤ 2 chu kỳ heartbeat
- [ ] Quét lỗ hổng dependency (pip-audit, dotnet list package --vulnerable), sửa finding High

**✅ Tiêu chí đóng Phase 1 (Go/No-Go):**
1. One-liner cài thành công ≥ 95% trên Windows 10/11 sạch
2. Heartbeat ổn định ≥ 7 ngày liên tục, agent RAM < 60MB, CPU < 1% trung bình
3. Dashboard realtime đúng trạng thái on/off (sai lệch < 1 chu kỳ heartbeat)
4. Không máy trùng khi cài lại / ghost Win (fuzzy-match + idempotent)
5. Audit log đủ chuỗi: token → enroll → machine → heartbeat đầu
6. Windows Defender không gắn cờ (đã submit WDSI); quy trình whitelist AV cơ quan đã chạy thử 1 lần
7. Agent tự failover sang endpoint dự phòng khi primary mất kết nối (≤ 2 chu kỳ heartbeat)

---

## 5. PHASE 2 — LÀM GIÀU DỮ LIỆU (Tuần 9 → 14/16)

> Mục tiêu: biến dữ liệu sống thành dữ liệu hữu ích cho quản trị & an ninh.

| Tuần | Workstream | Đầu việc |
|---|---|---|
| 9–10 | WIN | Software inventory (registry Uninstall), trạng thái AV (`root\SecurityCenter2`), Windows Update status, phân biệt máy thật/ảo |
| 9–10 | BE | Timeline bật/tắt (tổng hợp từ `heartbeats` partition theo ngày), phát hiện máy ma (>30/60/90 ngày), Windows EOL report |
| 10–11 | FE | Trang timeline máy, danh sách máy ma, báo cáo EOL, chi tiết máy (specs + software + security posture) |
| 11–12 | BE | Alert rules engine (ARQ jobs): máy mới, mất liên lạc, phần mềm lạ, phần cứng đổi → Email (aiosmtplib) + Zalo OA/Telegram |
| 11–12 | WIN | BitLocker, RDP, tài khoản local, share → "cấu hình rủi ro" |
| 12–13 | BE | Token chế độ B (link tự khai báo) + bulk import CSV + gửi email hàng loạt; rule tự gán tổ chức theo IP/hostname |
| 12–13 | FE | Màn link tự khai báo, upload CSV, cấu hình rule gán tổ chức, cấu hình alert rules |
| 13–14 | BE | Anchor ký audit log định kỳ (ARQ job + khóa trong Vault/HSM) + lưu anchor ngoài DB |
| 13–14 | QA | Test alert end-to-end, load test 1.000 máy giả lập (chu kỳ 30s), import CSV 500 dòng |
| 14 | All | Hoàn thiện hardening checklist, demo + retro |

**✅ Tiêu chí đóng Phase 2:** dashboard trả lời được "bao nhiêu máy bỏ không / máy ma / Win sắp EOL / thiếu patch / chưa cài AV"; alert tới điện thoại admin < 5 phút; chịu tải 1.000 máy.

---

## 6. PHASE 3 — ĐẶC THÙ & NÂNG CAO (Tuần 15 → 20/22)

| Tuần | Đầu việc | Người |
|---|---|---|
| 15–16 | **Chế độ máy cách ly**: agent ghi inventory ra file ký số (CMS/PKCS#7 bằng client cert) → tool CLI export | WIN + BE |
| 15–16 | Portal màn import file offline, verify chữ ký file (`cryptography`) | BE + FE |
| 17 | Phát hiện dual-homed (≥2 interface active khác dải) + cảnh báo | WIN + BE |
| 17–18 | SMART ổ cứng (WMI `MSStorageDriver_*`), cảnh báo ổ sắp hỏng | WIN |
| 17–18 | Fingerprint drift: log + màn admin duyệt khi đổi main/ghost Win | BE + FE |
| 19 | Vòng đời tài sản: Mới cài → Đang dùng → Sửa chữa → Thanh lý | BE + FE |
| 19–20 | Diff cấu hình; pending approval cho máy mới enroll | BE + FE |
| 20 | On-demand rescan: server đẩy yêu cầu (agent poll kèm heartbeat / Redis flag) → agent quét ngay | WIN + BE |
| 20 | **Config ký số từ xa** (signed config push): đổi endpoint IP/domain + chu kỳ heartbeat không cần cài lại; chữ ký ECDSA, public key nhúng sẵn trong agent, rollback khi endpoint mới lỗi | WIN + BE |
| 20 | QA tổng hợp + pilot tại 1 cơ quan thật | QA |

**✅ Tiêu chí đóng Phase 3:** import được máy cách ly; dual-homed/SMART/drift có cảnh báo; vòng đời tài sản đầy đủ; đổi endpoint server từ xa thành công trên máy pilot.

---

## 7. PHASE 4 — TÍCH HỢP & MỞ RỘNG (Tuần 21 → 24/28)

| Tuần | Đầu việc | Người |
|---|---|---|
| 21–22 | AD/LDAP sync (ldap3) + SSO OIDC cho portal (authlib) | BE |
| 21–22 | Dashboard lãnh đạo (read-only, số to, biểu đồ tổng quan) | FE |
| 23 | API mở: API key theo scope, tài liệu OpenAPI (FastAPI tự sinh), rate-limit riêng | BE |
| 23–24 | Báo cáo PDF theo biểu mẫu hành chính (WeasyPrint từ HTML template) | BE + FE |
| 24 | UAT + runbook vận hành (renew cert, restore backup, xử lý AV gắn cờ, whitelist tại cơ quan mới) + bàn giao | All |

---

## 8. MA TRẬN PHÂN CÔNG TỔNG HỢP

| Thành phần | Chính | Hỗ trợ |
|---|---|---|
| Agent C# / MSI / install.ps1 | WIN | QA (test AV) |
| FastAPI + DB + Redis | BE | — |
| nginx mTLS + step-ca/CRL + Vault | BE | PM (hạ tầng cơ quan) |
| Portal React | FE | BE (API contract) |
| Alert / báo cáo Excel-PDF | BE | FE |
| OV cert / WDSI / tên miền / pháp lý / liên hệ an ninh cơ quan | PM | BE |
| Test plan / pilot / load test | QA | All |

---

## 9. DEFINITION OF DONE (áp dụng mọi tính năng)

- [ ] Code review + merge qua PR, CI xanh (server: pytest + ruff + mypy; agent: build + unit test + ký artifact)
- [ ] Có audit log cho mọi thao tác nhạy cảm (token, quyền, export, xác nhận tuân thủ)
- [ ] Dữ liệu cá nhân mới → cập nhật bản thông báo tuân thủ tương ứng
- [ ] Test trên Windows 10 + 11 thật (không chỉ VM)
- [ ] Không detection mới trên Windows Defender; binary mới → cập nhật hash whitelist AV
- [ ] Tài liệu API (OpenAPI) + runbook cập nhật

---

## 10. MILESTONE & LỊCH DEMO

| Mốc | Nội dung demo |
|---|---|
| Cuối tuần 2 | Agent enroll vào DB qua mTLS |
| Cuối tuần 4 | One-liner → máy online trên dashboard |
| Cuối tuần 6 | Dashboard realtime + 2FA + MSI ký OV cert |
| **Cuối tuần 8** | **MVP hoàn chỉnh — pilot nội bộ** |
| Cuối tuần 14 | Dữ liệu giàu + alert Zalo/email — **demo cho cơ quan khách hàng** |
| Cuối tuần 20 | Offline USB + vòng đời tài sản |
| Cuối tuần 24 | SSO + dashboard lãnh đạo — **bàn giao vận hành** |

---

## 11. RỦI RO HÀNG ĐẦU & HÀNH ĐỘNG NGAY

| Rủi ro | Ảnh hưởng | Hành động |
|---|---|---|
| **SmartScreen cảnh báo vàng (không có EV cert)** | Người dùng hoang mang khi cài | Whitelist AV tập trung + kênh GPO/file server nội bộ + ảnh hướng dẫn "Run anyway" + ký nhất quán 1 OV cert lâu dài |
| AV VN (BKAV/Kaspersky) gắn cờ | Trễ triển khai tại cơ quan | Bàn giao hash/cert whitelist **từ Phase 1**; submit WDSI mỗi release |
| nginx/mTLS cấu hình sai → agent mất kết nối hoặc giả header | Mất dữ liệu / lỗ hổng | Làm từ tuần 0, QA test bypass nginx trong Sprint 3, app chỉ bind IP nội bộ |
| Người dùng không chạy one-liner | Dữ liệu thiếu | Phễu triển khai trên dashboard ngay Phase 1 + bulk email Phase 2 |
| Server đổi IP/domain → agent mất liên lạc hàng loạt | Mất dữ liệu hàng loạt | Endpoint dự phòng (Phase 1) + signed config push (Phase 3) + runbook chạy song song server cũ/mới khi chuyển đổi |
| Cert client hết hạn hàng loạt | Máy "lost" oan | Renew tự động từ Sprint 3 + cảnh báo sớm 30 ngày |
| Team 1 WIN dev bị kẹt | Agent là critical path | BE cross-train C# từ Sprint 1; review code agent sớm |
| Scope creep thành công cụ giám sát | Mất niềm tin, pháp lý | Từ chối screenshot/keylog — viện dẫn mục 6.6 tài liệu gốc |

---

## 12. VIỆC CẦN LÀM NGAY (Tuần này)

1. ☐ Đặt mua **OV Code Signing certificate** (3–7 ngày, rẻ hơn EV nhiều)
2. ☐ Đăng ký tên miền server + tài khoản WDSI
3. ☐ Dựng repo mono + CI (FastAPI / C# agent / React) + docker-compose dev
4. ☐ Dựng step-ca + nginx mTLS "hello world" (mảng rủi ro nhất của stack — làm sớm)
5. ☐ Kickoff: thống nhất DoD (mục 9) và danh sách "cố tình không làm"
6. ☐ Liên hệ đội an ninh cơ quan pilot — hỏi trước họ dùng AV gì, quy trình whitelist ra sao

---

*Plan v1.3 — bám sát KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md v1.2, điều chỉnh theo yêu cầu: FastAPI server + không dùng EV cert + đổi endpoint từ xa + heartbeat ~30s + đặc tả payload JSON/mTLS. Điều chỉnh sau mỗi retro 2 tuần.*
