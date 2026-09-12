using System.Net;
using System.Net.Http;
using System.Reflection;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// AG-P1-05: Trust boundary mTLS/proxy phải sạch.
///
/// Bug trước fix: agent tự gửi <c>X-SSL-Client-CN</c> và <c>X-SSL-Client-Verify: SUCCESS</c>
/// (xem <c>ApiClient.BuildMessage</c>). Nếu production FastAPI bị truy cập trực tiếp
/// (không qua nginx proxy strip), server tin các header này như là đã verify thành công
/// mTLS client cert → attacker bypass được authentication bằng cách gửi header thủ công.
///
/// Fix:
/// - Agent KHÔNG gửi bất kỳ <c>X-SSL-*</c> nào. Reverse proxy (nginx) phải STRIP incoming
///   X-SSL-* rồi tự generate từ verified client certificate.
/// - Test này verify các header không xuất hiện trong outgoing HttpRequestMessage bất
///   kể useClientCert flag (true hay false).
/// - Acceptance: <c>BuildMessage(...)</c> KHÔNG chứa
///   <c>X-SSL-Client-CN</c>, <c>X-SSL-Client-Verify</c>.
///   (Production server FastAPI fix riêng: <c>tests/api/test_mtls_spoof.py</c> xác nhận
///   forged header bị 401, valid cert accepted.)
/// </summary>
public sealed class ApiClientTrustBoundaryTests
{
    /// <summary>Đọc BuildMessage qua reflection (private method) để test header
    /// generation không cần mock full HTTP pipeline.</summary>
    private static HttpRequestMessage InvokeBuildMessage(object apiClient, string url, string? json,
        bool useClientCert)
    {
        var method = apiClient.GetType().GetMethod(
            "BuildMessage",
            BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.NotNull(method);
        return (HttpRequestMessage)method!.Invoke(
            apiClient,
            new object?[] { HttpMethod.Post, url, json, useClientCert })!;
    }

    [Fact]
    public void Agent_Does_Not_Send_X_SSL_Client_CN_Header()
    {
        // AG-P1-05 acceptance: agent KHÔNG tự gửi X-SSL-Client-CN.
        // Nếu server direct-access nhận header này, nó có thể bypass mTLS.
        var api = BuildApiClientWithFakeConfig(machineId: "machine-abc123");
        using var req = InvokeBuildMessage(api, "https://server/api/heartbeat", "{}", true);

        Assert.False(req.Headers.Contains("X-SSL-Client-CN"),
            $"AG-P1-05 BUG: agent gửi X-SSL-Client-CN — server có thể trust khi direct-access, " +
            $"bypass được mTLS. Headers: {string.Join(',', req.Headers.Select(h => h.Key))}");
        Assert.False(req.Headers.Contains("x-ssl-client-cn"),
            "Header check phải case-insensitive.");
    }

    [Fact]
    public void Agent_Does_Not_Send_X_SSL_Client_Verify_Header()
    {
        // AG-P1-05: KHÔNG được gửi X-SSL-Client-Verify=SUCCESS (đây là header proxy
        // generate SAU khi verify cert thật, KHÔNG phải client tự gửi).
        var api = BuildApiClientWithFakeConfig(machineId: "machine-abc");
        using var req = InvokeBuildMessage(api, "https://server/api/heartbeat", "{}", true);

        Assert.False(req.Headers.Contains("X-SSL-Client-Verify"));
        Assert.False(req.Headers.Contains("x-ssl-client-verify"));
    }

    [Fact]
    public void Agent_Does_Not_Send_Any_X_SSL_Headers()
    {
        // Catch-all: kiểm tra mọi header bắt đầu bằng X-SSL- thì KHÔNG có.
        var api = BuildApiClientWithFakeConfig(machineId: "machine-abc");
        using var req = InvokeBuildMessage(api, "https://server/api/heartbeat", "{}", true);

        var sslHeaders = req.Headers
            .Select(h => h.Key)
            .Where(k => k.StartsWith("X-SSL", StringComparison.OrdinalIgnoreCase))
            .ToList();
        Assert.Empty(sslHeaders);
    }

    [Fact]
    public void Agent_Can_Still_Send_X_Machine_Id_Header()
    {
        // X-Machine-Id là application header (không phải trust boundary) — agent được
        // phép gửi vì server dùng nó cho logging/audit, KHÔNG dùng để authenticate.
        var api = BuildApiClientWithFakeConfig(machineId: "machine-abc");
        using var req = InvokeBuildMessage(api, "https://server/api/heartbeat", "{}", true);

        Assert.True(req.Headers.Contains("X-Machine-Id"),
            "X-Machine-Id là application header (không phải trust boundary) — server " +
            "không nên dùng để authenticate. Agent được phép gửi.");
    }

    [Fact]
    public void Headers_Absent_Even_When_ClientCert_False()
    {
        // Even for non-mTLS requests (e.g., /api/enroll pre-mTLS), agent KHÔNG được
        // gửi X-SSL-* — vì server có thể vẫn trust header nếu cấu hình sai.
        var api = BuildApiClientWithFakeConfig(machineId: "machine-abc");
        using var req = InvokeBuildMessage(api, "https://server/api/enroll", "{}", false);

        Assert.False(req.Headers.Contains("X-SSL-Client-CN"));
        Assert.False(req.Headers.Contains("X-SSL-Client-Verify"));
    }

    private static OrgInventoryAgent.Core.Net.ApiClient BuildApiClientWithFakeConfig(string machineId)
    {
        var cfg = new OrgInventoryAgent.Core.AgentConfig
        {
            MachineId = machineId,
            Enrolled = true,
            ClientCertThumbprint = "fake-thumb",
            Endpoints = new[] { "https://server" },
        };
        // Tạo ApiClient không cần thật sự gửi request — chỉ cần gọi BuildMessage.
        var endpoints = new OrgInventoryAgent.Core.Net.EndpointManager(
            cfg,
            Microsoft.Extensions.Logging.Abstractions.NullLogger<OrgInventoryAgent.Core.Net.EndpointManager>.Instance);
        var keyStore = new NullKeyStore();
        return new OrgInventoryAgent.Core.Net.ApiClient(
            cfg, endpoints, keyStore,
            Microsoft.Extensions.Logging.Abstractions.NullLogger<OrgInventoryAgent.Core.Net.ApiClient>.Instance);
    }

    /// <summary>IKeyStore stub — không dùng cho BuildMessage, chỉ để khởi tạo ApiClient.</summary>
    private sealed class NullKeyStore : OrgInventoryAgent.Core.Crypto.IKeyStore
    {
        public bool HasPrivateKey(string machineId) => true;
        public string? GetPrivateKeyPem(string machineId) => null;
        public string? GetCertificatePem(string machineId) => null;
        public void InstallCertificate(string machineId, string certPem, string? keyPem) { }
        public void DeleteCertificate(string machineId) { }
        public bool HasClientCertificate(OrgInventoryAgent.Core.AgentConfig config) => true;
        public System.Security.Cryptography.X509Certificates.X509Certificate2? FindClientCertificate(OrgInventoryAgent.Core.AgentConfig config) => null;
    }
}