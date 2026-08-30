using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Fingerprint đa nguồn trên Linux: product_uuid (sysfs), /etc/machine-id, board_serial.</summary>
public sealed class LinuxFingerprintCollector
{
    private readonly ILogger<LinuxFingerprintCollector> _logger;

    public LinuxFingerprintCollector(ILogger<LinuxFingerprintCollector> logger) => _logger = logger;

    public FingerprintPayload Collect()
    {
        var rawUuid = SafeRead("/sys/class/dmi/id/product_uuid");
        var rawGuid = SafeRead("/etc/machine-id");
        var rawSerial = SafeRead("/sys/class/dmi/id/board_serial");

        _logger.LogDebug("Linux fingerprint: uuid={Uuid}, guid={GuidSrc}, serial={SerialSrc}",
            rawUuid is null ? "(null)" : "set",
            rawGuid is null ? "(null)" : "set",
            rawSerial is null ? "(null)" : "set");

        return new FingerprintPayload
        {
            SmbiosUuid = Sanitize(rawUuid),
            MachineGuid = HashOrNull(rawGuid),
            MainboardSerial = HashOrNull(rawSerial),
        };
    }

    private static string? SafeRead(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            var v = File.ReadAllText(path).Trim();
            return string.IsNullOrWhiteSpace(v) ? null : v;
        }
        catch { return null; }
    }

    private static string? Sanitize(string
? v)
    {
        if (string.IsNullOrWhiteSpace(v)) return null;
        var low = v.Trim().ToLowerInvariant();
        if (low is "none" or "default string" or "to be filled by o.e.m." or "not applicable"
            or "system serial number" or "unknown" or "n/a" or "00000000-0000-0000-0000-000000000000"
            or "00000000-0000-0000-0000-000000000001")
            return null;
        return v.Trim();
    }

    private static string? HashOrNull(string? raw)
    {
        var clean = Sanitize(raw);
        if (clean is null) return null;
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(clean));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}