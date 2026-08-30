using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Linux-side façade for SecurityPostureV4. Aggregates all Linux security collectors.</summary>
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

/// <summary>Thu thập trạng thái auto-update — KHÔNG tự chạy apt update / dnf makecache.</summary>
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
            return ParseApt(p.StandardOutput.ReadToEnd());
        }
        catch (Exception ex)
        {
            logger.LogDebug("apt-get dry-run lỗi: {Msg}", ex.Message);
            return new UpdateStatus { Status = "unknown" };
        }
    }

    private static UpdateStatus ParseApt(string output)
    {
        var idx = output.IndexOf("The following packages will be upgraded:", StringComparison.Ordinal);
        if (idx < 0) return new UpdateStatus { Status = "up-to-date", PendingCount = 0, SecurityPendingCount = 0 };
        var lines = output.Substring(idx).Split('\n').Skip(1)
            .TakeWhile(l => !string.IsNullOrWhiteSpace(l)).ToList();
        var pending = lines.Count;
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
}

/// <summary>Đọc trạng thái mã hóa ổ đĩa qua lsblk — chỉ trả kết quả khi xác định được LUKS.</summary>
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

/// <summary>Kiểm tra SSH/Remote Desktop — chỉ trả enabled khi systemctl thực sự enabled.</summary>
public static class LinuxRemoteAccessCollector
{
    public static RemoteAccessStatus Collect(ILogger logger)
    {
        var status = new RemoteAccessStatus();
        var services = new List<string>();

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/systemctl",
                Arguments = "list-unit-files --type=service --state=enabled -q",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return status; }
            var output = p.StandardOutput.ReadToEnd();
            if (output.Contains("ssh.service", StringComparison.OrdinalIgnoreCase))
            {
                status.SshEnabled = true;
                services.Add("sshd");
            }
            if (output.Contains("xrdp.service", StringComparison.OrdinalIgnoreCase) ||
                output.Contains("vncserver", StringComparison.OrdinalIgnoreCase))
            {
                status.RemoteDesktopEnabled = true;
                services.Add("xrdp/vnc");
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug("systemctl lỗi: {Msg}", ex.Message);
        }

        status.Services = services.Count > 0 ? services : null;
        return status;
    }
}

/// <summary>Allowlist endpoint-protection products — KHÔNG suy diễn "không tìm thấy" = "tắt".</summary>
public static class LinuxEndpointProtectionCollector
{
    private static readonly (string Product, string[] ProcessNames)[] KnownProducts =
    {
        ("ClamAV", new[] { "clamd", "clamav-daemon", "clamav-milter" }),
        ("CrowdStrike Falcon", new[] { "falcon-sensor" }),
        ("SentinelOne", new[] { "sentinelone", "sentinel-agent" }),
        ("Wazuh", new[] { "wazuh-agent", "wazuh-modulesd" }),
    };

    public static List<AntivirusInfo> Collect(ILogger logger)
    {
        var found = new List<AntivirusInfo>();
        foreach (var (product, procs) in KnownProducts)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "/usr/bin/pgrep",
                    Arguments = "-x " + string.Join("|", procs),
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                };
                using var p = Process.Start(psi);
                if (p is null) continue;
                if (!p.WaitForExit(2_000)) { p.Kill(); continue; }
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

/// <summary>Đọc sudo installed + root account locked. Chỉ đọc metadata (không lấy hash).</summary>
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

/// <summary>Đọc TCP listeners qua IPGlobalProperties — cross-platform .NET API.</summary>
public static class LinuxPortCollector
{
    public static List<ListeningPortInfo>? Collect(ILogger logger)
    {
        try
        {
            var props = System.Net.NetworkInformation.IPGlobalProperties.GetIPGlobalProperties();
            var endpoints = props.GetActiveTcpListeners();
            var list = endpoints
                .Select(ep => new ListeningPortInfo
                {
                    Port = ep.Port,
                    Protocol = "TCP",
                    Address = ep.Address.ToString(),
                })
                .Take(200) // cap
                .ToList();
            return list.Count > 0 ? list : null;
        }
        catch (Exception ex)
        {
            logger.LogDebug("GetActiveTcpListeners lỗi: {Msg}", ex.Message);
            return null;
        }
    }
}

/// <summary>Firewall detection — ufw / firewalld / nftables. null nếu không xác định.</summary>
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

        return null;
    }
}

/// <summary>Đọc /etc/passwd để liệt kê tài khoản local. Không đọc shadow/hash.</summary>
public static class LinuxAccountCollector
{
    public static List<LocalAccountInfo>? Collect(ILogger logger)
    {
        if (!File.Exists("/etc/passwd")) return null;
        var list = new List<LocalAccountInfo>();
        try
        {
            foreach (var line in File.ReadLines("/etc/passwd"))
            {
                var parts = line.Split(':');
                if (parts.Length < 7) continue;
                var username = parts[0];
                if (username.StartsWith('_')) continue;
                list.Add(new LocalAccountInfo
                {
                    Username = username,
                    Name = username,
                    FullName = parts[4].Replace(',', ' '),
                    Disabled = parts[6].Contains("nologin", StringComparison.OrdinalIgnoreCase),
                    IsAdmin = File.Exists("/etc/sudoers.d/" + username),
                });
            }
        }
        catch { }
        return list.Count > 0 ? list : null;
    }
}

/// <summary>Liệt kê systemd service enabled — cap 200 entries.</summary>
public static class LinuxStartupCollector
{
    public static List<StartupProgramInfo>? Collect(ILogger logger)
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
            var list = new List<StartupProgramInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                var name = line.Split(' ')[0];
                list.Add(new StartupProgramInfo { Name = name, Location = "systemd_enabled", Command = name });
                if (list.Count >= 200) break;
            }
            return list.Count > 0 ? list : null;
        }
        catch { return null; }
    }
}