# ĐẶC TẢ DỮ LIỆU ĐẨY LÊN TỪ AGENT (AGENT PAYLOAD SPECIFICATION)

Tài liệu này đặc tả chi tiết toàn bộ cấu trúc dữ liệu JSON mà Agent (Windows / Linux) thu thập và gửi lên Backend Server qua các API endpoint (`/api/inventory`, `/api/heartbeat`, `/api/enroll`), kèm hướng dẫn đồng bộ Database và Route trên Backend FastAPI.

---

## 1. Endpoint: `POST /api/inventory` (Snapshot Cấu hình Chi tiết)

Agent gửi snapshot này sau khi enroll thành công, định kỳ mỗi 24 giờ, hoặc ngay lập tức khi nhận được cờ `rescan_requested: true` từ heartbeat.

### 1.1. Cấu trúc JSON Payload mẫu (Thực tế thu thập từ Agent)

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

  "cpu": {
    "model": "13th Gen Intel(R) Core(TM) i7-13700H",
    "cores": 14,
    "threads": 20,
    "clock_mhz": 2400,
    "virtualization_enabled": true
  },

  "ram_gb": 31.7,

  "disks": [
    {
      "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00",
      "size_bytes": 1024209543168,
      "bus_type": "NVMe",
      "media_type": "SSD",
      "smart_health": "OK",
      "partitions": [
        {
          "drive_letter": "C:",
          "total_bytes": 511000000000,
          "free_bytes": 320000000000,
          "file_system": "NTFS"
        },
        {
          "drive_letter": "D:",
          "total_bytes": 513209543168,
          "free_bytes": 410000000000,
          "file_system": "NTFS"
        }
      ]
    }
  ],

  "gpu": {
    "model": "NVIDIA GeForce RTX 4060 Laptop GPU",
    "driver_version": "31.0.15.5123",
    "memory_mb": 8192
  },

  "mainboard": {
    "manufacturer": "Dell Inc.",
    "product": "0K5R1T",
    "serial": "/ABC1234/CN123456789/",
    "version": "A00"
  },

  "bios": {
    "vendor": "Dell Inc.",
    "version": "1.14.0",
    "release_date": "2024-01-10",
    "smbios_version": "3.5"
  },

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
    },
    {
      "name": "vEthernet (WSL)",
      "ip": "172.26.0.1",
      "mac": "00:15:5D:8A:9B:01",
      "is_dual_homed": false,
      "gateway": null,
      "dhcp_enabled": false,
      "dns_servers": [],
      "speed_mbps": 10000
    }
  ],

  "installed_software": [
    {
      "display_name": "Google Chrome",
      "version": "127.0.6533.100",
      "publisher": "Google LLC",
      "install_date": "2024-08-10",
      "uninstall_string": "\"C:\\Program Files\\Google\\Chrome\\Application\\...\"",
      "is_per_user": false
    },
    {
      "display_name": "Microsoft Visual Studio Code",
      "version": "1.92.2",
      "publisher": "Microsoft Corporation",
      "install_date": "2024-08-15",
      "uninstall_string": "\"C:\\Users\\LPH\\AppData\\Local\\Programs\\Microsoft VS Code\\...\"",
      "is_per_user": true
    },
    {
      "display_name": "Docker Desktop",
      "version": "4.33.1",
      "publisher": "Docker Inc.",
      "install_date": "2024-07-20",
      "uninstall_string": null,
      "is_per_user": false
    }
  ],

  "security": {
    "antivirus": [
      {
        "displayName": "Windows Defender",
        "name": "Windows Defender",
        "status": "enabled",
        "enabled": true,
        "upToDate": true
      }
    ],
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
      {
        "port": 135,
        "protocol": "TCP",
        "address": "0.0.0.0"
      },
      {
        "port": 445,
        "protocol": "TCP",
        "address": "0.0.0.0"
      },
      {
        "port": 8000,
        "protocol": "TCP",
        "address": "127.0.0.1"
      }
    ],
    "startup_programs": [
      {
        "name": "SecurityHealth",
        "command": "%windir%\\system32\\SecurityHealthSystray.exe",
        "location": "HKLM_Run"
      },
      {
        "name": "OneDrive",
        "command": "\"C:\\Program Files\\Microsoft OneDrive\\OneDrive.exe\" /background",
        "location": "HKCU_Run"
      },
      {
        "name": "UniKey",
        "command": "\"C:\\Program Files\\UniKey\\UniKeyNT.exe\"",
        "location": "HKCU_Run"
      }
    ],
    "local_accounts": [
      {
        "username": "Administrator",
        "name": "Administrator",
        "full_name": "Quản trị hệ thống",
        "disabled": true,
        "has_password": true,
        "is_admin": true
      },
      {
        "username": "LPH",
        "name": "LPH",
        "full_name": "Le Phu Hung",
        "disabled": false,
        "has_password": true,
        "is_admin": true
      }
    ],
    "smarts": [
      {
        "device": "PhysicalDrive0",
        "model": "NVMe SAMSUNG MZVL21T0HDLU-00B00",
        "health": "OK"
      }
    ]
  }
}
```

### 1.2. Bảng Mô Tả Chi Tiết Trường Dữ Liệu `InventoryRequest`

| Trường | Kiểu dữ liệu | Bắt buộc | Mô tả & Ý nghĩa nghiệp vụ |
|---|---|---|---|
| `os_name` | `string` | Không | Tên đầy đủ của HĐH (ví dụ: `Windows 11 Pro 25H2`, `Ubuntu 24.04 LTS`). |
| `os_version` | `string` | Không | Phiên bản nhân (ví dụ: `10.0.26200` trên Windows, `6.8.0-138-generic` trên Linux). |
| `os_build` | `string` | Không | Số hiệu bản dựng Build (ví dụ: `26200`). |
| `os_arch` | `string` | Không | Kiến trúc vi xử lý (`X64`, `Arm64`, `X86`). |
| `os_installed_at` | `ISO-8601 string` | Không | Thời điểm cài đặt hệ điều hành (UTC). |
| `activation_status` | `string` | Không | Bản quyền Windows (`Licensed`, `Unlicensed`, `Notification`, v.v.). |
| `is_vm` | `boolean` | Không | `true` nếu là máy ảo (Hyper-V, VMware, VirtualBox, KVM, QEMU), `false` nếu máy vật lý. |
| `logged_user` | `string` | Không | Tên tài khoản người dùng đang đăng nhập (ví dụ: `DOMAIN\User` hoặc `HOSTNAME\User`). |
| `config_hash` | `string (SHA-256)` | Không | Hash của toàn bộ payload để server so sánh tránh lưu trùng snapshot. |
| `cpu` | `object (JSON)` | Không | Thông tin CPU: `model`, `cores`. |
| `ram_gb` | `float` | Không | Dung lượng RAM khả dụng tính theo GB (ví dụ: `15.8`, `31.7`). |
| `disks` | `list[object] (JSON)` | Không | Danh sách ổ đĩa: `model`, `serial`, `size_bytes`, `size`, `size_gb`, `type` (`SSD`/`HDD`/`NVMe`). |
| `gpu` | `object (JSON)` | Không | Card đồ họa: `model`. |
| `mainboard` | `object (JSON)` | Không | Bo mạch chủ: `model`, `serial`. |
| `bios` | `object (JSON)` | Không | BIOS: `version`. |
| `network` | `list[NetworkInterface]` | Không | Danh sách card mạng: `name`, `ip`, `mac`, `is_dual_homed`. |
| `installed_software` | `list[SoftwareItem]` | Không | Danh sách ứng dụng cài trên máy (quét từ HKLM + HKCU): `display_name`, `name`, `version`, `publisher`, `install_date`, `uninstall_string`, `is_per_user`. |
| `security` | `SecurityPosture` | Không | Trạng thái bảo mật tổng hợp (xem mục 1.3). |

### 1.3. Chi Tiết Object `security` (Security Posture Toàn Diện)

- **`antivirus`** (`list[object]`): Danh sách phần mềm diệt virus:
  - `displayName` / `name`: Tên phần mềm diệt virus (VD: `Windows Defender`).
  - `status`: `"enabled"` / `"disabled"`.
  - `enabled`: `true` nếu đang bật bảo vệ thời gian thực.
  - `upToDate`: `true` nếu mẫu nhận diện virus đã cập nhật.
- **`windows_update_status`** (`string`): Trạng thái cập nhật Windows (`"up-to-date"` nếu có vá trong ≤ 45 ngày, `"outdated"` nếu quá hạn).
- **`bitlocker`** (`string`): Trạng thái mã hóa ổ đĩa hệ thống C: (`"on"`, `"off"`).
- **`firewall_enabled`** (`boolean`): `true` nếu Windows Firewall đang bật bảo vệ, `false` nếu bị tắt.
- **`uac_enabled`** (`boolean`): `true` nếu tính năng kiểm soát tài khoản người dùng User Account Control (LUA) đang bật.
- **`secure_boot_enabled`** (`boolean`): `true` nếu UEFI Secure Boot đang kích hoạt chống mã độc bootkit.
- **`usb_storage_blocked`** (`boolean`): `true` nếu cổng USB Storage bị chặn theo chính sách ATTT, `false` nếu cho phép cắm USB ngoài.
- **`weak_protocols`** (`object`): Trạng thái vô hiệu hóa các giao thức mã hóa cũ, mất an toàn:
  - `smbv1_disabled`: `true` (Đã tắt giao thức SMBv1 - phòng chống WannaCry).
  - `tls10_disabled`: `true` (Đã tắt TLS 1.0).
  - `tls11_disabled`: `true` (Đã tắt TLS 1.1).
  - `ssl3_disabled`: `true` (Đã tắt SSL 3.0).
- **`listening_ports`** (`list[object]`): Danh sách cổng mạng TCP đang mở (`port`, `protocol`, `address`) để phát hiện port lạ/cổng dịch vụ mở trái phép.
- **`startup_programs`** (`list[object]`): Danh sách phần mềm khởi động cùng Windows (`name`, `command`, `location`) để kiểm soát mã độc chạy ngầm.
- **`rdp_enabled`** (`boolean`): `true` nếu Remote Desktop (RDP - TCP 3389) đang mở, `false` nếu đã tắt.
- **`local_accounts`** (`list[object]`): Danh sách tài khoản người dùng cục bộ trên máy (`username`, `name`, `full_name`, `disabled`, `has_password`, `is_admin`).
- **`smarts`** (`list[object]`): Trạng thái sức khỏe ổ cứng SMART (`device`, `model`, `health`: `"OK"` / `"Pred Fail"`).

---

## 2. Endpoint: `POST /api/heartbeat` (Tín Hiệu Định Kỳ 30s)

### Request Payload:
```json
{
  "logged_user": "DESKTOP-EATRCNQ\\LPH",
  "uptime_sec": 3600,
  "ip": "10.10.0.253"
}
```

### Response từ Server:
```json
{
  "ok": true,
  "server_time": "2026-08-26T14:40:00Z",
  "renew_after": "2027-05-08T07:00:00Z",
  "rescan_requested": false,
  "notice_version": null,
  "heartbeat_interval_seconds": 30,
  "heartbeat_jitter_seconds": 8
}
```
> **Lưu ý**: Khi Quản trị viên bấm nút "Quét lại" (Rescan) trên Portal, Backend trả về `"rescan_requested": true` trong response của Heartbeat. Agent nhận cờ này sẽ kích hoạt thu thập và gửi ngay snapshot `POST /api/inventory`.

---

## 3. Endpoint: `POST /api/enroll` (Đăng Ký Thiết Bị Mới)

### Request Payload:
```json
{
  "token": "t_9hbDgeoVpo7WzFJXeiDaivRqNHDYVi",
  "hostname": "DESKTOP-EATRCNQ",
  "fingerprint": {
    "smbios_uuid": "4C4C4544-0042-3710-8048-B7C04F323634",
    "machine_guid": "de0aa4a0cb4afdfde97c2ce5d4b29268e8e48ca024dd81f51d824cfff3a538cb",
    "mainboard_serial": "3387afdeab304ff17a201aeb4bf6b4b08d6020ebc65965a783f6544cc25993fc"
  },
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\nMIIB...-----END CERTIFICATE REQUEST-----\n"
}
```

---

## 4. Hướng Dẫn Chi Tiết Đồng Bộ Backend FastAPI & Portal

Để Backend và Portal nhận và hiển thị đầy đủ 100% dữ liệu (bao gồm cả Port mạng, Tiến trình khởi động, Tường lửa, UAC, Secure Boot, USB, Weak Protocols), cần thực hiện 6 bước đồng bộ sau trên server:

---

### 4.1. BƯỚC 1: Cập nhật Schema Pydantic (`server/app/schemas/__init__.py`)
> **QUAN TRỌNG NHẤT**: FastAPI sử dụng Pydantic để validate request body. Nếu `SecurityPosture` không khai báo các trường này (hoặc không bật `extra="allow"`), **Pydantic sẽ tự động loại bỏ (strip) toàn bộ các trường mới**, khiến backend chỉ nhận được giá trị `None`!

Cập nhật hoặc thêm mới các class sau trong `server/app/schemas/__init__.py`:

```python
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

