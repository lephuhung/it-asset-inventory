using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Net;

namespace OrgInventoryAgent.Services;

/// <summary>
/// Đồng bộ cấu hình từ server: GET /api/agent/config (mTLS) định kỳ mỗi 6h.
/// Server là nguồn điều khiển hành vi agent (binary không đổi): server_url,
/// heartbeat interval/jitter, inventory interval, renew threshold.
/// </summary>
public sealed class ConfigSyncService : BackgroundService
{
    private static readonly TimeSpan SyncInterval = TimeSpan.FromHours(6);

    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollCoordinator _enroll;
    private readonly ILogger<ConfigSyncService> _logger;

    public ConfigSyncService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        ILogger<ConfigSyncService> logger)
    {
        _config = config;
        _api = api;
        _enroll = enroll;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        // Chờ enroll rồi đồng bộ lần đầu sau vài phút
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(30), ct); }
            catch (OperationCanceledException) { return; }
        }

        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (AgentIdentity.IsEnrolled(_config))
                    await SyncAsync(ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Đồng bộ cấu hình lỗi.");
            }

            try { await Task.Delay(SyncInterval, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    public async Task<bool> SyncAsync(CancellationToken ct)
    {
        try
        {
            var resp = await _api.GetJsonAsync("/api/agent/config", ct, useClientCert: true, timeoutSeconds: 30);
            if (!resp.Ok)
            {
                _logger.LogWarning("GET /api/agent/config thất bại HTTP {Status}: {Detail}",
                    (int)resp.Status, resp.Detail);
                return false;
            }

            var body = resp.Body;
            if (body is null) return false;

            var serverUrl = body["server_url"]?.GetValue<string>();
            int? interval = TryGetInt(body["heartbeat_interval_seconds"]);
            int? jitter = TryGetInt(body["heartbeat_jitter_seconds"]);
            int? invHours = TryGetInt(body["inventory_interval_hours"]);
            int? renewPct = TryGetInt(body["renew_before_percent"]);

            var changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct);
            if (changed)
            {
                _config.Save();
                _logger.LogInformation("Đã đồng bộ cấu hình từ server: server={Server}, interval={I}s, jitter={J}s, inventory={H}h, renew={P}%",
                    _config.PrimaryEndpoint, _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds,
                    _config.InventoryIntervalHours, _config.RenewBeforePercent);
            }
            return true;
        }
        catch (ApiTransportException ex)
        {
            _logger.LogWarning("Không lấy được cấu hình từ server: {Msg}", ex.Message);
            return false;
        }
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try { var v = node?.GetValue<int>(); return v is > 0 ? v : null; }
        catch { return null; }
    }
}
