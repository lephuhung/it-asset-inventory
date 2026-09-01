using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Logging;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux.Crypto;
using OrgInventoryAgent.Linux.Services;
using System.Text.Json;

namespace OrgInventoryAgent.Linux;

public class Program
{
    public static async Task<int> Main(string[] args)
    {
        var cli = CliArgs.Parse(args);

        // AppPaths phải Initialize TRƯỚC khi bất kỳ code nào dùng AppPaths.*
        var dataDir = cli.DataDir
            ?? Environment.GetEnvironmentVariable("ORGINV_DATA_DIR")
            ?? (Directory.Exists("/var/lib/orginventory") ? "/var/lib/orginventory"
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "OrgInventory"));
        try { AppPaths.Initialize(dataDir); }
        catch (Exception ex) { Console.Error.WriteLine($"Không thể khởi tạo data dir '{dataDir}': {ex.Message}"); return 10; }

        if (cli.PrintVersion) { Console.WriteLine($"{AppInfo.Name} v{AppInfo.Version}"); return 0; }
        if (cli.ShowHelp)
        {
            Console.WriteLine($"""
                OrgInventoryAgent v{AppInfo.Version} — Linux Agent
                Sử dụng: OrgInventoryAgent [tùy chọn]
                  --data-dir <path>        Thư mục dữ liệu (config/cache/log)
                  --config <path>          File config.json (mặc định /etc/orginventory/config.json)
                  --enroll-token <token>   Enroll token (lưu vào config, xóa sau enroll)
                  --endpoint <url>         Server URL mTLS
                  --inventory-seconds <n>  Chu kỳ inventory (giây, test)
                  --once                   Enroll (nếu cần) → inventory 1 lần rồi exit
                  --send-inventory         Gửi inventory 1 lần rồi exit (tương đương --once)
                  --print-config           In cấu hình hiện tại
                  --print-inventory        In payload inventory v4 đầy đủ
                  --print-security         In security posture
                  --print-fingerprint      In fingerprint
                  --version, -v            In version
                  --about, --info          In cam kết an toàn
                  --help, -h               In hướng dẫn này
                """);
            return 0;
        }
        if (cli.PrintAbout) { Console.WriteLine(AppInfo.TransparencyAndSafetyCommitment); return 0; }
        if (cli.PrintConfig)
        {
            var cfg = LinuxConfig.Load(cli.ConfigPath);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                data_dir = AppPaths.DataDir,
                config_path = cli.ConfigPath ?? LinuxConfig.DefaultConfigPath,
                endpoints = cfg.Endpoints,
                heartbeat_interval_seconds = cfg.HeartbeatIntervalSeconds,
                heartbeat_jitter_seconds = cfg.HeartbeatJitterSeconds,
                inventory_interval_hours = cfg.InventoryIntervalHours,
                renew_before_percent = cfg.RenewBeforePercent,
                enrolled = cfg.Enrolled,
                machine_id = cfg.MachineId,
                token = cfg.Token is null ? null : (cfg.Token.Length > 12 ? cfg.Token[..4] + "…" : "***"),
                client_cert_thumbprint = cfg.ClientCertThumbprint,
                cert_store_location = cfg.CertStoreLocation,
            }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintInventory)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var provider = new LinuxInventoryProvider(lf.CreateLogger<LinuxInventoryProvider>());
            var snapshot = provider.CollectSnapshot();
            var envelope = provider.Collect();
            Console.WriteLine(JsonSerializer.Serialize(new { envelope, snapshot }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintSecurity)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var sec = LinuxSecurityCollector.Collect(lf.CreateLogger("Security"));
            Console.WriteLine(JsonSerializer.Serialize(sec, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintFingerprint)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var fp = new LinuxFingerprintCollector(lf.CreateLogger<LinuxFingerprintCollector>()).Collect();
            Console.WriteLine(JsonSerializer.Serialize(fp, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }

        var config = LinuxConfig.Load(cli.ConfigPath);
        if (!string.IsNullOrWhiteSpace(cli.Endpoint)) config.SetPrimaryEndpoint(cli.Endpoint);
        if (cli.InventorySeconds.HasValue) config.InventoryIntervalSeconds = cli.InventorySeconds.Value;
        if (!string.IsNullOrWhiteSpace(cli.EnrollToken)) { config.Token = cli.EnrollToken; LinuxConfig.Save(config, cli.ConfigPath); }

        if (cli.Once || cli.SendInventory)
            return await RunOnceAsync(config, cli);

        return await RunServiceAsync(config, cli);
    }

    // ── Service mode ────────────────────────────────────────────
    private static async Task<int> RunServiceAsync(AgentConfig config, CliArgs cli)
    {
        var builder = Host.CreateApplicationBuilder(Array.Empty<string>());
        builder.Logging.ClearProviders();
        builder.Logging.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' "; });
        try { builder.Logging.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); } catch { }

        RegisterServices(builder, config);

        using var host = builder.Build();
        var logger = host.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Startup");
        logger.LogInformation("================================================================================");
        logger.LogInformation("{Name} v{Version} — {FullTitle}", AppInfo.Name, AppInfo.Version, AppInfo.FullTitle);
        logger.LogInformation("Đơn vị phát triển: {Dev}", AppInfo.DeveloperShort);
        logger.LogInformation("DataDir={Dir} Config={Cfg}", AppPaths.DataDir, cli.ConfigPath ?? LinuxConfig.DefaultConfigPath);
        logger.LogInformation("================================================================================");

        var coordinator = host.Services.GetRequiredService<EnrollCoordinator>();
        _ = Task.Run(() => coordinator.EnsureEnrolledAsync(CancellationToken.None));

        await host.RunAsync();
        return 0;
    }

    private static void RegisterServices(HostApplicationBuilder builder, AgentConfig config)
    {
        builder.Services.AddSingleton(config);
        builder.Services.AddSingleton(AgentState.Load());
        builder.Services.AddSingleton<KeyStore>();
        builder.Services.AddSingleton<IKeyStore>(sp => sp.GetRequiredService<KeyStore>());
        builder.Services.AddSingleton<EndpointManager>();
        builder.Services.AddSingleton<OfflineCache>();
        builder.Services.AddSingleton<LinuxFingerprintCollector>();
        builder.Services.AddSingleton<LinuxInventoryProvider>();
        builder.Services.AddSingleton<ApiClient>();
        builder.Services.AddSingleton<EnrollClient>();
        builder.Services.AddSingleton<EnrollCoordinator>();
        builder.Services.AddSingleton<HeartbeatService>();
        builder.Services.AddSingleton<InventoryService>();
        builder.Services.AddSingleton<RenewService>();
        builder.Services.AddSingleton<ConfigSyncService>();
        builder.Services.AddHostedService(sp => sp.GetRequiredService<HeartbeatService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<InventoryService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<RenewService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<ConfigSyncService>());
    }

    // ── Once mode (smoke test install / --send-inventory) ────────
    private static async Task<int> RunOnceAsync(AgentConfig config, CliArgs cli)
    {
        using var loggerFactory = LoggerFactory.Create(b =>
        {
            b.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' "; });
            try { b.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); } catch { }
        });
        var logger = loggerFactory.CreateLogger("Once");
        logger.LogInformation("Chế độ --once: enroll (nếu cần) → heartbeat → inventory.");

        var keyStore = new KeyStore(loggerFactory.CreateLogger<KeyStore>());
        var endpoints = new EndpointManager(config, loggerFactory.CreateLogger<EndpointManager>());
        var api = new ApiClient(config, endpoints, keyStore, loggerFactory.CreateLogger<ApiClient>());
        var enrollClient = new EnrollClient(api, loggerFactory.CreateLogger<EnrollClient>());
        var state = AgentState.Load();
        var fingerprint = new LinuxFingerprintCollector(loggerFactory.CreateLogger<LinuxFingerprintCollector>());
        var enroll = new EnrollCoordinator(config, api, enrollClient, endpoints, keyStore, fingerprint, state,
            loggerFactory.CreateLogger<EnrollCoordinator>());
        var cache = new OfflineCache(loggerFactory.CreateLogger<OfflineCache>());
        var provider = new LinuxInventoryProvider(loggerFactory.CreateLogger<LinuxInventoryProvider>());
        var inventory = new InventoryService(config, api, endpoints, enroll, cache, provider, state,
            loggerFactory.CreateLogger<InventoryService>());

        var ok = await enroll.EnsureEnrolledAsync(CancellationToken.None);
        if (!ok && !AgentIdentity.IsEnrolled(config)) { logger.LogWarning("Chưa enroll được — exit 0 (service sẽ retry)."); return 0; }
        await inventory.SendOnceAsync(CancellationToken.None);
        return 0;
    }
}
