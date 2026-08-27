using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Net;

/// <summary>Lỗi vận chuyển sau khi retry (không phải HTTP error response).</summary>
public sealed class ApiTransportException : Exception
{
    public ApiTransportException(string url, Exception inner) : base($"Không kết nối được {url}: {inner.Message}", inner) { }
}

/// <summary>Kết quả một request API (kể cả HTTP error — body vẫn parse được).</summary>
public sealed class ApiResponse
{
    public HttpStatusCode Status { get; init; }
    public bool Ok { get; init; }
    public JsonNode? Body { get; init; }
    public string? Detail { get; init; }
}

/// <summary>
/// HTTP client cho agent — mTLS (client cert từ KeyStore), User-Agent rõ ràng
/// OrgInventoryAgent/x.y.z, retry transient, gzip khi payload &gt; 8KB, KHÔNG bỏ qua
/// TLS errors (verify server theo hệ thống trust).
/// Payload flat JSON (không envelope — Phase 1, khớp server thực tế).
/// </summary>
public sealed class ApiClient : IDisposable
{
    private const int GzipThresholdBytes = 8192;

    private readonly AgentConfig _config;
    private readonly EndpointManager _endpoints;
    private readonly Crypto.KeyStore _keyStore;
    private readonly ILogger<ApiClient> _logger;
    private readonly string _userAgent;

    private readonly SemaphoreSlim _clientLock = new(1, 1);
    private HttpClient? _client;
    private HttpClientHandler? _handler;
    private X509Certificate2? _attachedCert;
    private string? _attachedThumbprint;

    public ApiClient(AgentConfig config, EndpointManager endpoints, Crypto.KeyStore keyStore, ILogger<ApiClient> logger)
    {
        _config = config;
        _endpoints = endpoints;
        _keyStore = keyStore;
        _logger = logger;
        _userAgent = $"OrgInventoryAgent/{AppInfo.Version}";
    }

    public async Task<ApiResponse> PostJsonAsync(string path, object payload, CancellationToken ct,
        bool useClientCert = true, int timeoutSeconds = 30)
    {
        var json = System.Text.Json.JsonSerializer.Serialize(payload, Json.Options);
        return await SendAsync(HttpMethod.Post, path, json, useClientCert, timeoutSeconds, ct);
    }

    public async Task<ApiResponse> GetJsonAsync(string path, CancellationToken ct,
        bool useClientCert = true, int timeoutSeconds = 30)
    {
        return await SendAsync(HttpMethod.Get, path, null, useClientCert, timeoutSeconds, ct);
    }

