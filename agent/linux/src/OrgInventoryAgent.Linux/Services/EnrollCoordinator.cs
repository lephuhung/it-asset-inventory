using System.Net;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux.Crypto;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>
/// Điều phối enrollment: token + fingerprint + CSR → server ký → cài cert PEM → lưu config.
/// Idempotent: đã enroll (cert + machine_id) → bỏ qua. Retry 1 lần/60s.
/// </summary>
public sealed class EnrollCoordinator
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollClient _enrollClient;
    private readonly EndpointManager _endpoints;
    private readonly KeyStore _keyStore;
    private readonly LinuxFingerprintCollector _fingerprint;
    private readonly AgentState _state;
    private readonly ILogger<EnrollCoordinator> _logger;
    private readonly object _lock = new();
    private bool _inFlight;
    private DateTimeOffset _lastAttempt = DateTimeOffset.MinValue;

    public EnrollCoordinator(AgentConfig config, ApiClient api, EnrollClient enrollClient,
        EndpointManager endpoints, KeyStore keyStore, LinuxFingerprintCollector fingerprint,
        AgentState state, ILogger<EnrollCoordinator> logger)
    {
        _config = config; _api = api; _enrollClient = enrollClient; _endpoints = endpoints;
        _keyStore = keyStore; _fingerprint = fingerprint; _state = state; _logger = logger;
    }

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
        try { return await EnrollCoreAsync(ct); }
        finally { lock (_lock) _inFlight = false; }
    }

    private async Task<bool> EnrollCoreAsync(CancellationToken ct)
    {
        var token = _config.Token;
        if (string.IsNullOrWhiteSpace(token))
        {
            _logger.LogCritical("Chưa có enroll token — ghi config.json (field \"token\" hoặc \"enroll_token\").");
            return false;
        }
        if (_endpoints.Current is null)
        {
            _logger.LogCritical("Chưa có endpoint server — truyền --endpoint hoặc ghi config.json (field \"endpoints\").");
            return false;
        }

        _logger.LogInformation("Bắt đầu enroll tới {Endpoint}...", _endpoints.Current);
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
        try { response = await _enrollClient.EnrollAsync(request, ct); }
        catch (ApiTransportException ex) { _logger.LogError("Không kết nối được server enroll: {Msg}", ex.Message); return false; }

        if (response is null || string.IsNullOrWhiteSpace(response.MachineId) || string.IsNullOrWhiteSpace(response.ClientCertPem))
        {
            _logger.LogError("Enroll không thành công — thử lại ở chu kỳ sau.");
            return false;
        }

        _keyStore.InstallCertificate(response.ClientCertPem, key, _config);
        _config.MachineId = response.MachineId;
        _config.Enrolled = true;
        _config.RenewAfter = response.RenewAfter;
        _config.LastEnrolledAt = DateTimeOffset.UtcNow;
        var changed = _config.ApplyServerSettings(
            response.AgentServerUrl, response.HeartbeatIntervalSeconds,
            response.HeartbeatJitterSeconds, response.InventoryIntervalHours, null);
        if (!string.IsNullOrWhiteSpace(response.CaCertPem))
        {
            try { File.WriteAllText(Path.Combine(AppPaths.DataDir, "ca-cert.pem"), response.CaCertPem); }
            catch { }
        }
        _config.Token = null; // token 1 lần — xóa ngay
        _config.Save();
        _logger.LogInformation("Enroll thành công: machine_id={MachineId}, is_new={IsNew}, status={Status}",
            response.MachineId, response.IsNewMachine, response.Status);

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
                if (_config.ApplyServerSettings(sUrl, hb, jit, inv, renew)) _config.Save();
                var serverHash = cfgResp.Body["agent_config_hash"]?.GetValue<string>();
                if (!string.IsNullOrWhiteSpace(serverHash)) { _state.LastAgentConfigHash = serverHash; _state.Save(); }
            }
        }
        catch (Exception ex) { _logger.LogWarning("Không tải được /api/agent/config sau enroll: {Msg}", ex.Message); }
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