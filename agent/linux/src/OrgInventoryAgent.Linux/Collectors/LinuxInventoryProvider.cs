using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>
/// OS-specific collector for Linux. Builds a v4 InventoryEnvelope populated
/// with agent metadata, OS metadata, and SecurityPostureV4 from Linux collectors.
/// Hardware/software fields live in <see cref="InventorySnapshot"/> (flat schema) —
/// exposed via <see cref="CollectSnapshot"/> for callers that still need the flat shape.
/// </summary>
public sealed class LinuxInventoryProvider : IInventoryProvider
{
    private readonly ILogger<LinuxInventoryProvider> _logger;

    public LinuxInventoryProvider(ILogger<LinuxInventoryProvider> logger) => _logger = logger;

    public InventoryEnvelope Collect()
    {
        var arch = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant(); // x64 | arm64
        var pkgType = DetectPackageType();

        return new InventoryEnvelope
        {
            Agent = new AgentMetadata
            {
                Name = AppInfo.Name,
                Version = AppInfo.Version,
                Runtime = ".NET 8.0",
                Platform = "linux",
                Architecture = arch,
                PackageType = pkgType,
            },
            Os = ReadOsMetadata(arch),
            Security = LinuxSecurityCollector.Collect(_logger),
        };
    }

    /// <summary>Collect flat InventorySnapshot (CPU, RAM, disks, network, software, etc.) — Linux equivalent of Windows collector.</summary>
    public InventorySnapshot CollectSnapshot()
    {
        var arch = RuntimeInformation.OSArchitecture.ToString().ToLowerInvariant();
        return new InventorySnapshot
        {
            OsName = ReadPrettyName(),
            OsVersion = ReadOsMetadata(arch).DistributionVersion,
            OsBuild = ReadOsMetadata(arch).KernelVersion,
            OsArch = arch,
            Cpu = LinuxOsCollector.GetCpu(),
            RamGb = LinuxOsCollector.GetRamGb(),
            Disks = LinuxOsCollector.GetDisks(),
            Gpu = LinuxOsCollector.GetGpuModel() is { } gpu ? new GpuInfo { Model = gpu } : null,
            Mainboard = LinuxOsCollector.GetMainboard(),
            Bios = LinuxOsCollector.GetBios(),
            Network = LinuxNetworkCollector.Collect(),
            LoggedUser = LinuxOsCollector.GetLoggedUser(),
            InstalledSoftware = LinuxSoftwareCollector.Collect(_logger),
            Security = LinuxSecurityCollector.Collect(_logger),
            IsVm = LinuxOsCollector.GetIsVm(),
        };
    }

    private static string? DetectPackageType()
    {
        if (File.Exists("/etc/debian_version")) return "deb";
        if (File.Exists("/etc/redhat-release")) return "rpm";
        try
        {
            if (File.Exists("/etc/os-release"))
            {
                var content = File.ReadAllText("/etc/os-release").ToLowerInvariant();
                if (content.Contains("rhel") || content.Contains("rocky") ||
                    content.Contains("almalinux") || content.Contains("fedora") ||
                    content.Contains("centos"))
                    return "rpm";
                if (content.Contains("ubuntu") || content.Contains("debian"))
                    return "deb";
            }
        }
        catch { }
        return null;
    }

    private static string? ReadPrettyName()
    {
        try
        {
            foreach (var line in File.ReadAllLines("/etc/os-release"))
            {
                if (line.StartsWith("PRETTY_NAME=", StringComparison.Ordinal))
                    return line.Substring("PRETTY_NAME=".Length).Trim('"');
            }
        }
        catch { }
        return null;
    }

    private static OsMetadata ReadOsMetadata(string arch)
    {
        var meta = new OsMetadata { Platform = "linux", Architecture = arch };
        try
        {
            if (File.Exists("/etc/os-release"))
            {
                foreach (var line in File.ReadAllLines("/etc/os-release"))
                {
                    var parts = line.Split('=', 2);
                    if (parts.Length != 2) continue;
                    var v = parts[1].Trim('"');
                    switch (parts[0])
                    {
                        case "ID": meta.Distribution = v; break;
                        case "VERSION_ID": meta.DistributionVersion = v; break;
                    }
                }
            }
            meta.KernelVersion = SafeRead("/proc/sys/kernel/osrelease");
        }
        catch { }
        return meta;
    }

    private static string? SafeRead(string path)
    {
        try { return File.Exists(path) ? File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }
}