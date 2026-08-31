using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;

namespace OrgInventoryAgent.Linux.Crypto;

/// <summary>
/// Linux KeyStore — lưu client cert + private key dạng PEM files tại AppPaths.CertFile/KeyFile
/// (data dir). API mirror Windows KeyStore (config-based: thumbprint + CertStoreLocation="File")
/// để EnrollCoordinator/RenewService dùng chung logic. Implement đủ IKeyStore contract.
/// </summary>
public sealed class KeyStore : IKeyStore
{
    private readonly ILogger<KeyStore> _logger;

    public KeyStore(ILogger<KeyStore> logger) => _logger = logger;

    public bool HasClientCertificate(AgentConfig config) =>
        FindClientCertificate(config) is not null;

    public X509Certificate2? FindClientCertificate(AgentConfig config)
    {
        try
        {
            if (File.Exists(AppPaths.CertFile) && File.Exists(AppPaths.KeyFile))
            {
                var cert = X509Certificate2.CreateFromPemFile(AppPaths.CertFile, AppPaths.KeyFile);
                if (cert.HasPrivateKey)
                {
                    config.ClientCertThumbprint ??= cert.Thumbprint;
                    return cert;
                }
                cert.Dispose();
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Load client cert (Linux file) lỗi: {Msg}", ex.Message);
        }
        return null;
    }

    public void InstallCertificate(string certPem, ECDsa key, AgentConfig config)
    {
        certPem = certPem.Trim();
        File.WriteAllText(AppPaths.CertFile, certPem + "\n");
        File.WriteAllText(AppPaths.KeyFile, key.ExportPkcs8PrivateKeyPem());
        try
        {
            File.SetUnixFileMode(AppPaths.KeyFile, UnixFileMode.UserRead | UnixFileMode.UserWrite); // 0600
            File.SetUnixFileMode(AppPaths.CertFile, UnixFileMode.UserRead | UnixFileMode.UserWrite); // 0600
        }
        catch { }
        using var loaded = X509Certificate2.CreateFromPemFile(AppPaths.CertFile, AppPaths.KeyFile);
        config.ClientCertThumbprint = loaded.Thumbprint;
        config.CertStoreLocation = "File";
        _logger.LogInformation("Đã lưu client cert (Linux file) thumbprint {Thumb}", loaded.Thumbprint);
    }

    public void ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config)
    {
        try
        {
            if (File.Exists(AppPaths.CertFile)) File.Delete(AppPaths.CertFile);
            if (File.Exists(AppPaths.KeyFile)) File.Delete(AppPaths.KeyFile);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Xóa PEM cũ lỗi: {Msg}", ex.Message);
        }
        InstallCertificate(certPem, newKey, config);
    }

    // ── IKeyStore contract mới (machineId-based) — delegate Core LinuxKeyStore ──
    private readonly LinuxKeyStore _legacy = new();
    public bool HasPrivateKey(string machineId) => _legacy.HasPrivateKey(machineId);
    public string? GetPrivateKeyPem(string machineId) => _legacy.GetPrivateKeyPem(machineId);
    public string? GetCertificatePem(string machineId) => _legacy.GetCertificatePem(machineId);
    public void InstallCertificate(string machineId, string certPem, string? keyPem) =>
        _legacy.InstallCertificate(machineId, certPem, keyPem);
    public void DeleteCertificate(string machineId) => _legacy.DeleteCertificate(machineId);
}