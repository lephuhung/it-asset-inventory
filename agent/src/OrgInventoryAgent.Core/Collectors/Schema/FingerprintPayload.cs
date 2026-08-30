using System.Text.Json.Serialization;

namespace OrgInventoryAgent.Core.Collectors.Schema;

/// <summary>
/// Fingerprint gửi lên server khi enroll (3 nguồn RIÊNG — server tính hash có trọng số).
/// Pure DTO, không phụ thuộc OS. FingerprintCollector OS-specific nằm trong Windows/Linux project.
/// </summary>
public sealed class FingerprintPayload
{
    [JsonPropertyName("smbios_uuid")] public string? SmbiosUuid { get; set; }
    [JsonPropertyName("machine_guid")] public string? MachineGuid { get; set; }
    [JsonPropertyName("mainboard_serial")] public string? MainboardSerial { get; set; }
}