class WeakProtocols(BaseModel):
    smbv1_disabled: bool | None = None
    tls10_disabled: bool | None = None
    tls11_disabled: bool | None = None
    ssl3_disabled: bool | None = None

class ListeningPort(BaseModel):
    port: int | None = Field(default=None, ge=0, le=65535)
    protocol: str | None = None   # "TCP" | "UDP"
    address: str | None = None    # "0.0.0.0" | "127.0.0.1" | "::1"

class StartupProgram(BaseModel):
    name: str | None = None
    command: str | None = None
    location: str | None = None   # "HKLM_Run" | "HKCU_Run" | ...

class AntivirusInfo(BaseModel):
    displayName: str | None = None
    name: str | None = None
    status: str | None = None
    enabled: bool | None = None
    upToDate: bool | None = None

class LocalAccountInfo(BaseModel):
    username: str | None = None
    name: str | None = None
    full_name: str | None = None
    disabled: bool | None = None
    has_password: bool | None = None
    is_admin: bool | None = None

class SmartDeviceInfo(BaseModel):
    device: str | None = None
    model: str | None = None
    health: str | None = None

class SecurityPosture(BaseModel):
    # Khai báo đầy đủ các trường an toàn thông tin
    antivirus: list[AntivirusInfo] | None = None
    windows_update_status: str | None = None
    bitlocker: str | None = None
    rdp_enabled: bool | None = None
    firewall_enabled: bool | None = None
    uac_enabled: bool | None = None
    secure_boot_enabled: bool | None = None
    usb_storage_blocked: bool | None = None
    weak_protocols: WeakProtocols | None = None
    listening_ports: list[ListeningPort] | None = None
    startup_programs: list[StartupProgram] | None = None
    local_accounts: list[LocalAccountInfo] | None = None
    smarts: list[SmartDeviceInfo] | None = None

    # Cho phép linh hoạt nhận thêm mọi trường mở rộng trong tương lai mà không bị lỗi
    model_config = ConfigDict(extra="allow")
