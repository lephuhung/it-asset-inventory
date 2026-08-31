using OrgInventoryAgent.Core;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Collectors;
using OrgInventoryAgent.Crypto;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Logging;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Services;
using OrgInventoryAgent.Core.Services;

namespace OrgInventoryAgent;

/// <summary>
/// Agent Windows — IT Asset Inventory (Phase 1 MVP).
/// Chạy như Windows Service (UseWindowsService) khi Windows; console trên Linux (dev/test).
/// CLI flags: --data-dir, --enroll-token, --endpoint, --print-config, --print-fingerprint,
/// --version, --once, --help.
/// </summary>
internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }

        var cli = CliArgs.Parse(args);
        if (cli.ShowHelp)
        {
            PrintHelp();
            return 0;
        }

        try { AppPaths.Initialize(cli.DataDir); }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[fatal] {ex.Message}");
            return 1;
        }

        if (cli.PrintVersion)
        {
            Console.WriteLine($"{AppInfo.Name} v{AppInfo.Version}");
            Console.WriteLine($"Đơn vị phát triển: {AppInfo.Developer}");
            Console.WriteLine($"Mục đích: {AppInfo.Purpose}");
            return 0;
        }

        if (cli.PrintAbout)
        {
            PrintAbout();
            return 0;
        }

        if (cli.PrintFingerprint)
        {
            using var loggerFactory = LoggerFactory.Create(b => b.AddSimpleConsole());
            var fp = new FingerprintCollector(loggerFactory.CreateLogger<FingerprintCollector>()).Collect();
            Console.WriteLine(JsonSerializer.Serialize(fp, new JsonSerializerOptions(Json.Options) { WriteIndented = true }));
            return 0;
        }

        if (cli.PrintInventory)
        {
            using var loggerFactory = LoggerFactory.Create(b => b.AddSimpleConsole());
            var inv = new InventoryCollector(loggerFactory.CreateLogger<InventoryCollector>()).Collect();
            Console.WriteLine(JsonSerializer.Serialize(inv, new JsonSerializerOptions(Json.Options) { WriteIndented = true }));
            return 0;
        }

        if (cli.PrintSecurity)
        {
            using var loggerFactory = LoggerFactory.Create(b => b.AddSimpleConsole());
            var sec = SecurityCollector.Collect(loggerFactory.CreateLogger(nameof(SecurityCollector)));
            Console.WriteLine(JsonSerializer.Serialize(sec, new JsonSerializerOptions(Json.Options) { WriteIndented = true }));
            return 0;
        }

        var config = AgentConfig.Load();

        // Ghi đè endpoint từ CLI (dev/test)
        if (!string.IsNullOrWhiteSpace(cli.Endpoint))
            config.SetPrimaryEndpoint(cli.Endpoint);

        if (cli.InventorySeconds.HasValue)
            config.InventoryIntervalSeconds = cli.InventorySeconds.Value;

        // Token từ CLI được lưu vào config để service retry được (token 1 lần — xóa sau enroll)
        if (!string.IsNullOrWhiteSpace(cli.EnrollToken))
        {
            config.Token = cli.EnrollToken;
            config.Save();
        }

        if (cli.PrintConfig)
        {
            var masked = new
            {
                data_dir = AppPaths.DataDir,
                endpoints = config.Endpoints,
                heartbeat_interval_seconds = config.HeartbeatIntervalSeconds,
                heartbeat_jitter_seconds = config.HeartbeatJitterSeconds,
                inventory_interval_hours = config.InventoryIntervalHours,
                renew_before_percent = config.RenewBeforePercent,
                enrolled = config.Enrolled,
                machine_id = config.MachineId,
                token = config.Token is null ? null : (config.Token.Length > 12 ? config.Token[..4] + "…" : "***"),
                client_cert_thumbprint = config.ClientCertThumbprint,
                cert_store_location = config.CertStoreLocation,
                renew_after = config.RenewAfter,
                http_proxy = config.HttpProxy,
                config_version = config.ConfigVersion,
            };
            Console.WriteLine(JsonSerializer.Serialize(masked, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }

        if (!string.IsNullOrWhiteSpace(cli.ExportBundlePath))
        {
            using var loggerFactory = LoggerFactory.Create(b => b.AddSimpleConsole(o => { o.SingleLine = true; }));
            var logger = loggerFactory.CreateLogger("ExportBundle");
            var ok = await OfflineBundleExporter.ExportBundleAsync(
                cli.ExportBundlePath,
                cli.ServerKeyPath,
                cli.OrgId,
                config,
                logger);
            return ok ? 0 : 1;
        }

        if (cli.Once)
            return await RunOnceAsync(config);

        return await RunServiceAsync(config);
    }

    // ── Chế độ service ────────────────────────────────────────────
    private static async Task<int> RunServiceAsync(AgentConfig config)
    {
        var builder = Host.CreateApplicationBuilder(Array.Empty<string>());

        builder.Logging.ClearProviders();
        builder.Logging.AddSimpleConsole(o =>
        {
            o.SingleLine = true;
            o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' ";
        });
        builder.Logging.AddProvider(new FileLoggerProvider(AppPaths.LogsDir));

        if (OperatingSystem.IsWindows())
            builder.Services.AddWindowsService(o => o.ServiceName = "OrgInventoryAgent");

        RegisterServices(builder, config, hosted: true);

        using var host = builder.Build();

        var startupLogger = host.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Startup");
        startupLogger.LogInformation("================================================================================");
        startupLogger.LogInformation("{Name} v{Version} — {FullTitle}", AppInfo.Name, AppInfo.Version, AppInfo.FullTitle);
        startupLogger.LogInformation("Đơn vị phát triển: {Dev}", AppInfo.Developer);
        startupLogger.LogInformation("Mục đích: {Purpose}", AppInfo.Purpose);
        startupLogger.LogInformation("Cam kết: Chế độ chỉ đọc (Read-only), không thu thập dữ liệu cá nhân, mTLS bảo mật.");
        startupLogger.LogInformation("================================================================================");

        // Enroll sớm ngay khi khởi động (fire-and-forget; HeartbeatService retry nếu lỗi)
        var coordinator = host.Services.GetRequiredService<EnrollCoordinator>();
        _ = Task.Run(() => coordinator.EnsureEnrolledAsync(CancellationToken.None));

        await host.RunAsync();
        return 0;
    }

    // ── Chế độ --once (test/CI trên Linux) ─────────────────────────
    private static async Task<int> RunOnceAsync(AgentConfig config)
    {
        using var loggerFactory = LoggerFactory.Create(b =>
        {
            b.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' "; });
            b.AddProvider(new FileLoggerProvider(AppPaths.LogsDir));
        });

        var logger = loggerFactory.CreateLogger("once");

        // Dựng DI thủ công (không chạy BackgroundService)
        var state = AgentState.Load();
        var keyStore = new KeyStore(loggerFactory.CreateLogger<KeyStore>());
        var endpoints = new EndpointManager(config, loggerFactory.CreateLogger<EndpointManager>());
        var cache = new OfflineCache(loggerFactory.CreateLogger<OfflineCache>());
        var fingerprint = new FingerprintCollector(loggerFactory.CreateLogger<FingerprintCollector>());
        var inventoryCollector = new InventoryCollector(loggerFactory.CreateLogger<InventoryCollector>());
        var api = new ApiClient(config, endpoints, keyStore, loggerFactory.CreateLogger<ApiClient>());
        var enrollClient = new EnrollClient(api, loggerFactory.CreateLogger<EnrollClient>());
        var coordinator = new EnrollCoordinator(config, api, enrollClient, endpoints, keyStore,
            fingerprint, inventoryCollector, state, loggerFactory.CreateLogger<EnrollCoordinator>());

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));

        try
        {
            if (!await coordinator.EnsureEnrolledAsync(cts.Token))
            {
                logger.LogError("--once: enroll chưa thành công — dừng.");
                return 1;
            }

            var configSync = new ConfigSyncService(config, api, coordinator, state, loggerFactory.CreateLogger<ConfigSyncService>());
            var cfgOk = await configSync.SyncAsync(cts.Token);
            logger.LogInformation("--once config sync: {Ok}", cfgOk ? "OK" : "FAIL");

            var inv = new InventoryService(config, api, endpoints, coordinator, cache, inventoryCollector,
                state, loggerFactory.CreateLogger<InventoryService>());
            var hb = new HeartbeatService(config, api, endpoints, coordinator, cache, inventoryCollector, inv, keyStore,
                configSync, state, loggerFactory.CreateLogger<HeartbeatService>());

            var hbOk = await hb.SendOnceAsync(cts.Token);
            logger.LogInformation("--once heartbeat: {Ok}", hbOk ? "OK" : "FAIL");
            var invOk = await inv.SendOnceAsync(cts.Token);
            logger.LogInformation("--once inventory: {Ok}", invOk ? "OK" : "FAIL");

            return hbOk && invOk ? 0 : 2;
        }
        catch (Exception ex)
        {
            logger.LogError("--once lỗi: {Msg}", ex.Message);
            return 1;
        }
        finally
        {
            api.Dispose();
            cache.Dispose();
        }
    }

    private static void RegisterServices(HostApplicationBuilder builder, AgentConfig config, bool hosted)
    {
        builder.Services.AddSingleton(config);
        builder.Services.AddSingleton(AgentState.Load());
        builder.Services.AddSingleton<KeyStore>();
        builder.Services.AddSingleton<IKeyStore>(sp => sp.GetRequiredService<KeyStore>());
        builder.Services.AddSingleton<EndpointManager>();
        builder.Services.AddSingleton<OfflineCache>();
        builder.Services.AddSingleton<FingerprintCollector>();
        builder.Services.AddSingleton<InventoryCollector>();
        builder.Services.AddSingleton<IInventoryProvider>(sp => sp.GetRequiredService<InventoryCollector>());
        builder.Services.AddSingleton<ApiClient>();
        builder.Services.AddSingleton<EnrollClient>();
        builder.Services.AddSingleton<EnrollCoordinator>();
        builder.Services.AddSingleton<HeartbeatService>();
        builder.Services.AddSingleton<InventoryService>();
        builder.Services.AddSingleton<RenewService>();
        builder.Services.AddSingleton<ConfigSyncService>();

        if (hosted)
        {
            builder.Services.AddHostedService(sp => sp.GetRequiredService<HeartbeatService>());
            builder.Services.AddHostedService(sp => sp.GetRequiredService<InventoryService>());
            builder.Services.AddHostedService(sp => sp.GetRequiredService<RenewService>());
            builder.Services.AddHostedService(sp => sp.GetRequiredService<ConfigSyncService>());
        }
    }

    private static void PrintHelp()
    {
        Console.WriteLine($"""
            ================================================================================
              {AppInfo.Name} v{AppInfo.Version}
              {AppInfo.FullTitle}
              Đơn vị phát triển: {AppInfo.Developer}
            ================================================================================

            Mục đích:
              {AppInfo.Purpose}

            Cam kết an toàn & Minh bạch thông tin:
              {AppInfo.TransparencyAndSafetyCommitment.Replace("\n", "\n  ")}

            Sử dụng:
              OrgInventoryAgent [tùy chọn]

            Tùy chọn:
              --data-dir <path>       Thư mục dữ liệu (config/cache/log). Mặc định:
                                      Windows: %ProgramData%\OrgInventory
                                      Linux:   ~/.local/share/OrgInventory
                                      (hoặc env ORGINVENTORY_DATA_DIR)
              --enroll-token <token>  Token enroll (1 lần). Lưu vào config tới khi enroll xong.
              --endpoint <url>        Endpoint server (primary). Ghi đè config.
              --print-config          In cấu hình hiện tại (token được che) rồi thoát.
              --print-fingerprint     Thu thập và in fingerprint 3 nguồn rồi thoát.
              --print-inventory       Thu thập và in toàn bộ JSON Inventory rồi thoát.
              --print-security        Thu thập và in toàn bộ JSON Security Posture rồi thoát.
              --export-bundle <path>  Thu thập, ký số ECDSA và mã hóa lai ra gói ZIP offline rồi thoát.
              --server-key <path>     Đường dẫn file server_public_key.pem (dùng khi export-bundle).
              --org-id <guid>         Mã tổ chức gán cho máy cách ly khi export-bundle.
              --about / --info        In thông tin chi tiết về đơn vị phát triển, mục đích và tính năng.
              --version / -v          In phiên bản và đơn vị phát triển.
              --once                  Chạy 1 lần: enroll → heartbeat → inventory rồi thoát (test/CI).
              --help / -h             Hướng dẫn này.

            Đường dẫn hệ thống:
              Config: %ProgramData%\OrgInventory\config.json (Windows)
              Log:    %ProgramData%\OrgInventory\logs\agent.log
              Cache:  %ProgramData%\OrgInventory\cache.db (SQLite — offline cache)
            """);
    }

    private static void PrintAbout()
    {
        Console.WriteLine($"""
            ================================================================================
              {AppInfo.Name} — Phiên bản {AppInfo.Version}
              {AppInfo.FullTitle}
            ================================================================================

            1. ĐƠN VỊ PHÁT TRIỂN:
               {AppInfo.Developer}
               ({AppInfo.DeveloperShort})

            2. MỤC ĐÍCH SỬ DỤNG:
               {AppInfo.Purpose}

            3. CÁC TÍNH NĂNG CHÍNH:
            """);

        for (int i = 0; i < AppInfo.Features.Length; i++)
        {
            Console.WriteLine($"   {i + 1}. {AppInfo.Features[i]}");
        }

        Console.WriteLine($"""

            4. NGUYÊN TẮC AN TOÀN & MINH BẠCH:
            {AppInfo.TransparencyAndSafetyCommitment}
            ================================================================================
            """);
    }
}

