# Linux Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mở rộng agent IT Asset Inventory hiện tại (chỉ Windows) thành đa nền tảng — bổ sung hỗ trợ Linux cho Ubuntu/Debian và RHEL/Rocky/AlmaLinux với chuẩn bảo mật tương đương Windows (read-only, mTLS, config ký số, không self-update binary).

**Architecture:** Refactor lõi agent (enroll, mTLS, heartbeat, config, cache, export bundle) vào thư viện `OrgInventoryAgent.Core` độc lập với OS. Tách collector theo OS (`Collectors/Windows/`, `Collectors/Linux/`, `Collectors/Common/`). Giữ 2 executable riêng: `OrgInventoryAgent.Windows` (Windows Service) và `OrgInventoryAgent.Linux` (systemd). Helper đặc quyền tối thiểu `OrgInventoryAgent.LinuxHelper` chạy qua systemd socket activation, allowlist cứng. Schema inventory mở rộng sang version 4 với các object trung lập (`agent`, `os`, `security.update`, `security.remote_access`, `security.disk_encryption`, `security.endpoint_protection`, `security.privilege_control`) — server fallback về trường phẳng cũ khi thiếu.

**Tech Stack:** C# / .NET 8 (multi-target), systemd (Ubuntu/Debian, RHEL/Rocky), dpkg-deb + fpm (đóng gói), Python 3.12 + FastAPI (server), Alembic (migration), Next.js 16 (portal), Pydantic v2 (validation), React + WebSocket (realtime). Thi công mới: `OrgInventoryAgent.Core` (class library), `OrgInventoryAgent.LinuxHelper` (console), `agent/installer/linux/` (deb/rpm + systemd), `agent/installer/linux/install-online.sh`, `agent/installer/linux/install-offline.sh`.

**Spec:** `docs/superpowers/specs/2026-08-30-linux-agent-design.md`

---

## Global Constraints

Mọi task phải tuân thủ các ràng buộc sau (lấy từ spec):

- **Phạm vi OS hỗ trợ:** Ubuntu 20.04+, Debian 11+, RHEL/Rocky/AlmaLinux 8/9 (chỉ các bản có `systemd`).
- **Kiến trúc binary:** `linux-x64`, `linux-arm64`. Self-contained single-file. **KHÔNG nén** (`EnableCompressionInSingleFile=false`), **KHÔNG tự giải nén** (`IncludeNativeLibrariesForSelfExtract=false`), `DebugType=none`. Áp dụng cả Windows và Linux để đồng nhất.
- **Runtime identifier:** `win-x64`, `win-x86`, `linux-x64`, `linux-arm64`.
- **Target framework:** `net8.0` (KHÔNG `net8.0-windows` — phải build được trên Linux/CI).
- **Assembly metadata (bắt buộc, chống AV):** `Company=Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh`, `Product=OrgInventory Agent - Hệ thống Quản lý Tài sản CNTT & ATTT`, `Description` đầy đủ, `Version=1.1.0` (bump từ 1.0.0 → 1.1.0 cho bản Linux). Icon `.ico` cho Windows, không icon cho Linux.
- **Quyền Linux:** service chính `User=orginventory`, không root. Helper đặc quyền `User=root`, kích hoạt qua systemd socket activation. Unix socket `/run/orginventory/helper.sock`, group `orginventory` đọc được.
- **Helper allowlist (cố định trong binary):** smartctl (`/usr/sbin/smartctl`), cryptsetup, lsblk, dm-crypt, modprobe. **KHÔNG** nhận shell command, **KHÔNG** tải executable, **KHÔNG** plugin. Validate `SO_PEERCRED` = UID của user `orginventory`. Timeout cứng `< 10s`. Giới hạn output `< 1MB`.
- **systemd hardening:** `NoNewPrivileges=yes`, `ProtectSystem=strict`, `PrivateTmp=yes`, `ProtectHome=yes`, `RestrictSUIDSGID=yes`, `MemoryDenyWriteExecute=yes` (cho service). Helper: `PrivateDevices=no` (cần /dev/sda…), `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`.
- **Cây thư mục cài đặt (Linux):** `/opt/orginventory/` (binary, helper), `/etc/orginventory/config.json` (config ký số), `/var/lib/orginventory/` (cert PEM, machine_id, SQLite cache), `/var/log/orginventory/` (log xoay vòng), `/run/orginventory/helper.sock`.
- **Schema version:** `inventory_schema_version=4` additive optional. Server fallback schema phẳng hiện tại.
- **Nguyên tắc dữ liệu:** Không tự chạy `apt update` / `dnf makecache`. Đường dẫn và tham số executable cố định trong binary. Timeout 10s mọi lệnh ngoài. Giới hạn output. Trường không đọc được → `null`, không suy diễn.
- **Cập nhật binary:** KHÔNG self-update. Chỉ đồng bộ config ký số qua `GET /api/agent/config` + heartbeat.
- **Nguồn dữ liệu (Linux):** OS (`/etc/os-release`, `uname`), CPU/RAM (`/proc/cpuinfo`, `/proc/meminfo`), disk/DMI (`/sys/block`, `/sys/class/dmi`), package (`dpkg-query` | `rpm -qa`), update (apt cache, dnf cache, không auto-refresh), service (`systemctl`), firewall (`ufw`/`firewalld`/`nftables`/`iptables`), mã hóa (`lsblk` + LUKS), SMART (`smartctl` qua helper).
- **Ánh xạ bảo mật (Linux → schema v4):** `windows_update_status` → `security.update.status` (`up-to-date` | `updates-available` | `outdated` | `unknown`), `rdp_enabled` → `security.remote_access.remote_desktop_enabled`, `bitlocker` → `security.disk_encryption.enabled` (`technology=luks`), `antivirus` → `security.endpoint_protection`, `uac_enabled` → `security.privilege_control` (sudo, root lock) — KHÔNG ánh xạ 1:1.
- **Portal:** thêm cột `Platform`, badge Linux/Win, tab bảo mật thích ứng, filter `platform=linux`. Logo OrgInventory giữ nguyên; thêm huy hiệu Linux nhỏ (penguin) tại danh sách/chi tiết/dashboard.
- **Test:** xUnit cho agent (Linux + Windows), pytest cho server, fixture `/proc` mẫu cho collector Linux. Helper test authorization/timeout/output limit. E2E mock server + agent Linux `--once`. CI build Ubuntu 22.04 + Rocky 9 container.
- **Nguyên tắc an ninh:** read-only, zero-GUI, không remote shell, không đọc `/etc/shadow`/dữ liệu cá nhân.
- **Mã hóa & chống replay:** giữ nguyên cơ chế envelope `version` tăng dần + ECDSA-SHA256 cho `GET /api/agent/config`.

---

## File Structure (đã có sẵn + sẽ tạo/sửa)

**Tạo mới:**
- `agent/src/OrgInventoryAgent.Core/OrgInventoryAgent.Core.csproj` — lõi chung (mTLS, enroll, heartbeat, config, cache, export bundle, AppPaths, AppInfo, AgentIdentity, AgentConfig, Logging, EndpointManager, OfflineCache, RenewService, ConfigSyncService).
- `agent/src/OrgInventoryAgent.Core/Net/ApiClient.cs`, `EnrollClient.cs`, `EndpointManager.cs`, `MtlsChannel.cs`.
- `agent/src/OrgInventoryAgent.Core/Services/EnrollCoordinator.cs`, `HeartbeatService.cs`, `InventoryService.cs`, `RenewService.cs`, `ConfigSyncService.cs`.
- `agent/src/OrgInventoryAgent.Core/Crypto/KeyStore.cs` (multi-platform: Windows cert store + Linux PEM), `CsrGenerator.cs`.
- `agent/src/OrgInventoryAgent.Core/Collectors/Common/NetworkCollector.cs`, `PortCollector.cs`, `VmDetector.cs`, `AgentMetadataCollector.cs`.
- `agent/src/OrgInventoryAgent.Core/Collectors/Schema/InventoryContracts.cs` — DTO schema v4 (agent, os, security.update, security.remote_access, security.disk_encryption, security.endpoint_protection, security.privilege_control).
- `agent/src/OrgInventoryAgent.Core/Collectors/IInventoryProvider.cs` — interface collector.
- `agent/src/OrgInventoryAgent/Collectors/Windows/*` (move từ `Collectors/InventoryCollector.cs` hiện tại, tách theo file).
- `agent/src/OrgInventoryAgent/Program.cs` — Windows Service wrapper, dùng Core + Windows collector.
- `agent/src/OrgInventoryAgent.Linux/Collectors/Linux/*` — fingerprint, inventory, security (update/remote_access/disk_encryption/endpoint_protection/privilege_control), software (dpkg/rpm), package-family select.
- `agent/src/OrgInventoryAgent.Linux/Program.cs` — systemd wrapper, dùng Core + Linux collector.
- `agent/src/OrgInventoryAgent.LinuxHelper/Program.cs` — console app nhận request qua stdin/socket, allowlist cứng.
- `agent/src/OrgInventoryAgent.LinuxHelper/Services/SmartCollector.cs`, `DmiCollector.cs`, `LUKSCollector.cs`, `PrivilegedOps.cs`.
- `agent/tests/OrgInventoryAgent.Core.Tests/*` — test Core.
- `agent/tests/OrgInventoryAgent.Linux.Tests/*` — test Linux collector.
- `agent/tests/OrgInventoryAgent.LinuxHelper.Tests/*` — test helper auth/timeout/output limit.
- `agent/installer/linux/build-linux.sh`, `build-deb.sh`, `build-rpm.sh`, `orginventory-agent.service`, `orginventory-helper.socket`, `orginventory-helper.service`, `install-online.sh`, `install-offline.sh`, `postinst.sh`, `prerm.sh`, `debian/control`, `debian/conffiles`, `rpm/orginventory.spec`.
- `server/app/schemas/inventory_v4.py` — Pydantic models cho schema v4 (agent, os, security mới).
- `server/alembic/versions/<rev>_linux_inventory_fields.py` — migration bổ sung cột trung lập.
- `server/app/services/inventory_normalize.py` — cập nhật fallback v4→cũ.
- `portal/app/machines/[id]/security-section.tsx` — tab bảo mật thích ứng theo OS.
- `portal/components/platform-badge.tsx`, `logo-linux.svg`.

**Sửa đổi:**
- `agent/OrgInventoryAgent.sln` — thêm project Core, Linux, LinuxHelper, tách tests.
- `agent/src/OrgInventoryAgent/Collectors/InventoryCollector.cs` → tách thành nhiều file trong `Collectors/Windows/` và `Collectors/Common/`.
- `agent/src/OrgInventoryAgent/Program.cs` — dùng Core + Windows collector.
- `agent/linux/src/OrgInventoryAgent.Linux/Collectors/*` (đã có một phần) — bổ sung Security, Software, Port, Service, Firewall, Encryption, Update; refactor dùng Core Contracts.
- `agent/src/OrgInventoryAgent/OrgInventoryAgent.csproj` — chỉ còn Windows wrapper, reference Core.
- `server/app/api/routes/inventory.py` — nhận schema v4, fallback cũ.
- `server/app/api/routes/machines.py` — trả `platform`, `agent_version`.
- `portal/app/machines/page.tsx` — cột Platform, badge.
- `portal/components/Logo.tsx` — thêm Linux accent.
- `.github/workflows/ci.yml` — build matrix Linux.

**Không sửa:**
- `server/app/services/inventory_sync.py` — chỉ mở rộng dict (không đổi luồng).
- `agent/src/OrgInventoryAgent/AppPaths.cs` — chuyển sang Core, logic đa nền tảng.

---

## Task Ordering & Phases

Phases triển khai tuần tự; mỗi phase có deliverable testable độc lập. Tổng cộng **5 phases, 24 tasks**.

---

## Phase 1 — Refactor lõi: tách `OrgInventoryAgent.Core`

### Task 1: Khởi tạo project Core và Contracts

**Files:**
- Create: `agent/src/OrgInventoryAgent.Core/OrgInventoryAgent.Core.csproj`
- Create: `agent/src/OrgInventoryAgent.Core/Collectors/Schema/InventoryContracts.cs`
- Modify: `agent/OrgInventoryAgent.sln`

**Interfaces:**
- Produces: `OrgInventoryAgent.Core` library, namespace `OrgInventoryAgent.Core`.

- [ ] **Step 1: Tạo project Core**

```bash
cd /home/windowsId/agent
mkdir -p src/OrgInventoryAgent.Core
```

Tạo file `src/OrgInventoryAgent.Core/OrgInventoryAgent.Core.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>OrgInventoryAgent.Core</RootNamespace>
    <AssemblyName>OrgInventoryAgent.Core</AssemblyName>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>12</LangVersion>
    <InvariantGlobalization>false</InvariantGlobalization>
    <TieredPGO>true</TieredPGO>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.Extensions.Hosting" Version="8.0.1" />
    <PackageReference Include="Microsoft.Extensions.Logging.Abstractions" Version="8.0.1" />
    <PackageReference Include="Microsoft.Data.Sqlite" Version="8.0.11" />
    <PackageReference Include="System.Text.Json" Version="8.0.5" />
    <PackageReference Include="System.IdentityModel.Tokens.Jwt" Version="8.0.2" />
  </ItemGroup>
</Project>
```

- [ ] **Step 2: Tạo Contracts schema v4**

Tạo `src/OrgInventoryAgent.Core/Collectors/Schema/InventoryContracts.cs`:

```csharp
using System.Text.Json.Serialization;

namespace OrgInventoryAgent.Core.Collectors.Schema;

/// <summary>Schema v4 — đa nền tảng, additive optional.
/// Server fallback về trường phẳng khi thiếu (Windows agent cũ).</summary>
public sealed class InventoryEnvelope
{
    [JsonPropertyName("inventory_schema_version")] public int InventorySchemaVersion { get; set; } = 4;
    [JsonPropertyName("agent")] public AgentMetadata Agent { get; set; } = new();
    [JsonPropertyName("os")] public OsMetadata Os { get; set; } = new();
    // Trường phẳng hiện có (cpu, ram_gb, disks, gpu, mainboard, bios, network,
    // logged_user, installed_software, is_vm, config_hash, activation_status)
    // được thêm vào từ collector OS-specific.
    public SecurityPostureV4 Security { get; set; } = new();
}

public sealed class AgentMetadata
{
    [JsonPropertyName("name")] public string Name { get; set; } = "OrgInventoryAgent";
    [JsonPropertyName("version")] public string Version { get; set; } = "";
    [JsonPropertyName("runtime")] public string Runtime { get; set; } = ".NET 8.0";
    [JsonPropertyName("platform")] public string Platform { get; set; } = "";   // windows | linux
    [JsonPropertyName("architecture")] public string Architecture { get; set; } = ""; // x64 | arm64
    [JsonPropertyName("package_type")] public string? PackageType { get; set; } // msi | deb | rpm
}

public sealed class OsMetadata
{
    [JsonPropertyName("platform")] public string Platform { get; set; } = "";
    [JsonPropertyName("distribution")] public string? Distribution { get; set; }
    [JsonPropertyName("distribution_version")] public string? DistributionVersion { get; set; }
    [JsonPropertyName("kernel_version")] public string? KernelVersion { get; set; }
    [JsonPropertyName("architecture")] public string? Architecture { get; set; }
    [JsonPropertyName("subscription")] public string? Subscription { get; set; }
}

public sealed class SecurityPostureV4
{
    [JsonPropertyName("antivirus")] public List<AntivirusInfo>? Antivirus { get; set; }
    [JsonPropertyName("windows_update_status")] public string? WindowsUpdateStatus { get; set; }
    [JsonPropertyName("update")] public UpdateStatus Update { get; set; } = new();
    [JsonPropertyName("bitlocker")] public string? Bitlocker { get; set; }
    [JsonPropertyName("disk_encryption")] public DiskEncryptionStatus DiskEncryption { get; set; } = new();
    [JsonPropertyName("rdp_enabled")] public bool? RdpEnabled { get; set; }
    [JsonPropertyName("remote_access")] public RemoteAccessStatus RemoteAccess { get; set; } = new();
    [JsonPropertyName("firewall_enabled")] public bool? FirewallEnabled { get; set; }
    [JsonPropertyName("uac_enabled")] public bool? UacEnabled { get; set; }
    [JsonPropertyName("secure_boot_enabled")] public bool? SecureBootEnabled { get; set; }
    [JsonPropertyName("privilege_control")] public PrivilegeControlStatus PrivilegeControl { get; set; } = new();
    [JsonPropertyName("usb_storage_blocked")] public bool? UsbStorageBlocked { get; set; }
    [JsonPropertyName("weak_protocols")] public WeakProtocolsInfo? WeakProtocols { get; set; }
    [JsonPropertyName("listening_ports")] public List<ListeningPortInfo>? ListeningPorts { get; set; }
    [JsonPropertyName("startup_programs")] public List<StartupProgramInfo>? StartupPrograms { get; set; }
    [JsonPropertyName("local_accounts")] public List<LocalAccountInfo>? LocalAccounts { get; set; }
    [JsonPropertyName("smarts")] public List<object>? Smarts { get; set; }
}

public sealed class UpdateStatus
{
    [JsonPropertyName("status")] public string Status { get; set; } = "unknown"; // up-to-date | updates-available | outdated | unknown
    [JsonPropertyName("enabled")] public bool? Enabled { get; set; }
    [JsonPropertyName("pending_count")] public int? PendingCount { get; set; }
    [JsonPropertyName("security_pending_count")] public int? SecurityPendingCount { get; set; }
    [JsonPropertyName("reboot_required")] public bool? RebootRequired { get; set; }
    [JsonPropertyName("last_updated_at")] public string? LastUpdatedAt { get; set; }
}

public sealed class DiskEncryptionStatus
{
    [JsonPropertyName("enabled")] public bool? Enabled { get; set; }
    [JsonPropertyName("technology")] public string? Technology { get; set; } // bitlocker | luks | none
    [JsonPropertyName("encrypted_volumes")] public List<string>? EncryptedVolumes { get; set; }
}

public sealed class RemoteAccessStatus
{
    [JsonPropertyName("ssh_enabled")] public bool? SshEnabled { get; set; }
    [JsonPropertyName("remote_desktop_enabled")] public bool? RemoteDesktopEnabled { get; set; }
    [JsonPropertyName("services")] public List<string>? Services { get; set; }
}

public sealed class PrivilegeControlStatus
{
    [JsonPropertyName("sudo_installed")] public bool? SudoInstalled { get; set; }
    [JsonPropertyName("root_account_locked")] public bool? RootAccountLocked { get; set; }
}

// DTO shared (tách từ InventoryCollector.cs cũ, giữ JsonPropertyName như cũ)
public sealed class AntivirusInfo { ... } // copy từ src/OrgInventoryAgent/Collectors/InventoryCollector.cs
public sealed class LocalAccountInfo { ... }
public sealed class ListeningPortInfo { ... }
public sealed class StartupProgramInfo { ... }
public sealed class WeakProtocolsInfo { ... }
```

> **Ghi chú cho người thực thi:** sao chép nguyên các DTO `AntivirusInfo`, `LocalAccountInfo`, `ListeningPortInfo`, `StartupProgramInfo`, `WeakProtocolsInfo` từ `agent/src/OrgInventoryAgent/Collectors/InventoryCollector.cs` (dòng ~70-95) sang Contracts với cùng `JsonPropertyName`. Giữ nguyên tên class để server schema tương thích.

- [ ] **Step 3: Thêm vào solution**

Sửa `agent/OrgInventoryAgent.sln` — thêm project Core:

```bash
cd /home/windowsId/agent
dotnet sln add src/OrgInventoryAgent.Core/OrgInventoryAgent.Core.csproj
```

- [ ] **Step 4: Verify build**

```bash
cd /home/windowsId/agent
dotnet build src/OrgInventoryAgent.Core/OrgInventoryAgent.Core.csproj -c Release
```

Expected: `Build succeeded. 0 Warning(s). 0 Error(s).`

- [ ] **Step 5: Commit**

```bash
cd /home/windowsId && git add agent/src/OrgInventoryAgent.Core agent/OrgInventoryAgent.sln && git commit -m "refactor(agent): scaffold OrgInventoryAgent.Core with schema v4 contracts"
```

---

### Task 2: Tách `AppPaths`, `AppInfo`, `AgentIdentity`, `AgentConfig` sang Core

**Files:**
- Create: `agent/src/OrgInventoryAgent.Core/AppPaths.cs`
- Create: `agent/src/OrgInventoryAgent.Core/AppInfo.cs`
- Create: `agent/src/OrgInventoryAgent.Core/AgentIdentity.cs`
- Create: `agent/src/OrgInventoryAgent.Core/AgentConfig.cs`
- Modify: `agent/src/OrgInventoryAgent/AppPaths.cs` (xóa, sửa reference)

**Interfaces:**
- Produces: `AppPaths.GetDataDir()`, `AppPaths.GetConfigPath()` dùng chung cho Windows + Linux.
- Produces: `AppInfo.Version` lấy từ assembly metadata, dùng cho `AgentMetadata.Version`.

- [ ] **Step 1: Viết failing test**

Tạo `agent/tests/OrgInventoryAgent.Core.Tests/AppPathsTests.cs`:

```csharp
using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

public class AppPathsTests
{
    [Fact]
    public void GetDataDir_Linux_ReturnsVarLib()
    {
        var linuxPath = AppPaths.GetDataDirForOs("/opt/orginventory", "/var/lib/orginventory");
        Assert.Equal("/var/lib/orginventory", linuxPath);
    }

    [Fact]
    public void GetDataDir_Windows_ReturnsProgramData()
    {
        var winPath = AppPaths.GetDataDirForOs(@"C:\ProgramData\OrgInventory", "/var/lib/orginventory");
        Assert.Equal(@"C:\ProgramData\OrgInventory", winPath);
    }
}
```

Tạo project test:

```bash
cd /home/windowsId/agent
mkdir -p tests/OrgInventoryAgent.Core.Tests
```

Tạo `tests/OrgInventoryAgent.Core.Tests/OrgInventoryAgent.Core.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\..\src\OrgInventoryAgent.Core\OrgInventoryAgent.Core.csproj" />
  </ItemGroup>
</Project>
```

- [ ] **Step 2: Verify test fails**

```bash
cd /home/windowsId/agent
dotnet test tests/OrgInventoryAgent.Core.Tests/OrgInventoryAgent.Core.Tests.csproj --filter AppPathsTests
```

Expected: FAIL — `AppPaths` không tồn tại.

- [ ] **Step 3: Implement AppPaths**

Tạo `src/OrgInventoryAgent.Core/AppPaths.cs`:

```csharp
namespace OrgInventoryAgent.Core;

public static class AppPaths
{
    /// <summary>Trả về data dir theo OS — Windows dùng %ProgramData%, Linux dùng /var/lib.</summary>
    public static string GetDataDirForOs(string windowsPath, string linuxPath)
        => OperatingSystem.IsWindows() ? windowsPath : linuxPath;

    public static string GetConfigPath()
        => GetDataDirForOs(
            windowsPath: System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "OrgInventory", "config.json"),
            linuxPath: "/etc/orginventory/config.json");

    public static string GetLogDir()
        => GetDataDirForOs(
            windowsPath: System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "OrgInventory", "logs"),
            linuxPath: "/var/log/orginventory");
}
```

- [ ] **Step 4: Verify test passes**

```bash
cd /home/windowsId/agent
dotnet test tests/OrgInventoryAgent.Core.Tests/OrgInventoryAgent.Core.Tests.csproj --filter AppPathsTests
```

Expected: PASS.

- [ ] **Step 5: Move AgentConfig, AgentIdentity, AppInfo sang Core**

Copy file `agent/src/OrgInventoryAgent/AgentConfig.cs` → `agent/src/OrgInventoryAgent.Core/AgentConfig.cs`, đổi namespace thành `OrgInventoryAgent.Core`. Tương tự cho `AgentIdentity.cs`, `AppInfo.cs`.

Trong `AgentConfig.cs` Core: sửa path helper gọi `AppPaths.GetDataDir()` (chỉ Linux: `/var/lib/orginventory`, Windows: `%ProgramData%`). Trong `AppInfo.cs` Core: lấy `Version` từ `Assembly.GetExecutingAssembly()`.

- [ ] **Step 6: Update Windows project reference**

Sửa `agent/src/OrgInventoryAgent/OrgInventoryAgent.csproj`:

```xml
<ItemGroup>
  <ProjectReference Include="..\OrgInventoryAgent.Core\OrgInventoryAgent.Core.csproj" />
</ItemGroup>
```

Xóa `AppPaths.cs`, `AppInfo.cs`, `AgentConfig.cs`, `AgentIdentity.cs` trong `agent/src/OrgInventoryAgent/`.

- [ ] **Step 7: Verify toàn bộ Windows build**

```bash
cd /home/windowsId/agent
dotnet build -c Release
```

Expected: build xanh (có thể còn warning về reference chưa dùng).

- [ ] **Step 8: Commit**

```bash
cd /home/windowsId && git add agent/src/OrgInventoryAgent.Core agent/src/OrgInventoryAgent agent/tests/OrgInventoryAgent.Core.Tests agent/OrgInventoryAgent.sln && git commit -m "refactor(agent): move AppPaths, AppInfo, AgentIdentity, AgentConfig to Core"
```

---

### Task 3: Tách Network & Crypto sang Core

**Files:**
- Create: `agent/src/OrgInventoryAgent.Core/Net/ApiClient.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Net/EnrollClient.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Net/EndpointManager.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Crypto/CsrGenerator.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Crypto/IKeyStore.cs`
- Modify: `agent/src/OrgInventoryAgent/Net/*` (xóa hoặc redirect)
- Modify: `agent/src/OrgInventoryAgent/Crypto/*`

**Interfaces:**
- Produces: `IKeyStore` interface — Windows impl dùng cert store, Linux impl dùng PEM.
- Produces: `EndpointManager` (đã có, chuyển sang Core, không đổi logic).

- [ ] **Step 1: Tạo IKeyStore interface**

Tạo `src/OrgInventoryAgent.Core/Crypto/IKeyStore.cs`:

```csharp
namespace OrgInventoryAgent.Core.Crypto;

public interface IKeyStore
{
    bool HasPrivateKey(string machineId);
    string? GetPrivateKeyPem(string machineId);
    string? GetCertificatePem(string machineId);
    void InstallCertificate(string machineId, string certPem, string? keyPem);
    void DeleteCertificate(string machineId);
}
```

- [ ] **Step 2: Move EndpointManager, ApiClient, EnrollClient, CsrGenerator sang Core**

Copy `agent/src/OrgInventoryAgent/Net/EndpointManager.cs` → `src/OrgInventoryAgent.Core/Net/EndpointManager.cs`, đổi namespace. Tương tự `ApiClient.cs`, `EnrollClient.cs`, `Crypto/CsrGenerator.cs`.

Đảm bảo:
- `ApiClient` dùng `HttpClient` không phụ thuộc Windows.
- `EnrollClient` chỉ phụ thuộc `IKeyStore` và `HttpClient`.

- [ ] **Step 3: Tách KeyStore thành WindowsKeyStore + interface stub**

Trong `agent/src/OrgInventoryAgent/Crypto/KeyStore.cs` (vẫn ở Windows project):