```

---

### 4.2. BƯỚC 2: Migration Database PostgreSQL

Nếu database đang chạy, thực hiện chạy lệnh SQL sau để đảm bảo các bảng `machine_specs` và `machine_current` có đủ cột lưu trữ:

```sql
-- 1. Đảm bảo bảng machine_specs lưu trữ đầy đủ snapshot JSONB
ALTER TABLE machine_specs ADD COLUMN IF NOT EXISTS installed_software JSONB;
ALTER TABLE machine_specs ADD COLUMN IF NOT EXISTS mainboard JSONB;
ALTER TABLE machine_specs ADD COLUMN IF NOT EXISTS bios JSONB;
ALTER TABLE machine_specs ADD COLUMN IF NOT EXISTS activation_status VARCHAR(64);
ALTER TABLE machine_specs ADD COLUMN IF NOT EXISTS os_installed_at TIMESTAMPTZ;

-- 2. Đảm bảo bảng machine_current có các cột bảo mật phục vụ lọc & thống kê
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS firewall_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS uac_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS secure_boot_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS usb_storage_blocked BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS rdp_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS bitlocker VARCHAR(16);
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS windows_update_status VARCHAR(32);
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS windows_update_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS antivirus_enabled BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS antivirus_up_to_date BOOLEAN;
ALTER TABLE machine_current ADD COLUMN IF NOT EXISTS antivirus JSONB;

