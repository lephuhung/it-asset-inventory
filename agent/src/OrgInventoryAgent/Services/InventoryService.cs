using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Services;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Collectors;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Collectors.Schema;
using InventorySnapshot = OrgInventoryAgent.Core.Collectors.Schema.InventorySnapshot;

namespace OrgInventoryAgent.Services;

/// <summary>
/// Gửi inventory đầy đủ: lần đầu sau enroll, khi config_hash thay đổi,
/// định kỳ inventory_interval_hours (24h), và khi server yêu cầu rescan.
/// Thất bại → lưu offline cache (gửi bù khi có mạng).
/// </summary>
public sealed class InventoryService : BackgroundService
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EndpointManager _endpoints;
    private readonly EnrollCoordinator _enroll;
    private readonly OfflineCache _cache;
    private readonly InventoryCollector _collector;
    private readonly ILogger<InventoryService> _logger;

    private readonly AgentState _state;
    private readonly object _sendLock = new();
    private volatile bool _rescanRequested = true; // Gửi inventory ngay khi service khởi động
    private bool _sending; // guard chống gửi inventory song song (rescan + định kỳ)

    public InventoryService(AgentConfig config, ApiClient api, EndpointManager endpoints,
        EnrollCoordinator enroll, OfflineCache cache, InventoryCollector collector,
        AgentState state, ILogger<InventoryService> logger)
    {
        _config = config;
        _api = api;
        _endpoints = endpoints;
        _enroll = enroll;
        _cache = cache;
        _collector = collector;
        _state = state;
        _logger = logger;
    }

    public void TriggerRescan() => _rescanRequested = true;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        // Chờ enroll xong mới gửi inventory (cần mTLS)
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(15), ct); }
            catch (OperationCanceledException) { return; }
        }

        var intervalDesc = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
            ? $"{_config.InventoryIntervalSeconds.Value}s"
            : $"{_config.InventoryIntervalHours}h";
        _logger.LogInformation("InventoryService khởi động (interval={Interval}).", intervalDesc);

        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (AgentIdentity.IsEnrolled(_config) && IsDue())
                {
                    _rescanRequested = false;
                    await SendInventoryAsync(ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Chu kỳ inventory lỗi.");
            }

            var delaySec = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
                ? Math.Clamp(_config.InventoryIntervalSeconds.Value, 5, 30)
                : 30;

            try { await Task.Delay(TimeSpan.FromSeconds(delaySec), ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private bool IsDue()
    {
        if (_rescanRequested) return true;

        var configHash = _config.ComputeConfigHash();
        if (_state.LastInventoryConfigHash != configHash) return true;

        if (_state.LastInventoryAt is null) return true;

        if (DateTimeOffset.TryParse(_state.LastInventoryAt, out var last))
        {
            var interval = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
                ? TimeSpan.FromSeconds(_config.InventoryIntervalSeconds.Value)
                : TimeSpan.FromHours(Math.Max(1, _config.InventoryIntervalHours));

            return DateTimeOffset.UtcNow - last >= interval;
        }
        return true;
    }

    /// <summary>Gửi inventory 1 lần (dùng cho --once).</summary>
    public async Task<bool> SendOnceAsync(CancellationToken ct)
    {
        if (!AgentIdentity.IsEnrolled(_config)) return false;
        return await SendInventoryAsync(ct);
    }

    private async Task<bool> SendInventoryAsync(CancellationToken ct)
    {
        lock (_sendLock)
        {
            // tránh gửi song song (rescan + định kỳ)
            if (_sending) return false;
            _sending = true;
        }
        try
        {
            var configHash = _config.ComputeConfigHash();
            var snapshot = _collector.Collect();
            // config_hash: canonical hash của payload (trừ chính nó) — server dùng để dedupe
            snapshot.ConfigHash = CanonicalJson.Hash(snapshot, excludeProperty: "config_hash");

            var url = _endpoints.BuildUrl("/api/inventory");
            try
            {
                var resp = await _api.PostJsonAsync("/api/inventory", snapshot, ct, useClientCert: true, timeoutSeconds: 60);
                if (resp.Ok)
                {
                    _state.LastInventoryAt = DateTimeOffset.UtcNow.ToString("o");
                    _state.LastInventoryConfigHash = configHash;
                    _state.Save();
                    _logger.LogInformation("Đã gửi inventory (config_changed={C}).",
                        resp.Body?["config_changed"]?.GetValue<bool>());
                    return true;
                }

                _logger.LogWarning("Inventory thất bại HTTP {StatusCode}: {Detail} → lưu offline cache.",
                    (int)resp.Status, resp.Detail);
                EnqueueOffline(url, snapshot);
                return false;
            }
            catch (ApiTransportException ex)
            {
                _logger.LogWarning("Inventory không gửi được: {Msg} → lưu offline cache.", ex.Message);
                EnqueueOffline(url, snapshot);
                return false;
            }
        }
        finally
        {
            lock (_sendLock) _sending = false;
        }
    }

    private void EnqueueOffline(string url, InventorySnapshot snapshot)
    {
        try
        {
            var body = System.Text.Json.JsonSerializer.Serialize(snapshot, Json.Options);
            _cache.Enqueue(url, body);
        }
        catch (Exception ex)
        {
            _logger.LogError("Lưu offline cache inventory lỗi: {Msg}", ex.Message);
        }
    }
}
