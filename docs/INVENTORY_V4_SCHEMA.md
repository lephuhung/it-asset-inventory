# Inventory Schema v4 — Tích hợp Windows + Linux Agent

> Tài liệu này là **checklist thực thi** để đồng bộ 2 agent (Windows + Linux) gửi inventory với schema v4. Mục tiêu: cột `platform`, `agent_version`, `update_status`, ... trong DB không còn `null`.

**Phạm vi:**
- 2 thiết bị test: **30HUYTU** (Windows) và **AI** (Ubuntu 24.04, hostname `AI`).
- Sau khi hoàn thiện, cả 2 agent sẽ gửi payload **schema v4 đầy đủ**.
- DB sẽ fill đầy đủ các cột v4, Portal hiển thị OS logo đúng (Windows/Tux), SecuritySection render theo OS.

**Liên quan:**
- Schema đặc tả: `docs/AGENT_INVENTORY_PAYLOAD_SPEC.md` (DSH Agent viết — schema cũ).
- Spec v4 (lý thuyết): `docs/superpowers/specs/2026-08-30-linux-agent-design.md` §3.
- Code C# schema: `agent/src/OrgInventoryAgent.Core/Collectors/Schema/InventoryContracts.cs`.
- Code Python schema: `server/app/schemas/__init__.py`.

---

## 1. Trạng thái hiện tại (đã verify bằng DB query)

| Máy | OS | `platform` | `agent_version` | `update_status` | Endpoint Protection | Disk Encryption | SSH |
|---|---|---|---|---|---|---|---|
| `30HUYTU` (Windows) | win | **null** ❌ | **null** ❌ | (legacy `windows_update_status`) | depends on `antivirus` | depends on `bitlocker` | — |
| `AI` (Linux, machine_id=30b056f4) | linux | `linux` ✅ | `1.0.0` ✅ | `updates-available` ✅ | depends on `endpoint_protection` | depends on `disk_encryption` | depends on `remote_access.ssh_enabled` |

**Quan sát:**
- Linux agent (commit `ca40b0c`) **đã** gửi v4 envelope khi chạy với `--send-inventory`. DB fill `platform`, `agent_version`, `update_status`.
- Windows agent **chưa** update code → chỉ gửi schema cũ → cột v4 = null.

---

## 2. Payload schema — cấu trúc phải gửi

Agent **luôn** gửi object `agent` và `os` ở root level (cùng cấp với `os_name`, `cpu`, ...). Server validate và lưu vào `agent` (JSONB), `os_metadata` (JSONB) của `machine_specs`, fill `platform`, `agent_version`, ... vào `machine_current`.

### 2.1. Schema tổng thể

```json
{
  "inventory_schema_version": 4,

  "os_name": "Windows 11 Pro 25H2",        // legacy — server vẫn lưu
  "os_version": "10.0.26200",              // legacy
  "os_build": "26200",                     // legacy
  "os_arch": "X64",                       // legacy
  "is_vm": false,
  "logged_user": "DESKTOP-XXX\\LPH",       // legacy
  "config_hash": "sha256...",              // legacy

  "cpu": { "model": "...", "cores": 14, "threads": 20 },
  "ram_gb": 31.7,
  "disks": [...],
  "gpu": { "model": "..." },
  "mainboard": { "model": "...", "serial": "..." },
  "bios": { "version": "..." },
  "network": [...],
  "installed_software": [...],

  "security": { /* SecurityPostureV4 — cả legacy flat + object v4 */ },

  // ── v4 envelope (MỚI — bắt buộc từ phiên bản này) ──
  "agent": {
    "name": "OrgInventoryAgent",
    "version": "1.1.0",
    "runtime": ".NET 8.0",
    "platform": "windows",          // "windows" | "linux"  ← BẮT BUỘC
    "architecture": "x64",          // "x64" | "arm64"
    "package_type": "msi"           // "msi" | "deb" | "rpm"
  },
  "os": {
    "platform": "windows",          // ← BẮT BUỘC, mirror agent.platform
    "distribution": "windows",      // cho Linux: "ubuntu" | "debian" | "rhel" | "rocky"
    "distribution_version": "11",  // cho Linux: "24.04" | "9"
    "kernel_version": "10.0.26200",// cho Linux: "6.8.0-138-generic"
    "architecture": "x64",
    "subscription": null            // cho RHEL: license status; null nếu không có
  }
}
```