/// <summary>Parse CLI args đơn giản (--key value / --flag).</summary>
internal sealed class CliArgs
{
    public string? DataDir { get; private set; }
    public string? EnrollToken { get; private set; }
    public string? Endpoint { get; private set; }
    public int? InventorySeconds { get; private set; }
    public bool PrintConfig { get; private set; }
    public bool PrintFingerprint { get; private set; }
    public bool PrintInventory { get; private set; }
    public bool PrintSecurity { get; private set; }
    public string? ExportBundlePath { get; private set; }
    public string? ServerKeyPath { get; private set; }
    public string? OrgId { get; private set; }
    public bool PrintAbout { get; private set; }
    public bool PrintVersion { get; private set; }
    public bool Once { get; private set; }
    public bool ShowHelp { get; private set; }

    public static CliArgs Parse(string[] args)
    {
        var cli = new CliArgs();
        for (int i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            string? Next() => i + 1 < args.Length ? args[++i] : null;

            switch (arg)
            {
                case "--data-dir": cli.DataDir = Next(); break;
                case "--enroll-token": cli.EnrollToken = Next(); break;
                case "--endpoint": cli.Endpoint = Next(); break;
                case "--inventory-seconds":
                case "--inventory-interval":
                    if (int.TryParse(Next(), out var sec)) cli.InventorySeconds = sec;
                    break;
                case "--print-config": cli.PrintConfig = true; break;
                case "--print-fingerprint": cli.PrintFingerprint = true; break;
                case "--print-inventory": cli.PrintInventory = true; break;
                case "--print-security": cli.PrintSecurity = true; break;
                case "--export-bundle": cli.ExportBundlePath = Next(); break;
                case "--server-key": cli.ServerKeyPath = Next(); break;
                case "--org-id": cli.OrgId = Next(); break;
                case "--about":
                case "--info":
                    cli.PrintAbout = true;
                    break;
                case "--version":
                case "-v":
                    cli.PrintVersion = true;
                    break;
                case "--once": cli.Once = true; break;
                case "--help":
                case "-h":
                    cli.ShowHelp = true;
                    break;
                default:
                    Console.Error.WriteLine($"[warn] Bỏ qua tham số không biết: {arg}");
                    break;
            }
        }
        return cli;
    }
}
