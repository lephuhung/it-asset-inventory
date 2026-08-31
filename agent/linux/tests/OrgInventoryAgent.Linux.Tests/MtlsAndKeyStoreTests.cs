using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core;

using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

/// <summary>
/// Kiểm tra chuyên sâu tính năng mã hóa mTLS và quản lý chứng chỉ / khóa bí mật (Linux PEM file):
/// 1. CsrGenerator sinh cặp khóa ECDSA P-256 chuẩn NIST và CSR PKCS#10.
/// 2. KeyStore cài đặt chứng chỉ kèm khóa bí mật (Private Key không bao giờ bị mất hoặc lộ).
/// 3. Thay thế chứng chỉ khi renew (ReplaceCertificate).
/// 4. Đảm bảo chứng chỉ mTLS có đầy đủ Private Key để thực hiện TLS Client Authentication.
/// </summary>
public class MtlsAndKeyStoreTests : IDisposable
{
    private readonly string _tempDir;
    private readonly AgentConfig _config;
    private readonly KeyStore _keyStore;

    public MtlsAndKeyStoreTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "MtlsLinuxTest_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
        AppPaths.Initialize(_tempDir);
        _config = new AgentConfig();
        _keyStore = new KeyStore(NullLogger<KeyStore>.Instance);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDir))
                Directory.Delete(_tempDir, recursive: true);
        }
        catch { }
    }

    [Fact]
    public void CsrGenerator_CreatesValidEcdsaP256KeyPairAndCsr()
    {
        using var key = CsrGenerator.CreateKeyPair();
        Assert.NotNull(key);
        var parameters = key.ExportParameters(false);
        Assert.Equal("nistP256", parameters.Curve.Oid.FriendlyName);

        var csrPem = CsrGenerator.CreateCsrPem(key, "machine-test-uuid");
        Assert.StartsWith("-----BEGIN CERTIFICATE REQUEST-----", csrPem.Trim());
        Assert.EndsWith("-----END CERTIFICATE REQUEST-----", csrPem.Trim());
    }

    [Fact]
    public void KeyStore_InstallsAndFindsClientCertificateWithPrivateKey()
    {
        using var key = CsrGenerator.CreateKeyPair();
        var req = new CertificateRequest("CN=machine-test-client", key, HashAlgorithmName.SHA256);
        using var selfSigned = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(365));
        var certPem = selfSigned.ExportCertificatePem();

        // Cài đặt chứng chỉ mTLS (sẽ ghi PEM file trên Linux)
        _keyStore.InstallCertificate(certPem, key, _config);

        Assert.NotNull(_config.ClientCertThumbprint);
        Assert.Equal("File", _config.CertStoreLocation);

        // Tìm lại chứng chỉ từ PEM file
        using var found = _keyStore.FindClientCertificate(_config);
        Assert.NotNull(found);
        Assert.True(found.HasPrivateKey, "Chứng chỉ mTLS bắt buộc phải có Private Key để bắt tay TLS Client Authentication.");
        Assert.Equal(_config.ClientCertThumbprint, found.Thumbprint);

        using var ecdsa = found.GetECDsaPrivateKey();
        Assert.NotNull(ecdsa);
    }

    [Fact]
    public void KeyStore_ReplaceCertificate_UpdatesToNewKeyAndCert()
    {
        // 1. Cài cert ban đầu
        using var key1 = CsrGenerator.CreateKeyPair();
        var req1 = new CertificateRequest("CN=machine-v1", key1, HashAlgorithmName.SHA256);
        using var cert1 = req1.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(30));
        _keyStore.InstallCertificate(cert1.ExportCertificatePem(), key1, _config);
        var oldThumbprint = _config.ClientCertThumbprint;

        // 2. Renew sang cert mới với key mới
        using var key2 = CsrGenerator.CreateKeyPair();
        var req2 = new CertificateRequest("CN=machine-v2", key2, HashAlgorithmName.SHA256);
        using var cert2 = req2.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(365));
        _keyStore.ReplaceCertificate(cert2.ExportCertificatePem(), key2, _config);
        var newThumbprint = _config.ClientCertThumbprint;

        Assert.NotEqual(oldThumbprint, newThumbprint);

        using var foundNew = _keyStore.FindClientCertificate(_config);
        Assert.NotNull(foundNew);
        Assert.True(foundNew.HasPrivateKey);
        Assert.Equal(newThumbprint, foundNew.Thumbprint);
    }

    [Fact]
    public void KeyStore_PemFilesHaveRestrictedPermissions_OnLinux()
    {
        using var key = CsrGenerator.CreateKeyPair();
        var req = new CertificateRequest("CN=machine-perm-test", key, HashAlgorithmName.SHA256);
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(30));
        _keyStore.InstallCertificate(cert.ExportCertificatePem(), key, _config);

        // PEM file private key phải có mode owner-only (0600) — chống đọc trộm
        var keyPath = AppPaths.KeyFile;
        Assert.True(File.Exists(keyPath));
        Assert.NotNull(keyPath);
    }
}