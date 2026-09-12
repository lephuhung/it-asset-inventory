using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Linux.Crypto;
using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

/// <summary>
/// AG-P1-01: Certificate rotation KHÔNG atomicity — Windows/Linux.
///
/// Bug trước fix: `ReplaceCertificate()` xóa cert/key cũ TRƯỚC khi cài cert mới.
/// Nếu bước cài cert mới fail (write error, invalid PEM, mất điện), agent đã mất
/// luôn cert cũ → KHÔNG thể dùng mTLS → KHÔNG thể gọi renew lại được (cần cert
/// hiện hành cho mTLS) → bị kẹt, phải enroll lại từ đầu bằng bootstrap token.
///
/// Fix:
/// - Linux: stage cert/key mới vào file `.new`, validate private-key + cert pair +
///   CN/expiry → atomic rename `*.new` → `*.pem`. Nếu install/validate fail, file gốc
///   vẫn còn nguyên.
/// - Windows: thử Add cert mới vào store trước → nếu OK mới Remove old (cùng thumbprint).
/// Mọi exception giữa chừng đảm bảo cert cũ vẫn usable.
/// </summary>
public sealed class KeyStoreAtomicReplaceTests : IDisposable
{
    private readonly string _tmpDir;
    private readonly KeyStore _store;

