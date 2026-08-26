using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Net;

/// <summary>
/// Failover endpoint (mục 3.5 kế hoạch — Tầng 1):
/// - Endpoints[0] là primary, các endpoint sau là backup.
/// - Primary lỗi 5 lần liên tiếp → chuyển sang endpoint kế tiếp.
/// - Mỗi 10 chu kỳ thử lại primary (nếu đang dùng backup).
/// </summary>
public sealed class EndpointManager
{
    private const int FailThreshold = 5;
    private const int RetryPrimaryEvery = 10;

    private readonly AgentConfig _config;
    private readonly ILogger<EndpointManager> _logger;
    private readonly object _lock = new();

    private int _current;
    private int _consecutiveFailures;
    private int _cycleCount;

    public EndpointManager(AgentConfig config, ILogger<EndpointManager> logger)
    {
        _config = config;
        _logger = logger;
    }

    /// <summary>Endpoint đang dùng (base URL).</summary>
    public string? Current
    {
        get
        {
            lock (_lock)
            {
                _config.Normalize();
                return _config.Endpoints.Length > 0 ? _config.Endpoints[_current % _config.Endpoints.Length] : null;
            }
        }
    }

    /// <summary>Gọi khi request tới endpoint hiện tại thành công (2xx).</summary>
    public void OnSuccess()
    {
        lock (_lock)
        {
            _consecutiveFailures = 0;
            _cycleCount++;
        }
    }

    /// <summary>Gọi khi request tới endpoint hiện tại thất bại (lỗi mạng/5xx/429/timeout).</summary>
    public void OnFailure()
    {
        lock (_lock)
        {
            _consecutiveFailures++;
            _cycleCount++;
            _config.Normalize();
            if (_config.Endpoints.Length <= 1) return;

            // Primary lỗi đủ 5 lần liên tiếp → chuyển backup
            if (_consecutiveFailures >= FailThreshold)
            {
                var from = _config.Endpoints[_current];
                _current = (_current + 1) % _config.Endpoints.Length;
                _consecutiveFailures = 0;
                _logger.LogWarning("Endpoint {From} lỗi {N} lần liên tiếp → chuyển sang {To}",
                    from, FailThreshold, _config.Endpoints[_current]);
                return;
            }

            // Đang dùng backup và đã qua 10 chu kỳ → thử lại primary
            if (_current != 0 && _cycleCount % RetryPrimaryEvery == 0)
            {
                _logger.LogInformation("Thử lại endpoint primary (chu kỳ {Cycle})", _cycleCount);
                _current = 0;
                _consecutiveFailures = 0;
            }
        }
    }

    /// <summary>Ghép base URL + path (path bắt đầu bằng "/").</summary>
    public string BuildUrl(string path)
    {
        var baseUrl = Current?.TrimEnd('/') ?? throw new InvalidOperationException("Chưa có endpoint server.");
        return baseUrl + path;
    }
}
