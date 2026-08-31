using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Linux.Crypto;

namespace OrgInventoryAgent.Linux.Services;

public sealed class RenewRequest
{
    [System.Text.Json.Serialization.JsonPropertyName("csr_pem")]
    public string? CsrPem { get; set; }
}

/// <summary>
/// Tự gia hạn client cert: kiểm tra định kỳ (6h + lúc khởi động) — khi cert còn
/// &lt; renew_before_percent (70%) vòng đời → CSR mới (CN=machine-&lt;machine_id&gt;)
/// → POST /api/renew (mTLS bằng cert cũ) → thay cert PEM.
/// </summary>
public sealed class RenewService : BackgroundService
{
    private static readonly TimeSpan CheckInterval = TimeSpan.FromHours(6);

    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollCoordinator _enroll;
    private readonly KeyStore _keyStore;
    private readonly ILogger<RenewService> _logger;

    public RenewService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        KeyStore keyStore, ILogger<RenewService> logger)
    {
        _config = config;
        _api = api;
        _enroll = enroll;
        _keyStore = keyStore;
        _logger = logger;
    }

    /// <summary>Phần trăm vòng đời cert còn lại (NotBefore→NotAfter).</summary>
    public static double RemainingLifePercent(X509Certificate2 cert, DateTimeOffset now)
    {
        var notBefore = cert.NotBefore.ToUniversalTime();
        var notAfter = cert.NotAfter.ToUniversalTime();
        var total = (notAfter - notBefore).TotalSeconds;
        if (total <= 0) return 0;
        var remaining = (notAfter - now.UtcDateTime).TotalSeconds;
        return Math.Clamp(remaining / total * 100.0, 0, 100);
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(20), ct); }
            catch (OperationCanceledException) { return; }
        }
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (AgentIdentity.IsEnrolled(_config))
                    await CheckAndRenewAsync(ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Chu kỳ kiểm tra renew lỗi."); }
            try { await Task.Delay(CheckInterval, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task CheckAndRenewAsync(CancellationToken ct)
    {
        X509Certificate2? cert;
        try { cert = _keyStore.FindClientCertificate(_config); }
        catch (Exception ex) { _logger.LogWarning("Không load được client cert: {Msg}", ex.Message); return; }
        if (cert is null) { _logger.LogWarning("Không thấy client cert — chờ re-enroll."); return; }

        using (cert)
        {
            var now = DateTimeOffset.UtcNow;
            var remaining = RemainingLifePercent(cert, now);
            if (DateTimeOffset.TryParse(_config.RenewAfter, out var renewAfter) && now >= renewAfter)
            {
                _logger.LogInformation("Đến hạn renew (renew_after={RenewAfter}).", _config.RenewAfter);
                await RenewAsync(ct);
                return;
            }
            if (remaining < _config.RenewBeforePercent)
            {
                _logger.LogInformation("Cert còn {Pct:0.0}% vòng đời (< {Threshold}%) → renew.",
                    remaining, _config.RenewBeforePercent);
                await RenewAsync(ct);
            }
        }
    }

    private async Task RenewAsync(CancellationToken ct)
    {
        using var newKey = CsrGenerator.CreateKeyPair();
        var csrPem = CsrGenerator.CreateCsrPem(newKey, $"machine-{_config.MachineId}");
        try
        {
            var resp = await _api.PostJsonAsync("/api/renew", new RenewRequest { CsrPem = csrPem }, ct,
                useClientCert: true, timeoutSeconds: 45);
            if (!resp.Ok)
            {
                _logger.LogError("Renew thất bại HTTP {StatusCode}: {Detail}", (int)resp.Status, resp.Detail);
                return;
            }
            var certPem = resp.Body?["client_cert_pem"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(certPem))
            {
                _logger.LogError("Renew response thiếu client_cert_pem.");
                return;
            }
            _keyStore.ReplaceCertificate(certPem, newKey, _config);
            _config.RenewAfter = resp.Body?["renew_after"]?.GetValue<string>() ?? _config.RenewAfter;
            _config.Save();
            _logger.LogInformation("Renew thành công — cert mới thumbprint={Thumb}.", _config.ClientCertThumbprint);
        }
        catch (ApiTransportException ex)
        {
            _logger.LogWarning("Không gọi được /api/renew: {Msg}", ex.Message);
        }
    }
}

// TODO Task 4: thay bằng EnrollCoordinator thật
public sealed class EnrollCoordinator
{
    public Task<bool> EnsureEnrolledAsync(CancellationToken ct) => Task.FromResult(true);
}