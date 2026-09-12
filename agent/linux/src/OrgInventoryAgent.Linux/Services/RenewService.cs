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
            // AG-P1-02: nếu reenroll đang chờ fresh token → KHÔNG spam.
            if (AgentIdentity.IsReenrollPending(_config))
            {
                _logger.LogInformation(
                    "Cert biến mất; chờ admin issue fresh bootstrap token để re-enroll " +
                    "(state: REENROLL_REQUIRED, machine_id={MachineId}).", _config.MachineId);
                // KHÔNG tăng rate-limit ở đây — chờ cho đến khi admin issue token.
                try { await Task.Delay(TimeSpan.FromMinutes(5), ct); }
                catch (OperationCanceledException) { return; }
                continue;
            }
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
        // AG-P1-02: nếu reenroll đang chờ fresh token → KHÔNG tìm cert, không renew.
        if (_config.ReenrollRequired)
        {
            // Cert chưa còn → không renew (cần reenroll trước).
            return;
        }
        X509Certificate2? cert;
        try { cert = _keyStore.FindClientCertificate(_config); }
        catch (Exception ex) { _logger.LogWarning("Không load được client cert: {Msg}", ex.Message); return; }
        if (cert is null)
        {
            // AG-P1-02: cert missing + không phải reenroll_required → đặt cờ reenroll + log.
            // Không spam log trong các chu kỳ tiếp theo; Coordinator sẽ KHÔNG gọi /api/enroll.
            if (!_config.ReenrollRequired)
            {
                _logger.LogCritical(
                    "Client cert không tìm thấy. Có thể PEM file bị xóa hoặc store bị corrupt. " +
                    "Đặt trạng thái REENROLL_REQUIRED. Agent sẽ KHÔNG tự enroll; chờ admin issue fresh bootstrap token.");
                _config.Enrolled = false;
                _config.ClientCertThumbprint = null;
                _config.ReenrollRequired = true;
                _config.Save();
            }
            return;
        }

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
        // AG-P1-01: cert rotation phải atomic — _keyStore.ReplaceCertificate đã handle.
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
            try
            {
                _keyStore.ReplaceCertificate(certPem, newKey, _config);
            }
            catch (Exception ex)
            {
                // AG-P1-01: nếu install fail, cert cũ vẫn còn (atomic swap bảo vệ).
                // Không raise — chu kỳ tiếp theo sẽ retry renew bằng cert cũ.
                _logger.LogError(ex,
                    "Cert mới KHÔNG cài được (atomic swap fail). Cert cũ vẫn còn — sẽ retry ở chu kỳ sau.");
                return;
            }
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