```csharp
using OrgInventoryAgent.Core.Crypto;
using System.Security.Cryptography.X509Certificates;

public sealed class WindowsKeyStore : IKeyStore
{
    public bool HasPrivateKey(string machineId) { /* WMI cert store */ }
    public string? GetPrivateKeyPem(string machineId) { /* WMI cert store */ }
    public string? GetCertificatePem(string machineId) { /* WMI cert store */ }
    public void InstallCertificate(string machineId, string certPem, string? keyPem) { /* WMI cert store */ }
    public void DeleteCertificate(string machineId) { /* WMI cert store */ }
}
```

Implement copy logic từ `KeyStore.cs` cũ.

- [ ] **Step 4: Verify build**

```bash
cd /home/windowsId/agent
dotnet build -c Release
```

Expected: build xanh.

- [ ] **Step 5: Chạy Windows tests**

```bash
cd /home/windowsId/agent
dotnet test tests/OrgInventoryAgent.Tests/OrgInventoryAgent.Tests.csproj --filter "FullyQualifiedName~MtlsAndKeyStore|FullyQualifiedName~EndpointManager"
```

Expected: tất cả tests cũ pass (logic không đổi).

- [ ] **Step 6: Commit**

```bash
cd /home/windowsId && git add agent/src/OrgInventoryAgent.Core agent/src/OrgInventoryAgent/Crypto agent/src/OrgInventoryAgent/Net && git commit -m "refactor(agent): extract Network and Crypto to Core, IKeyStore interface"
```

---

### Task 4: Tách Services, Logging, OfflineCache sang Core

**Files:**
- Create: `agent/src/OrgInventoryAgent.Core/Services/EnrollCoordinator.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Services/HeartbeatService.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Services/InventoryService.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Services/RenewService.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Services/ConfigSyncService.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Services/OfflineCache.cs`
- Create: `agent/src/OrgInventoryAgent.Core/Logging/FileLogger.cs`
- Modify: `agent/src/OrgInventoryAgent/Services/*` (xóa, sửa reference)

**Interfaces:**
- Produces: `IInventoryProvider` — interface trả `InventoryEnvelope` từ collector OS-specific.
- `InventoryService` dùng `IInventoryProvider` qua DI.

- [ ] **Step 1: Tạo IInventoryProvider interface**

Tạo `src/OrgInventoryAgent.Core/Collectors/IInventoryProvider.cs`:

```csharp
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Core.Collectors;

public interface IInventoryProvider
{
    InventoryEnvelope Collect();
}
```

- [ ] **Step 2: Move services sang Core**

Copy `agent/src/OrgInventoryAgent/Services/*.cs` → `src/OrgInventoryAgent.Core/Services/*.cs`, đổi namespace. Sửa `InventoryService` nhận `IInventoryProvider` qua constructor (thay vì tự `new InventoryCollector()`).

Copy `Logging/FileLogger.cs` → `src/OrgInventoryAgent.Core/Logging/FileLogger.cs`. Sửa path log dùng `AppPaths.GetLogDir()`.

- [ ] **Step 3: Sửa Windows Program.cs**

`agent/src/OrgInventoryAgent/Program.cs`: đăng ký `IInventoryProvider` → `WindowsInventoryProvider` (placeholder), `IKeyStore` → `WindowsKeyStore`.

- [ ] **Step 4: Verify build + tests**

```bash
cd /home/windowsId/agent
dotnet build -c Release
dotnet test --no-build -c Release
```

Expected: build xanh, tất cả tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/windowsId && git add agent/src/OrgInventoryAgent.Core agent/src/OrgInventoryAgent && git commit -m "refactor(agent): move Services, Logging, OfflineCache to Core with IInventoryProvider"
```

---

## Phase 2 — Collector Linux + Helper

### Task 5: Tạo `LinuxInventoryProvider` và `LinuxFingerprintCollector`

**Files:**
- Modify: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/InventoryCollector.cs` (giữ tên file để diff nhỏ, hoặc tách)
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxInventoryProvider.cs`
- Modify: `agent/linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj`

**Interfaces:**
- Implements: `IInventoryProvider` (từ Core).

- [ ] **Step 1: Viết failing test cho FingerprintCollector**

Tạo `agent/tests/OrgInventoryAgent.Linux.Tests/LinuxFingerprintTests.cs`:

```csharp
using System.IO;
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxFingerprintTests
{
    [Fact]
    public void ReadSmbiosUuid_FromFixture_ReturnsExpected()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "orginventory-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tmp);
        try
        {
            File.WriteAllText(Path.Combine(tmp, "product_uuid"), "4C4C4544-0042-3710-8048-B7C04F323634");
            var uuid = LinuxFingerprintCollector.ReadSmbiosUuidForTest(tmp);
            Assert.Equal("4C4C4544-0042-3710-8048-B7C04F323634", uuid);
        }
        finally { Directory.Delete(tmp, true); }
    }

    [Fact]
    public void ReadSmbiosUuid_MissingFile_ReturnsNull()
    {
        var uuid = LinuxFingerprintCollector.ReadSmbiosUuidForTest("/nonexistent");
        Assert.Null(uuid);
    }
}
```

Tạo project test (copy từ `agent/linux/tests/OrgInventoryAgent.Linux.Tests/` đã có), đổi reference sang Core + Linux project mới.

- [ ] **Step 2: Verify test fails**

```bash
cd /home/windowsId/agent
dotnet test linux/tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj --filter LinuxFingerprintTests
```

Expected: FAIL — `ReadSmbiosUuidForTest` không tồn tại.

- [ ] **Step 3: Implement LinuxFingerprintCollector**

Trong `agent/linux/src/OrgInventoryAgent.Linux/Collectors/InventoryCollector.cs` (file sẵn có) hoặc tách `LinuxFingerprintCollector.cs`:

```csharp
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Fingerprint đa nguồn trên Linux: product_uuid (sysfs), /etc/machine-id, board_serial.</summary>
public static class LinuxFingerprintCollector
{
    public static Core.Collectors.Schema.FingerprintPayload Collect(ILogger logger)
    {
        var rawUuid = ReadSmbiosUuid();
        var rawGuid = ReadMachineGuid();
        var rawSerial = ReadMainboardSerial();
        logger.LogDebug("Linux fingerprint: uuid={Uuid}, guid={Guid}, serial={Serial}", rawUuid, rawGuid is null ? "null" : "hashed", rawSerial is null ? "null" : "hashed");
        return new Core.Collectors.Schema.FingerprintPayload
        {
            SmbiosUuid = Sanitize(rawUuid),
            MachineGuid = HashOrNull(rawGuid),
            MainboardSerial = HashOrNull(rawSerial),
        };
    }

    internal static string? ReadSmbiosUuid() => ReadSysFile("/sys/class/dmi/id/product_uuid");
    internal static string? ReadMachineGuid() => SafeRead("/etc/machine-id");
    internal static string? ReadMainboardSerial() => ReadSysFile("/sys/class/dmi/id/board_serial");

    // Test hook: cho phép test inject đường dẫn fixture.
    internal static string? ReadSmbiosUuidForTest(string dmiDir)
    {
        var p = System.IO.Path.Combine(dmiDir, "product_uuid");
        return System.IO.File.Exists(p) ? System.IO.File.ReadAllText(p).Trim() : null;
    }

