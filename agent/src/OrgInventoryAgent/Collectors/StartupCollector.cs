using Microsoft.Win32;

namespace OrgInventoryAgent.Collectors;

/// <summary>
/// Thu thập danh sách các chương trình/tiến trình khởi động cùng Windows (Startup Programs).
/// Quét từ Registry Run keys của HKLM (64-bit/32-bit) và HKCU.
/// </summary>
public static class StartupCollector
{
    public static List<StartupProgramInfo>? Collect()
    {
        if (!OperatingSystem.IsWindows()) return null;

        var list = new List<StartupProgramInfo>();
        var paths = new (string location, bool isLocalMachine, string path)[]
        {
            ("HKLM_Run", true, @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
            ("HKLM_Run64", true, @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
            ("HKCU_Run", false, @"Software\Microsoft\Windows\CurrentVersion\Run"),
        };

        foreach (var (loc, isLm, subPath) in paths)
        {
            try
            {
                using var root = isLm
                    ? Registry.LocalMachine.OpenSubKey(subPath)
                    : Registry.CurrentUser.OpenSubKey(subPath);
                if (root is null) continue;
                foreach (var name in root.GetValueNames())
                {
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    var cmd = root.GetValue(name)?.ToString();
                    list.Add(new StartupProgramInfo
                    {
                        Name = name,
                        Command = cmd,
                        Location = loc
                    });
                }
            }
            catch { }
        }

        return list
            .GroupBy(p => p.Name, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .OrderBy(p => p.Name, StringComparer.OrdinalIgnoreCase)
            .Take(50)
            .ToList();
    }
}
