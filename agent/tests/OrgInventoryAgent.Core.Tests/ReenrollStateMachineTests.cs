using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// AG-P1-02: Re-enrollment state machine sai.
///
/// Bug trước fix:
/// - enrollment token là one-time, bị xóa sau enroll.
/// - Khi cert mất (vd OS cài lại), HeartbeatService chỉ set `_config.Enrolled = false`
///   rồi để EnrollCoordinator retry. Coordinator thấy IsEnrolled=false → đi vào
///   EnrollCoreAsync → check token trống → log CRITICAL và return false. Chu kỳ sau lại
///   lặp lại → spam log + gọi ensureEnrolled ngay cả khi không có fresh token.
///
/// Fix:
/// - Thêm `REENROLL_REQUIRED` vào EnrollStatus, lưu persistent trong AgentConfig.
/// - Heartbeat / Renew / Inventory phát hiện cert biến mất → set reenroll_required=true.
/// - EnrollCoordinator: nếu reenroll_required + không có fresh token → không retry, chỉ
///   log 1 lần rồi chờ admin issue token (return false ngay, không spam).
/// - Khi admin issue fresh token mới vào config.Token → Coordinator re-enroll + clear
///   reenroll_required trên đường thành công.
/// - KHÔNG reuse token cũ (đã xóa sau enroll).
/// </summary>
public sealed class ReenrollStateMachineTests
{
    /// <summary>In-memory IKeyStore giả lập — tạo cert ECDSA thật, có thể bật/tắt.</summary>
    private sealed class FakeKeyStore : IKeyStore, IDisposable
    {
        public bool CertExists { get; set; } = true;
        private readonly System.Security.Cryptography.ECDsa _key =
            System.Security.Cryptography.ECDsa.Create(System.Security.Cryptography.ECCurve.NamedCurves.nistP256);
        private readonly Lazy<X509Certificate2> _cert;

        public FakeKeyStore()
        {
            _cert = new Lazy<X509Certificate2>(() =>
            {
                var req = new System.Security.Cryptography.X509Certificates.CertificateRequest(
                    "CN=test", _key, System.Security.Cryptography.HashAlgorithmName.SHA256);
                return req.Create(
                    new System.Security.Cryptography.X509Certificates.X500DistinguishedName("CN=test"),
                    System.Security.Cryptography.X509Certificates.X509SignatureGenerator.CreateForECDsa(_key),
                    DateTimeOffset.UtcNow.AddDays(-1),
                    DateTimeOffset.UtcNow.AddDays(90),
                    new byte[] { 1, 2, 3, 4 });
            });
        }

        public X509Certificate2? FindClientCertificate(AgentConfig config) =>
            CertExists ? _cert.Value : null;

        public bool HasClientCertificate(AgentConfig config) => CertExists;

        public bool HasPrivateKey(string machineId) => CertExists;
        public string? GetPrivateKeyPem(string machineId) => null;
        public string? GetCertificatePem(string machineId) => null;
        public void InstallCertificate(string machineId, string certPem, string? keyPem) { }
        public void DeleteCertificate(string machineId) { }
        public void Dispose()
        {
            if (_cert.IsValueCreated) _cert.Value.Dispose();
            _key.Dispose();
        }
    }

    [Fact]
    public void Reenroll_Required_Status_Added_To_Enum()
    {
        // GREEN: enum có REENROLL_REQUIRED dùng cho trạng thái "đã enroll, cert
        // mất, cần fresh token từ admin".
        Assert.True(Enum.IsDefined(typeof(EnrollStatus), EnrollStatus.ReenrollRequired),
            "EnrollStatus enum phải có giá trị ReenrollRequired để heartbeat/renew " +
            "có thể chuyển trạng thái sau khi cert biến mất.");
        // Khác các giá trị cũ.
        Assert.NotEqual(EnrollStatus.Enrolled, EnrollStatus.ReenrollRequired);
    }

