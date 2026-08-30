using System.Diagnostics;

namespace OrgInventoryAgent.LinuxHelper.Services;

public static class LUKSCollector
{
    public static object? Collect(string? device)
    {
        if (string.IsNullOrEmpty(device) ||
            !(device.StartsWith("/dev/sd", StringComparison.Ordinal) ||
              device.StartsWith("/dev/nvme", StringComparison.Ordinal) ||
              device.StartsWith("/dev/vd", StringComparison.Ordinal)))
            return null;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/cryptsetup",
                Arguments = $"isLuks {device}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null) return null;
            if (!p.WaitForExit(3_000)) { p.Kill(); return null; }
            return new { device, isLuks = p.ExitCode == 0 };
        }
        catch
        {
            return null;
        }
    }
}