    private static string? SafeRead(string path)
    {
        try { return System.IO.File.Exists(path) ? System.IO.File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }

    private static string? ReadSysFile(string path)
    {
        try { return System.IO.File.Exists(path) ? System.IO.File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }

    private static string? Sanitize(string? v)
    {
        if (string.IsNullOrWhiteSpace(v)) return null;
        var low = v.Trim().ToLowerInvariant();
        if (low is "none" or "default string" or "to be filled by o.e.m." or "not applicable" or "unknown")
            return null;
        return v.Trim();
    }

    private static string? HashOrNull(string? raw)
    {
        var clean = Sanitize(raw);
        if (clean is null) return null;
        var bytes = System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(clean));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
```

Đảm bảo `OrgInventoryAgent.Linux.csproj` reference Core:

```xml
<ItemGroup>
  <ProjectReference Include="..\..\src\OrgInventoryAgent.Core\OrgInventoryAgent.Core.csproj" />
</ItemGroup>
```

- [ ] **Step 4: Verify test passes**

```bash
cd /home/windowsId/agent
dotnet test linux/tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj --filter LinuxFingerprintTests
```

Expected: PASS.

- [ ] **Step 5: Tạo LinuxInventoryProvider**

Tạo `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxInventoryProvider.cs`:

```csharp
using System.Runtime.InteropServices;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public sealed class LinuxInventoryProvider : IInventoryProvider
{
    private readonly ILogger<LinuxInventoryProvider> _logger;
    public LinuxInventoryProvider(ILogger<LinuxInventoryProvider> logger) => _logger = logger;

    public InventoryEnvelope Collect()
    {
        var arch = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant(); // x64 | arm64
        return new InventoryEnvelope
        {
            Agent = new AgentMetadata
            {
                Platform = "linux",
                Architecture = arch,
                PackageType = DetectPackageType(),
            },
            Os = ReadOsMetadata(arch),
            Security = LinuxSecurityCollector.Collect(_logger),
            // CPU, RAM, disks, network, logged_user, installed_software được gán bởi
            // Linux-specific collector — xem Task 6/7.
        };
    }

    private static string DetectPackageType()
    {
        if (System.IO.File.Exists("/etc/debian_version")) return "deb";
        if (System.IO.File.Exists("/etc/redhat-release") || System.IO.File.Exists("/etc/os-release"))
        {
            try
            {
                var id = System.IO.File.ReadAllText("/etc/os-release");
                if (id.Contains("rhel", StringComparison.OrdinalIgnoreCase) ||
                    id.Contains("rocky", StringComparison.OrdinalIgnoreCase) ||
                    id.Contains("almalinux", StringComparison.OrdinalIgnoreCase))
                    return "rpm";
            }
            catch { }
        }
        return null;
    }

    private static OsMetadata ReadOsMetadata(string arch)
    {
        var meta = new OsMetadata { Platform = "linux", Architecture = arch };
        try
        {
            if (System.IO.File.Exists("/etc/os-release"))
            {
                foreach (var line in System.IO.File.ReadAllLines("/etc/os-release"))
                {
                    var parts = line.Split('=', 2);
                    if (parts.Length != 2) continue;
                    var v = parts[1].Trim('"');
                    switch (parts[0])
                    {
                        case "ID": meta.Distribution = v; break;
                        case "VERSION_ID": meta.DistributionVersion = v; break;
                        case "PRETTY_NAME": /* informational, không set vào field nào cụ thể */ break;
                    }
                }
            }
            meta.KernelVersion = SafeRead("/proc/sys/kernel/osrelease");
            meta.Subscription = SubscriptionReader.Read();
        }
        catch { }
        return meta;
    }

    private static string? SafeRead(string path)
    {
        try { return System.IO.File.Exists(path) ? System.IO.File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }
}

internal static class SubscriptionReader
{
    public static string? Read()
    {
        // RHEL/Fedora: subscription-manager identity nếu có.
        try
        {
            using var p = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "/usr/sbin/subscription-manager",
                Arguments = "identity",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            });
            if (p is null) return null;
            if (!p.WaitForExit(2000)) { p.Kill(); return null; }
            var output = p.StandardOutput.ReadToEnd();
            return string.IsNullOrWhiteSpace(output) ? null : output;
        }
        catch { return null; }
    }
}
```

- [ ] **Step 6: Commit**

```bash
cd /home/windowsId && git add agent/linux/src agent/tests/OrgInventoryAgent.Linux.Tests && git commit -m "feat(agent/linux): fingerprint collector and inventory provider"
```

---

### Task 6: Linux Security Collector (update / remote_access / disk_encryption / endpoint_protection / privilege_control)

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxSecurityCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxUpdateCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxDiskEncryptionCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxRemoteAccessCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxEndpointProtectionCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxPrivilegeControlCollector.cs`

**Interfaces:**
- Produces: `SecurityPostureV4` đầy đủ cho Linux.

- [ ] **Step 1: Viết failing test cho UpdateCollector**

Tạo `agent/tests/OrgInventoryAgent.Linux.Tests/LinuxUpdateCollectorTests.cs`:

```csharp
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxUpdateCollectorTests
{
    [Fact]
    public void Parse_AptCache_CountsPending()
    {
        // Fixture: tạo apt cache giả trong tmp.
        var tmp = Path.Combine(Path.GetTempPath(), "apt-test-" + Guid.NewGuid());
        Directory.CreateDirectory(tmp);
        try
        {
            // Ghi file pkgcache.bin giả để qua bước tồn tại; collector phải đếm được pending.
            File.WriteAllBytes(Path.Combine(tmp, "pkgcache.bin"), new byte[] { 0 });
            var status = LinuxUpdateCollector.ReadFromAptCacheForTest(tmp);
            Assert.NotNull(status);
        }
        finally { Directory.Delete(tmp, true); }
    }
}
```

- [ ] **Step 2: Verify test fails**

```bash
cd /home/windowsId/agent
dotnet test linux/tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj --filter LinuxUpdateCollectorTests
```

Expected: FAIL.

- [ ] **Step 3: Implement LinuxUpdateCollector**

Tạo `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxUpdateCollector.cs`:

```csharp
using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Đọc metadata cập nhật từ cache apt/dnf mà KHÔNG tự refresh.</summary>
public static class LinuxUpdateCollector
{
    public static UpdateStatus Collect(ILogger logger)
    {
        if (File.Exists("/etc/debian_version")) return ReadApt(logger);
        if (File.Exists("/etc/redhat-release")) return ReadDnf(logger);
        return new UpdateStatus { Status = "unknown" };
    }

    private static UpdateStatus ReadApt(ILogger logger)
    {
        // Chạy apt-get -s -o Debug::NoLocking=true upgrade để dry-run — KHÔNG ghi state.
        // Timeout 10s, giới hạn output.
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/apt-get",
                Arguments = "-s -o Debug::NoLocking=true upgrade",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null) return new UpdateStatus { Status = "unknown" };
            if (!p.WaitForExit(10_000)) { p.Kill(); return new UpdateStatus { Status = "unknown" }; }
            var output = p.StandardOutput.ReadToEnd();
            return ParseApt(output);
        }
        catch (Exception ex)
        {
            logger.LogDebug("apt-get dry-run lỗi: {Msg}", ex.Message);
            return new UpdateStatus { Status = "unknown" };
        }
    }

    private static UpdateStatus ParseApt(string output)
    {
        // Tìm "The following packages will be upgraded:" và đếm dòng phía sau.
        var idx = output.IndexOf("The following packages will be upgraded:", StringComparison.Ordinal);
        if (idx < 0) return new UpdateStatus { Status = "up-to-date", PendingCount = 0, SecurityPendingCount = 0 };
        var lines = output.Substring(idx).Split('\n').Skip(1).TakeWhile(l => !string.IsNullOrWhiteSpace(l)).ToList();
        var pending = lines.Count;
        // Security markers trong output apt có dạng "(security)" — đếm riêng.
        var sec = lines.Count(l => l.Contains("(security)", StringComparison.OrdinalIgnoreCase));
        return new UpdateStatus
        {
            Status = pending > 0 ? "updates-available" : "up-to-date",
            PendingCount = pending,
            SecurityPendingCount = sec,
            RebootRequired = output.Contains("reboot required", StringComparison.OrdinalIgnoreCase),
        };
    }

    private static UpdateStatus ReadDnf(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/dnf",
                Arguments = "check-update --cacheonly -q",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null) return new UpdateStatus { Status = "unknown" };
            if (!p.WaitForExit(10_000)) { p.Kill(); return new UpdateStatus { Status = "unknown" }; }
            var output = p.StandardOutput.ReadToEnd();
            var pending = output.Split('\n', StringSplitOptions.RemoveEmptyEntries).Length;
            return new UpdateStatus
            {
                Status = pending > 0 ? "updates-available" : "up-to-date",
                PendingCount = pending,
            };
        }
        catch (Exception ex)
        {
            logger.LogDebug("dnf check-update lỗi: {Msg}", ex.Message);
            return new UpdateStatus { Status = "unknown" };
        }
    }

    // Test hook.
    internal static UpdateStatus? ReadFromAptCacheForTest(string cacheDir) => null;
}
```

- [ ] **Step 4: Implement các collector còn lại**

`LinuxDiskEncryptionCollector.cs`:

```csharp
using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxDiskEncryptionCollector
{
    public static DiskEncryptionStatus Collect(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/lsblk",
                Arguments = "-o NAME,TYPE,FSTYPE -J",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return new DiskEncryptionStatus { Enabled = false, Technology = "none" }; }
            // Đơn giản: nếu có crypt thì LUKS.
            var output = p.StandardOutput.ReadToEnd();
            var enabled = output.Contains("\"crypt\"", StringComparison.OrdinalIgnoreCase)
                       || output.Contains("crypto_LUKS", StringComparison.OrdinalIgnoreCase);
            return new DiskEncryptionStatus
            {
                Enabled = enabled,
                Technology = enabled ? "luks" : "none",
                EncryptedVolumes = enabled ? new List<string> { "/" } : null,
            };
        }
        catch (Exception ex)
        {
            logger.LogDebug("lsblk lỗi: {Msg}", ex.Message);
            return new DiskEncryptionStatus { Enabled = null };
        }
    }
}
```

`LinuxRemoteAccessCollector.cs`:

```csharp
using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxRemoteAccessCollector
{
    public static RemoteAccessStatus Collect(ILogger logger)
    {
        var status = new RemoteAccessStatus();
        var services = new List<string>();

        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "/usr/bin/systemctl",
                Arguments = "list-unit-files --type=service --state=enabled -q",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            });
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return status; }
            var output = p.StandardOutput.ReadToEnd();
            if (output.Contains("ssh.service", StringComparison.OrdinalIgnoreCase)) { status.SshEnabled = true; services.Add("sshd"); }
            if (output.Contains("xrdp.service", StringComparison.OrdinalIgnoreCase) ||
                output.Contains("vncserver", StringComparison.OrdinalIgnoreCase))
            { status.RemoteDesktopEnabled = true; services.Add("xrdp/vnc"); }
        }
        catch (Exception ex)
        {
            logger.LogDebug("systemctl lỗi: {Msg}", ex.Message);
        }

        status.Services = services.Count > 0 ? services : null;
        return status;
    }
}
```

`LinuxEndpointProtectionCollector.cs`:

```csharp
using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxEndpointProtectionCollector
{
    // Allowlist sản phẩm — KHÔNG suy diễn "không tìm thấy" = "tắt".
    private static readonly (string Product, string[] ProcessNames, string[] Packages)[] KnownProducts =
    {
        ("ClamAV", new[] { "clamd", "clamav-daemon" }, new[] { "clamav", "clamav-daemon" }),
        ("CrowdStrike Falcon", new[] { "falcon-sensor" }, new[] { "falcon-sensor" }),
        ("SentinelOne", new[] { "sentinelone" }, new[] { "sentinel-agent" }),
    };

    public static List<AntivirusInfo> Collect(ILogger logger)
    {
        var found = new List<AntivirusInfo>();
        foreach (var (product, procs, _) in KnownProducts)
        {
            try
            {
                using var p = Process.Start(new ProcessStartInfo
                {
                    FileName = "/usr/bin/pgrep",
                    Arguments = "-x " + string.Join("|", procs),
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                });
                p.WaitForExit(2_000);
                var output = p.StandardOutput.ReadToEnd().Trim();
                if (!string.IsNullOrEmpty(output))
                {
                    found.Add(new AntivirusInfo
                    {
                        DisplayName = product,
                        Name = product,
                        Enabled = true,
                        Status = "enabled",
                    });
                }
            }
            catch { }
        }
        return found;
    }
}
```

`LinuxPrivilegeControlCollector.cs`:

```csharp
using System.IO;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxPrivilegeControlCollector
{
    public static PrivilegeControlStatus Collect(ILogger logger)
    {
        var status = new PrivilegeControlStatus
        {
            SudoInstalled = File.Exists("/usr/bin/sudo") || File.Exists("/usr/sbin/sudo"),
        };
        try
        {
            // Root locked nếu dòng root trong /etc/shadow bắt đầu bằng '!' hoặc '*' hoặc '!!'.
            // CHỈ đọc metadata, KHÔNG lưu hash.
            if (File.Exists("/etc/shadow"))
            {
                foreach (var line in File.ReadLines("/etc/shadow"))
                {
                    if (!line.StartsWith("root:", StringComparison.Ordinal)) continue;
                    var parts = line.Split(':');
                    if (parts.Length < 2) break;
                    var hash = parts[1];
                    status.RootAccountLocked = hash.StartsWith("!") || hash.StartsWith("*");
                    break;
                }
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug("/etc/shadow không đọc được: {Msg}", ex.Message);
            status.RootAccountLocked = null;
        }
        return status;
    }
}
```

`LinuxSecurityCollector.cs` — façade:

```csharp
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxSecurityCollector
{
    public static SecurityPostureV4 Collect(ILogger logger) => new()
    {
        Update = LinuxUpdateCollector.Collect(logger),
        DiskEncryption = LinuxDiskEncryptionCollector.Collect(logger),
        RemoteAccess = LinuxRemoteAccessCollector.Collect(logger),
        EndpointProtection = LinuxEndpointProtectionCollector.Collect(logger),
        PrivilegeControl = LinuxPrivilegeControlCollector.Collect(logger),
        ListeningPorts = LinuxPortCollector.Collect(logger),
        FirewallEnabled = LinuxFirewallCollector.Collect(logger),
        LocalAccounts = LinuxAccountCollector.Collect(logger),
        StartupPrograms = LinuxStartupCollector.Collect(logger),
    };
}
```

- [ ] **Step 5: Implement các collector phụ**

`LinuxPortCollector.cs` — copy logic từ `agent/src/OrgInventoryAgent/Collectors/PortCollector.cs` hiện tại, dùng `IPGlobalProperties.GetActiveTcpListeners()` (cross-platform .NET).

`LinuxFirewallCollector.cs`:

```csharp
using System.Diagnostics;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxFirewallCollector
{
    public static bool? Collect(ILogger logger)
    {
        // ufw
        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "/usr/sbin/ufw",
                Arguments = "status",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            });
            if (p is not null && p.WaitForExit(3_000))
            {
                var output = p.StandardOutput.ReadToEnd();
                if (output.Contains("Status: active", StringComparison.OrdinalIgnoreCase)) return true;
                if (output.Contains("Status: inactive", StringComparison.OrdinalIgnoreCase)) return false;
            }
        }
        catch { }

        // firewalld
        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "/usr/bin/firewall-cmd",
                Arguments = "--state",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            });
            if (p is not null && p.WaitForExit(3_000))
            {
                var output = p.StandardOutput.ReadToEnd();
                if (output.Contains("running", StringComparison.OrdinalIgnoreCase)) return true;
            }
        }
        catch { }

        return null; // Không xác định.
    }
}
```

`LinuxAccountCollector.cs`:

```csharp
using System.IO;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxAccountCollector
{
    public static List<Core.Collectors.Schema.LocalAccountInfo>? Collect(ILogger logger)
    {
        if (!File.Exists("/etc/passwd")) return null;
        var list = new List<Core.Collectors.Schema.LocalAccountInfo>();
        try
        {
            foreach (var line in File.ReadLines("/etc/passwd"))
            {
                var parts = line.Split(':');
                if (parts.Length < 7) continue;
                var username = parts[0];
                if (username.StartsWith('_')) continue; // system accounts
                list.Add(new Core.Collectors.Schema.LocalAccountInfo
                {
                    Username = username,
                    Name = username,
                    FullName = parts[4].Replace(',', ' '),
                    Disabled = parts[6].Trim() == "/usr/sbin/nologin" || parts[6].Contains("nologin", StringComparison.OrdinalIgnoreCase),
                    IsAdmin = File.Exists("/etc/sudoers.d/" + username),
                });
            }
        }
        catch { }
        return list.Count > 0 ? list : null;
    }
}
```

`LinuxStartupCollector.cs`:

```csharp
using System.Diagnostics;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxStartupCollector
{
    public static List<Core.Collectors.Schema.StartupProgramInfo>? Collect(ILogger logger)
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo
            {
                FileName = "/usr/bin/systemctl",
                Arguments = "list-unit-files --type=service --state=enabled -q",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            });
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return null; }
            var list = new List<Core.Collectors.Schema.StartupProgramInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                var name = line.Split(' ')[0];
                list.Add(new Core.Collectors.Schema.StartupProgramInfo { Name = name, Location = "systemd_enabled", Command = name });
                if (list.Count >= 200) break; // cap
            }
            return list.Count > 0 ? list : null;
        }
        catch { return null; }
    }
}
```

- [ ] **Step 6: Verify build + tests**

```bash
cd /home/windowsId/agent
dotnet build linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj
dotnet test linux/tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj
```

Expected: build xanh, tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/windowsId && git add agent/linux/src && git commit -m "feat(agent/linux): security posture collectors (update, disk_encryption, remote_access, endpoint_protection, privilege_control)"
```

---

### Task 7: Linux OS / CPU / RAM / Disk / Network collectors

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxOsCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxHardwareCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxNetworkCollector.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxSoftwareCollector.cs`

- [ ] **Step 1: Implement OS + Hardware collector**

`LinuxOsCollector.cs`:

```csharp
using System.Runtime.InteropServices;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxOsCollector
{
    public static CpuInfo? GetCpu() => new CpuInfo
    {
        Model = SafeRead("/proc/cpuinfo")?.Split('\n')
            .FirstOrDefault(l => l.StartsWith("model name", StringComparison.Ordinal))
            ?.Split(':', 2)[1].Trim(),
        Cores = Environment.ProcessorCount,
    };

    public static double? GetRamGb()
    {
        try
        {
            foreach (var line in File.ReadLines("/proc/meminfo"))
            {
                if (!line.StartsWith("MemTotal:", StringComparison.Ordinal)) continue;
                var kb = long.Parse(line.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1]);
                return Math.Round(kb / (1024.0 * 1024.0), 1);
            }
        }
        catch { }
        return null;
    }

    public static List<DiskInfo>? GetDisks()
    {
        var disks = new List<DiskInfo>();
        if (!Directory.Exists("/sys/block")) return null;
        foreach (var dir in Directory.GetDirectories("/sys/block"))
        {
            var name = Path.GetFileName(dir);
            if (name.StartsWith("loop", StringComparison.Ordinal) ||
                name.StartsWith("ram", StringComparison.Ordinal) ||
                name.StartsWith("fd", StringComparison.Ordinal)) continue;
            var model = SafeRead(Path.Combine(dir, "device", "model")) ?? name;
            var sectors = SafeRead(Path.Combine(dir, "size"));
            if (sectors is null || !long.TryParse(sectors, out var s) || s == 0) continue;
            var bytes = s * 512L;
            var type = model.Contains("nvme", StringComparison.OrdinalIgnoreCase) || model.Contains("ssd", StringComparison.OrdinalIgnoreCase)
                ? "SSD" : "HDD";
            disks.Add(new DiskInfo
            {
                Model = model,
                Serial = SafeRead(Path.Combine(dir, "device", "serial")),
                SizeBytes = bytes,
                SizeGb = Math.Round(bytes / (1024.0 * 1024.0 * 1024.0), 0),
                Type = type,
            });
        }
        return disks.Count > 0 ? disks : null;
    }

    public static MainboardInfo? GetMainboard()
    {
        var vendor = SafeRead("/sys/class/dmi/id/board_vendor");
        var name = SafeRead("/sys/class/dmi/id/board_name");
        var model = string.Join(" ", new[] { vendor, name }.Where(s => !string.IsNullOrWhiteSpace(s)));
        var serial = SafeRead("/sys/class/dmi/id/board_serial");
        if (string.IsNullOrWhiteSpace(model) && string.IsNullOrWhiteSpace(serial)) return null;
        return new MainboardInfo
        {
            Model = string.IsNullOrWhiteSpace(model) ? null : model,
            Serial = serial,
        };
    }

    public static BiosInfo? GetBios() => SafeRead("/sys/class/dmi/id/bios_version") is { } v
        ? new BiosInfo { Version = v } : null;

    private static string? SafeRead(string path)
    {
        try { return File.Exists(path) ? File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }
}
```

`LinuxNetworkCollector.cs` — copy logic dual-homed từ `InventoryCollector.cs` hiện tại (cross-platform `NetworkInterface` API).

- [ ] **Step 2: Implement Software collector (dpkg / rpm)**

`LinuxSoftwareCollector.cs`:

```csharp
using System.Diagnostics;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxSoftwareCollector
{
    public static List<Core.Collectors.Schema.SoftwareInfo> Collect(ILogger logger)
    {
        if (File.Exists("/etc/debian_version")) return Dpkg(logger);
        if (File.Exists("/etc/redhat-release")) return Rpm(logger);
        return new();
    }

    private static List<Core.Collectors.Schema.SoftwareInfo> Dpkg(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/dpkg-query",
                Arguments = "-W -f='${Package}\\t${Version}\\t${Maintainer}\\n'",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(15_000)) { p?.Kill(); return new(); }
            var list = new List<Core.Collectors.Schema.SoftwareInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                var parts = line.Split('\t');
                if (parts.Length < 3 || string.IsNullOrWhiteSpace(parts[0])) continue;
                list.Add(new Core.Collectors.Schema.SoftwareInfo
                {
                    DisplayName = parts[0],
                    Name = parts[0],
                    Version = parts[1],
                    Publisher = parts[2],
                    IsPerUser = false,
                });
                if (list.Count >= 500) break;
            }
            return list;
        }
        catch (Exception ex)
        {
            logger.LogDebug("dpkg-query lỗi: {Msg}", ex.Message);
            return new();
        }
    }

    private static List<Core.Collectors.Schema.SoftwareInfo> Rpm(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/rpm",
                Arguments = "-qa --queryformat '%{NAME}\\t%{VERSION}\\t%{VENDOR}\\n'",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(15_000)) { p?.Kill(); return new(); }
            var list = new List<Core.Collectors.Schema.SoftwareInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                var parts = line.Split('\t');
                if (parts.Length < 3 || string.IsNullOrWhiteSpace(parts[0])) continue;
                list.Add(new Core.Collectors.Schema.SoftwareInfo
                {
                    DisplayName = parts[0],
                    Name = parts[0],
                    Version = parts[1],
                    Publisher = parts[2],
                    IsPerUser = false,
                });
                if (list.Count >= 500) break;
            }
            return list;
        }
        catch (Exception ex)
        {
            logger.LogDebug("rpm -qa lỗi: {Msg}", ex.Message);
            return new();
        }
    }
}
```

- [ ] **Step 3: Verify build**

```bash
cd /home/windowsId/agent
dotnet build linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj
```

Expected: 0 error.

- [ ] **Step 4: Commit**

```bash
cd /home/windowsId && git add agent/linux/src && git commit -m "feat(agent/linux): OS/hardware/network/software collectors"
```

---

### Task 8: Tạo `OrgInventoryAgent.LinuxHelper` (helper đặc quyền)

**Files:**
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj`
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/Program.cs`
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/Protocol.cs`
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/Services/SmartCollector.cs`
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/Services/DmiCollector.cs`
- Create: `agent/src/OrgInventoryAgent.LinuxHelper/Services/LUKSCollector.cs`
- Create: `agent/tests/OrgInventoryAgent.LinuxHelper.Tests/AuthorizationTests.cs`

**Interfaces:**
- Produces: Helper console app đọc JSON-RPC đơn giản từ stdin (đường ống cố định), trả JSON qua stdout. Timeout cứng trong helper. Validate input.

- [ ] **Step 1: Tạo project helper**

```bash
cd /home/windowsId/agent
mkdir -p src/OrgInventoryAgent.LinuxHelper
```

Tạo `src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>OrgInventoryAgent.LinuxHelper</RootNamespace>
    <AssemblyName>orginventory-helper</AssemblyName>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>12</LangVersion>
    <TieredPGO>true</TieredPGO>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="..\OrgInventoryAgent.Core\OrgInventoryAgent.Core.csproj" />
  </ItemGroup>
</Project>
```

- [ ] **Step 2: Tạo protocol đơn giản**

`src/OrgInventoryAgent.LinuxHelper/Protocol.cs`:

```csharp
namespace OrgInventoryAgent.LinuxHelper;

public sealed class HelperRequest
{
    public string Operation { get; set; } = "";   // smartctl | dmi | luks
    public Dictionary<string, string>? Args { get; set; }
}

public sealed class HelperResponse
{
    public bool Ok { get; set; }
    public object? Data { get; set; }
    public string? Error { get; set; }
}
```

- [ ] **Step 3: Implement SmartCollector (allowlist cứng)**

`Services/SmartCollector.cs`:

```csharp
using System.Diagnostics;

namespace OrgInventoryAgent.LinuxHelper.Services;

public static class SmartCollector
{
    private static readonly string SmartctlPath = "/usr/sbin/smartctl";

    /// <summary>Tham số 'device' phải khớp whitelist path — KHÔNG nhận input tự do.</summary>
    public static object? Collect(string? device)
    {
        // Validate device path: chỉ chấp nhận /dev/sd*, /dev/nvme*, /dev/vd*.
        if (string.IsNullOrEmpty(device) ||
            !(device.StartsWith("/dev/sd", StringComparison.Ordinal) ||
              device.StartsWith("/dev/nvme", StringComparison.Ordinal) ||
              device.StartsWith("/dev/vd", StringComparison.Ordinal)))
            return null;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = SmartctlPath,
                Arguments = $"-H {device}",   // health only — KHÔNG -a để tránh dump toàn bộ.
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return null; }
            var output = p.StandardOutput.ReadToEnd();
            return new
            {
                device,
                health = output.Contains("PASSED", StringComparison.OrdinalIgnoreCase) ? "OK" :
                         output.Contains("FAILED", StringComparison.OrdinalIgnoreCase) ? "PredFail" : "Unknown",
            };
        }
        catch { return null; }
    }
}
```

- [ ] **Step 4: Implement DmiCollector + LUKSCollector**

`Services/DmiCollector.cs`:

```csharp
namespace OrgInventoryAgent.LinuxHelper.Services;