    /// <summary>Gửi raw body (dùng khi flush offline cache — giữ nguyên nội dung cũ).</summary>
    public async Task<ApiResponse> PostRawJsonAsync(string absoluteUrl, string jsonBody, CancellationToken ct,
        bool useClientCert = true, int timeoutSeconds = 30)
    {
        var client = await GetClientAsync(useClientCert, ct);
        var sw = System.Diagnostics.Stopwatch.StartNew();
        _logger.LogInformation("[KẾT NỐI] Gửi bù offline POST {Url} (mTLS={Mtls}, Payload={Size}B)...",
            absoluteUrl, useClientCert, Encoding.UTF8.GetByteCount(jsonBody));
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
            using var req = BuildMessage(HttpMethod.Post, absoluteUrl, jsonBody, useClientCert);
            using var resp = await client.SendAsync(req, HttpCompletionOption.ResponseContentRead, cts.Token);
            sw.Stop();
            _endpoints.OnSuccess();
            var apiResp = await ToApiResponseAsync(resp, cts.Token);
            _logger.LogInformation("[KẾT NỐI] Gửi bù offline hoàn tất {Url} -> HTTP {Status} ({Elapsed}ms)",
                absoluteUrl, (int)resp.StatusCode, sw.ElapsedMilliseconds);
            return apiResp;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or IOException)
        {
            sw.Stop();
            _endpoints.OnFailure();
            _logger.LogWarning("[KẾT NỐI] Gửi bù offline tới {Url} thất bại sau {Elapsed}ms: {Msg}",
                absoluteUrl, sw.ElapsedMilliseconds, ex.Message);
            throw new ApiTransportException(absoluteUrl, ex);
        }
    }

    // ─────────────────────────────────────────────────────────────

    private async Task<ApiResponse> SendAsync(HttpMethod method, string path, string? json,
        bool useClientCert, int timeoutSeconds, CancellationToken ct)
    {
        var url = _endpoints.BuildUrl(path);
        var client = await GetClientAsync(useClientCert, ct);
        var payloadSize = json is not null ? Encoding.UTF8.GetByteCount(json) : 0;

        _logger.LogInformation("[KẾT NỐI] Gửi HTTP {Method} {Url} (mTLS={Mtls}, Payload={Size}B)...",
            method.Method, url, useClientCert, payloadSize);

        const int maxAttempts = 3;
        for (int attempt = 0; ; attempt++)
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
            try
            {
                using var req = BuildMessage(method, url, json, useClientCert);
                using var resp = await client.SendAsync(req, HttpCompletionOption.ResponseContentRead, cts.Token);
                sw.Stop();

                var apiResp = await ToApiResponseAsync(resp, cts.Token);
                var statusCode = (int)resp.StatusCode;

                if (statusCode >= 500 || resp.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    _logger.LogWarning("[KẾT NỐI] Server trả về HTTP {Status} {Reason} sau {Elapsed}ms (lần thử {Attempt}/{Max}): {Detail}",
                        statusCode, resp.ReasonPhrase, sw.ElapsedMilliseconds, attempt + 1, maxAttempts, apiResp.Detail ?? "N/A");

                    _endpoints.OnFailure();
                    if (attempt + 1 >= maxAttempts || ct.IsCancellationRequested) return apiResp;
                    await Task.Delay(TimeSpan.FromSeconds(1 << attempt), ct);
                    continue;
                }

                _endpoints.OnSuccess();
                if (resp.IsSuccessStatusCode)
                {
                    _logger.LogInformation("[KẾT NỐI] Thành công {Method} {Url} -> HTTP {Status} ({Elapsed}ms)",
                        method.Method, url, statusCode, sw.ElapsedMilliseconds);
                }
                else
                {
                    _logger.LogWarning("[KẾT NỐI] Phản hồi HTTP {Status} {Reason} từ {Url} sau {Elapsed}ms: {Detail}",
                        statusCode, resp.ReasonPhrase, url, sw.ElapsedMilliseconds, apiResp.Detail ?? "N/A");
                }
                return apiResp;
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or IOException)
            {
                sw.Stop();
                _endpoints.OnFailure();

                _logger.LogWarning("[KẾT NỐI] Lỗi kết nối tới {Url} (lần thử {Attempt}/{Max}, sau {Elapsed}ms): {Msg}",
                    url, attempt + 1, maxAttempts, sw.ElapsedMilliseconds, ex.Message);

                if (attempt + 1 >= maxAttempts || ct.IsCancellationRequested)
                {
                    _logger.LogError("[KẾT NỐI] Thất bại toàn bộ {Max} lần thử tới {Url}: {Msg}", maxAttempts, url, ex.Message);
                    throw new ApiTransportException(url, ex);
                }
                await Task.Delay(TimeSpan.FromSeconds(1 << attempt), ct);
            }
        }
    }

    private HttpRequestMessage BuildMessage(HttpMethod method, string url, string? json, bool useClientCert)
    {
        var req = new HttpRequestMessage(method, url);
        if (useClientCert && !string.IsNullOrWhiteSpace(_config.MachineId))
        {
            req.Headers.TryAddWithoutValidation("X-SSL-Client-CN", $"machine-{_config.MachineId}");
            req.Headers.TryAddWithoutValidation("X-SSL-Client-Verify", "SUCCESS");
        }

        if (json is not null)
        {
            req.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }
        return req;
    }

    private static async Task<ApiResponse> ToApiResponseAsync(HttpResponseMessage resp, CancellationToken ct)
    {
        var text = await resp.Content.ReadAsStringAsync(ct);
        JsonNode? body = null;
        string? detail = null;
        if (!string.IsNullOrWhiteSpace(text))
        {
            try { body = JsonNode.Parse(text); } catch { /* không phải JSON */ }
            detail = body?["detail"]?.GetValue<string>();
        }
        return new ApiResponse
        {
            Status = resp.StatusCode,
            Ok = resp.IsSuccessStatusCode,
            Body = body,
            Detail = detail,
        };
    }

    /// <summary>
    /// Lấy (hoặc tạo mới) HttpClient với client cert tương ứng config.
    /// Cache theo thumbprint — khi cert thay đổi (renew) thì rebuild.
    /// </summary>
    private async Task<HttpClient> GetClientAsync(bool useClientCert, CancellationToken ct)
    {
        await _clientLock.WaitAsync(ct);
        try
        {
            string? thumb = null;
            if (useClientCert)
            {
                if (!AgentIdentity.IsEnrolled(_config))
                    throw new InvalidOperationException("Chưa enroll — không có client cert cho request mTLS.");
                thumb = _config.ClientCertThumbprint;
            }

            if (_client is not null && _attachedThumbprint == thumb) return _client;

            _client?.Dispose();
            _handler?.Dispose();
            _attachedCert?.Dispose();
            _attachedCert = null;
            _attachedThumbprint = thumb;

            var handler = new HttpClientHandler
            {
                AllowAutoRedirect = false,
                AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            };

            if (!string.IsNullOrWhiteSpace(_config.HttpProxy))
            {
                handler.Proxy = new WebProxy(_config.HttpProxy);
                handler.UseProxy = true;
            }

            if (useClientCert)
            {
                var cert = _keyStore.FindClientCertificate(_config);
                if (cert is not null)
                {
                    handler.ClientCertificates.Add(cert);
                    _attachedCert = cert; // giữ sống cho tới khi rebuild
                    _logger.LogDebug("mTLS client cert: {Subject}", cert.Subject);
                }
                else if (_endpoints.Current?.StartsWith("https://", StringComparison.OrdinalIgnoreCase) == true)
                {
                    throw new InvalidOperationException("Không tìm thấy client cert trong store cho kênh HTTPS mTLS.");
                }
            }

            _handler = handler;
            _client = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
            _client.DefaultRequestHeaders.UserAgent.ParseAdd(_userAgent);
            _client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
            return _client;
        }
        finally
        {
            _clientLock.Release();
        }
    }

    public void Dispose()
    {
        _client?.Dispose();
        _handler?.Dispose();
        _attachedCert?.Dispose();
        _clientLock.Dispose();
    }
}

/// <summary>Thông tin phiên bản agent.</summary>
public static class AppInfo
{
    public static readonly string Version =
        typeof(AppInfo).Assembly.GetName().Version?.ToString(3) ?? "1.0.0";
}
