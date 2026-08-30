using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Fingerprint gửi lên server khi enroll (3 nguồn RIÊNG — server tính hash có trọng số).</summary>
public sealed class FingerprintPayload
{
    [JsonPropertyName("smbios_uuid")] public string? SmbiosUuid { get; set; }
    [JsonPropertyName("machine_guid")] public string? MachineGuid { get; set; }
    [JsonPropertyName("mainboard_serial")] public string? MainboardSerial { get; set; }
}

/// <summary>
/// Thu thập fingerprint đa nguồn trên Linux (read-only):
///  - smbios_uuid   ← /sys/class/dmi/id/product_uuid (đọc thẳng; server dùng để match)
///  - machine_guid  ← /etc/machine-id (HASH SHA-256 hex — tránh lộ raw id)
///  - mainboard_serial ← /sys/class/dmi/id/board_serial (HASH SHA-256 hex)
/// Mỗi nguồn bọc try/catch riêng — nguồn nào đọc không được (permission denied,
/// container không có SMBIOS...) thì trả null, server tự xử lý hash có trọng số.
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
        try
        {
            var v = ReadSysFile("/sys/class/dmi/id/product_uuid");
            return v;
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/sys/class/dmi/id/product_uuid không đọc được: {Msg}", ex.Message);
            return null;
        }
    }

    // ── Nguồn 2: Machine ID ───────────────────────────────────────
    private string? ReadMachineGuid()
    {
        try
        {
            if (!File.Exists("/etc/machine-id"))
            {
                _logger.LogDebug("/etc/machine-id không tồn tại (container rất cũ?).");
                return null;
            }
            var v = File.ReadAllText("/etc/machine-id").Trim();
            return string.IsNullOrWhiteSpace(v) ? null : v;
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/etc/machine-id không đọc được: {Msg}", ex.Message);
            return null;
        }
    }

    // ── Nguồn 3: Serial mainboard ─────────────────────────────────
    private string? ReadMainboardSerial()
    {
        try
        {
            return ReadSysFile("/sys/class/dmi/id/board_serial");
        }
        catch (Exception ex)
        {
            _logger.LogDebug("/sys/class/dmi/id/board_serial không đọc được: {Msg}", ex.Message);
            return null;
        }
    }

    // ── Helpers ───────────────────────────────────────────────────

    private static string? ReadSysFile(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            var v = File.ReadAllText(path).Trim();
            return string.IsNullOrWhiteSpace(v) ? null : v;
        }
        catch
        {
            // permission denied / container không có SMBIOS → nguồn bỏ qua
            return null;
        }
    }

    /// <summary>
    /// Bỏ qua các giá trị placeholder của BIOS/mainboard (chính hãng chưa set serial
    /// hoặc ảo hóa không xuất serial thật) — coi như nguồn thiếu.
    /// </summary>
    private static string? Sanitize(string? v)
    {
        if (string.IsNullOrWhiteSpace(v)) return null;
        var t = v.Trim();
        var low = t.ToLowerInvariant();
        if (low is "none" or "default string" or "to be filled by o.e.m." or "not applicable"
            or "system serial number" or "unknown" or "n/a" or "00000000-0000-0000-0000-000000000000"
            or "00000000-0000-0000-0000-000000000001" or "no asset information")
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