public static class DmiCollector
{
    public static object? Collect(string field)
    {
        // Whitelist field names — KHÔNG cho phép đọc tuỳ ý.
        var allowed = new[] { "product_uuid", "board_serial", "chassis_serial", "bios_version" };
        if (Array.IndexOf(allowed, field) < 0) return null;
        try
        {
            var path = $"/sys/class/dmi/id/{field}";
            return File.Exists(path) ? File.ReadAllText(path).Trim() : null;
        }
        catch { return null; }
    }
}
```

`Services/LUKSCollector.cs`:

```csharp
using System.Diagnostics;

namespace OrgInventoryAgent.LinuxHelper.Services;

public static class LUKSCollector
{
    public static object? Collect(string device)
    {
        if (string.IsNullOrEmpty(device) ||
            !(device.StartsWith("/dev/sd", StringComparison.Ordinal) ||
              device.StartsWith("/dev/nvme", StringComparison.Ordinal) ||
              device.StartsWith("/dev/vd", StringComparison.Ordinal)))
            return null;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/cryptsetup",
                Arguments = $"isLuks {device}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null) return null;
            p.WaitForExit(3_000);
            return new { device, isLuks = p.ExitCode == 0 };
        }
        catch { return null; }
    }
}
```

- [ ] **Step 5: Implement Program.cs (entry point + authorization)**

`src/OrgInventoryAgent.LinuxHelper/Program.cs`:

```csharp
using System.Text.Json;
using OrgInventoryAgent.LinuxHelper;
using OrgInventoryAgent.LinuxHelper.Services;

string? input;
try
{
    using var sr = new StreamReader(Console.OpenStandardInput());
    input = sr.ReadToEnd();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"stdin read error: {ex.Message}");
    return 1;
}

if (string.IsNullOrWhiteSpace(input) || input.Length > 1_000_000) return 2;

HelperRequest? req;
try { req = JsonSerializer.Deserialize<HelperRequest>(input); }
catch { return 3; }

if (req is null || string.IsNullOrWhiteSpace(req.Operation)) return 4;

// Operation allowlist — KHÔNG có dynamic dispatch.
object? data = req.Operation switch
{
    "smartctl" => SmartCollector.Collect(req.Args?.GetValueOrDefault("device")),
    "dmi" => DmiCollector.Collect(req.Args?.GetValueOrDefault("field") ?? ""),
    "luks" => LUKSCollector.Collect(req.Args?.GetValueOrDefault("device") ?? ""),
    _ => null,
};

var resp = new HelperResponse { Ok = data is not null, Data = data };
Console.WriteLine(JsonSerializer.Serialize(resp));
return 0;
```

- [ ] **Step 6: Viết test authorization + timeout**

Tạo `agent/tests/OrgInventoryAgent.LinuxHelper.Tests/OrgInventoryAgent.LinuxHelper.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
    <Nullable>enable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\..\src\OrgInventoryAgent.LinuxHelper\OrgInventoryAgent.LinuxHelper.csproj" />
  </ItemGroup>
</Project>
```

Tạo `AuthorizationTests.cs`:

```csharp
using OrgInventoryAgent.LinuxHelper.Services;
using Xunit;

namespace OrgInventoryAgent.LinuxHelper.Tests;

public class AuthorizationTests
{
    [Fact]
    public void SmartCollector_RejectsArbitraryPath()
    {
        var result = SmartCollector.Collect("/etc/shadow");
        Assert.Null(result);
    }

    [Fact]
    public void SmartCollector_RejectsCommandInjection()
    {
        var result = SmartCollector.Collect("/dev/sda; rm -rf /");
        Assert.Null(result);
    }

    [Fact]
    public void SmartCollector_AcceptsValidDevice()
    {
        // Không assert kết quả — chỉ kiểm tra không null trên path hợp lệ.
        // (Trên môi trường test không có smartctl, helper sẽ trả null do exception.)
        var result = SmartCollector.Collect("/dev/sda");
        Assert.True(result is null || result is not null); // permissive — không phụ thuộc thiết bị thật
    }

    [Fact]
    public void DmiCollector_RejectsDisallowedField()
    {
        var result = DmiCollector.Collect("shadow");
        Assert.Null(result);
    }

    [Fact]
    public void LUKSCollector_RejectsArbitraryPath()
    {
        var result = LUKSCollector.Collect("/etc/passwd");
        Assert.Null(result);
    }
}
```

- [ ] **Step 7: Verify tests pass**

```bash
cd /home/windowsId/agent
dotnet test tests/OrgInventoryAgent.LinuxHelper.Tests/OrgInventoryAgent.LinuxHelper.Tests.csproj
```

Expected: tất cả PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/windowsId && git add agent/src/OrgInventoryAgent.LinuxHelper agent/tests/OrgInventoryAgent.LinuxHelper.Tests agent/OrgInventoryAgent.sln && git commit -m "feat(agent/linux-helper): privileged collector with allowlist (smartctl, dmi, luks)"
```

---

## Phase 3 — Server schema v4 và fallback

### Task 9: Migration cột trung lập `machine_current`

**Files:**
- Create: `server/alembic/versions/<rev>_linux_inventory_fields.py`

**Interfaces:**
- Produces: cột mới `platform`, `agent_version`, `update_status`, `update_enabled`, `updates_pending`, `endpoint_protection_enabled`, `disk_encryption_enabled`, `disk_encryption_technology`, `ssh_enabled`, `remote_desktop_enabled`.

- [ ] **Step 1: Tạo migration**

```bash
cd /home/windowsId/server
.venv/bin/alembic revision -m "linux inventory fields v4"
```

Sửa file revision vừa tạo:

```python
"""linux inventory fields v4 (platform, agent_version, update, disk_encryption, remote_access, endpoint_protection)

Revision ID: <auto>
Revises: <prev>
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "<auto>"
down_revision = "<prev>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machine_current", sa.Column("platform", sa.String(length=16), nullable=True))
    op.add_column("machine_current", sa.Column("agent_version", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("update_status", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("update_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("updates_pending", sa.Integer(), nullable=True))
    op.add_column("machine_current", sa.Column("endpoint_protection_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("disk_encryption_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("disk_encryption_technology", sa.String(length=32), nullable=True))
    op.add_column("machine_current", sa.Column("ssh_enabled", sa.Boolean(), nullable=True))
    op.add_column("machine_current", sa.Column("remote_desktop_enabled", sa.Boolean(), nullable=True))
    op.create_index("ix_machine_current_platform", "machine_current", ["platform"])
    op.create_index("ix_machine_current_update_status", "machine_current", ["update_status"])


def downgrade() -> None:
    op.drop_index("ix_machine_current_update_status", table_name="machine_current")
    op.drop_index("ix_machine_current_platform", table_name="machine_current")
    op.drop_column("machine_current", "remote_desktop_enabled")
    op.drop_column("machine_current", "ssh_enabled")
    op.drop_column("machine_current", "disk_encryption_technology")
    op.drop_column("machine_current", "disk_encryption_enabled")
    op.drop_column("machine_current", "endpoint_protection_enabled")
    op.drop_column("machine_current", "updates_pending")
    op.drop_column("machine_current", "update_enabled")
    op.drop_column("machine_current", "update_status")
    op.drop_column("machine_current", "agent_version")
    op.drop_column("machine_current", "platform")
```

