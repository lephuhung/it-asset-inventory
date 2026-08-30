using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Services;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Collectors;
using OrgInventoryAgent.Crypto;
using OrgInventoryAgent.Core.Net;

namespace OrgInventoryAgent.Services;

/// <summary>
/// Heartbeat định kỳ: chu kỳ ngẫu nhiên trong [interval - jitter, interval + jitter]
/// (mặc định 30±8s ≈ 22–38s) — chống pattern C2. Trước khi gửi: flush offline cache.
/// Đồng bộ interval/jitter/renew_after từ response; rescan_requested → chạy inventory ngay.
/// Định kỳ (mỗi 20 chu kỳ) kiểm tra cert thực sự tồn tại trong store — nếu mất (ví dụ OS
/// cài lại) thì reset enrollment state để tự re-enroll.
///
/// Phase 4: server trả `agent_config_hash` trong heartbeat response. Nếu hash KHÁC với
/// hash lưu trong AgentState → gọi ngay ConfigSyncService.SyncAsync() để đồng bộ cấu hình
/// mới nhất (thay vì đợi tới chu kỳ 6h). Cho phép admin đổi cấu hình trên portal được
/// áp dụng trong vòng ~30s thay vì 6h.
/// </summary>
public sealed class HeartbeatService : BackgroundService
{
    private const int CertCheckEvery = 20; // chu kỳ kiểm tra cert thực sự

    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EndpointManager _endpoints;
    private readonly EnrollCoordinator _enroll;
    private readonly OfflineCache _cache;
    private readonly InventoryCollector _inventory;
    private readonly InventoryService _inventoryService;
    private readonly KeyStore _keyStore;
    private readonly ConfigSyncService _configSync;
    private readonly ILogger<HeartbeatService> _logger;
    private readonly AgentState _state;
    private int _cycleCount;

