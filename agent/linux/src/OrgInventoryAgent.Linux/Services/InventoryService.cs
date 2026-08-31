using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>
/// Gửi inventory v4 đầy đủ: lần đầu sau enroll, config_hash thay đổi, định kỳ
/// inventory_interval_hours (24h), rescan_requested. Thất bại → offline cache.
/// </summary>
public sealed class InventoryService : BackgroundService
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EndpointManager _endpoints;
    private readonly EnrollCoordinator _enroll;
    private readonly OfflineCache _cache;
    private readonly LinuxInventoryProvider _collector;
    private readonly ILogger<InventoryService> _logger;
    private readonly AgentState _state;
    private readonly object _sendLock = new();
    private volatile bool _rescanRequested;
    private bool _sending;

    public InventoryService(AgentConfig config, ApiClient api, EndpointManager endpoints,
        EnrollCoordinator enroll, OfflineCache cache, LinuxInventoryProvider collector,
        AgentState state, ILogger<InventoryService> logger)
    {
        _config = config; _api = api; _endpoints = endpoints; _enroll = enroll; _cache = cache;
        _collector = collector; _state = state; _logger = logger;
    }

    public void TriggerRescan() => _rescanRequested = true;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(15), ct); }
            catch (OperationCanceledException) { return; }
        }
        var intervalDesc = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
            ? $"{_config.InventoryIntervalSeconds.Value}s" : $"{_config.InventoryIntervalHours}h";
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
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Chu kỳ inventory lỗi."); }
            var delaySec = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
                ? Math.Clamp(_config.InventoryIntervalSeconds.Value, 5, 30) : 30;
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

    public async Task<bool> SendOnceAsync(CancellationToken ct)
    {
        if (!AgentIdentity.IsEnrolled(_config)) return false;
        return await SendInventoryAsync(ct);
    }

    private async Task<bool> SendInventoryAsync(CancellationToken ct)
    {
        lock (_sendLock) { if (_sending) return false; _sending = true; }
        try
        {
            var configHash = _config.ComputeConfigHash();
            var payload = InventoryPayloadBuilder.Build(_collector, Environment.UserName);
            var url = _endpoints.BuildUrl("/api/inventory");
            try
            {
                var resp = await _api.PostJsonAsync("/api/inventory", payload, ct, useClientCert: true, timeoutSeconds: 60);
                if (resp.Ok)
                {
                    _state.LastInventoryAt = DateTimeOffset.UtcNow.ToString("o");
                    _state.LastInventoryConfigHash = configHash;
                    _state.Save();
                    _logger.LogInformation("Đã gửi inventory (config_changed={C}).", resp.Body?["config_changed"]?.GetValue<bool>());
                    return true;
                }
                _logger.LogWarning("Inventory thất bại HTTP {StatusCode}: {Detail} → lưu offline cache.", (int)resp.Status, resp.Detail);
                EnqueueOffline(url, payload);
                return false;
            }
            catch (ApiTransportException ex)
            {
                _logger.LogWarning("Inventory không gửi được: {Msg} → lưu offline cache.", ex.Message);
                EnqueueOffline(url, payload);
                return false;
            }
        }
        finally { lock (_sendLock) _sending = false; }
    }

    private void EnqueueOffline(string url, object payload)
    {
        try
        {
            var body = System.Text.Json.JsonSerializer.Serialize(payload, OrgInventoryAgent.Core.Json.Options);
            _cache.Enqueue(url, body);
        }
        catch (Exception ex) { _logger.LogError("Lưu offline cache inventory lỗi: {Msg}", ex.Message); }
    }
}