using System.Globalization;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Linux.Collectors;

// ── DTO khớp đúng InventoryRequest của server (flat, giữ schema từ Windows agent) ──

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
    [JsonPropertyName("status")] public string? Status { get; set; }
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
/// Thu thập cấu hình máy Linux (read-only — chỉ đọc /proc, /sys, /etc/os-release,
/// NetworkInterface). Mọi nguồn bọc try/catch — trường nào không đọc được → null
/// (server chấp nhận optional). Tham chiếu schema payload xem
/// <c>docs/AGENT_INVENTORY_PAYLOAD_SPEC.md</c>.
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
        catch (Exception ex)
        {
            _logger.LogDebug("GetPrimaryIp lỗi: {Msg}", ex.Message);
        }
        return null;
    }

    // ── OS ─────────────────────────────────────────────────────────
    private string? GetOsName()
    {
        try
        {
            if (File.Exists("/etc/os-release"))
            {
                var lines = File.ReadAllLines("/etc/os-release");
                var pretty = lines.FirstOrDefault(l => l.StartsWith("PRETTY_NAME=", StringComparison.Ordinal))
                    ?.Split('=', 2)[1].Trim().Trim('"');
                if (!string.IsNullOrWhiteSpace(pretty)) return pretty;
                var name = lines.FirstOrDefault(l => l.StartsWith("NAME=", StringComparison.Ordinal))
                    ?.Split('=', 2)[1].Trim().Trim('"');
                if (!string.IsNullOrWhiteSpace(name)) return name;
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/etc/os-release không đọc được: {Msg}", ex.Message);
        }
        return RuntimeInformation.OSDescription;
    }

    private string? GetOsVersion()
    {
        try { return Environment.OSVersion.Version.ToString(); }
        catch { return null; }
    }

    private string? GetOsBuild()
    {
        try
        {
            if (File.Exists("/proc/sys/kernel/osrelease"))
            {
                var v = File.ReadAllText("/proc/sys/kernel/osrelease").Trim();
                if (!string.IsNullOrWhiteSpace(v)) return v;
            }
        }
        catch { }
        try { return Environment.OSVersion.Version.Build.ToString(); } catch { return null; }
    }

    private string? GetOsInstalledAt()
    {
        // Không có cách portable để detect OS install time trên Linux (touch /etc, stat /, etc.
        // không chính xác vì container/snapshot làm sai). Trả null cho an toàn.
        return null;
    }

    private string? GetActivationStatus()
    {
        // Không có khái niệm "activation" trên Linux (open-source distro). Trả null.
        return null;
    }

    // ── CPU / RAM / DISK / GPU / MAINBOARD / BIOS ─────────────────
    private CpuInfo? GetCpu()
    {
        try
        {
            if (File.Exists("/proc/cpuinfo"))
            {
                string? model = null;
                int logicalCount = 0;
                foreach (var line in File.ReadLines("/proc/cpuinfo"))
                {
                    if (model is null && line.StartsWith("model name", StringComparison.Ordinal))
                    {
                        model = line.Split(':', 2)[1].Trim();
                    }
                    if (line.StartsWith("processor", StringComparison.Ordinal))
                    {
                        logicalCount++;
                    }
                    if (model is not null && logicalCount > 0) { /* keep scanning */ }
                }
                // physical cores nếu có; fallback Environment.ProcessorCount
                var cores = Environment.ProcessorCount;
                try
                {
                    var coresLine = File.ReadLines("/proc/cpuinfo")
                        .FirstOrDefault(l => l.StartsWith("cpu cores", StringComparison.Ordinal));
                    if (coresLine is not null)
                    {
                        var perCpu = int.Parse(coresLine.Split(':', 2)[1].Trim(), CultureInfo.InvariantCulture);
                        var siblingsLine = File.ReadLines("/proc/cpuinfo")
                            .FirstOrDefault(l => l.StartsWith("siblings", StringComparison.Ordinal));
                        var siblings = siblingsLine is not null ? int.Parse(siblingsLine.Split(':', 2)[1].Trim(), CultureInfo.InvariantCulture) : 0;
                        if (siblings > 0) cores = siblings; // logical processors (gần với Environment.ProcessorCount)
                    }
                }
                catch { /* giữ Environment.ProcessorCount */ }

                return new CpuInfo { Model = model, Cores = cores };
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/proc/cpuinfo lỗi: {Msg}", ex.Message);
        }
        return new CpuInfo { Cores = Environment.ProcessorCount };
    }

    private double? GetRamGb()
    {
        try
        {
            if (File.Exists("/proc/meminfo"))
            {
                var line = File.ReadLines("/proc/meminfo").FirstOrDefault(l => l.StartsWith("MemTotal:", StringComparison.Ordinal));
                if (line is not null)
                {
                    var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length >= 2 && long.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var kb))
                        return Math.Round(kb / (1024.0 * 1024.0), 1);
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/proc/meminfo lỗi: {Msg}", ex.Message);
        }
        return null;
    }

    private List<DiskInfo>? GetDisks()
    {
        var disks = new List<DiskInfo>();
        try
        {
            if (!Directory.Exists("/sys/block")) return disks.Count > 0 ? disks : null;
            foreach (var dir in Directory.GetDirectories("/sys/block"))
            {
                var name = Path.GetFileName(dir);
                if (name.StartsWith("loop", StringComparison.Ordinal) ||
                    name.StartsWith("ram", StringComparison.Ordinal) ||
                    name.StartsWith("fd", StringComparison.Ordinal))
                    continue;

                string? model = null;
                string? serial = null;
                long bytes = 0;

                try
                {
                    var deviceDir = Path.Combine(dir, "device");
                    if (Directory.Exists(deviceDir))
                    {
                        model = ReadSysFile(Path.Combine(deviceDir, "model"));
                        serial = ReadSysFile(Path.Combine(deviceDir, "serial"));
                    }
                    var sizeRaw = ReadSysFile(Path.Combine(dir, "size"));
                    if (sizeRaw is not null && long.TryParse(sizeRaw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var sectors))
                        bytes = sectors * 512L;
                }
                catch (Exception ex)
                {
                    _logger.LogDebug("Đọc block device {Name} lỗi: {Msg}", name, ex.Message);
                }

                if (bytes == 0) continue;
                model ??= name;

                var lowModel = model.ToLowerInvariant();
                var type = "HDD";
                if (lowModel.Contains("nvme", StringComparison.Ordinal)) type = "NVMe";
                else if (lowModel.Contains("ssd", StringComparison.Ordinal)) type = "SSD";

                disks.Add(new DiskInfo
                {
                    Model = model.Trim(),
                    Serial = string.IsNullOrWhiteSpace(serial) ? null : serial.Trim(),
                    SizeBytes = bytes,
                    SizeGb = Math.Round(bytes / (1024.0 * 1024.0 * 1024.0), 0),
                    Type = type,
                });
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug("Quét /sys/block lỗi: {Msg}", ex.Message);
        }
        return disks.Count > 0 ? disks : null;
    }

    private GpuInfo? GetGpu()
    {
        // Best effort: gọi `lspci` nếu có sẵn trên hệ thống. Nếu không có (container tối giản)
        // → null. Bảo đảm: agent vẫn hoạt động kể cả khi không có GPU / không có lspci.
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo("/usr/bin/lspci", "-mm")
            {
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using var p = System.Diagnostics.Process.Start(psi);
            if (p is null) return null;
            if (!p.WaitForExit(5000)) { try { p.Kill(); } catch { } return null; }

            string? chosen = null;
            string? line;
            while ((line = p.StandardOutput.ReadLine()) is not null)
            {
                // Format: "Class\tVendor\tDevice\tSVendor\tSDevice"
                // Quan tâm dòng VGA compatible controller + 3D controller
                if (line.Contains("VGA compatible controller", StringComparison.OrdinalIgnoreCase) ||
                    line.Contains("3D controller", StringComparison.OrdinalIgnoreCase) ||
                    line.Contains("Display controller", StringComparison.OrdinalIgnoreCase))
                {
                    var parts = line.Split('\t');
                    if (parts.Length >= 4)
                    {
                        // Vendor + Device
                        chosen = $"{parts[2]} {parts[3]}".Trim('"', ' ', '\t');
                        break; // lấy GPU đầu tiên
                    }
                }
            }
            if (!string.IsNullOrWhiteSpace(chosen)) return new GpuInfo { Model = chosen };
        }
        catch (System.ComponentModel.Win32Exception) { /* lspci không tồn tại */ }
        catch (Exception ex)
        {
            _logger.LogDebug("lspci lỗi: {Msg}", ex.Message);
        }
        return null;
    }

    private MainboardInfo? GetMainboard()
    {
        var vendor = ReadSysFile("/sys/class/dmi/id/board_vendor");
        var name = ReadSysFile("/sys/class/dmi/id/board_name");
        var serial = ReadSysFile("/sys/class/dmi/id/board_serial");

        // Bỏ placeholder (mainboard không có thật) — bảo đảm model = null khi placeholder
        if (name is not null && IsPlaceholder(name)) name = null;
        if (vendor is not null && IsPlaceholder(vendor)) vendor = null;
        if (serial is not null && IsPlaceholder(serial)) serial = null;

        var model = string.Join(" ", new[] { vendor, name }.Where(s => !string.IsNullOrWhiteSpace(s))).Trim();
        if (string.IsNullOrWhiteSpace(model) && string.IsNullOrWhiteSpace(serial)) return null;
        return new MainboardInfo
        {
            Model = string.IsNullOrWhiteSpace(model) ? null : model,
            Serial = serial,
        };
    }

    private BiosInfo? GetBios()
    {
        var v = ReadSysFile("/sys/class/dmi/id/bios_version");
        if (string.IsNullOrWhiteSpace(v)) return null;
        return new BiosInfo { Version = v };
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

    private string? GetLoggedUser() => Environment.UserName;

    // ── Security posture ───────────────────────────────────────────
    private SecurityPosture? GetSecurity()
    {
        try
        {
            return SecurityCollector.Collect(_logger);
        }
        catch (Exception ex)
        {
            _logger.LogDebug("SecurityCollector lỗi: {Msg}", ex.Message);
            return null;
        }
    }

    // ── VM detection ───────────────────────────────────────────────
    private bool? GetIsVm()
    {
        var markers = new[] { "vmware", "virtualbox", "qemu", "kvm", "hyper-v", "virtual machine", "xen", "innotek", "microsoft corporation", "amazon ec2", "google compute engine" };
        try
        {
            var name = ReadSysFile("/sys/class/dmi/id/product_name");
            var vendor = ReadSysFile("/sys/class/dmi/id/sys_vendor");
            var haystack = $"{vendor} {name}".ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(haystack)) return null;
            return markers.Any(m => haystack.Contains(m, StringComparison.OrdinalIgnoreCase));
        }
        catch { return null; }
    }

    private static string? ReadSysFile(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                var v = File.ReadAllText(path).Trim();
                return string.IsNullOrWhiteSpace(v) ? null : v;
            }
        }
        catch { /* permission denied / container không có sysfs */ }
        return null;
    }

    private static bool IsPlaceholder(string? v)
    {
        if (string.IsNullOrWhiteSpace(v)) return true;
        var low = v.Trim().ToLowerInvariant();
        return low is "none" or "default string" or "to be filled by o.e.m."
            or "not applicable" or "system serial number" or "unknown" or "n/a"
            or "no asset information" or "null";
    }
}