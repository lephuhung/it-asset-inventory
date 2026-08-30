using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace OrgInventoryAgent.Core.Crypto;

/// <summary>
/// Linux KeyStore — lưu cert + private key dạng PEM files trong data dir.
/// - Cert: <c>{certDir}/machine-{machineId}.crt.pem</c> (mode 0644).
/// - Key:  <c>{certDir}/machine-{machineId}.key.pem</c> (mode 0600, ECDSA PKCS#8).
///
/// Không dùng OpenSSL tool — toàn bộ thao tác qua <see cref="System.Security.Cryptography"/>.
/// <c>certDir</c> mặc định <c>{DataDir}/certs</c>, override bằng env <c>ORGINV_CERT_DIR</c>.
/// </summary>
public sealed class LinuxKeyStore : IKeyStore
{
    private readonly string _certDir;

    public LinuxKeyStore(string? certDir = null)
    {
        _certDir = certDir
            ?? Environment.GetEnvironmentVariable("ORGINV_CERT_DIR")
            ?? Path.Combine(AppPaths.DataDir, "certs");
        Directory.CreateDirectory(_certDir);
    }

    private string CertFile(string machineId) => Path.Combine(_certDir, $"machine-{machineId}.crt.pem");
    private string KeyFile(string machineId) => Path.Combine(_certDir, $"machine-{machineId}.key.pem");

    public bool HasPrivateKey(string machineId) =>
        File.Exists(KeyFile(machineId)) && File.Exists(CertFile(machineId));

    public string? GetPrivateKeyPem(string machineId)
    {
        var path = KeyFile(machineId);
        return File.Exists(path) ? File.ReadAllText(path).Trim() : null;
    }

    public string? GetCertificatePem(string machineId)
    {
        var path = CertFile(machineId);
        return File.Exists(path) ? File.ReadAllText(path).Trim() : null;
    }

    public void InstallCertificate(string machineId, string certPem, string? keyPem)
    {
        if (string.IsNullOrWhiteSpace(machineId))
            throw new ArgumentException("machineId không được rỗng", nameof(machineId));
        if (string.IsNullOrWhiteSpace(certPem))
            throw new ArgumentException("certPem không được rỗng", nameof(certPem));
        if (string.IsNullOrWhiteSpace(keyPem))
            throw new ArgumentException("keyPem không được rỗng trên Linux (Windows store không có sẵn key)", nameof(keyPem));

        // Validate cert.
        using (var cert = X509Certificate2.CreateFromPem(certPem, keyPem))
        {
            if (!cert.HasPrivateKey)
                throw new InvalidOperationException("Cert PEM không có private key đi kèm.");
        }

        File.WriteAllText(CertFile(machineId), certPem.Trim() + "\n");
        File.WriteAllText(KeyFile(machineId), keyPem.Trim() + "\n");
        TrySetUnixMode();
    }

    public void DeleteCertificate(string machineId)
    {
        var c = CertFile(machineId);
        var k = KeyFile(machineId);
        if (File.Exists(c)) File.Delete(c);
        if (File.Exists(k)) File.Delete(k);
    }

    private void TrySetUnixMode()
    {
        if (OperatingSystem.IsWindows()) return;
        try
        {
            foreach (var file in Directory.GetFiles(_certDir))
            {
                var name = Path.GetFileName(file);
                if (name.EndsWith(".key.pem", StringComparison.Ordinal))
                    File.SetUnixFileMode(file, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                else
                    File.SetUnixFileMode(file, UnixFileMode.UserRead | UnixFileMode.GroupRead | UnixFileMode.OtherRead);
            }
        }
        catch { /* không critical */ }
    }

    // ── Windows back-compat: các method này KHÔNG dùng trên Linux, trả null/false. ──

    public bool HasClientCertificate(AgentConfig config) =>
        config is { MachineId: not null } && HasPrivateKey(config.MachineId);

    public X509Certificate2? FindClientCertificate(AgentConfig config)
    {
        if (config?.MachineId is not { } id) return null;
        var certPath = CertFile(id);
        var keyPath = KeyFile(id);
        if (!File.Exists(certPath) || !File.Exists(keyPath)) return null;
        try
        {
            var cert = X509Certificate2.CreateFromPemFile(certPath, keyPath);
            return cert.HasPrivateKey ? cert : null;
        }
        catch
        {
            return null;
        }
    }
}
