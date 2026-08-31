using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Build payload inventory v4: hợp nhất flat snapshot (os_name, cpu, ram_gb, ...)
/// + envelope v4 từ LinuxInventoryProvider.Collect() (agent, os, security) +
/// inventory_schema_version = 4. KHÔNG hard-code field envelope.
/// </summary>
public static class InventoryPayloadBuilder
{
    public static object Build(LinuxInventoryProvider provider, string loggedUser)
    {
        var envelope = provider.Collect();
        var snapshot = provider.CollectSnapshot();
        return new
        {
            os_name = snapshot.OsName,
            os_version = snapshot.OsVersion,
            os_build = snapshot.OsBuild,
            os_arch = snapshot.OsArch,
            is_vm = snapshot.IsVm,
            logged_user = loggedUser,
            cpu = snapshot.Cpu,
            ram_gb = snapshot.RamGb,
            disks = snapshot.Disks,
            gpu = snapshot.Gpu,
            mainboard = snapshot.Mainboard,
            bios = snapshot.Bios,
            network = snapshot.Network,
            installed_software = snapshot.InstalledSoftware,
            security = envelope.Security,
            agent = envelope.Agent,
            os = envelope.Os,
            inventory_schema_version = 4,
        };
    }
}