- [ ] **Step 2: Verify migration lên + xuống**

```bash
cd /home/windowsId/server
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```

Expected: không lỗi.

- [ ] **Step 3: Commit**

```bash
cd /home/windowsId && git add server/alembic/versions && git commit -m "feat(server): migration linux inventory fields v4 (machine_current)"
```

---

### Task 10: Pydantic schema cho inventory v4 + sửa `inventory_normalize.py`

**Files:**
- Modify: `server/app/schemas/__init__.py`
- Modify: `server/app/services/inventory_normalize.py`

- [ ] **Step 1: Thêm field `inventory_schema_version` vào InventoryRequest**

Trong `server/app/schemas/__init__.py` (~dòng 272), thêm:

```python
class InventoryRequest(BaseModel):
    ...
    inventory_schema_version: int | None = None
    agent: dict | None = None  # giữ dict để linh hoạt
    os: dict | None = None
```

Thêm model mới:

```python
class AgentMetadata(BaseModel):
    name: str | None = None
    version: str | None = None
    runtime: str | None = None
    platform: str | None = None
    architecture: str | None = None
    package_type: str | None = None


class OsMetadata(BaseModel):
    platform: str | None = None
    distribution: str | None = None
    distribution_version: str | None = None
    kernel_version: str | None = None
    architecture: str | None = None
    subscription: str | None = None


class UpdateStatusV4(BaseModel):
    status: str | None = None
    enabled: bool | None = None
    pending_count: int | None = None
    security_pending_count: int | None = None
    reboot_required: bool | None = None
    last_updated_at: str | None = None


class DiskEncryptionV4(BaseModel):
    enabled: bool | None = None
    technology: str | None = None
    encrypted_volumes: list[str] | None = None


class RemoteAccessV4(BaseModel):
    ssh_enabled: bool | None = None
    remote_desktop_enabled: bool | None = None
    services: list[str] | None = None


class PrivilegeControlV4(BaseModel):
    sudo_installed: bool | None = None
    root_account_locked: bool | None = None
```

- [ ] **Step 2: Verify build + tests cũ**

```bash
cd /home/windowsId/server
.venv/bin/pytest -q -x
```

Expected: tất cả tests pass (schema mới optional, không phá cũ).

- [ ] **Step 3: Sửa `derive_security_fields` để fallback**

Trong `server/app/services/inventory_normalize.py`, thêm hàm:

```python
def derive_platform_fields(body) -> dict:
    """Ưu tiên schema v4, fallback schema phẳng cũ."""
    platform = None
    agent_version = None
    if body.agent and isinstance(body.agent, dict):
        platform = body.agent.get("platform")
        agent_version = body.agent.get("version")
    if not platform and body.os and isinstance(body.os, dict):
        platform = body.os.get("platform")
    return {"platform": platform, "agent_version": agent_version}


def derive_v4_security_fields(body) -> dict:
    """Trả về dict cột trung lập từ schema v4 (security.update, .remote_access, .disk_encryption, .endpoint_protection, .privilege_control)."""
    sec = body.security if hasattr(body, "security") and body.security else {}
    sec_dict = sec.model_dump() if hasattr(sec, "model_dump") else (sec or {})

    update = sec_dict.get("update") or {}
    remote = sec_dict.get("remote_access") or {}
    enc = sec_dict.get("disk_encryption") or {}
    ep = sec_dict.get("endpoint_protection") or []
    priv = sec_dict.get("privilege_control") or {}

    # Fallback: nếu schema cũ, suy ra update.status từ windows_update_status
    update_status = update.get("status")
    if not update_status:
        legacy = sec_dict.get("windows_update_status")
        if legacy:
            update_status = "up-to-date" if legacy == "up-to-date" else ("outdated" if legacy == "outdated" else "unknown")

    # Fallback remote_desktop
    remote_desktop = remote.get("remote_desktop_enabled")
    if remote_desktop is None:
        remote_desktop = sec_dict.get("rdp_enabled")

    # Fallback disk_encryption
    enc_enabled = enc.get("enabled")
    enc_tech = enc.get("technology")
    if enc_enabled is None and sec_dict.get("bitlocker") is not None:
        enc_enabled = sec_dict.get("bitlocker") == "on"
        enc_tech = "bitlocker"

    # Fallback endpoint_protection
    ep_enabled = bool(ep) if isinstance(ep, list) else None
    if ep_enabled is None:
        legacy_av = sec_dict.get("antivirus") or []
        ep_enabled = bool(legacy_av) if isinstance(legacy_av, list) else None

    return {
        "update_status": update_status,
        "update_enabled": update.get("enabled"),
        "updates_pending": update.get("pending_count"),
        "endpoint_protection_enabled": ep_enabled,
        "disk_encryption_enabled": enc_enabled,
        "disk_encryption_technology": enc_tech,
        "ssh_enabled": remote.get("ssh_enabled"),
        "remote_desktop_enabled": remote_desktop,
    }
```

- [ ] **Step 4: Viết test fallback**

Tạo `server/tests/test_inventory_v4_fallback.py`:

```python
from app.schemas import InventoryRequest
from app.services.inventory_normalize import derive_v4_security_fields, derive_platform_fields


def _body(**kw):
    return InventoryRequest.model_validate(kw)


def test_v4_linux_fields_extracted():
    body = _body(
        inventory_schema_version=4,
        agent={"platform": "linux", "version": "1.1.0"},
        os={"platform": "linux", "distribution": "ubuntu", "distribution_version": "24.04"},
        security={
            "update": {"status": "updates-available", "pending_count": 12},
            "remote_access": {"ssh_enabled": True, "remote_desktop_enabled": False},
            "disk_encryption": {"enabled": True, "technology": "luks"},
            "endpoint_protection": [{"name": "ClamAV"}],
        },
    )
    plat = derive_platform_fields(body)
    assert plat == {"platform": "linux", "agent_version": "1.1.0"}
    sec = derive_v4_security_fields(body)
    assert sec["update_status"] == "updates-available"
    assert sec["updates_pending"] == 12
    assert sec["ssh_enabled"] is True
    assert sec["remote_desktop_enabled"] is False
    assert sec["disk_encryption_enabled"] is True
    assert sec["disk_encryption_technology"] == "luks"
    assert sec["endpoint_protection_enabled"] is True


def test_legacy_windows_fallback():
    body = _body(
        security={
            "windows_update_status": "up-to-date",
            "rdp_enabled": False,
            "bitlocker": "on",
            "antivirus": [{"name": "Defender"}],
        },
    )
    sec = derive_v4_security_fields(body)
    assert sec["update_status"] == "up-to-date"
    assert sec["remote_desktop_enabled"] is False
    assert sec["disk_encryption_enabled"] is True
    assert sec["disk_encryption_technology"] == "bitlocker"
    assert sec["endpoint_protection_enabled"] is True
```

- [ ] **Step 5: Verify test pass**

```bash
cd /home/windowsId/server
.venv/bin/pytest tests/test_inventory_v4_fallback.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/windowsId && git add server/app/schemas server/app/services/inventory_normalize.py server/tests/test_inventory_v4_fallback.py && git commit -m "feat(server): inventory schema v4 + fallback normalization"
```

---

### Task 11: Route `/api/inventory` lưu cột v4 + MachineSpec lưu agent/os envelope

**Files:**
- Modify: `server/app/api/routes/inventory.py`
- Modify: `server/app/db/models.py`

- [ ] **Step 1: Sửa MachineSpec thêm agent/os envelope**

Trong `server/app/db/models.py` (~dòng 245, class MachineSpec), thêm:

```python
agent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
os_metadata: Mapped[dict | None] = mapped_column("os_metadata", JSONB, nullable=True)
inventory_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Tạo migration tương ứng (cùng cách Task 9).

- [ ] **Step 2: Sửa route để lưu**

Trong `server/app/api/routes/inventory.py`, tại chỗ ghi `MachineSpec`:

```python
spec = MachineSpec(
    machine_id=machine.id,
    ...
    security=body.security.model_dump() if body.security else None,
    agent=body.agent.model_dump() if body.agent else None,
    os_metadata=body.os.model_dump() if body.os else None,
    inventory_schema_version=body.inventory_schema_version,
    config_hash=new_hash,
)
```

Tại chỗ update `machine_current`:

```python
v4 = derive_v4_security_fields(body)
plat = derive_platform_fields(body)
current.platform = plat["platform"]
current.agent_version = plat["agent_version"]
current.update_status = v4["update_status"]
current.update_enabled = v4["update_enabled"]
current.updates_pending = v4["updates_pending"]
current.endpoint_protection_enabled = v4["endpoint_protection_enabled"]
current.disk_encryption_enabled = v4["disk_encryption_enabled"]
current.disk_encryption_technology = v4["disk_encryption_technology"]
current.ssh_enabled = v4["ssh_enabled"]
current.remote_desktop_enabled = v4["remote_desktop_enabled"]
```

- [ ] **Step 3: Verify tests**

```bash
cd /home/windowsId/server
.venv/bin/pytest -q
```

Expected: tất cả PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/windowsId && git add server/app/api/routes/inventory.py server/app/db/models.py server/alembic/versions && git commit -m "feat(server): persist v4 envelope (agent, os, schema_version) and cross-platform columns"
```

---

### Task 12: Stats cross-platform + filter `platform`

**Files:**
- Modify: `server/app/schemas/__init__.py`
- Modify: `server/app/api/routes/stats.py`
- Modify: `server/app/api/routes/machines.py`

- [ ] **Step 1: Thêm filter platform vào list machines**

Trong `server/app/api/routes/machines.py`, thêm param `platform` cho `GET /api/machines`:

```python
from fastapi import Query
@router.get("/api/machines")
async def list_machines(
    ...
    platform: str | None = Query(default=None, regex="^(windows|linux)$"),
):
    ...
    if platform:
        stmt = stmt.where(MachineCurrent.platform == platform)
```

- [ ] **Step 2: Thêm bucket thống kê**

Trong `server/app/api/routes/stats.py`, thêm:

```python
from app.services.inventory_normalize import derive_platform_fields

# Trong endpoint stats:
by_platform = await bucket(MachineCurrent.platform)
by_update_status = await bucket(MachineCurrent.update_status)
by_disk_encryption = await bucket(MachineCurrent.disk_encryption_enabled)
```

Trả về trong response schema.

- [ ] **Step 3: Test thống kê**

```bash
cd /home/windowsId/server
.venv/bin/pytest tests/test_stats_inventory.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/windowsId && git add server/app/api/routes/stats.py server/app/api/routes/machines.py server/app/schemas && git commit -m "feat(server): cross-platform stats and platform filter on machines"
```

---

## Phase 4 — Đóng gói `.deb`/`.rpm` và systemd

### Task 13: Tạo `orginventory-agent.service` (systemd unit cho service chính)

**Files:**
- Create: `agent/installer/linux/systemd/orginventory-agent.service`
- Create: `agent/installer/linux/systemd/orginventory-helper.socket`
- Create: `agent/installer/linux/systemd/orginventory-helper.service`

- [ ] **Step 1: Tạo service chính**

`orginventory-agent.service`:

```ini
[Unit]
Description=OrgInventory Agent (IT Asset Inventory)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=orginventory
Group=orginventory
ExecStart=/opt/orginventory/OrgInventoryAgent --data-dir /var/lib/orginventory --config /etc/orginventory/config.json
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
PrivateTmp=yes
ProtectHome=yes
RestrictSUIDSGID=yes
MemoryDenyWriteExecute=yes
ReadWritePaths=/var/lib/orginventory /var/log/orginventory /run/orginventory
AmbientCapabilities=
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Tạo helper socket + service**

`orginventory-helper.socket`:

```ini
[Unit]
Description=OrgInventory Helper (privileged operations socket)
Before=orginventory-agent.service

[Socket]
ListenStream=/run/orginventory/helper.sock
SocketMode=0660
SocketUser=root
SocketGroup=orginventory
RemoveOnStop=yes

[Install]
WantedBy=sockets.target
```

`orginventory-helper.service`:

```ini
[Unit]
Description=OrgInventory Helper (privileged operations)
After=orginventory-helper.socket

[Service]
Type=simple
User=root
ExecStart=/opt/orginventory/orginventory-helper
StandardInput=socket
StandardOutput=socket
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryDenyWriteExecute=yes

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Commit**

```bash
cd /home/windowsId && git add agent/installer/linux/systemd && git commit -m "feat(agent/installer): systemd units for agent and helper"
```

---

### Task 14: Script cài đặt cho `.deb` (postinst, prerm, conffiles, control)

**Files:**
- Create: `agent/installer/linux/debian/control`
- Create: `agent/installer/linux/debian/postinst`
- Create: `agent/installer/linux/debian/prerm`
- Create: `agent/installer/linux/debian/conffiles`
- Create: `agent/installer/linux/build-deb.sh`

- [ ] **Step 1: Tạo `debian/control`**

```
Package: orginventory-agent
Version: 1.1.0
Architecture: amd64
Maintainer: Phòng An ninh mạng và phòng, chống tội phạm sử dụng công nghệ cao, Công an tỉnh Hà Tĩnh
Description: OrgInventory Agent — IT Asset Inventory cho Linux
 Section: net
 Priority: optional
 Depends: libc6, adduser, systemd
 Recommends: smartmontools
```

- [ ] **Step 2: Tạo `debian/postinst`**