-- Tạo index để truy vấn thống kê siêu nhanh
CREATE INDEX IF NOT EXISTS ix_machine_current_firewall ON machine_current (firewall_enabled);
CREATE INDEX IF NOT EXISTS ix_machine_current_win_update ON machine_current (windows_update_status);
CREATE INDEX IF NOT EXISTS ix_machine_current_av_enabled ON machine_current (antivirus_enabled);
```

---

### 4.3. BƯỚC 3: Cập nhật Service Chuẩn Hóa (`server/app/services/inventory_normalize.py`)

Hàm `derive_security_fields` chịu trách nhiệm bóc tách các trường từ `security` dict sang các cột của bảng `machine_current`:

```python
def derive_security_fields(security: dict | None) -> dict:
    sec = security or {}

    antivirus = sec.get("antivirus") or []
    av_enabled: bool | None = None
    for av in antivirus:
        if not isinstance(av, dict):
            continue
        enabled = av.get("enabled")
        if enabled is None and av.get("status") is not None:
            enabled = av.get("status") == "enabled"
        if enabled is True:
            av_enabled = True
            break
        if enabled is False and av_enabled is None:
            av_enabled = False

    up_to_date_vals = [av.get("upToDate") for av in antivirus if isinstance(av, dict) and "upToDate" in av]
    av_up_to_date: bool | None = None
    if up_to_date_vals:
        av_up_to_date = all(v is True for v in up_to_date_vals)

    update_status = sec.get("windows_update_status")
    update_enabled: bool | None = None
    if isinstance(update_status, str) and update_status.strip():
        s = update_status.strip().lower()
        if s in {"up-to-date", "up to date", "uptodate", "pending", "checking", "enabled", "on", "active"}:
            update_enabled = True
        elif s in {"disabled", "off", "never", "paused", "stopped"}:
            update_enabled = False

    return {
        "antivirus": antivirus or None,
        "antivirus_enabled": av_enabled,
        "antivirus_up_to_date": av_up_to_date,
        "windows_update_status": update_status,
        "windows_update_enabled": update_enabled,
        "bitlocker": sec.get("bitlocker"),
        "firewall_enabled": sec.get("firewall_enabled"),
        "uac_enabled": sec.get("uac_enabled"),
        "secure_boot_enabled": sec.get("secure_boot_enabled"),
        "rdp_enabled": sec.get("rdp_enabled"),
        "usb_storage_blocked": sec.get("usb_storage_blocked"),
    }
