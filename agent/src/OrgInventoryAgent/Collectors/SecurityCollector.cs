using System.Management;
using Microsoft.Extensions.Logging;
using Microsoft.Win32;
using OrgInventoryAgent.Core.Collectors.Schema;
using AntivirusInfo = OrgInventoryAgent.Core.Collectors.Schema.AntivirusInfo;
using LocalAccountInfo = OrgInventoryAgent.Core.Collectors.Schema.LocalAccountInfo;
using WeakProtocolsInfo = OrgInventoryAgent.Core.Collectors.Schema.WeakProtocolsInfo;
using SecurityPosture = OrgInventoryAgent.Core.Collectors.Schema.SecurityPostureV4;

namespace OrgInventoryAgent.Collectors;

/// <summary>
/// Thu thập toàn diện trạng thái an toàn thông tin (Security Posture) của thiết bị:
/// Antivirus, Windows Update, BitLocker, Firewall, UAC, Secure Boot, USB Policy,
/// Weak Protocols, Listening Ports, Startup Programs, Local Accounts.
/// </summary>
public static class SecurityCollector
{
    public static SecurityPosture? Collect(ILogger logger)
    {
        if (!OperatingSystem.IsWindows()) return null;

        return new SecurityPosture
        {
            Antivirus = GetAntivirus(logger),
            WindowsUpdateStatus = GetWindowsUpdateStatus(logger),
            Bitlocker = GetBitlockerStatus(logger),
            RdpEnabled = GetRdpEnabled(),
            FirewallEnabled = GetFirewallEnabled(),
            UacEnabled = GetUacEnabled(),
            SecureBootEnabled = GetSecureBootEnabled(),
            UsbStorageBlocked = GetUsbStorageBlocked(),
            WeakProtocols = GetWeakProtocols(),
            ListeningPorts = PortCollector.Collect(),
            StartupPrograms = StartupCollector.Collect(),
            LocalAccounts = GetLocalAccounts(),
        };
    }

    public static List<AntivirusInfo>? GetAntivirus(ILogger logger)
    {
        try
        {
            var list = new List<AntivirusInfo>();
            using var searcher = new ManagementObjectSearcher(
                @"root\SecurityCenter2", "SELECT displayName, productState FROM AntiVirusProduct");
            foreach (ManagementObject o in searcher.Get())
            {
                using (o)
                {
                    var name = o["displayName"]?.ToString()?.Trim();
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    var state = o["productState"] is not null ? Convert.ToInt32(o["productState"]) : 0;
                    var enabled = (state & 0x1000) != 0; // bit 12: product enabled
                    var upToDate = (state & 0x0010) == 0; // bit 4: definition up to date
                    list.Add(new AntivirusInfo
                    {
                        DisplayName = name,
                        Name = name,
                        Status = enabled ? "enabled" : "disabled",
                        Enabled = enabled,
                        UpToDate = upToDate
                    });
                }
            }
            return list.Count > 0 ? list : null;
        }
        catch (Exception ex)
        {
            logger.LogDebug("SecurityCenter2 không đọc được: {Msg}", ex.Message);
            return null;
        }
    }

    public static string? GetWindowsUpdateStatus(ILogger logger)
    {
        try
        {
            DateTime? latest = null;
            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT InstalledOn FROM Win32_QuickFixEngineering");
                foreach (ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var raw = o["InstalledOn"]?.ToString();
                        if (string.IsNullOrWhiteSpace(raw)) continue;
                        if (DateTime.TryParse(raw, null, System.Globalization.DateTimeStyles.AssumeLocal, out var dt))
                        {
                            if (latest is null || dt > latest) latest = dt;
                        }
                        else if (DateTime.TryParseExact(raw, new[] { "M/d/yyyy", "MM/dd/yyyy", "yyyyMMdd", "M/d/yyyy h:mm:ss tt" },
                            System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AssumeLocal, out var dt2))
                        {
                            if (latest is null || dt2 > latest) latest = dt2;
                        }
                    }
                }
            }
            catch { }

            if (latest.HasValue)
            {
                var days = (DateTime.UtcNow - latest.Value.ToUniversalTime()).TotalDays;
                return days <= 45 ? "up-to-date" : "outdated";
            }