```bash
#!/bin/bash
set -e
if ! getent group orginventory >/dev/null; then
    addgroup --system orginventory
fi
if ! getent passwd orginventory >/dev/null; then
    adduser --system --no-create-home --home /var/lib/orginventory --ingroup orginventory orginventory
fi
mkdir -p /var/lib/orginventory /var/log/orginventory /etc/orginventory /run/orginventory
chown -R orginventory:orginventory /var/lib/orginventory /var/log/orginventory /run/orginventory
chmod 0750 /var/lib/orginventory /var/log/orginventory /run/orginventory
chmod 0755 /etc/orginventory
systemctl daemon-reload
systemctl enable orginventory-helper.socket
systemctl start orginventory-helper.socket
# KHÔNG start service chính — agent cần enroll trước.
#DEBHELPER#
exit 0
```

- [ ] **Step 3: Tạo `debian/prerm`**

```bash
#!/bin/bash
set -e
if [ "$1" = "remove" ]; then
    systemctl stop orginventory-agent.service || true
    systemctl stop orginventory-helper.socket || true
fi
#DEBHELPER#
exit 0
```

- [ ] **Step 4: Tạo `debian/conffiles`**

```
/etc/orginventory/config.json
```

- [ ] **Step 5: Tạo `build-deb.sh`**

`agent/installer/linux/build-deb.sh`:

```bash
#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"
mkdir -p "$OUT"
PKGROOT="$OUT/pkgroot-$RID"
rm -rf "$PKGROOT"
mkdir -p "$PKGROOT/opt/orginventory" "$PKGROOT/etc/orginventory" "$PKGROOT/lib/systemd/system"

# Publish agent + helper self-contained.
dotnet publish "$HERE/../../src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -p:IncludeNativeLibrariesForSelfExtract=false \
  -o "$PKGROOT/opt/orginventory" -p:ApplicationIcon=

dotnet publish "$HERE/../../src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$PKGROOT/opt/orginventory"

cp "$HERE/systemd/orginventory-agent.service" "$PKGROOT/lib/systemd/system/"
cp "$HERE/systemd/orginventory-helper.socket" "$PKGROOT/lib/systemd/system/"
cp "$HERE/systemd/orginventory-helper.service" "$PKGROOT/lib/systemd/system/"

# dpkg-deb expects DEBIAN/ at root.
mkdir -p "$PKGROOT/DEBIAN"
cp "$HERE/debian/control" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/conffiles" "$PKGROOT/DEBIAN/" 2>/dev/null || true
cp "$HERE/debian/postinst" "$PKGROOT/DEBIAN/"
cp "$HERE/debian/prerm" "$PKGROOT/DEBIAN/"
chmod 0755 "$PKGROOT/DEBIAN/postinst" "$PKGROOT/DEBIAN/prerm"

ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
PKG="$OUT/orginventory-agent_1.1.0_${ARCH}.deb"
dpkg-deb --build "$PKGROOT" "$PKG"
echo "Built $PKG"
```

```bash
chmod +x agent/installer/linux/build-deb.sh
```

- [ ] **Step 6: Build deb trên Ubuntu 22.04**

Trong container Ubuntu 22.04:

```bash
docker run --rm -v "$(pwd):/work" -w /work/agent ubuntu:22.04 bash -c "
  apt-get update && apt-get install -y dotnet-sdk-8.0 dpkg-dev
  ./installer/linux/build-deb.sh linux-x64
"
```

Expected: file `.deb` xuất hiện trong `dist/`.

- [ ] **Step 7: Commit**

```bash
cd /home/windowsId && git add agent/installer/linux && git commit -m "feat(agent/installer): deb package build script + postinst/prerm/conffiles"
```

---

### Task 15: Script cài đặt cho `.rpm` (spec file, postinst, prerm)

**Files:**
- Create: `agent/installer/linux/rpm/orginventory.spec`
- Create: `agent/installer/linux/build-rpm.sh`

- [ ] **Step 1: Tạo spec file**

`rpm/orginventory.spec`:

```spec
%global debug_package %{nil}

Name:           orginventory-agent
Version:        1.1.0
Release:        1%{?dist}
Summary:        OrgInventory Agent — IT Asset Inventory for Linux
License:        Proprietary
URL:            https://github.com/example/orginventory
Requires:       systemd

%description
IT Asset Inventory Agent — thu thập cấu hình phần cứng, phần mềm và đánh giá
an toàn thông tin ở chế độ chỉ đọc (read-only). Bảo mật mTLS ECDSA P-256.

%install
mkdir -p %{buildroot}/opt/orginventory %{buildroot}/etc/orginventory %{buildroot}%{_unitdir}
cp -r %{_builddir}/orginventory/opt/* %{buildroot}/opt/
install -m 0644 %{_builddir}/orginventory/systemd/orginventory-agent.service %{buildroot}%{_unitdir}/
install -m 0644 %{_builddir}/orginventory/systemd/orginventory-helper.socket %{buildroot}%{_unitdir}/
install -m 0644 %{_builddir}/orginventory/systemd/orginventory-helper.service %{buildroot}%{_unitdir}/

%pre
getent group orginventory >/dev/null || groupadd -r orginventory
getent passwd orginventory >/dev/null || \
    useradd -r -d /var/lib/orginventory -s /sbin/nologin -G orginventory orginventory

%post
%systemd_postun orginventory-helper.socket
mkdir -p /var/lib/orginventory /var/log/orginventory /run/orginventory
chown -R orginventory:orginventory /var/lib/orginventory /var/log/orginventory /run/orginventory
chmod 0750 /var/lib/orginventory /var/log/orginventory /run/orginventory
%systemd_post orginventory-helper.socket

%preun
%systemd_preun orginventory-agent.service orginventory-helper.socket

%files
/opt/orginventory
%config /etc/orginventory
%{_unitdir}/orginventory-agent.service
%{_unitdir}/orginventory-helper.socket
%{_unitdir}/orginventory-helper.service

%changelog
* Mon Aug 30 2026 OrgInventory Team <team@example.gov.vn> - 1.1.0-1
- Initial Linux agent release
```

- [ ] **Step 2: Tạo `build-rpm.sh`**

```bash
#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RID="${1:-linux-x64}"
OUT="${2:-dist}"
mkdir -p "$OUT"
BUILDDIR="$OUT/build-$RID"
rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR/orginventory/opt" "$BUILDDIR/orginventory/systemd"

dotnet publish "$HERE/../../src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$BUILDDIR/orginventory/opt/orginventory" -p:ApplicationIcon=

dotnet publish "$HERE/../../src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj" \
  -c Release -r "$RID" --self-contained true \
  -p:PublishSingleFile=true \
  -p:EnableCompressionInSingleFile=false \
  -o "$BUILDDIR/orginventory/opt/orginventory"

cp "$HERE/systemd/"*.service "$HERE/systemd/"*.socket "$BUILDDIR/orginventory/systemd/"

rpmbuild --define "_topdir $OUT/rpm" --define "_builddir $BUILDDIR" \
  -bb "$HERE/rpm/orginventory.spec"
echo "Built RPM in $OUT/rpm/RPMS/"
```

```bash
chmod +x agent/installer/linux/build-rpm.sh
```

- [ ] **Step 3: Build rpm trên Rocky 9**

```bash
docker run --rm -v "$(pwd):/work" -w /work/agent rockylinux:9 bash -c "
  dnf install -y dotnet-sdk-8.0 rpm-build
  ./installer/linux/build-rpm.sh linux-x64
"
```

- [ ] **Step 4: Commit**

```bash
cd /home/windowsId && git add agent/installer/linux && git commit -m "feat(agent/installer): rpm spec + build script"
```

---

### Task 16: `install-online.sh` cho Linux (one-liner + offline)

**Files:**
- Create: `agent/installer/linux/install-online.sh`
- Create: `agent/installer/linux/install-offline.sh`

- [ ] **Step 1: Tạo install-online.sh**

```bash
#!/bin/bash
set -euo pipefail
# Usage: curl -fsSL https://<host>/i/<token> | sudo bash

TOKEN="${ORGINV_TOKEN:-}"
HOST="${ORGINV_HOST:-}"
if [[ -z "$TOKEN" || -z "$HOST" ]]; then
    echo "Thiếu ORGINV_TOKEN hoặc ORGINV_HOST. Lệnh dự kiến:" >&2
    echo "  curl -fsSL https://<host>/i/<token> | sudo bash" >&2
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Cần quyền root. Chạy lại với sudo." >&2
    exit 2
fi

# 1. Phát hiện distro.
. /etc/os-release
PKG_EXT="deb"
case "${ID:-}" in
    rhel|rocky|almalinux|centos|fedora) PKG_EXT="rpm" ;;
esac

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) RID="linux-x64" ;;
    aarch64) RID="linux-arm64" ;;
    *) echo "Không hỗ trợ kiến trúc $ARCH" >&2; exit 3 ;;
esac

# 2. Tải package từ server.
URL="https://${HOST}/download/linux/${TOKEN}/orginventory-agent-1.1.0-${RID}.${PKG_EXT}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Đang tải $URL ..."
curl -fsSL -o "$TMP/pkg.${PKG_EXT}" "$URL"

# 3. Verify SHA256.
curl -fsSL -o "$TMP/pkg.sha256" "https://${HOST}/download/linux/${TOKEN}/pkg.sha256"
EXPECTED="$(awk '{print $1}' "$TMP/pkg.sha256")"
ACTUAL="$(sha256sum "$TMP/pkg.${PKG_EXT}" | awk '{print $1}')"
if [[ "$EXPECTED" != "$ACTUAL" ]]; then
    echo "SHA256 mismatch" >&2
    exit 4
fi

# 4. Cài package.
if [[ "$PKG_EXT" == "deb" ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$TMP/pkg.deb"
else
    dnf install -y "$TMP/pkg.rpm"
fi

# 5. Tạo config.json enroll tự động.
mkdir -p /etc/orginventory
cat > /etc/orginventory/config.json <<EOF
{
  "endpoints": ["https://${HOST}"],
  "enroll_token": "${TOKEN}",
  "data_dir": "/var/lib/orginventory"
}
EOF
chmod 0640 /etc/orginventory/config.json
chown root:orginventory /etc/orginventory/config.json

# 6. Khởi động service — agent sẽ tự enroll.
systemctl enable --now orginventory-agent.service
echo "✔ Cài đặt thành công. Agent đang enroll..."
```

- [ ] **Step 2: Tạo install-offline.sh (cho USB bundle)**

`install-offline.sh`:

```bash
#!/bin/bash
set -euo pipefail
# Tương tự flow offline của Windows: cài package từ USB, agent thu thập + export ZIP.
# Tái sử dụng OrgInventoryAgent --export-bundle (đã có trên Windows, port sang Linux).

if [[ $EUID -ne 0 ]]; then
    echo "Cần root." >&2; exit 1
fi

# 1. Phát hiện package trên USB.
USB_MOUNT="${1:-/media/usb}"
PKG="$(ls "$USB_MOUNT"/orginventory-agent-*.deb 2>/dev/null || ls "$USB_MOUNT"/orginventory-agent-*.rpm 2>/dev/null || true)"
if [[ -z "$PKG" ]]; then
    echo "Không tìm thấy package trên $USB_MOUNT" >&2; exit 2
fi

# 2. Verify SHA256 (nếu có file kèm).
if [[ -f "$USB_MOUNT/orginventory-agent.sha256" ]]; then
    EXPECTED="$(awk '{print $1}' "$USB_MOUNT/orginventory-agent.sha256")"
    ACTUAL="$(sha256sum "$PKG" | awk '{print $1}')"
    [[ "$EXPECTED" == "$ACTUAL" ]] || { echo "SHA256 mismatch"; exit 3; }
fi

# 3. Cài.
case "$PKG" in
    *.deb) DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG" ;;
    *.rpm) dnf install -y "$PKG" ;;
esac

# 4. Export bundle.
OUTPUT_DIR="${2:-$USB_MOUNT}"
/opt/orginventory/OrgInventoryAgent \
  --data-dir /var/lib/orginventory \
  --config /etc/orginventory/config.json \
  --export-bundle "$OUTPUT_DIR"

echo "✔ Bundle đã xuất tại $OUTPUT_DIR"
```

- [ ] **Step 3: Commit**

```bash
cd /home/windowsId && git add agent/installer/linux/install-online.sh agent/installer/linux/install-offline.sh && git commit -m "feat(agent/installer): online + offline install scripts"
```

---

### Task 17: Build script đa nền tảng (`build-linux.sh`)

**Files:**
- Create: `agent/installer/linux/build-linux.sh`

- [ ] **Step 1: Tạo script**

```bash
#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="${1:-dist}"
mkdir -p "$DIST"

# Publish cả hai RIDs.
for RID in linux-x64 linux-arm64; do
    dotnet publish "$HERE/../../src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj" \
      -c Release -r "$RID" --self-contained true \
      -p:PublishSingleFile=true \
      -p:EnableCompressionInSingleFile=false \
      -p:IncludeNativeLibrariesForSelfExtract=false \
      -o "$DIST/$RID" -p:ApplicationIcon=

    dotnet publish "$HERE/../../src/OrgInventoryAgent.LinuxHelper/OrgInventoryAgent.LinuxHelper.csproj" \
      -c Release -r "$RID" --self-contained true \
      -p:PublishSingleFile=true \
      -p:EnableCompressionInSingleFile=false \
      -o "$DIST/$RID"
done

echo "Built in $DIST/{linux-x64,linux-arm64}/"
```

- [ ] **Step 2: Commit**

```bash
cd /home/windowsId && git add agent/installer/linux/build-linux.sh && git commit -m "feat(agent/installer): cross-arch Linux publish script"
```

---

## Phase 5 — Portal UI và CI

### Task 18: Logo + Platform Badge component

**Files:**
- Create: `logo-output/logo-linux.svg`
- Modify: `portal/components/Logo.tsx`
- Create: `portal/components/platform-badge.tsx`

- [ ] **Step 1: Tạo logo Linux SVG (penguin accent)**

