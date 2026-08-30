using System.Text.Json.Serialization;

namespace OrgInventoryAgent.Core.Collectors.Schema;

/// <summary>
/// Snapshot inventory envelope — schema v4 (multi-platform, additive optional).
/// Server fallback về các trường phẳng hiện tại khi thiếu (agent Windows cũ).
/// </summary>
public sealed class InventoryEnvelope
{
    [JsonPropertyName("inventory_schema_version")]
    public int InventorySchemaVersion { get; set; } = 4;

    [JsonPropertyName("agent")]
    public AgentMetadata Agent { get; set; } = new();

    [JsonPropertyName("os")]
    public OsMetadata Os { get; set; } = new();

    // Trường phẳng hiện có (cpu, ram_gb, disks, gpu, mainboard, bios, network,
    // logged_user, installed_software, is_vm, config_hash, activation_status)
    // được thêm từ collector OS-specific.
    [JsonPropertyName("security")]
    public SecurityPostureV4 Security { get; set; } = new();
}

public sealed class AgentMetadata
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "OrgInventoryAgent";

    [JsonPropertyName("version")]
    public string Version { get; set; } = "";

    [JsonPropertyName("runtime")]
    public string Runtime { get; set; } = ".NET 8.0";

    /// <summary>"windows" | "linux"</summary>
    [JsonPropertyName("platform")]
    public string Platform { get; set; } = "";

    /// <summary>"x64" | "arm64"</summary>
    [JsonPropertyName("architecture")]
    public string Architecture { get; set; } = "";

    /// <summary>"msi" | "deb" | "rpm" | null.</summary>
    [JsonPropertyName("package_type")]
    public string? PackageType { get; set; }
}

public sealed class OsMetadata
{
    [JsonPropertyName("platform")]
    public string Platform { get; set; } = "";

    [JsonPropertyName("distribution")]
    public string? Distribution { get; set; }

    [JsonPropertyName("distribution_version")]
    public string? DistributionVersion { get; set; }

    [JsonPropertyName("kernel_version")]
    public string? KernelVersion { get; set; }

    [JsonPropertyName("architecture")]
    public string? Architecture { get; set; }

    [JsonPropertyName("subscription")]
    public string? Subscription { get; set; }
}

public sealed class SecurityPostureV4
{
    // Trường phẳng (giữ tương thích schema cũ)
    [JsonPropertyName("antivirus")]
    public List<AntivirusInfo>? Antivirus { get; set; }

    [JsonPropertyName("windows_update_status")]
    public string? WindowsUpdateStatus { get; set; }

    [JsonPropertyName("bitlocker")]
    public string? Bitlocker { get; set; }

    [JsonPropertyName("rdp_enabled")]
    public bool? RdpEnabled { get; set; }

    [JsonPropertyName("firewall_enabled")]
    public bool? FirewallEnabled { get; set; }

    [JsonPropertyName("uac_enabled")]
    public bool? UacEnabled { get; set; }

    [JsonPropertyName("secure_boot_enabled")]
    public bool? SecureBootEnabled { get; set; }

    [JsonPropertyName("usb_storage_blocked")]
    public bool? UsbStorageBlocked { get; set; }

    [JsonPropertyName("weak_protocols")]
    public WeakProtocolsInfo? WeakProtocols { get; set; }

    [JsonPropertyName("listening_ports")]
    public List<ListeningPortInfo>? ListeningPorts { get; set; }

    [JsonPropertyName("startup_programs")]
    public List<StartupProgramInfo>? StartupPrograms { get; set; }

    [JsonPropertyName("local_accounts")]
    public List<LocalAccountInfo>? LocalAccounts { get; set; }

    [JsonPropertyName("smarts")]
    public List<object>? Smarts { get; set; }

    // Object đa nền tảng (schema v4)
    [JsonPropertyName("update")]
    public UpdateStatus Update { get; set; } = new();