            using var key = Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\Results\Install");
            var lastSuccess = key?.GetValue("LastSuccessTime")?.ToString();
            if (!string.IsNullOrWhiteSpace(lastSuccess)
                && DateTime.TryParse(lastSuccess, null, System.Globalization.DateTimeStyles.AssumeLocal, out var dtReg))
            {
                return (DateTime.UtcNow - dtReg.ToUniversalTime()).TotalDays <= 45
                    ? "up-to-date"
                    : "outdated";
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug("Không đọc được Windows Update: {Msg}", ex.Message);
        }
        return "unknown";
    }

    public static string? GetBitlockerStatus(ILogger logger)
    {
        try
        {
            using var searcher = new ManagementObjectSearcher(
                @"root\CIMV2\Security\MicrosoftVolumeEncryption",
                "SELECT DriveLetter, ProtectionStatus FROM Win32_EncryptableVolume WHERE DriveLetter = 'C:'");
            foreach (ManagementObject o in searcher.Get())
            {
                using (o)
                {
                    var status = o["ProtectionStatus"];
                    if (status is null) continue;
                    var code = Convert.ToInt32(status);
                    return code == 1 ? "on" : "off";
                }
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug("Không đọc được BitLocker WMI: {Msg}", ex.Message);
        }
        return "off";
    }

    public static bool? GetFirewallEnabled()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile");
            var val = key?.GetValue("EnableFirewall");
            if (val is int i) return i == 1;
        }
        catch { }
        return null;
    }

    public static bool? GetUacEnabled()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System");
            var val = key?.GetValue("EnableLUA");
            if (val is int i) return i == 1;
        }
        catch { }
        return null;
    }

    public static bool? GetSecureBootEnabled()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Control\SecureBoot\State");
            var val = key?.GetValue("UEFISecureBootEnabled");
            if (val is int i) return i == 1;
        }
        catch { }
        return null;
    }

    public static bool? GetUsbStorageBlocked()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Services\USBSTOR");
            var val = key?.GetValue("Start");
            if (val is int i) return i == 4;
        }
        catch { }
        return null;
    }

    public static WeakProtocolsInfo? GetWeakProtocols()
    {
        var info = new WeakProtocolsInfo();
        try
        {
            using var keySmb = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters");
            var smb1 = keySmb?.GetValue("SMB1");
            if (smb1 is int s && s == 1) info.Smbv1Disabled = false;

            using var keyTls10 = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.0\Server");
            var tls10 = keyTls10?.GetValue("Enabled");
            if (tls10 is int t10 && t10 == 1) info.Tls10Disabled = false;

            using var keyTls11 = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.1\Server");
            var tls11 = keyTls11?.GetValue("Enabled");
            if (tls11 is int t11 && t11 == 1) info.Tls11Disabled = false;

            using var keySsl3 = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\SSL 3.0\Server");
            var ssl3 = keySsl3?.GetValue("Enabled");
            if (ssl3 is int s3 && s3 == 1) info.Ssl3Disabled = false;
        }
        catch { }
        return info;
    }

    public static bool? GetRdpEnabled()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Control\Terminal Server");
            var deny = key?.GetValue("fDenyTSConnections");
            if (deny is int d) return d == 0;
        }
        catch { }
        return null;
    }

    public static List<LocalAccountInfo>? GetLocalAccounts()
    {
        try
        {
            var list = new List<LocalAccountInfo>();
            using var searcher = new ManagementObjectSearcher(
                "SELECT Name, FullName, Disabled, PasswordRequired FROM Win32_UserAccount WHERE LocalAccount = TRUE");
            foreach (ManagementObject o in searcher.Get())
            {
                using (o)
                {
                    var name = o["Name"]?.ToString()?.Trim();
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    var fullName = o["FullName"]?.ToString()?.Trim();
                    var disabled = o["Disabled"] is bool dis && dis;
                    bool? hasPassword = null;
                    try
                    {
                        if (o["PasswordRequired"] is bool pr) hasPassword = pr;
                        else if (o["PasswordRequired"] is not null)
                            hasPassword = Convert.ToBoolean(o["PasswordRequired"]);
                    }
                    catch { }

                    list.Add(new LocalAccountInfo
                    {
                        Username = name,
                        Name = name,
                        FullName = string.IsNullOrWhiteSpace(fullName) ? null : fullName,
                        Disabled = disabled,
                        HasPassword = hasPassword,
                        IsAdmin = string.Equals(name, "Administrator", StringComparison.OrdinalIgnoreCase)
                    });
                }
            }
            return list.Count > 0 ? list : null;
        }
        catch { }
        return null;
    }
}
