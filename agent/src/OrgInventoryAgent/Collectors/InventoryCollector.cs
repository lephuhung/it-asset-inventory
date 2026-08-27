using System.Globalization;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Collectors;

// ── DTO khớp đúng InventoryRequest của server (flat) ─────────────────────────

public sealed class CpuInfo
{
    [JsonPropertyName("model")] public string? Model { get; set; }
    [JsonPropertyName("cores")] public int? Cores { get; set; }
}

public sealed class DiskInfo
{
    [JsonPropertyName("model")] public string? Model { get; set; }
    [JsonPropertyName("serial")] public string? Serial { get; set; }
    [JsonPropertyName("size_bytes")] public long? SizeBytes { get; set; }
    [JsonPropertyName("size")] public long? Size => SizeBytes;
    [JsonPropertyName("size_gb")] public double? SizeGb { get; set; }
    [JsonPropertyName("type")] public string? Type { get; set; } // SSD | HDD | NVMe
}

public sealed class GpuInfo
{
    [JsonPropertyName("model")] public string? Model { get; set; }
}

public sealed class MainboardInfo
{
    [JsonPropertyName("model")] public string? Model { get; set; }
    [JsonPropertyName("serial")] public string? Serial { get; set; }
}

public sealed class BiosInfo
{
    [JsonPropertyName("version")] public string? Version { get; set; }
}

public sealed class NetworkInterfaceInfo
{
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("ip")] public string? Ip { get; set; }
    [JsonPropertyName("mac")] public string? Mac { get; set; }
    [JsonPropertyName("is_dual_homed")] public bool IsDualHomed { get; set; }
}

public sealed class SoftwareInfo
{
    [JsonPropertyName("display_name")] public string? DisplayName { get; set; }
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("version")] public string? Version { get; set; }
    [JsonPropertyName("publisher")] public string? Publisher { get; set; }
    [JsonPropertyName("install_date")] public string? InstallDate { get; set; }
    [JsonPropertyName("uninstall_string")] public string? UninstallString { get; set; }
    [JsonPropertyName("is_per_user")] public bool IsPerUser { get; set; }
}

public sealed class AntivirusInfo
{
    [JsonPropertyName("displayName")] public string? DisplayName { get; set; }
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("status")] public string? Status { get; set; } // enabled | disabled
    [JsonPropertyName("enabled")] public bool Enabled { get; set; }
    [JsonPropertyName("upToDate")] public bool UpToDate { get; set; }
}

public sealed class LocalAccountInfo
{
    [JsonPropertyName("username")] public string? Username { get; set; }
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("full_name")] public string? FullName { get; set; }
    [JsonPropertyName("disabled")] public bool Disabled { get; set; }
    [JsonPropertyName("has_password")] public bool? HasPassword { get; set; }
    [JsonPropertyName("is_admin")] public bool IsAdmin { get; set; }
}

public sealed class ListeningPortInfo
{
    [JsonPropertyName("port")] public int Port { get; set; }
    [JsonPropertyName("protocol")] public string Protocol { get; set; } = "TCP";
    [JsonPropertyName("address")] public string? Address { get; set; }
}

public sealed class StartupProgramInfo
{
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("command")] public string? Command { get; set; }
    [JsonPropertyName("location")] public string? Location { get; set; }
}

public sealed class WeakProtocolsInfo
{
    [JsonPropertyName("smbv1_disabled")] public bool Smbv1Disabled { get; set; } = true;
    [JsonPropertyName("tls10_disabled")] public bool Tls10Disabled { get; set; } = true;
    [JsonPropertyName("tls11_disabled")] public bool Tls11Disabled { get; set; } = true;
    [JsonPropertyName("ssl3_disabled")] public bool Ssl3Disabled { get; set; } = true;
}