```

---

### 4.4. BƯỚC 4: Cập nhật Route Nhận Inventory (`server/app/api/routes/inventory.py`)

Khi lưu `MachineSpec`, chuyển đổi `body.security` sang dict:

```python
    spec = MachineSpec(
        machine_id=machine.id,
        os_name=body.os_name,
        os_product=product,
        os_release=release,
        os_family=family,
        os_version=body.os_version,
        os_build=body.os_build,
        os_arch=body.os_arch,
        os_installed_at=body.os_installed_at,
        activation_status=body.activation_status,
        cpu=body.cpu.model_dump() if body.cpu else None,
        ram_gb=body.ram_gb,
        disks=([d.model_dump() for d in body.disks] if body.disks else None),
        gpu=body.gpu.model_dump() if body.gpu else None,
        mainboard=body.mainboard.model_dump() if body.mainboard else None,
        bios=body.bios.model_dump() if body.bios else None,
        network=([n.model_dump() for n in body.network] if body.network else None),
        logged_user=body.logged_user,
        installed_software=(
            [s.model_dump() for s in body.installed_software] if body.installed_software else None
        ),
        # Lưu toàn bộ security object (bao gồm listening_ports, startup_programs, weak_protocols...)
        security=body.security.model_dump() if body.security else None,
        config_hash=new_hash,
    )