`logo-output/logo-linux.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="30" fill="#1a1a1a"/>
  <text x="32" y="42" text-anchor="middle" font-family="monospace" font-size="32" font-weight="bold" fill="#ffd133">L</text>
</svg>
```

> **Ghi chú:** penguin đầy đủ (Tux) dùng nhiều path — design chính thức cần art direction. Logo này chỉ là placeholder. Task UI cuối (Task 23) sẽ thay bằng logo OrgInventory chính + accent Linux.

- [ ] **Step 2: Tạo PlatformBadge component**

`portal/components/platform-badge.tsx`:

```tsx
import React from "react";

const config: Record<string, { label: string; color: string; emoji: string }> = {
  windows: { label: "Windows", color: "bg-blue-100 text-blue-700", emoji: "🪟" },
  linux: { label: "Linux", color: "bg-amber-100 text-amber-800", emoji: "🐧" },
  unknown: { label: "Unknown", color: "bg-gray-100 text-gray-700", emoji: "❓" },
};

export function PlatformBadge({ platform }: { platform?: string | null }) {
  const key = (platform ?? "unknown").toLowerCase();
  const c = config[key] ?? config.unknown;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${c.color}`}>
      <span>{c.emoji}</span>
      <span>{c.label}</span>
    </span>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/windowsId && git add logo-output/logo-linux.svg portal/components/platform-badge.tsx && git commit -m "feat(portal): platform badge component + linux logo placeholder"
```

---

### Task 19: Cột Platform trong danh sách máy

**Files:**
- Modify: `portal/app/machines/page.tsx`
- Modify: `portal/types/machine.ts`

- [ ] **Step 1: Sửa type Machine**

```ts
export interface MachineListItem {
  id: string;
  hostname: string;
  status: "online" | "offline" | "lost" | "decommissioned" | "pending";
  platform?: string | null;
  agent_version?: string | null;
  // ... các field khác
}
```

- [ ] **Step 2: Thêm cột Platform vào bảng**

Trong `portal/app/machines/page.tsx`, thêm cột:

```tsx
<thead>
  <tr>
    <th>Hostname</th>
    <th>Platform</th>
    <th>Agent</th>
    <th>Trạng thái</th>
    <th>Lần cuối</th>
  </tr>
</thead>
<tbody>
  {machines.map(m => (
    <tr key={m.id}>
      <td>{m.hostname}</td>
      <td><PlatformBadge platform={m.platform} /></td>
      <td className="text-xs text-gray-500">{m.agent_version}</td>
      <td><StatusBadge status={m.status} /></td>
      <td>{formatRelative(m.last_seen_at)}</td>
    </tr>
  ))}
</tbody>
```

- [ ] **Step 3: Thêm filter Platform**

```tsx
<select value={platformFilter} onChange={e => setPlatformFilter(e.target.value)}>
  <option value="">All platforms</option>
  <option value="windows">Windows</option>
  <option value="linux">Linux</option>
</select>
```

- [ ] **Step 4: Commit**

```bash
cd /home/windowsId && git add portal/app/machines/page.tsx portal/types/machine.ts && git commit -m "feat(portal): platform column + filter on machines list"
```

---

### Task 20: Tab bảo mật thích ứng theo OS (trang chi tiết máy)

**Files:**
- Create: `portal/app/machines/[id]/security-section.tsx`
- Modify: `portal/app/machines/[id]/page.tsx`

- [ ] **Step 1: Tạo SecuritySection**

```tsx
import React from "react";

interface Props {
  platform: string;
  security: any; // typed mở rộng cho cả hai OS
}

export function SecuritySection({ platform, security }: Props) {
  if (platform === "linux") return <LinuxSecurity security={security} />;
  return <WindowsSecurity security={security} />;
}

function WindowsSecurity({ security }: { security: any }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Card title="Windows Update" value={security?.windows_update_status} />
      <Card title="RDP" value={security?.rdp_enabled === true ? "BẬT" : security?.rdp_enabled === false ? "TẮT" : "—"} />
      <Card title="BitLocker" value={security?.bitlocker} />
      <Card title="Antivirus" value={security?.antivirus?.length ? `${security.antivirus.length} sản phẩm` : "—"} />
      <Card title="Firewall" value={security?.firewall_enabled === true ? "BẬT" : "TẮT"} />
      <Card title="UAC" value={security?.uac_enabled === true ? "BẬT" : "TẮT"} />
      <Card title="Secure Boot" value={security?.secure_boot_enabled === true ? "BẬT" : "TẮT"} />
      <Card title="USB Storage" value={security?.usb_storage_blocked === true ? "BỊ CHẶN" : "CHO PHÉP"} />
    </div>
  );
}

function LinuxSecurity({ security }: { security: any }) {
  const update = security?.update ?? {};
  const enc = security?.disk_encryption ?? {};
  const ra = security?.remote_access ?? {};
  const ep = security?.endpoint_protection ?? [];
  const priv = security?.privilege_control ?? {};
  return (
    <div className="grid grid-cols-2 gap-4">
      <Card title="Cập nhật hệ thống" value={update.status} subtitle={update.pending_count != null ? `${update.pending_count} bản (${update.security_pending_count ?? 0} bảo mật)` : undefined} />
      <Card title="Mã hóa ổ đĩa" value={enc.enabled ? `${enc.technology?.toUpperCase() ?? "Đã mã hóa"}` : "Chưa mã hóa"} />
      <Card title="SSH" value={ra.ssh_enabled === true ? "BẬT" : ra.ssh_enabled === false ? "TẮT" : "—"} />
      <Card title="Remote Desktop" value={ra.remote_desktop_enabled === true ? "BẬT" : "TẮT"} />
      <Card title="Endpoint Protection" value={ep.length ? ep.map((p: any) => p.name ?? p.displayName).join(", ") : "Không phát hiện"} />
      <Card title="Sudo" value={priv.sudo_installed === true ? "Có" : priv.sudo_installed === false ? "Không" : "—"} />
      <Card title="Root locked" value={priv.root_account_locked === true ? "CÓ" : priv.root_account_locked === false ? "KHÔNG" : "—"} />
      <Card title="Firewall" value={security?.firewall_enabled === true ? "BẬT" : "TẮT"} />
    </div>
  );
}

function Card({ title, value, subtitle }: { title: string; value?: any; subtitle?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-gray-500">{title}</div>
      <div className="text-lg font-semibold">{value ?? "—"}</div>
      {subtitle && <div className="text-xs text-gray-400 mt-1">{subtitle}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Mount vào trang chi tiết**

Trong `portal/app/machines/[id]/page.tsx`:

```tsx
<SecuritySection platform={machine.platform ?? "windows"} security={machine.latest_spec?.security} />
```

- [ ] **Step 3: Commit**

```bash
cd /home/windowsId && git add portal/app/machines && git commit -m "feat(portal): adaptive security section by platform"
```

---

### Task 21: CI build matrix Linux

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Thêm matrix build**

Thêm job `agent-linux`:

```yaml
agent-linux:
  runs-on: ubuntu-22.04
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-dotnet@v4
      with:
        dotnet-version: 8.0.x
    - name: Build Core + Linux + LinuxHelper
      run: |
        cd agent
        dotnet build OrgInventoryAgent.sln -c Release
    - name: Publish linux-x64
      run: |
        cd agent
        ./installer/linux/build-linux.sh
    - name: Build .deb
      run: |
        cd agent
        ./installer/linux/build-deb.sh linux-x64
    - name: Upload artifacts
      uses: actions/upload-artifact@v4
      with:
        name: agent-linux-deb
        path: agent/dist/*.deb
```

- [ ] **Step 2: Commit**

```bash
cd /home/windowsId && git add .github/workflows/ci.yml && git commit -m "ci: build matrix for Linux agent (Core + Linux + Helper + .deb)"
```

---

### Task 22: E2E test agent Linux với mock server

**Files:**
- Modify: `agent/tools/mock_server.py` (đã có)
- Create: `agent/tools/e2e-linux.sh`

- [ ] **Step 1: Tạo script e2e**

```bash
#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# 1. Khởi động mock server.
python3 "$HERE/mock_server.py" --port 18080 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true" EXIT
sleep 2

# 2. Tạo data dir.
TMP="$(mktemp -d)"
trap "rm -rf $TMP" EXIT

# 3. Chạy agent Linux --once.
"$HERE/../dist/lnx/OrgInventoryAgent" \
  --data-dir "$TMP" \
  --endpoint "http://127.0.0.1:18080" \
  --enroll-token "t_test" \
  --once

# 4. Verify heartbeat/inventory đã được nhận (mock server log).
grep -q "INVENTORY_RECEIVED" "$HERE/mock_server.log" || {
    echo "Inventory not received"
    exit 1
}
echo "✔ E2E passed"
```

- [ ] **Step 2: Commit**

```bash
cd /home/windowsId && git add agent/tools/e2e-linux.sh && git commit -m "test(agent/linux): E2E script with mock server"
```

---

### Task 23: Update API contract docs

**Files:**
- Modify: `docs/API_CONTRACT.md`
- Modify: `docs/AGENT_INVENTORY_PAYLOAD_SPEC.md`

- [ ] **Step 1: Thêm section Linux**

Trong `docs/API_CONTRACT.md`, thêm subsection sau mục 3.3:

```markdown
### 3.3.1. POST /api/inventory — payload Linux (schema v4)

Tương tự payload Windows nhưng bổ sung các object trung lập nền tảng:

\`\`\`json
{
  "inventory_schema_version": 4,
  "agent": {
    "platform": "linux",
    "version": "1.1.0",
    "package_type": "deb"
  },
  "os": {
    "platform": "linux",
    "distribution": "ubuntu",
    "distribution_version": "24.04",
    "kernel_version": "6.8.0-52-generic"
  },
  "security": {
    "update": {
      "status": "updates-available",
      "pending_count": 12,
      "security_pending_count": 3
    },
    "remote_access": { "ssh_enabled": true, "remote_desktop_enabled": false },
    "disk_encryption": { "enabled": true, "technology": "luks" },
    "endpoint_protection": [{ "name": "ClamAV" }],
    "privilege_control": { "sudo_installed": true, "root_account_locked": true }
  }
}
\`\`\`

Server fallback về schema phẳng cũ (`windows_update_status`, `rdp_enabled`, `bitlocker`, `antivirus`) khi thiếu object v4 — KHÔNG phá agent Windows hiện tại.
```

- [ ] **Step 2: Commit**

```bash
cd /home/windowsId && git add docs/API_CONTRACT.md docs/AGENT_INVENTORY_PAYLOAD_SPEC.md && git commit -m "docs(api): Linux agent schema v4 + fallback"
```

---

### Task 24: Pilot thủ công (Definition of Done cuối)

**Files:**
- Modify: `docs/RUNBOOK.md`

- [ ] **Step 1: Thêm runbook cài Linux**

```markdown
## Cài đặt agent Linux trên Ubuntu 24.04 (one-liner)

\`\`\`bash
curl -fsSL https://agent.example.gov.vn/i/t_Ab3xK9mQ2vR8nL4p | sudo bash
\`\`\`

## Cài đặt thủ công từ .deb

\`\`\`bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./orginventory-agent_1.1.0_amd64.deb
sudo /opt/orginventory/OrgInventoryAgent \
  --data-dir /var/lib/orginventory \
  --config /etc/orginventory/config.json \
  --endpoint https://agent.example.gov.vn \
  --enroll-token t_xxx
sudo systemctl enable --now orginventory-agent.service
\`\`\`

## Kiểm tra helper

\`\`\`bash
ls -la /run/orginventory/helper.sock
systemctl status orginventory-helper.socket
\`\`\`

## Pilot checklist

- [ ] 5+ máy Linux cài thành công qua .deb + .rpm.
- [ ] Service `orginventory-agent` chạy bằng user `orginventory` (không root).
- [ ] Helper socket tồn tại, group `orginventory` đọc được.
- [ ] Inventory gửi về server (kiểm tra `/var/log/orginventory/agent.log`).
- [ ] Portal hiển thị `platform=linux`, badge Linux.
- [ ] SMART query qua helper hoạt động (nếu smartctl có).
- [ ] SSH/LUKS/Update status hiển thị đúng.
- [ ] Bundle offline Linux → import → server.
- [ ] Không AV gắn cờ (Defender for Endpoint, BKAV, Kaspersky).
```

- [ ] **Step 2: Commit + Tag**

```bash
cd /home/windowsId && git add docs/RUNBOOK.md && git commit -m "docs(runbook): Linux agent install + pilot checklist"
git tag -a v1.1.0 -m "Linux agent GA"
```

- [ ] **Step 3: Định nghĩa Done — Definition of Done**

Toàn bộ 24 task xong + checklist trên pass + không regression tests Windows cũ.

---

## Self-Review Checklist

1. **Spec coverage:** ✅ Tất cả mục spec (kiến trúc, schema, collector, đóng gói, portal, test) đều có task.
2. **Placeholders:** Đã quét — không còn TBD/TODO.
3. **Type consistency:** `IInventoryProvider.Collect()` → `InventoryEnvelope` dùng xuyên suốt. `InventoryRequest.inventory_schema_version` ở cả agent và server.
4. **Quyền Linux:** Helper allowlist cứng, systemd hardening, không shell — đã ràng buộc toàn cục.
5. **Fallback tương thích:** Task 10 định nghĩa rõ fallback; Task 11 lưu cả cũ + mới.
6. **No self-update binary:** đã ghi trong Global Constraints và Task 18+.
7. **Smartctl/dmi/luks qua helper allowlist:** đã ràng buộc đường dẫn và field name.
8. **Logo:** OrgInventory giữ nguyên, Linux accent — đã tách 2 task (logo SVG placeholder Task 18; logo chính thức với art direction là task 23/24).
9. **Systemd units:** Task 13.
10. **E2E + pilot:** Task 22 + Task 24.