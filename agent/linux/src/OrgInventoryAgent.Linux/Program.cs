using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Collectors.Schema;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Logging;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Linux.Collectors;
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Linux agent entry point — host that loads LinuxInventoryProvider + LinuxKeyStore,
/// enrolls với server nếu chưa có cert, rồi giữ alive (Phase 3 sẽ thêm
/// heartbeat + inventory loops).
/// </summary>
public class Program
{
    public static async Task<int> Main(string[] args)
    {
        // Resolve data dir TRƯỚC khi khởi tạo logger/keyStore — AppPaths cần giá trị
        // hợp lệ để FileLoggerProvider + LinuxKeyStore tạo file đúng chỗ.
        // Ưu tiên: --data-dir arg > ORGINV_DATA_DIR env > /var/lib/orginventory (production)
        // > $HOME/.local/share/OrgInventory (dev fallback).
        string dataDir = args.Length > 0 && args[0] == "--data-dir" && args.Length > 1
            ? args[1]
            : (Environment.GetEnvironmentVariable("ORGINV_DATA_DIR")
               ?? (Directory.Exists("/var/lib/orginventory") ? "/var/lib/orginventory"
                   : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "OrgInventory")));

        // Initialize AppPaths TRƯỚC khi bất kỳ code nào dùng AppPaths.* (FileLoggerProvider, LinuxKeyStore, ...).
        // Nếu không Initialize, DataDir = "" → logger/keyStore tạo file ở CWD = "/" → fail với
        // "Read-only file system" khi chạy qua systemd với ProtectSystem=strict.
        try
        {
            AppPaths.Initialize(dataDir);
        }
        catch (Exception ex)
        {
            // Log ra stderr (FileLogger chưa sẵn sàng nếu Initialize fail).
            Console.Error.WriteLine($"Không thể khởi tạo data dir '{dataDir}': {ex.Message}");
            return 10;
        }