```

---

### 4.5. BƯỚC 5: Cập nhật Route Chi Tiết Máy (`server/app/api/routes/machines.py`)

Đảm bảo `latest_spec` trả về trường `security` nguyên vẹn cho Portal:

```python
    return MachineDetail(
        id=machine.id,
        hostname=machine.hostname,
        machine_uuid=machine.machine_uuid,
        status=machine.status,
        lifecycle=machine.lifecycle,
        is_vm=machine.is_vm,
        last_seen_at=machine.last_seen_at,
        enrolled_at=machine.enrolled_at,
        org_id=machine.org_id,
        assigned_user_id=machine.assigned_user_id,
        fingerprint=machine.fingerprint or {},
        note=machine.note,
        latest_spec=(
            {
                "os_name": latest.os_name,
                "os_version": latest.os_version,
                "os_build": latest.os_build,
                "os_arch": latest.os_arch,
                "os_installed_at": latest.os_installed_at,
                "activation_status": latest.activation_status,
                "cpu": latest.cpu,
                "ram_gb": latest.ram_gb,
                "disks": latest.disks,
                "gpu": latest.gpu,
                "mainboard": latest.mainboard,
                "bios": latest.bios,
                "network": latest.network,
                "logged_user": latest.logged_user,
                "installed_software": latest.installed_software,
                "security": latest.security,  # Trả về toàn bộ security JSONB
                "collected_at": latest.collected_at,
            }
            if latest
            else None
        ),
        phone_masked=assigned_phone,
        assigned_user_name=assigned_name,
        org_name=org.name if org else None,
    )
```

---

### 4.6. BƯỚC 6: Khởi động lại Backend Service (Reload)

Sau khi chỉnh sửa code Python, cần reload lại process FastAPI/Uvicorn:

#### Nếu chạy Uvicorn trực tiếp (Development):
Uvicorn nếu có cờ `--reload` sẽ tự khởi động lại. Nếu không, nhấn `Ctrl+C` và chạy lại:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Nếu chạy qua Docker:
```bash
docker compose restart server
# Hoặc rebuild lại container nếu cần:
docker compose up -d --build server
```

#### Nếu chạy qua Systemd (Linux Service):
```bash
sudo systemctl restart it-asset-inventory-server
sudo journalctl -u it-asset-inventory-server -f
```

---

### 4.7. Hướng dẫn Hiển thị trên Frontend Web Portal (Next.js / React)

Trong trang chi tiết thiết bị (`/machines/[id]`), truy xuất `machine.latest_spec?.security`:

1. **Trạng thái Tường lửa & UAC & Secure Boot:**
   ```tsx
   <Badge color={sec?.firewall_enabled ? "green" : "red"}>
     Tường lửa: {sec?.firewall_enabled ? "BẬT" : "TẮT"}
   </Badge>
   <Badge color={sec?.uac_enabled ? "green" : "red"}>
     UAC: {sec?.uac_enabled ? "BẬT" : "TẮT"}
   </Badge>
   <Badge color={sec?.secure_boot_enabled ? "green" : "yellow"}>
     Secure Boot: {sec?.secure_boot_enabled ? "BẬT" : "TẮT"}
   </Badge>
   ```

2. **Cổng mạng đang lắng nghe (`listening_ports`):**
   ```tsx
   <Table>
     <thead>
       <tr><th>Cổng (Port)</th><th>Giao thức</th><th>Địa chỉ bind</th></tr>
     </thead>
     <tbody>
       {sec?.listening_ports?.map(p => (
         <tr key={p.port}>
           <td><strong>{p.port}</strong></td>
           <td>{p.protocol}</td>
           <td>{p.address}</td>
         </tr>
       ))}
     </tbody>
   </Table>
   ```

3. **Ứng dụng khởi động cùng hệ thống (`startup_programs`):**
   ```tsx
   <Table>
     <thead>
       <tr><th>Tên ứng dụng</th><th>Lệnh khởi chạy</th><th>Vị trí Registry</th></tr>
     </thead>
     <tbody>
       {sec?.startup_programs?.map(app => (
         <tr key={app.name}>
           <td><strong>{app.name}</strong></td>
           <td className="font-mono text-xs">{app.command}</td>
           <td><Badge>{app.location}</Badge></td>
         </tr>
       ))}
     </tbody>
   </Table>
   ```