### 2.2. Mapping `agent` → `machine_current`

| Field trong payload v4 | Cột trong `machine_current` | Ghi chú |
|---|---|---|
| `agent.platform` | `platform` | `'windows'` \| `'linux'` |
| `agent.version` | `agent_version` | semver, vd `'1.1.0'` |
| `agent.architecture` | (chưa lưu cột riêng — dùng `os_arch` cũ) | |
| `agent.package_type` | (chưa lưu — chỉ để debug / dashboard) | |
| `os.distribution` + `os.distribution_version` | (chưa lưu cột — dùng `os_product` cũ) | |

### 2.3. Mapping `security` → cột v4 trong `machine_current`

Cột v4 chỉ fill nếu **object v4 tồn tại** trong payload. Nếu agent gửi **legacy flat fields** (`windows_update_status`, `bitlocker`, `rdp_enabled`...), server **fallback** từ flat fields (xem `inventory_normalize.py::derive_v4_security_fields`).

| Field v4 (object) | Field cũ (flat fallback) | Cột `machine_current` |
|---|---|---|
| `security.update.status` | `security.windows_update_status` | `update_status` |
| `security.update.enabled` | (suy từ `windows_update_status`) | `update_enabled` |
| `security.update.pending_count` | — | `updates_pending` |
| `security.disk_encryption.enabled` | `security.bitlocker == "on"` | `disk_encryption_enabled` |
| `security.disk_encryption.technology` | nếu `bitlocker="on"` → `"bitlocker"`, Linux → `"luks"` | `disk_encryption_technology` |
| `security.endpoint_protection` (list) | `security.antivirus` (list) | `endpoint_protection_enabled` = bool(list) |
| `security.remote_access.ssh_enabled` | — | `ssh_enabled` |
| `security.remote_access.remote_desktop_enabled` | `security.rdp_enabled` | `remote_desktop_enabled` |

**Lưu ý:**
- Linux **không có** `windows_update_status` → server fallback `update_status="unknown"` nếu object `security.update` cũng thiếu.
- Server **ưu tiên** v4 object. Nếu agent gửi cả hai (flat + v4), server dùng v4, bỏ qua flat.

---

## 3. Công việc cần làm trên từng agent

### 3.1. Linux agent (`OrgInventoryAgent.Linux`)

**Trạng thái:** ✅ Đã làm (commit `ca40b0c`). Program.cs gọi `LinuxInventoryProvider.Collect()` → trả `InventoryEnvelope` đã có `agent`, `os`, `security.update.*`.

**Verify bằng DB query** (đã chạy):

```sql
SELECT machine_id, platform, agent_version, update_status
FROM machine_current WHERE machine_id = '30b056f4-bb51-4a12-90cf-3e0d7e245bd6';
-- platform=linux, agent_version=1.0.0, update_status=updates-available ✓
```

**Còn thiếu (chưa cần fix ngay, có thể làm sau):**
- Software inventory: hiện `dpkg-query` đã chạy, trả `InstalledSoftware` list.
- `update.pending_count`: hiện dùng `apt-get -s upgrade` → chính xác. **OK**.
- `disk_encryption.technology`: hard-code `"luks"` khi `lsblk` thấy `crypt`/`crypto_LUKS`. **OK**.
- `endpoint_protection`: dùng `pgrep` để detect (ClamAV / CrowdStrike / SentinelOne / Wazuh). Nếu không match → trả `[]` → server tính `endpoint_protection_enabled=false`.

### 3.2. Windows agent (`OrgInventoryAgent`)

**Trạng thái:** ❌ Code cũ, chỉ gửi schema flat (`InventorySnapshot` ở `Program.cs` cũ, không có `agent`/`os` envelope).

