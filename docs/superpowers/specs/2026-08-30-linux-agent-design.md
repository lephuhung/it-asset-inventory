# Linux Agent — Thiết kế mở rộng agent đa nền tảng

> **Dự án:** IT Asset Inventory (Hệ thống Quản lý Tài sản CNTT & ATTT)  
> **Căn cứ:** `KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md` v1.2, `PLAN_THUC_HIEN.md` v1.3, `docs/API_CONTRACT.md` v1.6  
> **Ngày:** 2026-08-30  
> **Trạng thái:** Đã phê duyệt thiết kế, chờ review spec

---

## 1. Tổng quan

Mở rộng agent C# .NET 8 hiện tại (chỉ Windows) thành đa nền tảng, hỗ trợ **Ubuntu/Debian** và **RHEL/Rocky/AlmaLinux** (`linux-x64`, `linux-arm64`). Giữ nguyên lõi agent (enroll, mTLS, heartbeat, config ký số, offline cache, export bundle), tách collector theo OS.

### 1.1. Phạm vi

- Agent Linux online (mTLS) + offline (USB bundle).
- Schema đa nền tảng additive, tương thích ngược với agent Windows cũ.
- Portal hiển thị linh hoạt theo OS.
- Chỉ cài một lần, không self-update binary; chỉ đồng bộ config ký số.

### 1.2. Phạm vi không làm

- Plugin động, nạp assembly collector từ ngoài.
- Self-update binary.
- Tương tác với `/etc/shadow` hoặc dữ liệu người dùng cá nhân.
- Remote shell / điều khiển máy.
- Screenshot, keylog, lịch sử web.

---

## 2. Kiến trúc

### 2.1. Cấu trúc source

```
agent/src/
├── OrgInventoryAgent/
│   ├── Core/                         # lõi chung: enroll, mTLS, heartbeat, config
│   ├── Contracts/                    # DTO/Schema đa nền tảng
│   └── Collectors/
│       ├── Common/                   # dùng chung: network, port, VM, agent metadata
│       ├── Windows/                  # WMI, Registry, BitLocker, RDP...
│       └── Linux/                    # procfs, sysfs, dpkg/rpm, systemd...
├── OrgInventoryAgent.LinuxHelper/    # helper đặc quyền tối thiểu
└── tests/
    ├── OrgInventoryAgent.Tests/      # unit tests xUnit (Windows + Linux)
    └── OrgInventoryAgent.LinuxHelper.Tests/
```

### 2.2. Cây thư mục cài đặt

```
/opt/orginventory/                     # root: binary, helper (chỉ root ghi)
/etc/orginventory/config.json          # config ký số
/var/lib/orginventory/                 # runtime: cert PEM, machine_id, SQLite cache
/var/log/orginventory/                 # log xoay vòng
/run/orginventory/helper.sock          # systemd socket kích hoạt
```

### 2.3. Phân quyền

- **Service chính:** user `orginventory`, không root.
- **Helper đặc quyền:** chạy qua systemd socket activation, User=root, chạy khi có request.
- **Unix socket:** chỉ group `orginventory` (service chính) được connect.
- **Helper chỉ hỗ trợ thao tác read-only cố định:**
  - SMART (smartctl — đường dẫn cố định `/usr/sbin/smartctl`).
  - DMI bị hạn chế (nếu không đọc được qua sysfs).
  - Trạng thái LUKS (cryptsetup, lsblk).
  - Các dữ liệu cần quyền cao khác được allowlist cứng trong binary.
- **Không:** nhận lệnh tùy ý, không tải executable, không shell, không plugin.
- **Bảo vệ helper:** kiểm tra peer UID (`SO_PEERCRED`), timeout cứng (< 10s), giới hạn output (< 1MB), validate đường dẫn thiết bị, không tham số từ agent.

---

## 3. Schema đa nền tảng

### 3.1. inventory_schema_version = 4

Payload mới bổ sung các object trung lập, không phá vỡ schema cũ. Trường `inventory_schema_version` là field additive optional trong `InventoryRequest`; khi thiếu (agent Windows cũ) server mặc định xử lý theo schema phẳng hiện tại.

