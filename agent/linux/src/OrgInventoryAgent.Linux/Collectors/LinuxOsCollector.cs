using System.Runtime.InteropServices;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxOsCollector
{
    public static CpuInfo? GetCpu() => new()
    {
        Model = SafeRead("/proc/cpuinfo")?.Split('\n')
            .FirstOrDefault(l => l.StartsWith("model name", StringComparison.Ordinal))
            ?.Split(':', 2)[1].Trim(),
        Cores = Environment.ProcessorCount,
    };

    public static double? GetRamGb()
    {
        try
        {
            foreach (var line in File.ReadLines("/proc/meminfo"))
            {
                if (!line.StartsWith("MemTotal:", StringComparison.Ordinal)) continue;
                var kb = long.Parse(line.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1]);
                return Math.Round(kb / (1024.0 * 1024.0), 1);
            }
        }
        catch { }
        return null;
    }

    public static List<DiskInfo>? GetDisks()
    {
        var disks = new List<DiskInfo>();
        if (!Directory.Exists("/sys/block")) return null;
        foreach (var dir in Directory.GetDirectories("/sys/block"))
        {
            var name = Path.GetFileName(dir);
            if (name.StartsWith("loop", StringComparison.Ordinal) ||
                name.StartsWith("ram", StringComparison.Ordinal) ||
                name.StartsWith("fd", StringComparison.Ordinal)) continue;
            var model = SafeRead(Path.Combine(dir, "device", "model")) ?? name;
            var sectors = SafeRead(Path.Combine(dir, "size"));
            if (sectors is null || !long.TryParse(sectors, out var s) || s == 0) continue;
            var bytes = s * 512L;
            var type = model.Contains("nvme", StringComparison.OrdinalIgnoreCase) || model.Contains("ssd", StringComparison.OrdinalIgnoreCase)
                ? "SSD" : "HDD";
            disks.Add(new DiskInfo
            {
                Model = model,
                Serial = SafeRead(Path.Combine(dir, "device", "serial")),
                SizeBytes = bytes,
                SizeGb = Math.Round(bytes / (1024.0 * 1024.0 * 1024.0), 0),
                Type = type,
            });
        }
        return disks.Count > 0 ? disks : null;
    }

    public static MainboardInfo? GetMainboard()
    {
        var vendor = SafeRead("/sys/class/dmi/id/board_vendor");
        var name = SafeRead("/sys/class/dmi/id/board_name");
        var model = string.Join(" ", new[] { vendor, name }.Where(s => !string.IsNullOrWhiteSpace(s)));
        var serial = SafeRead("/sys/class/dmi/id/board_serial");
        if (string.IsNullOrWhiteSpace(model) && string.IsNullOrWhiteSpace(serial)) return null;
        return new MainboardInfo
        {
            Model = string.IsNullOrWhiteSpace(model) ? null : model,
            Serial = serial,
        };
    }

    public static BiosInfo? GetBios() => SafeRead("/sys/class/dmi/id/bios_version") is { } v
        ? new BiosInfo { Version = v } : null;

    public static string? GetGpuModel()
    {
        try
        {
            foreach (var dir in Directory.GetDirectories("/sys/class/drm"))
            {
                var name = Path.GetFileName(dir);
                if (!name.StartsWith("card", StringComparison.Ordinal)) continue;
                var model = SafeRead(Path.Combine(dir, "device", "label"));
                if (model is null) continue;
                return model;
            }
        }
        catch { }
        return null;
    }

    public static bool? GetIsVm()
    {
        var markers = new[] { "vmware", "virtualbox", "qemu", "kvm", "hyper-v", "virtual machine", "xen", "innotek" };
        var vendor = SafeRead("/sys/class/dmi/id/sys_vendor")?.ToLowerInvariant() ?? "";
        var product = SafeRead("/sys/class/dmi/id/product_name")?.ToLowerInvariant() ?? "";
        var haystack = $"{vendor} {product}";
        if (string.IsNullOrWhiteSpace(haystack)) return null;
        return markers.Any(m => haystack.Contains(m, StringComparison.OrdinalIgnoreCase));
    }

    public static string? GetLoggedUser()
    {
        try
        {
            // Read /proc/self/loginuid — current login uid
            if (File.Exists("/proc/self/loginuid"))
            {
                var uid = File.ReadAllText("/proc/self/loginuid").Trim();
                if (uid != "4294967295" && int.TryParse(uid, out var u) && u > 0)
                {
                    var pw = File.ReadAllLines("/etc/passwd");
                    foreach (var line in pw)
                    {
                        var parts = line.Split(':');
                        if (parts.Length >= 3 && int.TryParse(parts[2], out var p) && p == u)
                            return Environment.UserName;
                    }
                }
            }
        }
        catch { }
        return Environment.UserName;
    }

    private static string? SafeRead(string path)
    {
        try { return File.Exists(path) ? File.ReadAllText(path).Trim() : null; }
        catch { return null; }
    }
}