using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Collectors;

/// <summary>Fingerprint gửi lên server khi enroll (3 nguồn RIÊNG — server tính hash có trọng số).</summary>
public sealed class FingerprintPayload
{
    [JsonPropertyName("smbios_uuid")] public string? SmbiosUuid { get; set; }
    [JsonPropertyName("machine_guid")] public string? MachineGuid { get; set; }
    [JsonPropertyName("mainboard_serial")] public string? MainboardSerial { get; set; }
}

/// <summary>
/// Thu thập fingerprint đa nguồn: SMBIOS UUID + MachineGuid + serial mainboard.
/// Mỗi nguồn bọc try/catch riêng — nguồn nào thiếu (WMI không có quyền, máy ảo
/// không có serial...) thì bỏ qua (null), server tự xử lý hash có trọng số.
/// Read-only: chỉ đọc WMI/Registry/sysfs. Trên Linux (dev) đọc /sys/class/dmi-id + /etc/machine-id.
/// </summary>
public sealed class FingerprintCollector
{
    private readonly ILogger<FingerprintCollector> _logger;

    public FingerprintCollector(ILogger<FingerprintCollector> logger) => _logger = logger;

    public FingerprintPayload Collect()
    {
        var rawUuid = ReadSmbiosUuid();
        var rawGuid = ReadMachineGuid();
        var rawSerial = ReadMainboardSerial();

        _logger.LogDebug("Fingerprint nguồn: smbios_uuid={Uuid}, machine_guid_src={Guid}, mainboard_serial_src={Serial}",
            Safe(rawUuid), Safe(rawGuid), Safe(rawSerial));

        return new FingerprintPayload
        {
            SmbiosUuid = Sanitize(rawUuid),
            // Hash SHA-256 hex trước khi gửi (riêng tư: không gửi MachineGuid/serial thô lên server)
            MachineGuid = HashOrNull(rawGuid),
            MainboardSerial = HashOrNull(rawSerial),
        };
    }

    // ── Nguồn 1: SMBIOS UUID ──────────────────────────────────────
    private string? ReadSmbiosUuid()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT UUID FROM Win32_ComputerSystemProduct");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var v = o["UUID"]?.ToString();
                        if (!string.IsNullOrWhiteSpace(v)) return v.Trim();
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug("WMI Win32_ComputerSystemProduct không đọc được UUID: {Msg}", ex.Message);
            }
            // Fallback registry (một số máy expose UUID ở đây)
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Control\SystemInformation");
                var v = key?.GetValue("SystemProductName")?.ToString();
                return string.IsNullOrWhiteSpace(v) ? null : null; // không có UUID ở key này — trả null
            }
            catch
            {
                return null;
            }
        }

        // Linux dev: /sys/class/dmi/id/product_uuid
        return ReadSysFile("/sys/class/dmi/id/product_uuid");
    }

    // ── Nguồn 2: MachineGuid ──────────────────────────────────────
    private string? ReadMachineGuid()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Cryptography");
                var v = key?.GetValue("MachineGuid")?.ToString();
                return string.IsNullOrWhiteSpace(v) ? null : v.Trim();
            }
            catch (Exception ex)
            {
                _logger.LogDebug("Registry MachineGuid không đọc được: {Msg}", ex.Message);
                return null;
            }
        }

        // Linux dev: /etc/machine-id
        try
        {
            if (File.Exists("/etc/machine-id"))
            {
                var v = File.ReadAllText("/etc/machine-id").Trim();
                return string.IsNullOrWhiteSpace(v) ? null : v;
            }
        }
        catch { }
        return null;
    }

    // ── Nguồn 3: Serial mainboard ─────────────────────────────────
    private string? ReadMainboardSerial()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(
                    "SELECT SerialNumber FROM Win32_BaseBoard");
                foreach (System.Management.ManagementObject o in searcher.Get())
                {
                    using (o)
                    {
                        var v = o["SerialNumber"]?.ToString();
                        if (!string.IsNullOrWhiteSpace(v)) return v.Trim();
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug("WMI Win32_BaseBoard không đọc được serial: {Msg}", ex.Message);
            }
            return null;
        }

        return ReadSysFile("/sys/class/dmi/id/board_serial");
    }

    // ── Helpers ───────────────────────────────────────────────────

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
        catch
        {
            // không có quyền đọc dmi (một số container) → bỏ qua nguồn
        }
        return null;
    }

    /// <summary>Giá trị placeholder của nhà sản xuất → coi như thiếu.</summary>
    private static string? Sanitize(string? v)
    {
        if (string.IsNullOrWhiteSpace(v)) return null;
        var t = v.Trim();
        var low = t.ToLowerInvariant();
        if (low is "none" or "default string" or "to be filled by o.e.m." or "not applicable"
            or "system serial number" or "unknown" or "n/a" or "00000000-0000-0000-0000-000000000000"
            or "00000000-0000-0000-0000-000000000001")
            return null;
        return t;
    }

    private static string? HashOrNull(string? raw)
    {
        var clean = Sanitize(raw);
        if (clean is null) return null;
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(clean))).ToLowerInvariant();
    }

    private static string Safe(string? v) =>
        v is null ? "(thiếu)" : (v.Length > 24 ? v[..24] + "…" : v);
}