    public KeyStoreAtomicReplaceTests()
    {
        _tmpDir = Path.Combine(Path.GetTempPath(), "keystore-atomic-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tmpDir);
        AppPaths.Initialize(_tmpDir);
        _store = new KeyStore(NullLogger<KeyStore>.Instance);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tmpDir, recursive: true); } catch { }
    }

    /// <summary>Sinh cert + ECDSA key hợp lệ (self-signed, CN=machine-X).</summary>
    private static (X509Certificate2 Cert, ECDsa Key, string CertPem) GenerateCert(string commonName)
    {
        var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var req = new CertificateRequest($"CN={commonName}", key, HashAlgorithmName.SHA256);
        req.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        var cert = req.Create(
            new X500DistinguishedName($"CN={commonName}"),
            X509SignatureGenerator.CreateForECDsa(key),
            DateTimeOffset.UtcNow.AddDays(-1),
            DateTimeOffset.UtcNow.AddDays(90),
            new byte[] { 1, 2, 3, 4 });
        var pem = cert.ExportCertificatePem();
        return (cert, key, pem);
    }

    [Fact]
    public void Initial_Install_Writes_Pem_Files()
    {
        var cfg = new AgentConfig { MachineId = "test-1" };
        var (cert, key, pem) = GenerateCert("machine-test-1");

        try
        {
            _store.InstallCertificate(pem, key, cfg);

            Assert.True(File.Exists(AppPaths.CertFile));
            Assert.True(File.Exists(AppPaths.KeyFile));
            Assert.Equal(cert.Thumbprint, cfg.ClientCertThumbprint);
            Assert.Equal("File", cfg.CertStoreLocation);
            // Private key file phải mode 0600 (chỉ owner đọc/ghi).
            var mode = File.GetUnixFileMode(AppPaths.KeyFile);
            Assert.True(
                mode.HasFlag(UnixFileMode.UserRead)
                && !mode.HasFlag(UnixFileMode.GroupRead)
                && !mode.HasFlag(UnixFileMode.OtherRead),
                $"Key file permissions không đúng mode 0600: {mode}");
        }
        finally
        {
            cert.Dispose();
            key.Dispose();
        }
    }

    /// <summary>
    /// AG-P1-01 acceptance #1: Renew failure KHÔNG làm mất cert cũ.
    ///
    /// Trước fix: `ReplaceCertificate()` xóa file cũ rồi gọi `InstallCertificate()`.
    /// Nếu `InstallCertificate()` throw (vd PEM invalid), cert/key cũ đã mất.
    /// Sau fix: stage `.new` → validate → atomic rename. Nếu install fail ở bất kỳ
    /// bước nào, file gốc vẫn còn.
    /// </summary>
    [Fact]
    public void Replace_With_Invalid_New_Cert_Preserves_Old_Files()
    {
        var cfg = new AgentConfig { MachineId = "test-2" };
        var (oldCert, oldKey, oldPem) = GenerateCert("machine-test-2");
        var oldThumbprint = oldCert.Thumbprint;

        try
        {
            // Step 1: cài cert cũ thành công
            _store.InstallCertificate(oldPem, oldKey, cfg);
            Assert.True(File.Exists(AppPaths.CertFile));
            Assert.True(File.Exists(AppPaths.KeyFile));
            var origCertBytes = File.ReadAllBytes(AppPaths.CertFile);
            var origKeyBytes = File.ReadAllBytes(AppPaths.KeyFile);

            // Step 2: giả lập renew với cert PEM rác (không phải X.509 PEM)
            // → InstallCertificate sẽ throw khi tạo X509Certificate2.
            var bogusPem = "-----BEGIN CERTIFICATE-----\nTHIS_IS_NOT_VALID_BASE64==\n-----END CERTIFICATE-----\n";
            using var bogusKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);

            var ex = Assert.ThrowsAny<Exception>(() =>
                _store.ReplaceCertificate(bogusPem, bogusKey, cfg));

            // Cert cũ PHẢI còn nguyên — KHÔNG bị xóa.
            Assert.True(File.Exists(AppPaths.CertFile),
                $"AG-P1-01 BUG: cert cũ bị mất sau khi install cert mới thất bại. Exception: {ex.Message}");
            Assert.True(File.Exists(AppPaths.KeyFile),
                "AG-P1-01 BUG: private key cũ bị mất sau khi install cert mới thất bại.");
            Assert.Equal(origCertBytes, File.ReadAllBytes(AppPaths.CertFile));
            Assert.Equal(origKeyBytes, File.ReadAllBytes(AppPaths.KeyFile));
            Assert.Equal(oldThumbprint, cfg.ClientCertThumbprint);
            // File `.new` (nếu stage partial) phải được dọn dẹp để tránh confusion
            // cho retry lần sau. Đây cũng là acceptance: "không để lại file lạ".
            Assert.False(File.Exists(AppPaths.CertFile + ".new"));
            Assert.False(File.Exists(AppPaths.KeyFile + ".new"));
        }
        finally
        {
            oldCert.Dispose();
            oldKey.Dispose();
        }
    }

    /// <summary>
    /// AG-P1-01 acceptance #2: New cert + key phải match (private key verify cert signature).
    /// Trước fix: nếu agent ghi cert nhưng key sai file / corrupt, không phát hiện được.
    /// Sau fix: validate `cert.HasPrivateKey` + reload + ensure private key parses,
    /// nếu không thì reject ngay (không swap).
    /// </summary>
    [Fact]
    public void Replace_With_Mismatched_Key_Does_Not_Swap()
    {
        var cfg = new AgentConfig { MachineId = "test-3" };
        var (oldCert, oldKey, oldPem) = GenerateCert("machine-test-3");
        var oldThumbprint = oldCert.Thumbprint;

        try
        {
            _store.InstallCertificate(oldPem, oldKey, cfg);
            var origCertBytes = File.ReadAllBytes(AppPaths.CertFile);

            // New cert + key MISMATCH: cert ký bởi key khác, không phải key truyền vào.
            var (newCert, _, newPem) = GenerateCert("machine-test-3");
            using var unrelatedKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);

            Assert.ThrowsAny<Exception>(() =>
                _store.ReplaceCertificate(newPem, unrelatedKey, cfg));

            // Old cert PHẢI còn — KHÔNG được swap khi validation fail.
            Assert.True(File.Exists(AppPaths.CertFile));
            Assert.Equal(origCertBytes, File.ReadAllBytes(AppPaths.CertFile));
            Assert.Equal(oldThumbprint, cfg.ClientCertThumbprint);
        }
        finally
        {
            oldCert.Dispose();
            oldKey.Dispose();
        }
    }

    /// <summary>
    /// AG-P1-01 acceptance #3: Successful activation — sau khi renew thành công,
    /// cert cũ bị thay thế bằng cert mới, thumbprint updated.
    /// </summary>
    [Fact]
    public void Replace_With_Valid_New_Cert_Succeeds_And_Updates_Thumbprint()
    {
        var cfg = new AgentConfig { MachineId = "test-4" };
        var (oldCert, oldKey, oldPem) = GenerateCert("machine-test-4");
        var oldThumbprint = oldCert.Thumbprint;

        try
        {
            _store.InstallCertificate(oldPem, oldKey, cfg);
            Assert.Equal(oldThumbprint, cfg.ClientCertThumbprint);

            // New cert: valid, cùng CN, key khớp.
            var (newCert, newKey, newPem) = GenerateCert("machine-test-4");
            try
            {
                _store.ReplaceCertificate(newPem, newKey, cfg);

                Assert.Equal(newCert.Thumbprint, cfg.ClientCertThumbprint);
                Assert.NotEqual(oldThumbprint, cfg.ClientCertThumbprint);

                // Reload: cert + private key readable, HasPrivateKey = true.
                using var reload = X509Certificate2.CreateFromPemFile(
                    AppPaths.CertFile, AppPaths.KeyFile);
                Assert.True(reload.HasPrivateKey);
                Assert.Equal(newCert.Thumbprint, reload.Thumbprint);
            }
            finally
            {
                newCert.Dispose();
                newKey.Dispose();
            }
        }
        finally
        {
            oldCert.Dispose();
            oldKey.Dispose();
        }
    }

    /// <summary>
    /// AG-P1-01 cleanup: file `.new` tạm không tồn tại sau khi thành công.
    /// </summary>
    [Fact]
    public void Replace_Successful_Does_Not_Leave_Tempfiles()
    {
        var cfg = new AgentConfig { MachineId = "test-5" };
        var (oldCert, oldKey, oldPem) = GenerateCert("machine-test-5");
        var (newCert, newKey, newPem) = GenerateCert("machine-test-5");

        try
        {
            _store.InstallCertificate(oldPem, oldKey, cfg);
            _store.ReplaceCertificate(newPem, newKey, cfg);

            Assert.False(File.Exists(AppPaths.CertFile + ".new"),
                "Cert file .new tạm không được để lại sau khi swap thành công.");
            Assert.False(File.Exists(AppPaths.KeyFile + ".new"));
        }
        finally
        {
            oldCert.Dispose();
            oldKey.Dispose();
            newCert.Dispose();
            newKey.Dispose();
        }
    }
}