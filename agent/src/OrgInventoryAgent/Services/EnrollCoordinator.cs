using System.Net;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Collectors;
using OrgInventoryAgent.Crypto;
using OrgInventoryAgent.Net;

namespace OrgInventoryAgent.Services;

/// <summary>
/// Điều phối enrollment: token + fingerprint + CSR → server ký → cài cert → lưu config.
/// - Idempotent: đã enroll (cert + machine_id) → bỏ qua, không tạo máy trùng.
/// - Token lấy từ: config.Token (MSI ghi / --enroll-token / config.json).
/// - Retry: service gọi lại khi chưa enroll (backoff nội bộ).
/// </summary>
public sealed class EnrollCoordinator
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollClient _enrollClient;
    private readonly EndpointManager _endpoints;
    private readonly KeyStore _keyStore;
    private readonly FingerprintCollector _fingerprint;
    private readonly InventoryCollector _inventory;
    private readonly AgentState _state;
    private readonly ILogger<EnrollCoordinator> _logger;

    private readonly object _lock = new();
    private bool _inFlight;
    private DateTimeOffset _lastAttempt = DateTimeOffset.MinValue;

    public EnrollCoordinator(AgentConfig config, ApiClient api, EnrollClient enrollClient,
        EndpointManager endpoints, KeyStore keyStore, FingerprintCollector fingerprint,
        InventoryCollector inventory, AgentState state, ILogger<EnrollCoordinator> logger)
    {
        _config = config;
        _api = api;
        _enrollClient = enrollClient;
        _endpoints = endpoints;
        _keyStore = keyStore;
        _fingerprint = fingerprint;
        _inventory = inventory;
        _state = state;
        _logger = logger;
    }

    /// <summary>
    /// Đảm bảo đã enroll. Trả true nếu enroll thành công (hoặc đã enroll từ trước).
    /// Tối đa 1 attempt/60s (tránh spam server khi token sai).
    /// </summary>
    public async Task<bool> EnsureEnrolledAsync(CancellationToken ct)
    {
        if (AgentIdentity.IsEnrolled(_config)) return true;

        lock (_lock)
        {
            if (_inFlight) return false;
            if (DateTimeOffset.UtcNow - _lastAttempt < TimeSpan.FromSeconds(60)) return false;
            _inFlight = true;
            _lastAttempt = DateTimeOffset.UtcNow;
        }

        try
        {
            return await EnrollCoreAsync(ct);
        }
        finally
        {
            lock (_lock) _inFlight = false;
        }
    }

    private async Task<bool> EnrollCoreAsync(CancellationToken ct)
    {
        var token = _config.Token;
        if (string.IsNullOrWhiteSpace(token))
        {
            _logger.LogCritical("Chưa có enroll token — cài qua MSI với ENROLL_TOKEN=... hoặc ghi config.json (field \"token\").");
            return false;
        }

        if (_endpoints.Current is null)
        {
            _logger.LogCritical("Chưa có endpoint server — truyền --endpoint, ghi config.json (field \"endpoints\") hoặc qua MSI property ENDPOINTS.");
            return false;
        }

        _logger.LogInformation("Bắt đầu enroll tới {Endpoint}...", _endpoints.Current);

        // Sinh keypair ECDSA P-256 local — private key KHÔNG bao giờ gửi lên server
        using var key = CsrGenerator.CreateKeyPair();
        _config.CsrCnPlaceholder ??= "machine-" + Guid.NewGuid();
        var csrPem = CsrGenerator.CreateCsrPem(key, _config.CsrCnPlaceholder);

        var fingerprint = _fingerprint.Collect();
        var request = new EnrollRequestPayload
        {
            Token = token,
            Hostname = SafeHostname(),
            Fingerprint = fingerprint,
            CsrPem = csrPem,
        };

        EnrollResponse? response;
        try
        {
            response = await _enrollClient.EnrollAsync(request, ct);
        }
        catch (ApiTransportException ex)
        {
            _logger.LogError("Không kết nối được server enroll: {Msg}", ex.Message);
            return false;
        }

        if (response is null || string.IsNullOrWhiteSpace(response.MachineId) || string.IsNullOrWhiteSpace(response.ClientCertPem))
        {
            _logger.LogError("Enroll không thành công — thử lại ở chu kỳ sau.");
            return false;
        }

        // Cài cert + private key vào store (Windows) / file (Linux)
        _keyStore.InstallCertificate(response.ClientCertPem, key, _config);

        _config.MachineId = response.MachineId;
        _config.Enrolled = true;
        _config.RenewAfter = response.RenewAfter;
        _config.LastEnrolledAt = DateTimeOffset.UtcNow;

        // Lưu config server trả về (endpoint + interval/jitter + inventory interval)
        var changed = _config.ApplyServerSettings(
            response.AgentServerUrl,
            response.HeartbeatIntervalSeconds,
            response.HeartbeatJitterSeconds,
            response.InventoryIntervalHours,
            null);

        // Ghi CA cert nếu server trả (audit; không bắt buộc trust vì verify theo hệ thống trust)
        if (!string.IsNullOrWhiteSpace(response.CaCertPem))
        {
            try { File.WriteAllText(Path.Combine(AppPaths.DataDir, "ca-cert.pem"), response.CaCertPem); }
            catch { }
        }

        // Token dùng 1 lần — xóa ngay sau enroll thành công
        _config.Token = null;
        _config.Save();

        _logger.LogInformation("Enroll thành công: machine_id={MachineId}, is_new={IsNew}, status={Status}, server={Server}",
            response.MachineId, response.IsNewMachine, response.Status, _config.PrimaryEndpoint);

        // Tải cấu hình đầy đủ từ /api/agent/config bằng client cert mTLS vừa cài
        try
        {
            var cfgResp = await _api.GetJsonAsync("/api/agent/config", ct, useClientCert: true, timeoutSeconds: 30);
            if (cfgResp.Ok && cfgResp.Body is not null)
            {
                var sUrl = cfgResp.Body["server_url"]?.GetValue<string>();
                int? hb = TryGetInt(cfgResp.Body["heartbeat_interval_seconds"]);
                int? jit = TryGetInt(cfgResp.Body["heartbeat_jitter_seconds"]);
                int? inv = TryGetInt(cfgResp.Body["inventory_interval_hours"]);
                int? renew = TryGetInt(cfgResp.Body["renew_before_percent"]);
                if (_config.ApplyServerSettings(sUrl, hb, jit, inv, renew))
                {
                    _config.Save();
                    _logger.LogInformation("Đã tải cấu hình agent hoàn chỉnh từ /api/agent/config: server={Server}, interval={I}s, jitter={J}s, inv={H}h, renew={R}%",
                        _config.PrimaryEndpoint, _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds,
                        _config.InventoryIntervalHours, _config.RenewBeforePercent);
                }

                var serverHash = cfgResp.Body["agent_config_hash"]?.GetValue<string>();
                if (!string.IsNullOrWhiteSpace(serverHash))
                {
                    _state.LastAgentConfigHash = serverHash;
                    _state.Save();
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Không tải được /api/agent/config sau enroll (sẽ đồng bộ lại ở chu kỳ kế tiếp): {Msg}", ex.Message);
        }

        return true;
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try { var v = node?.GetValue<int>(); return v is > 0 ? v : null; }
        catch { return null; }
    }

    private string? SafeHostname()
    {
        try { return Dns.GetHostName(); } catch { return Environment.MachineName; }
    }
}
