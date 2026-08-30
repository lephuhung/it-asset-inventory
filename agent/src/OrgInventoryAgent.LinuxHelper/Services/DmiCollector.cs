namespace OrgInventoryAgent.LinuxHelper.Services;

public static class DmiCollector
{
    /// <summary>Whitelist field names — KHÔNG cho phép đọc tuỳ ý.</summary>
    private static readonly HashSet<string> AllowedFields = new(StringComparer.Ordinal)
    {
        "product_uuid", "board_serial", "chassis_serial", "bios_version"
    };

    public static object? Collect(string? field)
    {
        if (string.IsNullOrEmpty(field) || !AllowedFields.Contains(field)) return null;
        try
        {
            var path = $"/sys/class/dmi/id/{field}";
            return File.Exists(path) ? File.ReadAllText(path).Trim() : null;
        }
        catch
        {
            return null;
        }
    }
}