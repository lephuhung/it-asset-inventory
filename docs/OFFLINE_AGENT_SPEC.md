# SPEC — Agent cho chế độ máy cách ly (Offline USB 1-Click)

> Tài liệu dành cho team phát triển **agent (C#/.NET)**, **server (FastAPI)** và **portal (Next.js)**.
> Mô tả luồng triển khai và thu thập dữ liệu tài sản cho máy tính **hoàn toàn không có kết nối mạng tới server (Air-gapped)**.
>
> **Cập nhật v2.0 (2026-08-27): Tối ưu hóa trải nghiệm 1-Click (Nháy đúp chuột)**:
> Người dùng cuối tại máy cách ly **KHÔNG cần gõ lệnh PowerShell, KHÔNG cần nhập tham số `-Token` hay `-Endpoints`**.
> Chỉ cần **nháy đúp chuột vào file `install-offline` trên USB**, hệ thống tự động cài đặt, thu thập cấu hình, ký số ECDSA, mã hóa bằng Server Public Key và xuất ra **1 file ZIP duy nhất**.
> Backend giải mã, kiểm tra chữ ký số và tự động parse dữ liệu cập nhật hệ thống.
>
> **Cập nhật v2.1 (sau Phase 4)**: Agent trên máy cách ly **chỉ dùng `--export-bundle`** để xuất gói ZIP đã mã hoá. Mọi bước CSR / cert / token **đều KHÔNG cần** trên máy cách ly — server dùng fingerprint phần cứng để định danh máy khi nhận ZIP. Xem chi tiết ở mục 1B bên dưới.

---

## 0. Tóm tắt luồng 1-Click

```
[Máy cách ly (Air-gapped)]                                   [Máy Admin có mạng]
┌──────────────────────────────────────────────┐             ┌─────────────────────────────┐
│ 1. Cắm USB, NHÁY ĐÚP CHUỘT:                  │             │ 0. Admin tải gói offline    │
│    install-offline.cmd (hoặc .ps1)           │ ◄─ USB ──── │    vào USB từ Web Portal    │
│                                              │             │                             │
│ 2. Script & Agent tự động:                   │             │                             │
│    - Cài đặt Agent MSI (nếu chưa có)         │             │                             │
│    - Thu thập toàn bộ phần cứng & phần mềm   │             │                             │
│    - Ký số ECDSA P-256 (khóa riêng tại máy)  │             │                             │
│    - Mã hóa bằng Server Public Key           │             │                             │
│    - Xuất file ZIP duy nhất ra USB:          │             │                             │
│      E:\INVENTORY_<HOST>_<TIMESTAMP>.zip     │ ─ USB ────► │ 3. Upload file ZIP lên Web  │
│                                              │             │    Portal (/offline-import) │
│                                              │             │                             │
│                                              │             │ 4. Backend:                 │
│                                              │             │    - Giải mã Server Key     │
│                                              │             │    - Verify chữ ký số ECDSA │
│                                              │             │    - Parse & cập nhật DB    │
└──────────────────────────────────────────────┘             └─────────────────────────────┘
```

> Toàn bộ quy trình chỉ mất **1 lần cắm USB vào máy cách ly** và **1 lần nháy đúp chuột**.

---

## 1. Hai phương pháp triển khai Agent

### Phương pháp A — Cài bằng lệnh (Online, máy có mạng)

> **Dùng cho:** máy có mạng LAN / VPN / Internet ra Server.

**Thao tác:** Quản trị viên copy lệnh 1 dòng từ trình duyệt Web Portal (`/tokens`), dán vào PowerShell Admin:

```powershell
powershell -EP Bypass -c "irm https://portal.example.gov.vn/i/<token> | iex"
```

Script tải MSI từ `GET /download/agent.msi`, kiểm tra SHA-256 + Authenticode, cài đặt silent và tự động đăng ký (enroll) nhận certificate mTLS với Server.

---

### Phương pháp B — Cài & thu thập 1-Click qua USB (Offline, máy cách ly)

> **Dùng cho:** máy cách ly hoàn toàn (air-gapped), không có mạng tới Server.

#### Bước 1: Chuẩn bị USB (thực hiện trên máy Admin có mạng)

Admin vào Portal bấm **"Tải bộ cài máy cách ly"** (tải file `offline-package.zip` qua
endpoint `GET /download/offline-package.zip`), giải nén vào thư mục gốc của USB.

> **Lưu ý quan trọng**: File ZIP tải về **KHÔNG được đặt password** (yêu cầu nghiệp vụ —
> operator copy qua USB dễ dàng, không cần nhớ password). Tính bí mật dựa vào **mã hoá
> hybrid AES-256-GCM + RSA-OAEP** ở file ZIP do agent sinh ra SAU. Test
> `test_offline_package_zip_is_not_password_protected` chặn regression.

Trên USB gồm các file:

| File | Bắt buộc? | Vai trò |
|---|---|---|
| `install-offline.cmd` | ✅ | Launcher nháy đúp chuột (tự động bypass ExecutionPolicy + gọi PowerShell Admin) |
| `install-offline.ps1` | ✅ | Script điều phối cài đặt, thu thập, ký số và đóng gói mã hoá |
| `server_public_key.pem` | ✅ | Khoá công khai RSA-2048 của Server — agent dùng để mã hoá ZIP kết quả |
| `offline_config.json` | ⚪ | File cấu hình mẫu (admin điền `token` nếu muốn) |
| `OrgInventoryAgent.msi` | ⚪ | Bộ cài Agent đã ký số Authenticode (nếu server build sẵn) |
| `OrgInventoryAgent.msi.sha256` | ⚪ | Mã băm SHA-256 để verify MSI |

> **Tại sao KHÔNG cần `--enroll-offline` trên máy cách ly?**
> Phiên bản hiện tại của agent **chưa implement** flag `--enroll-offline` (xem
> `agent/src/OrgInventoryAgent/Program.cs`). Flow offline đã được tự động hoá hoàn toàn
> qua `install-offline.cmd`: agent chỉ chạy `--export-bundle` để sinh ZIP đã mã hoá +
> ký số. Khi admin upload ZIP lên server, server dùng **fingerprint phần cứng** (SMBIOS
> UUID / MachineGuid / Mainboard Serial) trong payload để định danh máy — không cần
> CSR, không cần cert, không cần client cert mTLS. Máy cách ly sẽ có trạng thái
> `status=offline` (không có heartbeat) nhưng có đầy đủ lịch sử cấu hình trong
> `machine_specs`.

#### Bước 2: Thao tác trên máy cách ly (Người dùng / Cán bộ nghiệp vụ)
1. Cắm USB vào máy cách ly.
2. Mở USB trong Windows Explorer, **nháy đúp chuột vào `install-offline.cmd`** (hoặc chuột phải chọn Run as Administrator).
3. Người dùng **không cần gõ bất kỳ lệnh nào, không cần nhập token hay URL server**.
4. Cửa sổ dòng lệnh chạy tự động trong 15–30 giây:
   - Kiểm tra và cài đặt `OrgInventoryAgent.msi` (nếu máy chưa cài).
   - Gọi Agent chạy chế độ thu thập nhanh (hoặc trích xuất từ SQLite cache nếu agent đã chạy).
   - Tự động sinh cặp khóa ECDSA P-256 trong Windows Certificate Store (`LocalMachine\My`) nếu máy chưa có khóa riêng. **Private key không bao giờ rời máy cách ly**.
   - Ký số ECDSA-SHA256 trên nội dung cấu hình thu thập.
   - Mã hóa toàn bộ dữ liệu bằng Server Public Key (AES-256-GCM + RSA/ECDH Hybrid Encryption).
   - Xuất ra file ZIP: `E:\INVENTORY_<HOSTNAME>_<YYYYMMDD_HHMMSS>.zip`.
   - In thông báo màu xanh:
     ```
     ============================================================
     ✔ THU THẬP VÀ ĐÓNG GÓI THÀNH CÔNG!
     File kết quả: E:\INVENTORY_PC-PHONG102_20260827_083000.zip
     Vui lòng rút USB và chuyển file cho Quản trị viên để cập nhật.
     ============================================================
     ```

#### Bước 3: Nạp dữ liệu lên hệ thống (Thực hiện trên máy Admin có mạng)
1. Admin cắm USB vào máy có mạng, đăng nhập Web Portal vào trang **[Import máy cách ly](file:///c:/Users/LPH/Documents/GitHub/it-asset-inventory/portal/app/(portal)/offline-import/page.tsx)**.
2. Chọn hoặc kéo thả file `INVENTORY_<HOSTNAME>_<TIMESTAMP>.zip` vào khung upload.
3. Nhấn **Xác nhận nạp dữ liệu**:
   - Backend nhận file qua `POST /api/offline/import` (multipart/form-data).
   - Backend dùng Server Private Key giải mã gói ZIP.
   - Backend kiểm tra chữ ký số ECDSA đối chiếu với payload bằng public key của máy trạm.
   - Nếu chữ ký đúng $\rightarrow$ parse dữ liệu phần cứng, phần mềm, bảo mật, tự động cập nhật database và bảng thống kê `machine_current`, `machine_software`.
   - Nếu chữ ký sai hoặc file bị sửa đổi trên USB $\rightarrow$ từ chối ngay lập tức (HTTP 400).

---

## 2. Cấu trúc và Quy cách Gói ZIP Mã hóa

### 2.1. Thành phần bên trong file ZIP

Gói ZIP xuất ra gồm các tệp tin sau:

| Tệp tin | Định dạng | Nội dung & Vai trò |
|---|---|---|
| `manifest.json` | JSON UTF-8 | Chứa metadata: `machine_uuid`, `hostname`, `fingerprint`, `exported_at`, `org_id` |
| `inventory.json` | JSON UTF-8 | Toàn bộ dữ liệu cấu hình tài sản theo schema chuẩn v2/v3 (OS, CPU, RAM, Disks, Network, Software, Security...) |
| `signature.sig` | Base64 DER | Chữ ký số **ECDSA-SHA256** của máy trạm trên Canonical JSON của `inventory.json` |
| `public_key.pem` | PEM (SPKI) | Khóa công khai của máy trạm (`-----BEGIN PUBLIC KEY-----`) dùng để verify `signature.sig` |
| `encrypted_key.bin` | Binary | Khóa phiên đối xứng AES-256 đã được mã hóa bằng `server_public_key.pem` |

### 2.2. Quy trình Ký số & Mã hóa 2 lớp

#### Lớp 1: Ký số (Digital Signature) — Bảo vệ tính toàn vẹn (Integrity)
1. Agent chuẩn hóa `inventory.json` thành **Canonical JSON**:
   `canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`
2. Tính digest `SHA-256(canonical)`.
3. Dùng ECDSA Private Key của máy (secp256r1) ký digest $\rightarrow$ tạo chữ ký `signature.sig` (định dạng RFC 3279 DER Sequence base64).

#### Lớp 2: Mã hóa lai (Hybrid Encryption) — Bảo vệ tính bí mật (Confidentiality)
1. Agent sinh ngẫu nhiên khóa đối xứng 256-bit `session_key` và 96-bit IV (Nonce).
2. Dùng thuật toán **AES-256-GCM** mã hóa nội dung dữ liệu (`inventory.json`, `manifest.json`, `signature.sig`, `public_key.pem`).
3. Dùng khóa công khai của Server `server_public_key.pem` mã hóa `session_key` $\rightarrow$ lưu thành `encrypted_key.bin`.
4. **Kết quả:** Người ngoài khi mở USB không thể đọc được nội dung cấu hình hay thông tin nội bộ của máy trạm cách ly. Chỉ duy nhất Server nắm giữ Private Key mới giải mã được.

### 2.3. Quy cách Bảo vệ File Cấu hình Tải về (`offline_config.json`): Ký số Chống Thay Đổi & Mã hóa

Nhằm ngăn chặn việc kẻ tấn công hoặc mã độc can thiệp sửa đổi các thiết lập trên USB (như thay đổi `endpoints` sang máy chủ độc hại, thay đổi `org_id`, hoặc chèn token giả), file cấu hình `offline_config.json` khi tải về từ Portal được bảo vệ bằng chữ ký số và/hoặc mã hóa:

#### Cấu trúc Envelope Ký số (Signed Config):
```json
{
  "version": 1,
  "issued_at": "2026-08-27T08:00:00Z",
  "payload": {
    "endpoints": "https://agent.example.gov.vn",
    "token": "t_Ab3xK9mQ2vR8nL4p",
    "org_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "note": "Cấu hình offline tạo bởi IT Asset Inventory Portal"
  },
  "signature": "<ECDSA_SHA256_BASE64>",
  "signer": "server_ecdsa_p256"
}
```

#### Cơ chế Kiểm tra Toàn vẹn (Tamper-proofing Check):
1. **Xác thực trước khi thực thi:** Khi người dùng nháy đúp chuột vào `install-offline.cmd` (hoặc chạy `.ps1`), script đọc `offline_config.json` và dùng khóa công khai Server (`server_public_key.pem`) có sẵn trong thư mục để verify chữ ký `signature` trên Canonical JSON của `{version, issued_at, payload}`.
2. **Ngăn chặn can thiệp trái phép:** Nếu file bị sửa đổi nội dung (dù chỉ đổi 1 ký tự IP hay token), script lập tức dừng lại, in thông báo lỗi màu đỏ:
   ```
   [LỖI NGUY HIỂM] File cấu hình offline_config.json đã bị chỉnh sửa trái phép hoặc chữ ký không hợp lệ!
   Quá trình cài đặt bị hủy để bảo đảm an toàn hệ thống.
   ```
3. **Mã hóa file cấu hình (`offline_config.enc`):**
   - Trường hợp cấu hình chứa bí mật đơn vị, Portal cung cấp tùy chọn tải file dưới dạng mã hóa `offline_config.enc` (AES-256-GCM). File chỉ được giải mã tự động trong bộ nhớ RAM khi chạy qua script cài đặt được cấp phép, không để lộ văn bản rõ (plaintext) trên USB.

---

## 3. Đặc tả Backend tiếp nhận: POST /api/offline/import

- **Content-Type:** `multipart/form-data`
- **Auth:** `Bearer <admin_jwt>`
- **Parameters:**
  - `file`: File ZIP nhị phân do script trên USB xuất ra.
  - `org_id` *(optional)*: Tổ chức tiếp nhận nếu muốn gán cụ thể.

**Xử lý phía Server:**
```python
# 1. Giải mã gói ZIP
session_key = server_private_key.decrypt(encrypted_key_bin)
bundle_content = aes_gcm_decrypt(session_key, encrypted_zip_data)

# 2. Kiểm tra chữ ký số ECDSA
canonical_payload = _canonical_json(bundle_content["inventory.json"])
digest = hashlib.sha256(canonical_payload).digest()
bundle_content["public_key"].verify(bundle_content["signature"], digest, ec.ECDSA(hashes.SHA256()))

# 3. Parse và cập nhật hệ thống
# Upsert Machine, MachineSpec, machine_current, machine_software
```

---

## 4. Tương thích ngược (Backward Compatibility)

Hệ thống vẫn giữ nguyên khả năng tiếp nhận payload JSON phẳng qua `POST /api/offline/import` (`{ payload, signature_b64, public_key_pem }`) phục vụ cho các công cụ script kiểm thử hoặc tự động hóa của quản trị viên cấp cao.

> **Lưu ý (sau Phase 4 cleanup)**: Endpoint `/api/offline/enroll` (admin proxy CSR) **đã bị loại bỏ** vì agent không có flag `--enroll-offline` để sinh CSR và `--install-cert` để cài cert. Toàn bộ flow offline đã được tự động hoá qua `--export-bundle` → upload ZIP.