```json
{
  "inventory_schema_version": 4,
  "agent": {
    "name": "OrgInventoryAgent",
    "version": "1.1.0",
    "runtime": ".NET 8.0",
    "platform": "linux",
    "architecture": "x64",
    "package_type": "deb"
  },
  "os": {
    "platform": "linux",
    "distribution": "ubuntu",
    "distribution_version": "24.04",
    "kernel_version": "6.8.0-52-generic",
    "architecture": "x64",
    "subscription": null
  },
  "security": {
    "update": {
      "status": "updates-available",
      "enabled": true,
      "pending_count": 12,
      "security_pending_count": 3,
      "reboot_required": false,
      "last_updated_at": "2026-08-20T10:00:00Z"
    },
    "remote_access": {
      "ssh_enabled": true,
      "remote_desktop_enabled": false,
      "services": ["sshd"]
    },
    "disk_encryption": {
      "enabled": true,
      "technology": "luks",
      "encrypted_volumes": ["/"]
    },
    "endpoint_protection": [],
    "privilege_control": {
      "sudo_installed": true,
      "root_account_locked": true
    }
  }
}
```

### 3.2. Fallback tương thích ngược

Server ưu tiên schema v4, fallback schema cũ:

| Trường v4 mới | Fallback từ schema cũ (Windows) |
|---|---|
| `update.status` | `windows_update_status` |
| `update.enabled` | suy từ `windows_update_status` |

> `update.enabled` trên Linux = cơ chế cập nhật tự động đang bật (`unattended-upgrades` / `dnf-automatic`), tương đương `windows_update_enabled`; không phải "có kết nối internet".
| `remote_access.remote_desktop_enabled` | `rdp_enabled` |
| `disk_encryption.enabled` | `bitlocker` |
| `endpoint_protection` | `antivirus` |

### 3.3. Cột `machine_current` mới

Bổ sung cột trung lập, tương thích với cả hai OS:

- `platform` (varchar(16)): `linux`, `windows`.
- `agent_version` (varchar(32)).
- `update_status` (varchar(32)): `up-to-date`, `updates-available`, `outdated`, `unknown`.
- `update_enabled` (boolean).
- `updates_pending` (int).
- `endpoint_protection_enabled` (boolean).
- `disk_encryption_enabled` (boolean).
- `disk_encryption_technology` (varchar(32)): `bitlocker`, `luks`.
- `ssh_enabled` (boolean).
- `remote_desktop_enabled` (boolean).

Không xóa cột cũ (`windows_update_*`, `rdp_enabled`, `bitlocker`). Chi tiết lưu trong JSONB `security`.

### 3.4. Quy tắc giá trị

- Không đọc được → `null`.
- Không áp dụng cho OS → bỏ trường.
- `false` chỉ khi đã kiểm tra chắc chắn tính năng đang tắt.
- Không suy diễn "không tìm thấy công cụ" → "không an toàn".
- `agent.version` từ assembly metadata, không hardcode.

---

## 4. Collector Linux

### 4.1. Nguồn dữ liệu

| Nhóm | Ubuntu/Debian | RHEL/Rocky/AlmaLinux |
|---|---|---|
| OS | `/etc/os-release`, `uname` | Tương tự |
| CPU/RAM | `/proc/cpuinfo`, `/proc/meminfo` | Tương tự |
| Disk/DMI | `/sys/block`, `/sys/class/dmi` | Tương tự |
| Package | `dpkg-query` | `rpm -qa` |
| Update | `apt` simulation từ cache | `dnf check-update --cacheonly` |
| Service | `systemctl` | `systemctl` |
| Firewall | `ufw`, `nftables`, `iptables` | `firewalld`, `nftables`, `iptables` |
| Mã hóa | `lsblk` + device mapper/LUKS | Tương tự |
| SMART | `smartctl` (nếu có) | `smartctl` (nếu có) |

### 4.2. Nguyên tắc

- **Không tự chạy `apt update` / `dnf makecache`** — chỉ đọc metadata có sẵn.
- **Không gọi executable bằng tham số từ bên ngoài** — đường dẫn và tham số cố định trong binary.
- **Timeout** cho mọi lệnh gọi ngoài (mặc định 10s).
- **Giới hạn output** để tránh OOM.
- **Trường không đọc được → `null`**, không suy diễn.

### 4.3. Ánh xạ bảo mật

