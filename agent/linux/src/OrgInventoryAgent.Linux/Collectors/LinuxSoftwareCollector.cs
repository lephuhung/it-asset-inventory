using System.Diagnostics;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Dùng dpkg-query cho Debian/Ubuntu và rpm cho RHEL/CentOS.</summary>
public static class LinuxSoftwareCollector
{
    public static List<SoftwareInfo> Collect(ILogger logger)
    {
        if (File.Exists("/etc/debian_version")) return Dpkg(logger);
        if (File.Exists("/etc/redhat-release")) return Rpm(logger);
        return new();
    }

    private static List<SoftwareInfo> Dpkg(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/dpkg-query",
                Arguments = "-W -f='${Package}\\t${Version}\\t${Maintainer}\\n'",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(15_000)) { p?.Kill(); return new(); }
            var list = new List<SoftwareInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                var parts = line.Split('\t');
                if (parts.Length < 3 || string.IsNullOrWhiteSpace(parts[0])) continue;
                list.Add(new SoftwareInfo
                {
                    DisplayName = parts[0],
                    Name = parts[0],
                    Version = parts[1],
                    Publisher = parts[2],
                    IsPerUser = false,
                });
                if (list.Count >= 500) break;
            }
            return list;
        }
        catch (Exception ex)
        {
            logger.LogDebug("dpkg-query lỗi: {Msg}", ex.Message);
            return new();
        }
    }

    private static List<SoftwareInfo> Rpm(ILogger logger)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/usr/bin/rpm",
                Arguments = "-qa --queryformat '%{NAME}\\t%{VERSION}\\t%{VENDOR}\\n'",
                RedirectStandardOutput = true,
                UseShellExecute = false,
            };
            using var p = Process.Start(psi);
            if (p is null || !p.WaitForExit(15_000)) { p?.Kill(); return new(); }
            var list = new List<SoftwareInfo>();
            foreach (var line in p.StandardOutput.ReadToEnd().Split('\n'))
            {
                var parts = line.Split('\t');
                if (parts.Length < 3 || string.IsNullOrWhiteSpace(parts[0])) continue;
                list.Add(new SoftwareInfo
                {
                    DisplayName = parts[0],
                    Name = parts[0],
                    Version = parts[1],
                    Publisher = parts[2],
                    IsPerUser = false,
                });
                if (list.Count >= 500) break;
            }
            return list;
        }
        catch (Exception ex)
        {
            logger.LogDebug("rpm -qa lỗi: {Msg}", ex.Message);
            return new();
        }
    }
}