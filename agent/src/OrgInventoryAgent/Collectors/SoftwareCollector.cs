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

        // Quét HKLM (64-bit + 32-bit)
        var lmKeys = new[]
        {
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        };

        foreach (var path in lmKeys)
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
                        var displayName = sub?.GetValue("DisplayName")?.ToString()?.Trim();
                        if (string.IsNullOrWhiteSpace(displayName)) continue;
                        var version = sub?.GetValue("DisplayVersion")?.ToString()?.Trim();
                        var publisher = sub?.GetValue("Publisher")?.ToString()?.Trim();
                        var installDate = sub?.GetValue("InstallDate")?.ToString()?.Trim();
                        var uninstall = sub?.GetValue("UninstallString")?.ToString()?.Trim();

                        result.Add(new SoftwareInfo
                        {
                            DisplayName = displayName,
                            Name = displayName,
                            Version = version,
                            Publisher = publisher,
                            InstallDate = installDate,
                            UninstallString = uninstall,
                            IsPerUser = false
                        });
                    }
                    catch
                    {
                        // bỏ qua key lỗi
                    }
                }
            }
            catch (Exception ex)
            {
                logger.LogDebug("Đọc HKLM Uninstall {Path} lỗi: {Msg}", path, ex.Message);
            }
        }

        // Quét HKCU (phần mềm cài per-user: VS Code, Teams, Spotify...)
        try
        {
            using var root = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Uninstall");
            if (root is not null)
            {
                foreach (var subName in root.GetSubKeyNames())
                {
                    try
                    {
                        using var sub = root.OpenSubKey(subName);
                        var displayName = sub?.GetValue("DisplayName")?.ToString()?.Trim();
                        if (string.IsNullOrWhiteSpace(displayName)) continue;
                        var version = sub?.GetValue("DisplayVersion")?.ToString()?.Trim();
                        var publisher = sub?.GetValue("Publisher")?.ToString()?.Trim();
                        var installDate = sub?.GetValue("InstallDate")?.ToString()?.Trim();
                        var uninstall = sub?.GetValue("UninstallString")?.ToString()?.Trim();

                        result.Add(new SoftwareInfo
                        {
                            DisplayName = displayName,
                            Name = displayName,
                            Version = version,
                            Publisher = publisher,
                            InstallDate = installDate,
                            UninstallString = uninstall,
                            IsPerUser = true
                        });
                    }
                    catch { }
                }
            }
        }
        catch (Exception ex)
        {
            logger.LogDebug("Đọc HKCU Uninstall lỗi: {Msg}", ex.Message);
        }

        return result
            .GroupBy(s => s.DisplayName ?? s.Name, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .OrderBy(s => s.DisplayName ?? s.Name, StringComparer.OrdinalIgnoreCase)
            .Take(500)
            .ToList();
    }
}
