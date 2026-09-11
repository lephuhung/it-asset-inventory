using OrgInventoryAgent.Core;
using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Build payload inventory v4: hợp nhất flat snapshot (os_name, cpu, ram_gb, ...)
/// + envelope v4 từ LinuxInventoryProvider.Collect() (agent, os, security) +
/// inventory_schema_version = 4 + config_hash (canonical hash của payload
/// trừ chính nó). KHÔNG hard-code field envelope.
///
/// AG-P1-04: Trước fix, payload Linux THIẾU <c>config_hash</c> → server không thể
/// dedupe hoặc phát hiện thay đổi inventory content. Windows đã có từ trước
/// (gọi <see cref="CanonicalJson.Hash"/>). Linux giờ dùng cùng helper ở Core để
/// đảm bảo contract giữa hai platform.
/// </summary>
public static class InventoryPayloadBuilder
{
    public static object Build(LinuxInventoryProvider provider, string loggedUser)
    {
        var envelope = provider.Collect();
        var snapshot = provider.CollectSnapshot();

        // AG-P1-04: build payload trước, sau đó tính canonical hash để fill config_hash
        // (đồng nhất với Windows). Hash này KHÔNG bao gồm config_hash field (exclude).
        var payload = new
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

        // Compute canonical hash excluding config_hash itself (round-trip safe).
        var configHash = CanonicalJson.Hash(payload, excludeProperty: "config_hash");
        return new
        {
            os_name = payload.os_name,
            os_version = payload.os_version,
            os_build = payload.os_build,
            os_arch = payload.os_arch,
            is_vm = payload.is_vm,
            logged_user = payload.logged_user,
            cpu = payload.cpu,
            ram_gb = payload.ram_gb,
            disks = payload.disks,
            gpu = payload.gpu,
            mainboard = payload.mainboard,
            bios = payload.bios,
            network = payload.network,
            installed_software = payload.installed_software,
            security = payload.security,
            agent = payload.agent,
            os = payload.os,
            inventory_schema_version = payload.inventory_schema_version,
            config_hash = configHash,
        };
    }
}