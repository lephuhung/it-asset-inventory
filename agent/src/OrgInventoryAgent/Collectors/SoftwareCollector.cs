using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Collectors;

/// <summary>
/// Danh sách phần mềm đã cài — khung Phase 2 (contract: installed_software trong inventory).
/// Đã implement cơ bản: đọc registry Uninstall keys 64-bit + 32-bit (WOW6432Node).
/// Trên Linux trả rỗng (không có registry).
/// </summary>
public static class SoftwareCollector
{
    public static List<SoftwareInfo> Collect(ILogger logger)
    {
        var result = new List<SoftwareInfo>();
        if (!OperatingSystem.IsWindows()) return result;

        var keys = new[]
        {
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        };

        foreach (var path in keys)
        {
            try
            {
                using var root = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(path);
                if (root is null) continue;
                foreach (var subName in root.GetSubKeyNames())
                {
                    try
                    {
                        using var sub = root.OpenSubKey(subName);
                        var displayName = sub?.GetValue("DisplayName")?.ToString();
                        if (string.IsNullOrWhiteSpace(displayName)) continue;
                        var version = sub?.GetValue("DisplayVersion")?.ToString();
                        result.Add(new SoftwareInfo { Name = displayName.Trim(), Version = version });
                    }
                    catch
                    {
                        // bỏ qua key lỗi
                    }
                }
            }
            catch (Exception ex)
            {
                logger.LogDebug("Đọc registry Uninstall {Path} lỗi: {Msg}", path, ex.Message);
            }
        }

        return result
            .GroupBy(s => s.Name, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .OrderBy(s => s.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }
}