    public HeartbeatService(AgentConfig config, ApiClient api, EndpointManager endpoints,
        EnrollCoordinator enroll, OfflineCache cache, InventoryCollector inventory,
        InventoryService inventoryService, KeyStore keyStore, ConfigSyncService configSync,
        AgentState state, ILogger<HeartbeatService> logger)
    {
        _config = config;
        _api = api;
        _endpoints = endpoints;
        _enroll = enroll;
        _cache = cache;
        _inventory = inventory;
        _inventoryService = inventoryService;
        _keyStore = keyStore;
        _configSync = configSync;
        _state = state;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        _logger.LogInformation("HeartbeatService khởi động (interval={I}s, jitter={J}s).",
            _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds);

        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (!AgentIdentity.IsEnrolled(_config))
                {
                    await _enroll.EnsureEnrolledAsync(ct);
                }
                else
                {
                    // Định kỳ kiểm tra cert thực sự còn trong store (ví dụ: OS được cài lại)
                    _cycleCount++;
                    if (_cycleCount % CertCheckEvery == 0)
                    {
                        var status = AgentIdentity.Validate(_config, _keyStore);
                        if (status == EnrollStatus.CertMissing)
                        {
                            _logger.LogCritical(
                                "Client cert (thumbprint={Thumb}) không còn trong Windows Certificate Store. " +
                                "Có thể OS được cài lại hoặc store bị xóa. " +
                                "Đặt lại trạng thái enrollment để tự re-enroll.",
                                _config.ClientCertThumbprint);
                            // Reset để EnsureEnrolledAsync chạy lại ở chu kỳ sau
                            _config.Enrolled = false;
                            _config.ClientCertThumbprint = null;
                            _config.Save();
                        }
                    }
                }

                if (AgentIdentity.IsEnrolled(_config))
                {
                    await FlushOfflineCacheAsync(ct);
                    await SendHeartbeatAsync(ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Chu kỳ heartbeat lỗi.");
            }

            var delay = NextDelay();
            try { await Task.Delay(delay, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    /// <summary>Chu kỳ thực tế = interval ± jitter, ngẫu nhiên mỗi lần.</summary>
    private TimeSpan NextDelay()
    {
        var interval = _config.HeartbeatIntervalSeconds;
        var jitter = Math.Min(_config.HeartbeatJitterSeconds, interval - 1);
        var min = Math.Max(5, interval - jitter);
        var max = Math.Max(min + 1, interval + jitter);
        var seconds = min + (Random.Shared.NextDouble() * (max - min));
        return TimeSpan.FromSeconds(seconds);
    }

    /// <summary>Gửi 1 heartbeat (dùng cho --once).</summary>
    public async Task<bool> SendOnceAsync(CancellationToken ct)
    {
        if (!AgentIdentity.IsEnrolled(_config)) return false;
        return await SendHeartbeatAsync(ct);
    }

    private async Task<bool> SendHeartbeatAsync(CancellationToken ct)
    {
        var payload = new
        {
            logged_user = _inventory.GetLoggedUserSafe(),
            uptime_sec = (long)(Environment.TickCount64 / 1000),
            ip = _inventory.GetPrimaryIp(),
        };

        try
        {
            var resp = await _api.PostJsonAsync("/api/heartbeat", payload, ct, useClientCert: true, timeoutSeconds: 20);
            if (!resp.Ok)
            {
                _logger.LogWarning("Heartbeat thất bại HTTP {StatusCode}: {Detail}", (int)resp.Status, resp.Detail);
                return false;
            }

            var body = resp.Body;
            _logger.LogInformation("Heartbeat thành công -> Server={Endpoint}, server_time={Time}, user={User}, ip={Ip}",
                _endpoints.Current, body?["server_time"]?.GetValue<string>(), payload.logged_user, payload.ip);

            // Đồng bộ cấu hình từ server (server_url / heartbeat / jitter / inventory interval / renew_after)
            var serverUrl = body?["server_url"]?.GetValue<string>() ?? body?["agent_server_url"]?.GetValue<string>();
            int? interval = TryGetInt(body?["heartbeat_interval_seconds"]);
            int? jitter = TryGetInt(body?["heartbeat_jitter_seconds"]);
            int? invHours = TryGetInt(body?["inventory_interval_hours"]);
            int? renewPct = TryGetInt(body?["renew_before_percent"]);

            bool changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct);

            var renewAfter = body?["renew_after"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(renewAfter) && _config.RenewAfter != renewAfter)
            {
                _config.RenewAfter = renewAfter;
                changed = true;
            }

            if (changed)
            {
                _config.Save();
                _logger.LogInformation("Đã cập nhật cấu hình từ heartbeat response: server={Server}, interval={I}s, jitter={J}s, inv={H}h",
                    _config.PrimaryEndpoint, _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds, _config.InventoryIntervalHours);
            }

            // Phase 4: nếu server báo hash cấu hình KHÁC với hash đã lưu → gọi ConfigSync
            // ngay để đồng bộ. Nếu KHỚP → heartbeat bình thường, không gọi thêm request.
            var serverCfgHash = body?["agent_config_hash"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(serverCfgHash)
                && !string.Equals(serverCfgHash, _state.LastAgentConfigHash, StringComparison.OrdinalIgnoreCase))
            {
                _logger.LogInformation(
                    "Server báo hash cấu hình thay đổi ({Old} → {New}) → gọi ConfigSync để refresh.",
                    _state.LastAgentConfigHash ?? "(none)", serverCfgHash);
                // SyncAndSaveHashAsync vừa đồng bộ cấu hình vừa cập nhật hash mới vào state
                var refreshed = await _configSync.SyncAndSaveHashAsync(ct);
                if (refreshed)
                {
                    _state.LastAgentConfigHash = serverCfgHash;
                    _logger.LogInformation("Đã refresh cấu hình từ server và cập nhật LastAgentConfigHash={Hash}", serverCfgHash);
                }
            }
            else if (!string.IsNullOrWhiteSpace(serverCfgHash))
            {
                _logger.LogDebug("Hash cấu hình khớp ({Hash}) → heartbeat bình thường.", serverCfgHash);
            }

            // Phase 3: on-demand rescan từ portal
            if (body?["rescan_requested"]?.GetValue<bool>() == true)
            {
                _logger.LogInformation("Server yêu cầu rescan → chạy inventory ngay.");
                _inventoryService.TriggerRescan();
            }

            return true;
        }
        catch (ApiTransportException ex)
        {
            _logger.LogWarning("Heartbeat không gửi được: {Msg}", ex.Message);
            return false;
        }
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try
        {
            var v = node?.GetValue<int>();
            return v is > 0 ? v : null;
        }
        catch { return null; }
    }

    /// <summary>Quyết định có cần gọi ConfigSyncService hay không dựa trên hash server
    /// trả về vs hash lưu trong AgentState.
    /// - serverHash null/rỗng → false (server không hỗ trợ field → fallback ConfigSync 6h)
    /// - localHash null (lần đầu) → true (luôn sync lần đầu để lấy hash)
    /// - khác nhau → true (admin đã đổi config trên portal)
    /// - giống nhau → false (heartbeat bình thường, không tốn thêm request)
    /// </summary>
    public static bool ShouldResyncConfig(string? serverHash, string? localHash)
    {
        if (string.IsNullOrWhiteSpace(serverHash)) return false;
        if (string.IsNullOrWhiteSpace(localHash)) return true;
        return !string.Equals(serverHash, localHash, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>Gửi bù offline cache khi online (giữ nguyên body — không thay đổi nội dung).</summary>
    private async Task FlushOfflineCacheAsync(CancellationToken ct)
    {
        var pending = _cache.GetAll();
        if (pending.Count == 0) return;

        _logger.LogInformation("Flush offline cache: {Count} bản ghi đang chờ.", pending.Count);
        foreach (var item in pending)
        {
            try
            {
                var resp = await _api.PostRawJsonAsync(item.Url, item.Body, ct, useClientCert: true, timeoutSeconds: 30);
                if (resp.Ok)
                {
                    _cache.Delete(item.Id);
                    _logger.LogInformation("Đã gửi bù offline bản ghi #{Id} → {Url}", item.Id, item.Url);
                }
                else
                {
                    var drop = _cache.IncrementAttempts(item.Id);
                    _logger.LogWarning("Gửi bù #{Id} thất bại HTTP {(int)Status}: {Detail}{Drop}",
                        item.Id, resp.Status, resp.Detail, drop ? " — quá số lần thử, bỏ." : "");
                    if (drop) _cache.Delete(item.Id);
                }
            }
            catch (Exception ex)
            {
                var drop = _cache.IncrementAttempts(item.Id);
                _logger.LogWarning("Gửi bù #{Id} lỗi: {Msg}{Drop}", item.Id, ex.Message, drop ? " — quá số lần thử, bỏ." : "");
                if (drop) _cache.Delete(item.Id);
            }
        }
    }
}