| Windows cũ | Linux mới | Ghi chú |
|---|---|---|
| `windows_update_status` | `update.status` | `updates-available` / `up-to-date` / `unknown` |
| `rdp_enabled` | `remote_access.remote_desktop_enabled` | SSH kiểm tra riêng |
| `bitlocker` | `disk_encryption` | Công nghệ = `luks` |
| `uac_enabled` | `privilege_control` | KHÔNG ánh xạ trực tiếp |
| `antivirus` | `endpoint_protection` | Allowlist sản phẩm đã biết |
| `startup_programs` | systemd enabled services | Giới hạn số lượng |
| `weak_protocols` | SSH + Samba policy | Chỉ khi dịch vụ tồn tại |
| `activation_status` | `os.subscription` | RHEL subscription (`subscription-manager` nếu có), null cho Ubuntu/Debian |
| `os_installed_at` | `null` | Không có nguồn tin cậy |

---

## 5. Đóng gói & triển khai

### 5.1. Build

- `build-linux.sh` publish `linux-x64` + `linux-arm64` (self-contained, không nén single-file).
- Helper đặc quyền đóng gói kèm trong cùng package.

### 5.2. systemd

```
orginventory-agent.service    # User=orginventory, After=network-online.target
orginventory-helper.socket    # systemd socket activation, User=root
orginventory-helper.service   # Service=orginventory-helper (chạy khi có request)
```

Hardening: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `ProtectHome`, `RestrictSUIDSGID`, `MemoryDenyWriteExecute`.

### 5.3. Cài đặt online

- **One-liner:** `curl -fsSL https://<host>/i/{token} | sudo bash`
- Server render script động: phát hiện distro → tải `.deb`/`.rpm` từ `/download/linux/{token}/{package}` → verify SHA256 → cài → agent enroll.

### 5.4. Cài đặt offline (máy cách ly)

- Tái sử dụng luồng export bundle hiện có (ký ECDSA + mã hóa hybrid AES-256-GCM/RSA-OAEP).
- Chỉ khác collector; phần đóng gói/ký/mã hóa dùng chung.
- Upload qua `/api/offline/import` — không cần endpoint mới.

---

## 6. Portal & nhận diện

### 6.1. Hiển thị

- **Danh sách máy:** thêm cột `Platform` (Windows/Linux) + badge/huy hiệu OS.
- **Dashboard:** thống kê dùng trường trung lập (`update_status`, `disk_encryption_enabled`, `platform`).
- **Chi tiết máy:**
  - Tab Tổng quan dùng chung.
  - Tab Bảo mật thích ứng theo OS.
- **Báo cáo:** filter `platform=linux`, `platform=windows`.

### 6.2. Logo

- Giữ logo OrgInventory làm thương hiệu chính.
- Thêm huy hiệu nền tảng nhỏ (Windows/Linux penguin) tại danh sách máy, header chi tiết, dashboard.
- Logo gói Linux: biến thể logo chính với accent Linux, giữ tên và nhận diện OrgInventory.
- Sinh SVG nội bộ, không dùng ảnh bitmap.

---

## 7. Kiểm thử & CI

### 7.1. Unit tests

- **Agent Linux:** xUnit (đọc fixture/proc mẫu).
- **Helper:** test authorization, timeout, output limit, path validation.
- **Build:** CI build trên Ubuntu 22.04 + Rocky 9 container.

### 7.2. Server tests

- Fallback schema cũ/mới.
- Normalization đa nền tảng.
- Thống kê cross-platform.

### 7.3. E2E

- Mock server + agent Linux `--once`.
- Bundle offline → import → hiển thị Portal.

### 7.4. Manual

- Cài `.deb`/`.rpm` thật: Ubuntu 24.04, Rocky 9.
- Kiểm tra permission, systemd hardening, helper hoạt động.

---

## 8. Không làm (cố tình giới hạn)

- Self-update binary.
- Plugin động / nạp collector từ ngoài.
- Remote shell, keylog, screenshot.
- Đọc `/etc/shadow` hoặc dữ liệu cá nhân.
- Ảnh bitmap cho logo (dùng SVG).
- Tương thích với distro không dùng systemd.

---

## 9. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Helper đặc quyền bị lạm dụng | Allowlist thao tác cứng, không nhận lệnh tùy ý; peer UID check; timeout; giới hạn output |
| .NET self-contained trên Linux bị AV gắn cờ | Không phổ biến trên Linux; chính sách "hiền" như Windows; dùng OV cert ký nếu cần |
| apt/dnf cache cũ → update sai | Không tự chạy update; ghi rõ thời gian cache; trả `unknown` nếu không có dữ liệu |
| Không đọc được DMI/sysfs (container) | Mỗi nguồn bọc try/catch riêng; trường null → server hiểu là không xác định |
| Thiếu tài liệu về helper | Giữ helper đơn giản (< 300 loc), test phủ kín, tài liệu trong source |