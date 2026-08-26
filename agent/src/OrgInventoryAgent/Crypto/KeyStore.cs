using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Crypto;

/// <summary>
/// Lưu trữ private key + client cert.
/// - Windows: Windows Certificate Store — thử LocalMachine\My (service LocalSystem),
///   fallback CurrentUser\My (console dev không admin). Private key không bao giờ rời máy.
/// - Linux (dev/test): lưu PEM file trong data dir.
/// Định danh cert: cấu hình lưu ClientCertThumbprint + CertStoreLocation.
/// </summary>
public sealed class KeyStore
{
    private readonly ILogger<KeyStore> _logger;

    public KeyStore(ILogger<KeyStore> logger) => _logger = logger;

    /// <summary>Có client cert (có private key) theo config không?</summary>
    public bool HasClientCertificate(AgentConfig config) =>
        FindClientCertificate(config) is not null;

    /// <summary>
    /// Tìm client cert kèm private key. Windows: tìm trong store theo thumbprint (hoặc CN=machine-*).
    /// Linux: load từ PEM files. Trả null nếu không có.
    /// </summary>
    public X509Certificate2? FindClientCertificate(AgentConfig config)
    {
        if (OperatingSystem.IsWindows())
        {
            return FindInStore(config);
        }

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

    /// <summary>Cài cert mới (enroll): lưu cert + private key.</summary>
    public void InstallCertificate(string certPem, ECDsa key, AgentConfig config)
    {
        certPem = certPem.Trim();
        if (OperatingSystem.IsWindows())
        {
            using var cert = X509Certificate2.CreateFromPem(certPem);
            using var certWithKey = cert.CopyWithPrivateKey(key);
            var (thumbprint, location) = AddToStore(certWithKey);
            config.ClientCertThumbprint = thumbprint;
            config.CertStoreLocation = location;
            _logger.LogInformation("Đã cài client cert {Thumb} vào store {Loc}", thumbprint, location);
        }
        else
        {
            File.WriteAllText(AppPaths.CertFile, certPem + "\n");
            File.WriteAllText(AppPaths.KeyFile, key.ExportPkcs8PrivateKeyPem());
            if (!OperatingSystem.IsWindows())
            {
                try
                {
                    File.SetUnixFileMode(AppPaths.KeyFile, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                    File.SetUnixFileMode(AppPaths.CertFile, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                }
                catch { }
            }
            using var loaded = X509Certificate2.CreateFromPemFile(AppPaths.CertFile, AppPaths.KeyFile);
            config.ClientCertThumbprint = loaded.Thumbprint;
            config.CertStoreLocation = "File";
            _logger.LogInformation("Đã lưu client cert (Linux file) thumbprint {Thumb}", loaded.Thumbprint);
        }
    }

    /// <summary>Thay cert cũ bằng cert mới (renew): xóa cert cũ theo thumbprint, cài cert mới.</summary>
    public void ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config)
    {
        if (OperatingSystem.IsWindows())
        {
            RemoveFromStore(config);
        }
        else
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
        }
        InstallCertificate(certPem, newKey, config);
    }

    // ── Windows store ──────────────────────────────────────────────

    private X509Certificate2? FindInStore(AgentConfig config)
    {
        var locations = config.CertStoreLocation == "CurrentUser"
            ? new[] { StoreLocation.CurrentUser, StoreLocation.LocalMachine }
            : new[] { StoreLocation.LocalMachine, StoreLocation.CurrentUser };

        foreach (var loc in locations)
        {
            try
            {
                using var store = new X509Store(StoreName.My, loc);
                store.Open(OpenFlags.ReadOnly);
                var all = store.Certificates;

                X509Certificate2? found = null;
                if (!string.IsNullOrWhiteSpace(config.ClientCertThumbprint))
                {
                    found = all
                        .FirstOrDefault(c => string.Equals(c.Thumbprint, config.ClientCertThumbprint,
                            StringComparison.OrdinalIgnoreCase));
                }
                found ??= all
                    .FirstOrDefault(c => c.Subject.Contains("CN=machine-", StringComparison.OrdinalIgnoreCase));

                if (found is not null && found.HasPrivateKey)
                {
                    _logger.LogDebug("Tìm thấy client cert {Thumb} trong store {Loc}", found.Thumbprint, loc);
                    return found; // caller dispose
                }
                found?.Dispose();
                foreach (var c in all) c.Dispose();
            }
            catch (Exception ex)
            {
                _logger.LogDebug("Mở store {Loc} lỗi: {Msg}", loc, ex.Message);
            }
        }
        return null;
    }

    private (string Thumbprint, string Location) AddToStore(X509Certificate2 certWithKey)
    {
        var attempts = new[]
        {
            (StoreLocation.LocalMachine, "LocalMachine"),
            (StoreLocation.CurrentUser, "CurrentUser"),
        };
        Exception? last = null;
        foreach (var (loc, name) in attempts)
        {
            try
            {
                using var store = new X509Store(StoreName.My, loc);
                store.Open(OpenFlags.ReadWrite);
                store.Add(certWithKey);
                _logger.LogInformation("Cert đã thêm vào store {Name}", name);
                return (certWithKey.Thumbprint, name);
            }
            catch (Exception ex)
            {
                last = ex;
                _logger.LogDebug("Thêm cert vào {Name} lỗi: {Msg}", name, ex.Message);
            }
        }
        throw new InvalidOperationException($"Không cài được cert vào Windows store: {last?.Message}");
    }

    private void RemoveFromStore(AgentConfig config)
    {
        var locations = config.CertStoreLocation == "CurrentUser"
            ? new[] { StoreLocation.CurrentUser, StoreLocation.LocalMachine }
            : new[] { StoreLocation.LocalMachine, StoreLocation.CurrentUser };
        foreach (var loc in locations)
        {
            try
            {
                using var store = new X509Store(StoreName.My, loc);
                store.Open(OpenFlags.ReadWrite);
                var toRemove = store.Certificates
                    .Where(c => string.Equals(c.Thumbprint, config.ClientCertThumbprint,
                        StringComparison.OrdinalIgnoreCase))
                    .ToList();
                foreach (var c in toRemove)
                {
                    store.Remove(c);
                    _logger.LogInformation("Đã xóa cert cũ {Thumb} khỏi {Loc}", c.Thumbprint, loc);
                    c.Dispose();
                }
                return;
            }
            catch (Exception ex)
            {
                _logger.LogDebug("Xóa cert khỏi {Loc} lỗi: {Msg}", loc, ex.Message);
            }
        }
    }
}
