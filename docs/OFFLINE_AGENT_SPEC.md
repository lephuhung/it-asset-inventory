# SPEC — Agent cho chế độ máy cách ly (offline USB)

> Tài liệu dành cho team phát triển **agent (C#/.NET)** — mô tả luồng agent khi máy
> hoàn toàn không có kết nối mạng tới server. Áp dụng từ Sprint 3 (mục 15–16 trong
> PLAN_THUC_HIEN.md).
>
> Ngữ cảnh: máy cách ly (air-gapped) cài agent bình thường nhưng **không bao giờ**
> gọi được server. Mọi trao đổi với server được thực hiện qua **file JSON trên USB**:
> private key của agent **không bao giờ rời máy cách ly**, mọi giao tiếp là CSR/file
> được ký ECDSA bằng private key đó.

---

## 0. Tóm tắt luồng

```
[Máy cách ly]                                                 [Máy admin có mạng]
┌──────────────────────────────────┐                          ┌──────────────────────────┐
│ 1. Cài agent từ MSI (có token)  │                          │ 3. POST /api/offline/    │
│ 2. agent sinh keypair + CSR      │  ─ USB đi ──►  file.json  │    enroll  (CSR + token) │
│    → --enroll-offline (CLI)      │                          │                          │
│ 4. agent nhận lại file cert.pem  │  ◄─ USB về ── file.json  │ 5. POST /api/offline/    │
│    → --install-cert (CLI)        │                          │    import  (signed inv.)  │
│ 6. agent ghi inventory vào cache │                          │                          │
│ 7. agent ký inventory:          │  ─ USB đi ── signed.json │                          │
│    → --export-inventory (CLI)    │                          │                          │
└──────────────────────────────────┘                          └──────────────────────────┘
```

> Bước 1–2 chỉ làm **một lần** lúc triển khai. Bước 6–7 lặp lại mỗi khi cần cập nhật
> inventory (hàng tuần / hàng tháng).

---

## 1. Hai phương pháp cài đặt agent

**Yêu cầu chung cho cả 2 phương pháp:**
- File `OrgInventoryAgent.msi` (đã ký Authenticode) — build trên Windows bằng
  `agent/installer/build-msi.ps1` (xem `agent/README.md` mục Build).
- `ENROLL_TOKEN` do admin cấp qua `POST /api/tokens` (token 1 lần, TTL 72h).
- `ENDPOINTS` URL server agent, ví dụ `https://agent.example.gov.vn`.

Lựa chọn phương pháp tùy thuộc máy **CÓ hay KHÔNG có mạng tới server**:

### Phương pháp A — Cài bằng lệnh (online, một dòng)

> **Dùng cho**: máy có mạng ra server (LAN / VPN). Nhanh nhất, ít thao tác nhất.

**Trên máy cần cài** (Admin PowerShell, máy có mạng):

```powershell
irm http://server/i/<enroll_token> | iex
```

**Cơ chế**:
1. Server render script `install.ps1` qua endpoint `GET /i/{token}` (xem
   `server/app/api/routes/install.py` + `app/templates/install.ps1.j2`).
2. Script tự kiểm tra quyền Admin, hiển thị thông báo tuân thủ, **tải MSI từ
   `GET /download/agent.msi`**, verify **SHA256** + **chữ ký Authenticode**, chạy
   `msiexec /i ... /qn ENROLL_TOKEN=... ENDPOINTS=...`.
3. Agent tự động enroll sau khi service khởi động (~30 giây đầu tiên).

**Yêu cầu**:
- PowerShell 5.1+ (Windows 10/11).
- Quyền Administrator.
- Đường truyền TCP tới cả `server` (cho `GET /i/...`) **và** `server:port` (cho
  `GET /download/agent.msi`) — thường cùng host.

**Ưu / nhược**:
- ✅ Một dòng lệnh, không cần USB, không cần tải file thủ công.
- ✅ Tự verify chữ ký + SHA256, tự rollback nếu lỗi.
- ❌ Cần mạng tới server lúc cài. Không dùng được cho máy cách ly.

---

### Phương pháp B — Cài bằng tải file (offline, copy qua USB)

> **Dùng cho**: máy cách ly (air-gapped) — không có mạng ra server.

**Trên máy admin có mạng**:

1. Cấp enroll token qua portal.
2. Tải về 3 file vào cùng thư mục trên USB:
   - `OrgInventoryAgent.msi` (do team agent build sẵn, ký Authenticode)
   - `OrgInventoryAgent.msi.sha256` (cùng SHA256 build script sinh)
   - `install-offline.ps1` (wrapper, do server phát hành tại
     `GET /download/install-offline.ps1`)
3. Ghi lại token + URL endpoint ra giấy / file `.txt` trên USB (KHÔNG truyền token
   qua email/kênh không mã hóa).

**Trên máy cách ly** (Admin PowerShell, KHÔNG cần mạng):

```powershell
E:\install-offline.ps1 -Token "<enroll_token>" -Endpoints "https://agent.example.gov.vn"
```

Trong đó `E:` là ký tự USB (thay nếu khác).

**Cơ chế**:
1. `install-offline.ps1` đọc 3 file trên USB, verify **SHA256** + **chữ ký
   Authenticode** của MSI (tương tự `install.ps1` nhưng bỏ bước tải).
2. Chạy `msiexec /i OrgInventoryAgent.msi /qn ENROLL_TOKEN=<token> ENDPOINTS=<url>`.
3. Agent cài xong, service chạy nền — nhưng **không enroll được** vì không có mạng.
4. Hoàn tất enroll bằng 3 subcommand mới (xem mục 2 phía dưới).

**Yêu cầu**:
- PowerShell 5.1+ (Windows 10/11).
- Quyền Administrator trên máy cách ly.
- USB chứa 3 file + token + URL.

**Ưu / nhược**:
- ✅ Hoạt động trên máy hoàn toàn không có mạng ra server.
- ✅ Mọi file đều verify SHA256 + Authenticode trước khi cài.
- ✅ Hỗ trợ cả CLI param (`-Token`, `-Endpoints`) lẫn nhập tương tác.
- ❌ Cần thao tác copy file qua USB; cần admin cấp token qua kênh riêng.

---

### So sánh nhanh

| | Phương pháp A (lệnh) | Phương pháp B (tải file) |
|---|---|---|
| Mạng ra server lúc cài | **Bắt buộc** | **Không cần** |
| Thao tác trên máy đích | 1 dòng PowerShell | Cắm USB + 1 lệnh PowerShell |
| File cần chuẩn bị trước | Không (server tự phục vụ) | MSI + SHA256 + script wrapper |
| Token enroll | Nhúng sẵn trong URL `/i/<token>` | Admin copy riêng vào USB |
| Verify SHA256 / Authenticode | ✅ Tự động | ✅ Tự động |
| Enrollment sau cài | Tự động (~30s) | **Thủ công** qua `--enroll-offline` |
| Phù hợp với | Máy LAN / VPN nội bộ | **Máy cách ly (air-gapped)** |

---

## 2. CLI commands — đặc tả

Agent thêm 3 subcommand mới (tham khảo `OrgInventoryAgent/Program.cs::PrintHelp` hiện tại).

### 2.1. `--enroll-offline <out.json>`

Sinh cặp keypair ECDSA P-256 + CSR ngay trên máy cách ly, ghi file JSON chờ admin
copy sang máy có mạng để gọi API.

**Input** (đọc từ config hiện tại của agent trong `%ProgramData%\OrgInventory\config.json`):

- `enroll_token`: token do admin cấp (cũng đã được MSI truyền qua `ENROLL_TOKEN=` lúc cài).
- `hostname`: hostname Windows hiện tại (`Environment.MachineName`).
- `fingerprint`: thu thập giống logic trong `FingerprintCollector` (smbios_uuid /
  machine_guid / mainboard_serial — hash SHA-256 hex trước khi ghi nếu có quy ước
  riêng).

**Hành vi**:

1. Sinh `ec.SECP256R1()` private key + CSR với CN=`machine-pending` (server sẽ override
   CN thành `machine-<id>` lúc ký — xem `app/services/ca.py::LocalCaService.sign_csr`).
2. Lưu private key vào **Windows Certificate Store** (`StoreName.My`, `StoreLocation.CurrentUser`)
   với label/timestamp để bước 1.3 dùng lại.
3. Ghi file JSON ở `<out>` (đường dẫn trên USB):

```json
{
  "schema_version": 1,
  "created_at": "2026-08-26T14:00:00Z",
  "token": "t_Ab3xK9mQ2vR8nL4p...",
  "hostname": "PC-ANPHU-01",
  "fingerprint": {
    "smbios_uuid": "4C4C4544-...",
    "machine_guid": "hash-sha256-hex",
    "mainboard_serial": "hash-sha256-hex"
  },
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\nMIIB...\n-----END CERTIFICATE REQUEST-----\n"
}
```

**Trả về / exit code**:

- 0 nếu ghi file thành công, in ra đường dẫn file + SHA-256 fingerprint của file để admin
  kiểm tra toàn vẹn USB.
- Non-zero nếu lỗi (thiếu token trong config, không ghi được file…).

**Không** thực hiện bất kỳ HTTP request nào.

---

### 2.2. `--install-cert <cert.json>`

Nhận lại file JSON response từ `/api/offline/enroll` (admin copy từ USB), cài cert
đã ký vào Windows Certificate Store.

**Input**: file JSON do admin lưu ra, schema:

```json
{
  "machine_id": "uuid",
  "client_cert_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n",
  "ca_cert_pem": null,
  "renew_after": "2027-05-08T23:40:04Z",
  "is_new_machine": true,
  "status": "pending",
  "agent_server_url": "http://10.10.0.241:8000",
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8,
  "inventory_interval_hours": 24
}
```

**Hành vi**:

1. Đọc `client_cert_pem`, import vào **Windows Certificate Store** (`StoreName.My`,
   `StoreLocation.LocalMachine` — match nơi agent sẽ load cert khi heartbeat).
2. Cập nhật file `%ProgramData%\OrgInventory\state.json`:
   - `machine_id` = `body.machine_id`
   - `fingerprint` (lưu lại để đối chiếu với máy cách ly)
   - `renew_after`, `agent_server_url`, các interval/jitter từ response.
3. KHÔNG verify TLS gọi lên server ở bước này (không có mạng). Phase sau có thể thêm
   sanity check: kiểm tra cert subject CN phải bắt đầu bằng `machine-` + đúng `machine_id`.

**Trả về / exit code**:

- 0: in `✔ Đã cài cert cho machine <id>`. Agent từ giờ có thể chạy service bình thường
  (heartbeat sẽ thất bại vì không có mạng, nhưng **không crash** — xem `OfflineCache`).
- Non-zero: lỗi parse cert, ghi store thất bại…

**Lưu ý**: lúc này agent vẫn chưa ký được gì cho đến khi `--export-inventory` chạy.
Phase sau có thể thử một cert `ECDsa.Verify()` nội bộ để chắc chắn cert dùng được.

---

### 2.3. `--export-inventory <out.json>`

Ký các inventory snapshot đang chờ trong `OfflineCache` và ghi file JSON để admin copy
USB đi import.

**Input**: không có flag bắt buộc (mặc định lấy mọi payload `pending` trong cache).

**Hành vi**:

1. Đọc tất cả bản ghi từ `OfflineCache.GetAll()` (hàm đã có — tham khảo
   `Services/OfflineCache.cs`).
2. Với mỗi `PendingItem` (ưu tiên `url=/api/inventory`, bỏ qua `/api/heartbeat` vì
   heartbeat không có giá trị lịch sử):
   - Parse `body` ra dict.
   - Chuẩn hóa thành payload offline:
     ```python
     {
       "machine_uuid": "<từ config/state>",
       "hostname": "<hostname>",
       "fingerprint": {...},          # từ state.json
       "spec": <body đã flatten>,     # toàn bộ body inventory
       "exported_at": "<ISO timestamp>"
     }
     ```
   - Ký `payload` bằng **ECDSA(secp256r1) + SHA-256** trên canonical JSON
     (`json.dumps(payload, sort_keys=True, separators=(",", ":"))` — xem
     `offline_import.py::_canonical_json` để khớp byte-for-byte).
   - Lấy public key từ private key trong Cert Store (dùng
     `ECDsa.ExportSubjectPublicKeyInfo()` → PEM).
3. Ghi 1 file `<out>.json` trên USB (mỗi snapshot là 1 file riêng — server hiện tại
   chỉ nhận 1 payload / request):
   ```json
   {
     "payload": {
       "machine_uuid": "fd0d8278-...",
       "hostname": "PC-ANPHU-01",
       "fingerprint": {"smbios_uuid": "..."},
       "spec": {...},
       "exported_at": "2026-08-26T14:00:00Z"
     },
     "signature_b64": "MEUCIQCx...",
     "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"
   }
   ```
   Với nhiều snapshot trong `OfflineCache`, agent nên ghi **mỗi file / snapshot**
   (admin import từng file qua API). Phase 4 có thể nâng cấp endpoint `/api/offline/import`
   chấp nhận `items[]` để giảm số lần thao tác USB.

**Trả về / exit code**:

- 0 nếu ghi file thành công, in ra đường dẫn file + SHA-256 fingerprint của file để admin
  kiểm tra toàn vẹn USB.
- Non-zero: không có cert private key (chưa chạy `--install-cert`), lỗi ghi file…

**Không xóa** bản ghi trong `OfflineCache` sau khi export. Phase sau có thể thêm flag
`--drop-after-export` để giảm cache; mặc định **giữ** để có thể export lại nếu file
USB hỏng.

---

## 3. Tích hợp với code hiện tại

| File agent hiện tại | Cần làm gì |
|---|---|
| `Program.cs::PrintHelp` | Thêm 3 subcommand vào help text |
| `Program.cs::RunOnce` (khi nhận flag mới) | Dispatch sang handler tương ứng |
| `Services/OfflineCache.cs` | Dùng lại `GetAll()`, `Delete()` y nguyên — không cần đổi |
| `Services/InventoryCollector.cs` | Dùng lại để build spec nếu muốn export ngay (bỏ qua gọi server) |
| (mới) `Services/OfflineExport.cs` | Logic ký ECDSA + canonical JSON + ghi file |
| (mới) `Services/OfflineEnroll.cs` | Sinh keypair, tạo CSR, lưu cert vào Store |

Khuyến nghị đặt code offline trong **assembly tách** hoặc ít nhất **namespace riêng**
(`OrgInventoryAgent.Offline`) để dễ bảo trì và unit test.

---

## 4. Đặc tả ký số (BẮT BUỘC khớp server)

Server (`app/api/routes/offline_import.py::_verify_signature`) verify bằng:

```
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
digest    = SHA-256(canonical)
verify(ECDSA(secp256r1) public_key, digest, signature)
```

**Lưu ý quan trọng**:

- `ensure_ascii=False` → trường có ký tự Unicode (hostname tiếng Việt) phải xuất ra UTF-8
  nguyên bản, không escape `\uXXXX`. Server đọc lại bằng Python `json.loads` nên tương
  thích. **Test bằng cách round-trip 1 payload có dấu tiếng Việt trước khi release.**
- `sort_keys=True` và `separators=(",", ":")` → không có khoảng trắng, khóa sắp xếp a-z.
- Signature là **DER encoding của ECDSA(r, s)** (chuẩn .NET trả về khi gọi
  `ECDsa.SignData(...)` với `DSASignatureFormat.Rfc3279DerSequence`). Base64 không wrap.
- Public key dùng **SubjectPublicKeyInfo** PEM (`-----BEGIN PUBLIC KEY-----`), KHÔNG phải
  EC private key hay certificate. Server dùng `cryptography` của Python — `load_pem_public_key()`
  chấp nhận cả 2 nhưng unit test sẽ fail nếu gửi cert thay vì public key.

Tham khảo `tests/test_phase3.py::test_offline_import_verified` cho test mẫu (ký + verify
bằng `cryptography` Python).

---

## 5. Tích hợp với dịch vụ (service / lifecycle)

Sau khi `--install-cert` thành công, agent service chạy bình thường:

- `HeartbeatService` gọi API → `ApiTransportException` → `OfflineCache.Enqueue()` (đã có).
- `InventoryService` tương tự.
- Service **không thoát** khi gặp lỗi mạng — vẫn tiếp tục heartbeat/inventory, cache tự
  đầy cho tới khi `--export-inventory` được gọi.

Quan trọng: agent **không cần** phân biệt "đang cách ly" hay "đang offline tạm". Chính
sách cache ở `OfflineCache.cs` đã chịu lỗi mạng — máy cách ly chỉ là trường hợp đặc biệt
của "không bao giờ có mạng trở lại".

---

## 6. Test khi phát triển

| Test | Mô tả |
|---|---|
| Unit: ECDSA sign+verify round-trip | Dùng `ECDsa.SignData` + `ECDsa.VerifyData` với chính key vừa sinh; so byte với `cryptography` Python. |
| Unit: canonical JSON | So byte-for-byte với output của `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` từ Python. |
| Integration: end-to-end qua server test | Dùng `tests/test_phase3.py::test_offline_enroll_*` và `test_offline_import_verified` làm reference; viết C# test tương đương nội bộ agent (không cần network) bằng cách gọi lại `LocalCAService` qua reflection hoặc tách helper. |
| Integration: cert import vào Store | Test trên Windows VM: chạy `--install-cert`, dùng `certmgr.msc` kiểm tra cert xuất hiện trong `LocalMachine\My`. |

---

## 7. Sai số thường gặp (lưu ý khi code)

1. **Ký nhầm JSON đẹp (indent=2)** thay vì canonical → server từ chối với
   `Chữ ký không hợp lệ`. Triệu chứng: payload verify fail 100% trong khi cùng key sinh
   cùng digest. Fix: dùng `JsonSerializer.Serialize` với options khớp canonical hoặc tự
   build canonical.
2. **Gửi public key PEM không có header `-----BEGIN PUBLIC KEY-----`** — server parse fail.
3. **Quên escape `+` thành space** trong base64 khi copy qua USB editor (Notepad thường
   giữ nguyên, nhưng tool zip/7zip đôi khi đụng). Khuyến nghị: ghi file binary base64
   `.b64` thay vì nhúng vào JSON — hoặc base64url. **Phase 2 sẽ chuyển sang CMS/PKCS#7**
   cho an toàn hơn (xem mục 3.6 tài liệu gốc).
4. **Cache quá tải**: `OfflineCache.MaxAttempts = 10` chỉ áp dụng cho retry online.
   Máy cách ly **không retry được**, nên các payload chờ export mãi mãi (không bị xóa).
   Khi export nhiều đợt, mỗi file là 1 snapshot (hiện tại server chỉ nhận 1 /
   request). Phase 4 sẽ nâng cấp endpoint `/api/offline/import` chấp nhận mảng `items[]`.

---

## 8. Tiêu chí nghiệm thu (Definition of Done)

- [ ] `--enroll-offline` sinh file JSON hợp lệ, có thể submit thẳng vào
      `POST /api/offline/enroll` (test trên staging với token do admin cấp) → nhận 200 +
      cert PEM.
- [ ] `--install-cert` cài cert vào Windows Cert Store; sau đó service chạy bình thường.
- [ ] `--export-inventory` sinh file với `items[]` ký ECDSA đúng chuẩn mục 4.
      Server `POST /api/offline/import` với file đó trả `verified: true`.
- [ ] Round-trip Việt Nam: hostname/dấu tiếng Việt trong payload → verify OK.
- [ ] Không có regression: các test Phase 1/2/3 của server vẫn xanh (`pytest tests/`).
- [ ] Code review checklist:
  - Không ghi private key ra file plaintext (chỉ Windows Cert Store).
  - Không log private key hoặc CSR có kèm key.
  - CLI flag --help liệt kê đủ 3 subcommand mới.

---

## 9. Liên hệ / tham chiếu

- Backend endpoint mới: `POST /api/offline/enroll` — xem `docs/API_CONTRACT.md` mục 5.
- Backend endpoint cũ: `POST /api/offline/import` — xem `docs/API_CONTRACT.md` mục 5.
- Server implementation: `server/app/api/routes/offline_import.py`,
  `server/app/api/routes/offline_enroll.py`.
- Test mẫu cho ký ECDSA: `server/tests/test_phase3.py::_sign_payload`.
- Plan triển khai: `PLAN_THUC_HIEN.md` mục Sprint 3, item 15–16.
