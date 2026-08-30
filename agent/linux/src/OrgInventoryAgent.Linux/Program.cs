using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Logging;
using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Linux agent entry point — minimal host that loads LinuxInventoryProvider + LinuxKeyStore.
/// Phase 4 will add systemd service registration + heartbeat/inventory/enroll orchestration.
/// </summary>
public class Program
{
    public static async Task<int> Main(string[] args)
    {
        using var loggerFactory = LoggerFactory.Create(builder =>
        {
            builder.AddSimpleConsole(o => o.SingleLine = true);
            try { builder.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); }
            catch { /* fallback nếu không ghi được file */ }
        });

        var logger = loggerFactory.CreateLogger("OrgInventoryAgent.Linux");
        logger.LogInformation("OrgInventory Agent (Linux) {Version} starting…", AppInfo.Version);

        // Resolve data dir: --data-dir arg > ORGINV_DATA_DIR env > /var/lib/orginventory (default production) > $HOME/.local/share/OrgInventory (dev fallback).
        string dataDir = args.Length > 0 && args[0] == "--data-dir" && args.Length > 1
            ? args[1]
            : (Environment.GetEnvironmentVariable("ORGINV_DATA_DIR")
               ?? (Directory.Exists("/var/lib/orginventory") ? "/var/lib/orginventory"
                   : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "OrgInventory")));
        try { Directory.CreateDirectory(dataDir); }
        catch (Exception ex) { logger.LogWarning("Không tạo được data dir {Dir}: {Msg}", dataDir, ex.Message); }

        var provider = new LinuxInventoryProvider(
            loggerFactory.CreateLogger<LinuxInventoryProvider>());
        var inv = provider.Collect();
        logger.LogInformation("Inventory envelope built: schema={Schema} agent={Agent}/{Version} OS={Os}",
            inv.InventorySchemaVersion,
            inv.Agent.Platform, inv.Agent.Version,
            inv.Os.Distribution);

        // Sanity log to verify LinuxKeyStore + AppPaths production path.
        var keystore = new LinuxKeyStore();
        logger.LogInformation("LinuxKeyStore certDir={CertDir}", Environment.GetEnvironmentVariable("ORGINV_CERT_DIR")
            ?? Path.Combine(dataDir, "certs"));

        // Quick self-test: collect fingerprint
        var fp = new LinuxFingerprintCollector(
            loggerFactory.CreateLogger<LinuxFingerprintCollector>()).Collect();
        logger.LogInformation("Fingerprint: smbios_uuid={Uuid} machine_guid_hash={Guid} mainboard_serial_hash={Serial}",
            fp.SmbiosUuid is null ? "(null)" : "set",
            fp.MachineGuid is null ? "(null)" : "set",
            fp.MainboardSerial is null ? "(null)" : "set");

        // Optional: --print-inventory dumps the full v4 envelope to stdout.
        if (args.Length > 0 && args[0] == "--print-inventory")
        {
            var snapshot = provider.CollectSnapshot();
            var envelope = new OrgInventoryAgent.Core.Collectors.Schema.InventoryEnvelope
            {
                Agent = inv.Agent,
                Os = inv.Os,
                Security = inv.Security,
            };
            var json = System.Text.Json.JsonSerializer.Serialize(new { envelope, snapshot },
                new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
            Console.WriteLine(json);
        }

        await Task.CompletedTask;
        return 0;
    }
}