public sealed class SecurityPosture
{
    [JsonPropertyName("antivirus")] public List<AntivirusInfo>? Antivirus { get; set; }
    [JsonPropertyName("windows_update_status")] public string? WindowsUpdateStatus { get; set; }
    [JsonPropertyName("bitlocker")] public string? Bitlocker { get; set; }
    [JsonPropertyName("rdp_enabled")] public bool? RdpEnabled { get; set; }
    [JsonPropertyName("firewall_enabled")] public bool? FirewallEnabled { get; set; }
    [JsonPropertyName("uac_enabled")] public bool? UacEnabled { get; set; }
    [JsonPropertyName("secure_boot_enabled")] public bool? SecureBootEnabled { get; set; }
    [JsonPropertyName("usb_storage_blocked")] public bool? UsbStorageBlocked { get; set; }
    [JsonPropertyName("weak_protocols")] public WeakProtocolsInfo? WeakProtocols { get; set; }
    [JsonPropertyName("listening_ports")] public List<ListeningPortInfo>? ListeningPorts { get; set; }
    [JsonPropertyName("startup_programs")] public List<StartupProgramInfo>? StartupPrograms { get; set; }
    [JsonPropertyName("local_accounts")] public List<LocalAccountInfo>? LocalAccounts { get; set; }
    [JsonPropertyName("smarts")] public List<object>? Smarts { get; set; }
}

/// <summary>Snapshot inventory — khớp đúng schema InventoryRequest server.</summary>
public sealed class InventorySnapshot
{
    [JsonPropertyName("os_name")] public string? OsName { get; set; }
    [JsonPropertyName("os_version")] public string? OsVersion { get; set; }
    [JsonPropertyName("os_build")] public string? OsBuild { get; set; }
    [JsonPropertyName("os_arch")] public string? OsArch { get; set; }
    [JsonPropertyName("os_installed_at")] public string? OsInstalledAt { get; set; }
    [JsonPropertyName("activation_status")] public string? ActivationStatus { get; set; }
    [JsonPropertyName("cpu")] public CpuInfo? Cpu { get; set; }
    [JsonPropertyName("ram_gb")] public double? RamGb { get; set; }
    [JsonPropertyName("disks")] public List<DiskInfo>? Disks { get; set; }
    [JsonPropertyName("gpu")] public GpuInfo? Gpu { get; set; }
    [JsonPropertyName("mainboard")] public MainboardInfo? Mainboard { get; set; }
    [JsonPropertyName("bios")] public BiosInfo? Bios { get; set; }
    [JsonPropertyName("network")] public List<NetworkInterfaceInfo>? Network { get; set; }
    [JsonPropertyName("logged_user")] public string? LoggedUser { get; set; }
    [JsonPropertyName("installed_software")] public List<SoftwareInfo>? InstalledSoftware { get; set; }
    [JsonPropertyName("security")] public SecurityPosture? Security { get; set; }
    [JsonPropertyName("is_vm")] public bool? IsVm { get; set; }
    [JsonPropertyName("config_hash")] public string? ConfigHash { get; set; }
}

/// <summary>
/// Thu thập cấu hình máy (read-only WMI/Registry/NetworkInterface).
/// Mọi nguồn bọc try/catch — trường nào không đọc được → null (server chấp nhận optional).
/// Trên Linux (dev) dùng /sys, /proc, Environment, NetworkInterface.
/// </summary>
public sealed class InventoryCollector
{
    private readonly ILogger<InventoryCollector> _logger;

    public InventoryCollector(ILogger<InventoryCollector> logger) => _logger = logger;

    public InventorySnapshot Collect()
    {
        var snapshot = new InventorySnapshot
        {
            OsName = GetOsName(),
            OsVersion = GetOsVersion(),
            OsBuild = GetOsBuild(),
            OsArch = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant(),
            OsInstalledAt = GetOsInstalledAt(),
            ActivationStatus = GetActivationStatus(),
            Cpu = GetCpu(),
            RamGb = GetRamGb(),
            Disks = GetDisks(),
            Gpu = GetGpu(),
            Mainboard = GetMainboard(),
            Bios = GetBios(),
            Network = GetNetwork(),
            LoggedUser = GetLoggedUser(),
            InstalledSoftware = SoftwareCollector.Collect(_logger),
            Security = GetSecurity(),
            IsVm = GetIsVm(),
        };
        return snapshot;
    }

