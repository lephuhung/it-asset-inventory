using System.Diagnostics;

namespace OrgInventoryAgent.LinuxHelper.Services;

public static class SmartCollector
{
    private const string SmartctlPath = "/usr/sbin/smartctl";

    /// <summary>
    /// Tham số 'device' phải khớp allowlist path — KHÔNG nhận input tự do.
    /// Chỉ -H (health check) — KHÔNG dump toàn bộ SMART data.
    /// </summary>
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
                FileName = SmartctlPath,
                Arguments = $"-H {device}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(5_000)) { p?.Kill(); return null; }
            var output = p.StandardOutput.ReadToEnd();
            return new
            {
                device,
                health = output.Contains("PASSED", StringComparison.OrdinalIgnoreCase) ? "OK" :
                         output.Contains("FAILED", StringComparison.OrdinalIgnoreCase) ? "PredFail" : "Unknown",
            };
        }
        catch
        {
            return null;
        }
    }
}