    [Fact]
    public void Validate_Returns_ReenrollRequired_When_Enrolled_But_Cert_Missing()
    {
        var cfg = new AgentConfig
        {
            Enrolled = true,
            MachineId = "abc",
            ClientCertThumbprint = "thumb-A",
        };
        var fakeStore = new FakeKeyStore { CertExists = false };

        var status = AgentIdentity.Validate(cfg, fakeStore);

        Assert.Equal(EnrollStatus.ReenrollRequired, status);
        // IMPORTANT: KHÔNG trả CertMissing như cũ — phải phân biệt để Coordinator
        // biết là cần token mới (không phải chỉ retry enroll).
    }

    [Fact]
    public void Validate_Returns_Enrolled_When_Cert_Present()
    {
        var cfg = new AgentConfig
        {
            Enrolled = true,
            MachineId = "abc",
            ClientCertThumbprint = "thumb-A",
        };
        var fakeStore = new FakeKeyStore { CertExists = true };

        Assert.Equal(EnrollStatus.Enrolled, AgentIdentity.Validate(cfg, fakeStore));
    }

    [Fact]
    public void Validate_Returns_NotEnrolled_When_Config_Empty()
    {
        var cfg = new AgentConfig { Enrolled = false, MachineId = null };
        var fakeStore = new FakeKeyStore { CertExists = true };

        Assert.Equal(EnrollStatus.NotEnrolled, AgentIdentity.Validate(cfg, fakeStore));
    }

    [Fact]
    public void IsEnrolled_Returns_False_When_Reenroll_Required()
    {
        // Trạng thái ReenrollRequired KHÔNG được coi là "enrolled" — agent không nên
        // gửi mTLS request (sẽ fail 401 vì cert gone).
        var cfg = new AgentConfig
        {
            Enrolled = false,
            MachineId = "abc",
            ClientCertThumbprint = null,
            ReenrollRequired = true,
        };

        Assert.False(AgentIdentity.IsEnrolled(cfg));
        Assert.False(AgentIdentity.HasUsableCertificate(cfg, new FakeKeyStore { CertExists = false }));
    }

    [Fact]
    public void AgentConfig_Persists_ReenrollRequired()
    {
        // ReenrollRequired phải serialize được qua config.json để restart agent
        // giữ được trạng thái này (KHÔNG retry nhưng chờ admin).
        var cfg = new AgentConfig
        {
            Enrolled = false,
            MachineId = "machine-abc",
            ClientCertThumbprint = null,
            ReenrollRequired = true,
            Token = null,
        };

        var json = System.Text.Json.JsonSerializer.Serialize(cfg);
        // AgentConfig uses CamelCase (JsonNamingPolicy.CamelCase); key là "reenrollRequired".
        // System.Text.Json mặc định viết true (không có dấu nháy).
        Assert.Contains("\"reenrollRequired\":true", json, StringComparison.OrdinalIgnoreCase);

        var loaded = System.Text.Json.JsonSerializer.Deserialize<AgentConfig>(json)!;
        Assert.True(loaded.ReenrollRequired);
        Assert.Equal("machine-abc", loaded.MachineId);
        Assert.Null(loaded.Token); // KHÔNG reuse token cũ
    }

    [Fact]
    public void IsReenrollPending_Is_True_When_Reenroll_Required_And_No_Fresh_Token()
    {
        // Helper xác định xem có nên retry enroll hay KHÔNG.
        // - Reenroll + không có token → KHÔNG retry (spam)
        // - Reenroll + có token mới → retry (admin vừa issue)
        var noToken = new AgentConfig { ReenrollRequired = true, Token = null };
        var withToken = new AgentConfig { ReenrollRequired = true, Token = "fresh-token-XYZ" };

        Assert.True(AgentIdentity.IsReenrollPending(noToken));
        Assert.False(AgentIdentity.IsReenrollPending(withToken),
            "Khi có fresh token, Coordinator phải thử lại ngay — trạng thái pending chỉ khi KHÔNG có token.");
    }

    [Fact]
    public void IsReenrollPending_Is_False_When_Already_Enrolled()
    {
        var enrolled = new AgentConfig { Enrolled = true, MachineId = "x", ClientCertThumbprint = "t" };
        Assert.False(AgentIdentity.IsReenrollPending(enrolled));
    }
}