**Cần fix:**

#### Bước 1 — Thêm envelope vào `InventorySnapshot` (hoặc `InventoryEnvelope`)

Có 2 cách:

**Cách A:** Mở rộng `InventorySnapshot` trong Core với 2 field mới:

```csharp
public sealed class InventorySnapshot : InventoryEnvelope
{
    // kế thừa: InventorySchemaVersion, Agent, Os, Security
    // các field phẳng: OsName, OsVersion, OsBuild, ... (giữ nguyên)
}
```

**Cách B:** Wrap snapshot vào một `InventoryPayload`:

```csharp
public sealed class InventoryPayload
{
    public InventorySnapshot Snapshot { get; set; }
    public InventoryEnvelope Envelope { get; set; }
}
```

→ Server cần được update để nhận cả 2 shape.

**Khuyến nghị:** Cách A — `InventorySnapshot` kế thừa `InventoryEnvelope`. Server code đã handle cả 2 (vì `InventoryEnvelope` có `InventorySchemaVersion`, `Agent`, `Os`, `Security`).

#### Bước 2 — Điền `Agent` trong Windows `InventoryCollector.Collect()`

```csharp
return new InventorySnapshot
{
    // ... existing fields ...
    InventorySchemaVersion = 4,
    Agent = new AgentMetadata
    {
        Name = AppInfo.Name,
        Version = AppInfo.Version,
        Runtime = ".NET 8.0",
        Platform = "windows",
        Architecture = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant(),
        PackageType = "msi",
    },
    Os = new OsMetadata
    {
        Platform = "windows",
        Distribution = "windows",
        DistributionVersion = /* từ registry DisplayVersion */,
        Architecture = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant(),
    },
};
```

Các field Windows-specific (`os.distribution_version`):
- Đọc từ `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\DisplayVersion` (vd "25H2").
- Hoặc từ WMI `Win32_OperatingSystem.BuildNumber` + Caption.

#### Bước 3 — Điền `Os` (distribution, kernel_version, architecture)

```csharp
var osMetadata = new OsMetadata
{
    Platform = "windows",
    Distribution = "windows",
    DistributionVersion = GetDisplayVersion(),   // "25H2" hoặc "11"
    KernelVersion = Environment.OSVersion.Version.ToString(),
    Architecture = "x64",  // hoặc "arm64"
    Subscription = null,   // Windows không có "subscription" — luôn null
};
```

#### Bước 4 — `SecurityPostureV4` đã có sẵn (chỉ cần fill `RemoteAccess`)

Hiện `SecurityCollector` ở Windows đang fill legacy flat fields (`bitlocker`, `rdp_enabled`, ...). Server fallback từ flat → v4. Nhưng để đồng nhất với Linux, có thể fill luôn object `remote_access`:

```csharp
Security = new SecurityPostureV4
{
    // ... existing ...
    RemoteAccess = new RemoteAccessStatus
    {
        SshEnabled = false,  // Windows không có SSH server mặc định
        RemoteDesktopEnabled = GetRdpEnabled(),  // từ registry fDenyTSConnections
        Services = new List<string> { "rdp" },
    },
    DiskEncryption = new DiskEncryptionStatus
    {
        Enabled = GetBitLockerStatus() == "on",
        Technology = "bitlocker",  // luôn là bitlocker trên Windows
        EncryptedVolumes = GetBitLockerVolumes(),
    },
};
```

Có thể để tương lai — server fallback vẫn đang hoạt động.

---

## 4. Test plan (2 thiết bị)

### 4.1. Sau khi Windows agent được update