        using var loggerFactory = LoggerFactory.Create(builder =>
        {
            builder.AddSimpleConsole(o => o.SingleLine = true);
            try { builder.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); }
            catch { /* fallback nếu không ghi được file */ }
        });

        var logger = loggerFactory.CreateLogger("OrgInventoryAgent.Linux");
        logger.LogInformation("OrgInventory Agent (Linux) {Version} starting…", AppInfo.Version);
        logger.LogInformation("DataDir = {Dir}", AppPaths.DataDir);

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

        // Giữ process alive khi chạy qua systemd (Type=simple yêu cầu process foreground).
        // Phase 3 sẽ thay thế loop này bằng BackgroundService enroll/heartbeat/inventory.
        // Tạm thời: nếu chưa enroll, thử gọi /api/enroll 1 lần để máy xuất hiện trên Portal.
        await TryEnrollAndHeartbeatOnceAsync(dataDir, inv, fp, logger);

        var stopSignal = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; stopSignal.Cancel(); };
        logger.LogInformation("Agent ready — waiting for Phase 3 services (Ctrl+C để thoát).");
        try
        {
            await Task.Delay(Timeout.Infinite, stopSignal.Token);
        }
        catch (TaskCanceledException) { /* expected */ }
        return 0;
    }

    private static async Task TryEnrollAndHeartbeatOnceAsync(
        string dataDir,
        InventoryEnvelope inv,
        FingerprintPayload fingerprint,
        ILogger logger)
    {
        try
        {
            // Đọc token từ config file (/etc/orginventory/config.json).
            string? token = null;
            string? serverUrl = null;
            string configPath = Path.Combine("/etc/orginventory", "config.json");
            if (File.Exists(configPath))
            {
                using var fs = File.OpenRead(configPath);
                using var doc = JsonDocument.Parse(fs);
                if (doc.RootElement.TryGetProperty("enroll_token", out var t)) token = t.GetString();
                if (doc.RootElement.TryGetProperty("endpoints", out var ep) && ep.ValueKind == JsonValueKind.Array && ep.GetArrayLength() > 0)
                    serverUrl = ep[0].GetString();
            }
            if (string.IsNullOrWhiteSpace(token) || string.IsNullOrWhiteSpace(serverUrl))
            {
                logger.LogWarning("Bỏ qua enroll: config.json thiếu enroll_token hoặc endpoints");
                return;
            }

            // Check cert đã tồn tại chưa — nếu có rồi thì chỉ gửi heartbeat.
            var keyStore = new LinuxKeyStore();
            // Cần machine_id để check; nếu chưa enroll thì machine_id = null.
            string? existingCertPem = null;
            var stateFile = Path.Combine(dataDir, "state.json");
            string? machineId = null;
            if (File.Exists(stateFile))
            {
                using var fs = File.OpenRead(stateFile);
                using var doc = JsonDocument.Parse(fs);
                if (doc.RootElement.TryGetProperty("machine_id", out var m)) machineId = m.GetString();
            }
            if (machineId is not null)
            {
                existingCertPem = keyStore.GetCertificatePem(machineId);
            }

            if (existingCertPem is null)
            {
                logger.LogInformation("Bắt đầu enroll với server {Url} ...", serverUrl);
                using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
                var csrPem = OrgInventoryAgent.Core.Crypto.CsrGenerator.CreateCsrPem(key, $"machine-pending");
                using var http = new HttpClient { BaseAddress = new Uri(serverUrl) };
                var enrollReq = new
                {
                    token,
                    hostname = Dns.GetHostName(),
                    fingerprint = new
                    {
                        smbios_uuid = fingerprint.SmbiosUuid,
                        machine_guid = fingerprint.MachineGuid,
                        mainboard_serial = fingerprint.MainboardSerial,
                    },
                    csr_pem = csrPem,
                };
                var resp = await http.PostAsJsonAsync("/api/enroll", enrollReq);
                var body = await resp.Content.ReadAsStringAsync();
                logger.LogInformation("Enroll HTTP {Status}: {Body}", (int)resp.StatusCode, body);
                if (!resp.IsSuccessStatusCode) return;

                using var enrollDoc = JsonDocument.Parse(body);
                if (!enrollDoc.RootElement.TryGetProperty("machine_id", out var midEl)) return;
                machineId = midEl.GetString();
                var certPem = enrollDoc.RootElement.GetProperty("client_cert_pem").GetString()!;
                var keyPem = key.ExportPkcs8PrivateKeyPem();
                keyStore.InstallCertificate(machineId!, certPem, keyPem);

                // Lưu state (machine_id, endpoints).
                Directory.CreateDirectory(dataDir);
                File.WriteAllText(stateFile, JsonSerializer.Serialize(new
                {
                    machine_id = machineId,
                    enrolled_at = DateTimeOffset.UtcNow,
                }));
                logger.LogInformation("Enroll thành công: machine_id={Id}", machineId);
            }

            // Gửi heartbeat đầu tiên.
            await SendHeartbeatAsync(serverUrl!, machineId!, logger);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Enroll/heartbeat thất bại");
        }
    }

    private static DateTimeOffset _processStartTime = DateTimeOffset.UtcNow;

    private static async Task SendHeartbeatAsync(string serverUrl, string machineId, ILogger logger)
    {
        try
        {
            using var http = new HttpClient { BaseAddress = new Uri(serverUrl) };
            var req = new HttpRequestMessage(HttpMethod.Post, "/api/heartbeat");
            req.Headers.TryAddWithoutValidation("X-Machine-Id", machineId);
            var uptime = (long)(DateTimeOffset.UtcNow - _processStartTime).TotalSeconds;
            // Gửi cert trong body (X-Client-Cert-Pem header không hợp lệ vì PEM có \n gây
            // parse error). Body field sẽ được server bỏ qua trong prod (nginx + mTLS thật),
            // nhưng dev sẽ đọc X-Machine-Id + verify từ DB.
            req.Content = JsonContent.Create(new
            {
                logged_user = Environment.UserName,
                uptime_sec = uptime,
                ip = "127.0.0.1",
            });
            var resp = await http.SendAsync(req);
            var body = await resp.Content.ReadAsStringAsync();
            if (!resp.IsSuccessStatusCode)
                logger.LogWarning("Heartbeat HTTP {Status}: {Body}", (int)resp.StatusCode, body);
            else
                logger.LogInformation("Heartbeat HTTP 200 OK");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Heartbeat lỗi");
        }
    }
}