    [JsonPropertyName("disk_encryption")]
    public DiskEncryptionStatus DiskEncryption { get; set; } = new();

    [JsonPropertyName("remote_access")]
    public RemoteAccessStatus RemoteAccess { get; set; } = new();

    [JsonPropertyName("privilege_control")]
    public PrivilegeControlStatus PrivilegeControl { get; set; } = new();
}

public sealed class UpdateStatus
{
    /// <summary>"up-to-date" | "updates-available" | "outdated" | "unknown"</summary>
    [JsonPropertyName("status")]
    public string Status { get; set; } = "unknown";

    [JsonPropertyName("enabled")]
    public bool? Enabled { get; set; }

    [JsonPropertyName("pending_count")]
    public int? PendingCount { get; set; }

    [JsonPropertyName("security_pending_count")]
    public int? SecurityPendingCount { get; set; }

    [JsonPropertyName("reboot_required")]
    public bool? RebootRequired { get; set; }

    [JsonPropertyName("last_updated_at")]
    public string? LastUpdatedAt { get; set; }
}

public sealed class DiskEncryptionStatus
{
    [JsonPropertyName("enabled")]
    public bool? Enabled { get; set; }

    /// <summary>"bitlocker" | "luks" | "none" | null</summary>
    [JsonPropertyName("technology")]
    public string? Technology { get; set; }

    [JsonPropertyName("encrypted_volumes")]
    public List<string>? EncryptedVolumes { get; set; }
}

public sealed class RemoteAccessStatus
{
    [JsonPropertyName("ssh_enabled")]
    public bool? SshEnabled { get; set; }

    [JsonPropertyName("remote_desktop_enabled")]
    public bool? RemoteDesktopEnabled { get; set; }

    [JsonPropertyName("services")]
    public List<string>? Services { get; set; }
}

public sealed class PrivilegeControlStatus
{
    [JsonPropertyName("sudo_installed")]
    public bool? SudoInstalled { get; set; }

    [JsonPropertyName("root_account_locked")]
    public bool? RootAccountLocked { get; set; }
}

// ── DTO shared — copy nguyên từ src/OrgInventoryAgent/Collectors/InventoryCollector.cs ──
// (giữ nguyên tên class + JsonPropertyName để server schema tương thích)

public sealed class AntivirusInfo
{
    [JsonPropertyName("displayName")]
    public string? DisplayName { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    /// <summary>"enabled" | "disabled"</summary>
    [JsonPropertyName("status")]
    public string? Status { get; set; }

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("upToDate")]
    public bool UpToDate { get; set; }
}

public sealed class LocalAccountInfo
{
    [JsonPropertyName("username")]
    public string? Username { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("full_name")]
    public string? FullName { get; set; }

    [JsonPropertyName("disabled")]
    public bool Disabled { get; set; }

    [JsonPropertyName("has_password")]
    public bool? HasPassword { get; set; }

    [JsonPropertyName("is_admin")]
    public bool IsAdmin { get; set; }
}

public sealed class ListeningPortInfo
{
    [JsonPropertyName("port")]
    public int Port { get; set; }

    [JsonPropertyName("protocol")]
    public string Protocol { get; set; } = "TCP";

    [JsonPropertyName("address")]
    public string? Address { get; set; }
}

public sealed class StartupProgramInfo
{
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("command")]
    public string? Command { get; set; }

    [JsonPropertyName("location")]
    public string? Location { get; set; }
}

public sealed class WeakProtocolsInfo
{
    [JsonPropertyName("smbv1_disabled")]
    public bool Smbv1Disabled { get; set; } = true;

    [JsonPropertyName("tls10_disabled")]
    public bool Tls10Disabled { get; set; } = true;

    [JsonPropertyName("tls11_disabled")]
    public bool Tls11Disabled { get; set; } = true;

    [JsonPropertyName("ssl3_disabled")]
    public bool Ssl3Disabled { get; set; } = true;
}