| Bước | Máy | Lệnh / Cách test | Kết quả mong đợi |
|---|---|---|---|
| 1 | `30HUYTU` (Windows) | Restart OrgInventoryAgent service hoặc trigger rescan | Service gửi inventory mới với schema v4 |
| 2 | DB | `SELECT platform, agent_version FROM machine_current WHERE machine_id = '<30HUYTU-id>'` | `platform='windows'`, `agent_version='1.1.0'` |
| 3 | Portal `/machines` | Reload trang | Row `30HUYTU` hiển thị logo Windows (4 ô vuông xanh) |
| 4 | Portal `/machines/[id]` | Click vào `30HUYTU` → SecuritySection | Hiển thị Windows security (BitLocker, RDP, Windows Update) |
| 5 | `AI` (Linux) | `sudo /opt/orginventory/OrgInventoryAgent --send-inventory` | Inventory HTTP 200 OK |
| 6 | DB | Cùng query như bước 2 | `platform='linux'`, `agent_version='1.0.0'` |
| 7 | Portal | Reload `/machines` | Row `AI` hiển thị logo Tux |

### 4.2. Smoke test payload

Sau khi 2 agent gửi inventory, verify payload đầy đủ:

```bash
# Từ server, dump 1 snapshot gần nhất:
psql ... -c "SELECT agent, os_metadata, inventory_schema_version
              FROM machine_specs ORDER BY collected_at DESC LIMIT 2;"
```

Kỳ vọng:

| machine | `inventory_schema_version` | `agent` | `os` |
|---|---|---|---|
| `30HUYTU` | `4` | `{"platform":"windows", "version":"1.1.0", ...}` | `{"platform":"windows", "distribution":"windows", "distribution_version":"25H2", ...}` |
| `AI` | `4` | `{"platform":"linux", "version":"1.1.0", "package_type":"deb", ...}` | `{"platform":"linux", "distribution":"ubuntu", "distribution_version":"24.04", ...}` |

### 4.3. Negative test — DB schema fallback

Để chắc chắn **server fallback** vẫn hoạt động khi agent cũ chưa update:

1. Không thay đổi agent Linux (đã update).
2. Khi Windows agent cũ gửi inventory (chỉ có flat fields), DB sẽ fill:
   - `update_status` ← từ `windows_update_status`
   - `disk_encryption_enabled` ← từ `bitlocker == "on"`
   - `ssh_enabled` ← `null` (Windows không có SSH)
   - `remote_desktop_enabled` ← từ `rdp_enabled`

3. Nếu `platform=null` → Portal hiển thị logo `?` (đã có trong commit `f5960d6`).

---

## 5. Done Definition

Khi tất cả các điều sau đúng:

- [ ] Windows `InventoryCollector.Collect()` populate `Agent` + `Os` envelope (commit mới).
- [ ] Windows agent rebuild MSI → publish lên `/download/agent.msi` trên server.
- [ ] Máy `30HUYTU` gửi inventory mới → DB có `platform='windows'`, `agent_version='1.1.0'`.
- [ ] Portal `/machines` hiển thị logo Windows cho `30HUYTU`, logo Tux cho `AI`.
- [ ] Portal `/machines/[id]` security section render đúng cho cả 2 máy.
- [ ] DB query `SELECT platform, agent_version, count(*) FROM machine_current GROUP BY platform, agent_version` trả ≥ 2 row (1 windows, 1 linux).
- [ ] Tất cả server tests pass: `cd server && .venv/bin/pytest -q`.
- [ ] Tất cả agent tests pass: `cd agent && dotnet test OrgInventoryAgent.sln -c Release`.
- [ ] Commit Windows agent fix + docs này.

---

## 6. Liên quan

- Spec v4: `docs/superpowers/specs/2026-08-30-linux-agent-design.md`
- Code C# schema: `agent/src/OrgInventoryAgent.Core/Collectors/Schema/InventoryContracts.cs`
- Server normalize: `server/app/services/inventory_normalize.py::derive_v4_security_fields`
- Server route: `server/app/api/routes/inventory.py`
- Server schema: `server/app/schemas/__init__.py::SecurityPosture`
- DB model: `server/app/db/models.py::MachineCurrent`
- Migration v4: `server/alembic/versions/46ec4332a98e_linux_inventory_fields_v4.py`
- Portal UI: `portal/app/(portal)/machines/page.tsx` (logo OS), `portal/components/platform-badge.tsx`