    /// <summary>IP đầu tiên của interface active (không loopback) — dùng cho heartbeat.</summary>
    public string? GetPrimaryIp()
    {
        try
        {
            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback || ni.NetworkInterfaceType == NetworkInterfaceType.Tunnel) continue;
                if (ni.OperationalStatus != OperationalStatus.Up) continue;
                foreach (var addr in ni.GetIPProperties().UnicastAddresses)
                {
                    if (addr.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                        return addr.Address.ToString();
                }
            }
        }
        catch { }
        return null;
    }

    // ── OS ─────────────────────────────────────────────────────────
    private string? GetOsName()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                // 1. Thử WMI Win32_OperatingSystem.Caption (trả về chính xác "Microsoft Windows 11 Pro")
                string? caption = null;
                try
                {
                    using var searcher = new System.Management.ManagementObjectSearcher("SELECT Caption FROM Win32_OperatingSystem");
                    foreach (System.Management.ManagementObject o in searcher.Get())
                    {
                        using (o)
                        {
                            caption = o["Caption"]?.ToString();
                            if (!string.IsNullOrWhiteSpace(caption)) break;
                        }
                    }
                }
                catch { }

                // 2. Đọc DisplayVersion và build từ registry
                string? display = null;
                string? buildStr = null;
                string? product = null;
                try
                {
                    using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                        @"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
                    display = key?.GetValue("DisplayVersion")?.ToString();
                    buildStr = key?.GetValue("CurrentBuildNumber")?.ToString();
                    product = key?.GetValue("ProductName")?.ToString();
                }
                catch { }

                // Nếu lấy được Caption từ WMI, chuẩn hóa và gắn DisplayVersion
                if (!string.IsNullOrWhiteSpace(caption))
                {
                    var cleanCaption = caption.Replace("Microsoft ", "", StringComparison.OrdinalIgnoreCase).Trim();
                    return string.IsNullOrWhiteSpace(display) ? cleanCaption : $"{cleanCaption} {display}";
                }

                // Fallback registry: Windows 11 giữ ProductName="Windows 10 ..." vì lý do tương thích ngược (build >= 22000 là Windows 11)
                if (!string.IsNullOrWhiteSpace(product))
                {
                    if (int.TryParse(buildStr, out var b) && b >= 22000 && product.Contains("Windows 10", StringComparison.OrdinalIgnoreCase))
                    {
                        product = product.Replace("Windows 10", "Windows 11", StringComparison.OrdinalIgnoreCase);
                    }
                    return string.IsNullOrWhiteSpace(display) ? product : $"{product} {display}";
                }
            }
            catch { }
        }
        else
        {
            try
            {
                var lines = File.ReadAllLines("/etc/os-release");
                var name = lines.FirstOrDefault(l => l.StartsWith("PRETTY_NAME="))?.Split('=', 2)[1].Trim('"');
                return name;
            }
            catch { }
        }
        return RuntimeInformation.OSDescription;
    }

    private string? GetOsVersion()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
                var ver = key?.GetValue("CurrentVersion")?.ToString();   // "10.0"
                var build = key?.GetValue("CurrentBuildNumber")?.ToString();
                if (!string.IsNullOrWhiteSpace(ver) && !string.IsNullOrWhiteSpace(build))
                    return $"{ver}.{build}";
            }
            catch { }
        }
        try { return Environment.OSVersion.Version.ToString(); } catch { }
        return null;
    }

    private string? GetOsBuild()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
                return key?.GetValue("CurrentBuildNumber")?.ToString();
            }
            catch { }
        }
        else
        {
            // Linux: kernel release (VD "6.8.0-138-generic")
            try { return File.ReadAllText("/proc/sys/kernel/osrelease").Trim(); }
            catch { }
        }
        try { return Environment.OSVersion.Version.Build.ToString(); } catch { }
        return null;
    }

    private string? GetOsInstalledAt()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
                var raw = key?.GetValue("InstallDate");
                long secs;
                if (raw is int i) secs = i;
                else if (raw is long l) secs = l;
                else return null;
                return DateTimeOffset.FromUnixTimeSeconds(secs).UtcDateTime
                    .ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
            }
            catch { }
        }
        return null;
    }

    private string? GetActivationStatus()
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                "SELECT LicenseStatus FROM SoftwareLicensingProduct WHERE PartialProductKey IS NOT NULL");
            foreach (System.Management.ManagementObject o in searcher.Get())
            {
                using (o)
                {
                    var s = o["LicenseStatus"]?.ToString();
                    if (s == "1") return "licensed";
                    if (s is not null) return "unlicensed";
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug("Không đọc được activation status: {Msg}", ex.Message);
        }
        return null;
    }

    // ── CPU / RAM / DISK / GPU / MAINBOARD / BIOS ─────────────────
    private CpuInfo? GetCpu()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT Name, NumberOfCores, NumberOfLogicalProcessors FROM Win32_Processor");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var model = o["Name"]?.ToString()?.Trim();
                        var cores = o["NumberOfCores"] is not null ? Convert.ToInt32(o["NumberOfCores"]) : (int?)null;
                        if (model is null && cores is null) continue;
                        return new CpuInfo { Model = model, Cores = cores };
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug("WMI CPU lỗi: {Msg}", ex.Message);
            }
        }
        else
        {
            // Linux: /proc/cpuinfo
            try
            {
                var model = File.ReadLines("/proc/cpuinfo")
                    .FirstOrDefault(l => l.StartsWith("model name"))?.Split(':', 2)[1].Trim();
                return new CpuInfo { Model = model, Cores = Environment.ProcessorCount };
            }
            catch { }
        }
        return null;
    }

    private double? GetRamGb()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT TotalPhysicalMemory FROM Win32_ComputerSystem");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        if (o["TotalPhysicalMemory"] is not null)
                        {
                            var bytes = Convert.ToUInt64(o["TotalPhysicalMemory"]);
                            return Math.Round(bytes / (1024.0 * 1024.0 * 1024.0), 1);
                        }
                    }
                }
            }
            catch { }
        }
        else
        {
            try
            {
                var line = File.ReadLines("/proc/meminfo").FirstOrDefault(l => l.StartsWith("MemTotal:"));
                if (line != null && long.TryParse(line.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1], out var kb))
                    return Math.Round(kb / (1024.0 * 1024.0), 1);
            }
            catch { }
        }
        return null;
    }

    private List<DiskInfo>? GetDisks()
    {
        var disks = new List<DiskInfo>();
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT Model, SerialNumber, Size, MediaType FROM Win32_DiskDrive");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var size = o["Size"] is not null ? Convert.ToUInt64(o["Size"]) : 0UL;
                        if (size == 0) continue;
                        var model = o["Model"]?.ToString()?.Trim();
                        var type = InferDiskType(o["MediaType"]?.ToString(), model);
                        disks.Add(new DiskInfo
                        {
                            Model = model,
                            Serial = o["SerialNumber"]?.ToString()?.Trim(),
                            SizeBytes = (long)size,
                            SizeGb = Math.Round(size / (1024.0 * 1024.0 * 1024.0), 0),
                            Type = type,
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug("WMI DiskDrive lỗi: {Msg}", ex.Message);
            }
        }
        else
        {
            // Linux: /sys/block/<dev> — bỏ loop/ram + thiết bị dung lượng 0
            try
            {
                foreach (var dir in Directory.GetDirectories("/sys/block"))
                {
                    var name = Path.GetFileName(dir);
                    if (name.StartsWith("loop") || name.StartsWith("ram") || name.StartsWith("fd")) continue;
                    var model = ReadSys($"{dir}/device/model") ?? name;
                    var sectors = ReadSys($"{dir}/size");
                    if (sectors is null || !long.TryParse(sectors, out var secs) || secs == 0) continue;
                    var bytes = secs * 512L;
                    var type = model.ToLowerInvariant().Contains("nvme") || model.ToLowerInvariant().Contains("ssd") ? "SSD" : "HDD";
                    disks.Add(new DiskInfo
                    {
                        Model = model,
                        Serial = ReadSys($"{dir}/device/serial"),
                        SizeBytes = bytes,
                        SizeGb = Math.Round(bytes / (1024.0 * 1024.0 * 1024.0), 0),
                        Type = type,
                    });
                }
            }
            catch { }
        }
        return disks.Count > 0 ? disks : null;
    }

    private static string? InferDiskType(string? mediaType, string? model)
    {
        var m = (mediaType ?? "").ToLowerInvariant();
        var md = (model ?? "").ToLowerInvariant();
        if (m.Contains("ssd") || m.Contains("solid") || md.Contains("nvme") || md.Contains("ssd"))
            return md.Contains("nvme") ? "NVMe" : "SSD";
        return "HDD";
    }

    private GpuInfo? GetGpu()
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                "SELECT Name FROM Win32_VideoController");
            foreach (System.Management.ManagementObject o in searcher.Get())
            {
                using (o)
                {
                    var name = o["Name"]?.ToString()?.Trim();
                    if (!string.IsNullOrWhiteSpace(name)) return new GpuInfo { Model = name };
                }
            }
        }
        catch { }
        return null;
    }

    private MainboardInfo? GetMainboard()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT Manufacturer, Product, SerialNumber FROM Win32_BaseBoard");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var manu = o["Manufacturer"]?.ToString()?.Trim();
                        var prod = o["Product"]?.ToString()?.Trim();
                        var model = string.Join(" ", new[] { manu, prod }.Where(s => !string.IsNullOrWhiteSpace(s)));
                        return new MainboardInfo
                        {
                            Model = string.IsNullOrWhiteSpace(model) ? null : model,
                            Serial = o["SerialNumber"]?.ToString()?.Trim(),
                        };
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug("WMI BaseBoard lỗi: {Msg}", ex.Message);
            }
        }
        else
        {
            var vendor = ReadSys("/sys/class/dmi/id/board_vendor");
            var name = ReadSys("/sys/class/dmi/id/board_name");
            var model = string.Join(" ", new[] { vendor, name }.Where(s => !string.IsNullOrWhiteSpace(s)));
            var serial = ReadSys("/sys/class/dmi/id/board_serial");
            if (string.IsNullOrWhiteSpace(model) && string.IsNullOrWhiteSpace(serial)) return null;
            return new MainboardInfo
            {
                Model = string.IsNullOrWhiteSpace(model) ? null : model,
                Serial = serial,
            };
        }
        return null;
    }

    private BiosInfo? GetBios()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT SMBIOSBIOSVersion FROM Win32_BIOS");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var v = o["SMBIOSBIOSVersion"]?.ToString()?.Trim();
                        if (!string.IsNullOrWhiteSpace(v)) return new BiosInfo { Version = v };
                    }
                }
            }
            catch { }
        }
        else
        {
            var v = ReadSys("/sys/class/dmi/id/bios_version");
            if (v is not null) return new BiosInfo { Version = v };
        }
        return null;
    }

    // ── Network ────────────────────────────────────────────────────
    private List<NetworkInterfaceInfo>? GetNetwork()
    {
        try
        {
            var result = new List<NetworkInterfaceInfo>();
            var entries = new List<(NetworkInterface Ni, string? Ip, string? Mac, string? NetGroup)>();
            var distinctSubnets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback || ni.NetworkInterfaceType == NetworkInterfaceType.Tunnel) continue;
                if (ni.OperationalStatus != OperationalStatus.Up) continue;

                string? ip = null;
                string? netGroup = null;

                foreach (var addr in ni.GetIPProperties().UnicastAddresses)
                {
                    if (addr.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                    {
                        ip = addr.Address.ToString();
                        var ipBytes = addr.Address.GetAddressBytes();
                        try
                        {
                            var mask = addr.IPv4Mask;
                            if (mask is not null && mask.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                            {
                                var maskBytes = mask.GetAddressBytes();
                                var netBytes = new byte[4];
                                for (int i = 0; i < 4; i++)
                                    netBytes[i] = (byte)(ipBytes[i] & maskBytes[i]);
                                int prefix = CountPrefixBits(maskBytes);
                                netGroup = $"{netBytes[0]}.{netBytes[1]}.{netBytes[2]}.{netBytes[3]}/{prefix}";
                            }
                        }
                        catch { }

                        netGroup ??= $"{ipBytes[0]}.{ipBytes[1]}.0.0/16";
                        break;
                    }
                }

                if (ip is null)
                {
                    foreach (var addr in ni.GetIPProperties().UnicastAddresses)
                    {
                        if (addr.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6)
                        {
                            ip = addr.Address.ToString();
                            break;
                        }
                    }
                }

                var macBytes = ni.GetPhysicalAddress().GetAddressBytes();
                var mac = macBytes.Length == 0 ? null : string.Join("-", macBytes.Select(b => b.ToString("X2")));

                if (!string.IsNullOrEmpty(netGroup))
                    distinctSubnets.Add(netGroup);

                entries.Add((ni, ip, mac, netGroup));
            }

            bool hasDualHomed = distinctSubnets.Count >= 2;
            string? firstSubnet = null;

            foreach (var (ni, ip, mac, netGroup) in entries)
            {
                bool isSecondary = false;
                if (hasDualHomed && netGroup is not null)
                {
                    firstSubnet ??= netGroup;
                    isSecondary = !string.Equals(firstSubnet, netGroup, StringComparison.OrdinalIgnoreCase);
                }

                result.Add(new NetworkInterfaceInfo
                {
                    Name = ni.Name,
                    Ip = ip,
                    Mac = mac,
                    IsDualHomed = hasDualHomed && isSecondary,
                });
            }

            return result.Count > 0 ? result : null;
        }
        catch (Exception ex)
        {
            _logger.LogDebug("Đọc network lỗi: {Msg}", ex.Message);
            return null;
        }
    }

    private static int CountPrefixBits(byte[] maskBytes)
    {
        int count = 0;
        foreach (var b in maskBytes)
        {
            var v = b;
            while (v != 0)
            {
                count += v & 1;
                v >>= 1;
            }
        }
        return count;
    }

    // ── User ───────────────────────────────────────────────────────
    /// <summary>User đang đăng nhập — không bao giờ throw (dùng cho heartbeat).</summary>
    public string? GetLoggedUserSafe()
    {
        try { return GetLoggedUser(); }
        catch { return Environment.UserName; }
    }

    private string? GetLoggedUser()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT UserName FROM Win32_ComputerSystem");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var u = o["UserName"]?.ToString()?.Trim();
                        if (!string.IsNullOrWhiteSpace(u)) return u;
                    }
                }
            }
            catch { }
            return Environment.UserName;
        }
        return Environment.UserName;
    }

    // ── Security posture (Phase 1 — antivirus + RDP + local accounts + WU + BitLocker) ─
    private SecurityPosture? GetSecurity()
    {
        return SecurityCollector.Collect(_logger);
    }

    // ── VM detection ───────────────────────────────────────────────
    private bool? GetIsVm()
    {
        var markers = new[] { "vmware", "virtualbox", "qemu", "kvm", "hyper-v", "virtual machine", "xen", "innotek" };
        string? haystack = null;
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT Manufacturer, Model FROM Win32_ComputerSystem");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        haystack = $"{o["Manufacturer"]} {o["Model"]}".ToLowerInvariant();
                        break;
                    }
                }
            }
            catch { }
        }
        else
        {
            var name = ReadSys("/sys/class/dmi/id/product_name");
            var vendor = ReadSys("/sys/class/dmi/id/sys_vendor");
            haystack = $"{vendor} {name}".ToLowerInvariant();
        }
        if (string.IsNullOrWhiteSpace(haystack)) return null;
        return markers.Any(m => haystack.Contains(m, StringComparison.OrdinalIgnoreCase));
    }

    private static string? ReadSys(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                var v = File.ReadAllText(path).Trim();
                return string.IsNullOrWhiteSpace(v) ? null : v;
            }
        }
        catch { }
        return null;
    }
}
