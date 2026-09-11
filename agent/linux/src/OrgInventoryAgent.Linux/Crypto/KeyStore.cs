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
        InstallCertificateAtomic(certPem, key, config, isReplace: false);
    }

    /// <summary>
    /// AG-P1-01: Thay cert KHÔNG atomicity cũ đã xóa file cũ trước khi cài cert mới.
    /// Nếu cert mới fail (invalid PEM, disk full, mất điện), cert cũ đã mất →
    /// agent không thể dùng mTLS, không thể gọi renew lại (cần cert hiện hành
    /// cho client cert), kẹt đến khi admin re-enroll bằng bootstrap token.
    ///
    /// Fix: stage `.new` file → validate (cert+key pair, CN, expiry) → atomic rename
    /// `*.new` → `*.pem`. Bất kỳ exception nào trước khi rename xong → file gốc
    /// vẫn còn nguyên. Sau khi rename thành công → file cũ đã được overwrite atomic.
    /// </summary>
    public void ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config)
    {
        certPem = certPem.Trim();
        InstallCertificateAtomic(certPem, newKey, config, isReplace: true);
    }

    /// <summary>
    /// Install (mới) hoặc replace (atomic swap) client cert.
    /// </summary>
    /// <param name="isReplace">
    /// false: cài lần đầu — nếu file đã tồn tại sẽ bị overwrite ngay lập tức
    /// (InitialInstall: không có file cũ để bảo vệ).
    /// true: renew — stage `.new` + validate + atomic rename. Old file intact nếu fail.
    /// </param>
    private void InstallCertificateAtomic(
        string certPem, ECDsa key, AgentConfig config, bool isReplace)
    {
        string certPath = AppPaths.CertFile;
        string keyPath = AppPaths.KeyFile;
        string certStaging = certPath + ".new";
        string keyStaging = keyPath + ".new";

        try
        {
            // Cleanup bất kỳ staging cũ từ lần trước (vd crash trước khi swap xong).
            // KHÔNG chạm file gốc.
            TryDelete(certStaging);
            TryDelete(keyStaging);

            // Step 1: stage new cert + key vào file `.new`.
            File.WriteAllBytes(certStaging, System.Text.Encoding.ASCII.GetBytes(certPem + "\n"));
            File.WriteAllBytes(keyStaging, System.Text.Encoding.ASCII.GetBytes(key.ExportPkcs8PrivateKeyPem()));

            // Set ownership/permissions NGAY khi stage (chưa swap, file gốc chưa chạm).
            try
            {
                File.SetUnixFileMode(keyStaging, UnixFileMode.UserRead | UnixFileMode.UserWrite);   // 0600
                File.SetUnixFileMode(certStaging, UnixFileMode.UserRead | UnixFileMode.UserWrite); // 0600
            }
            catch (Exception ex)
            {
                _logger.LogDebug("Set permissions trên .new file lỗi (không fatal): {Msg}", ex.Message);
            }

            // Step 2: validate cert + private key PAIR (đọc lại từ `.new`).
            // Nếu fail ở đây → xóa staging → throw → file gốc vẫn còn.
            X509Certificate2 loaded;
            try
            {
                loaded = X509Certificate2.CreateFromPemFile(certStaging, keyStaging);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(
                    "Cert mới KHÔNG hợp lệ (không load được từ staging): {Msg}. " +
                    "Cert cũ vẫn còn nguyên — không swap.", ex.Message);
                TryDelete(certStaging);
                TryDelete(keyStaging);
                throw new InvalidOperationException(
                    "Cert mới không hợp lệ — không swap để giữ cert cũ còn usable.", ex);
            }
            try
            {
                if (!loaded.HasPrivateKey)
                {
                    throw new InvalidOperationException(
                        "Cert mới load được nhưng không có private key (key mismatch?).");
                }
                // Check expiry (cert đã NotBefore, chưa NotAfter)
                var now = DateTimeOffset.UtcNow;
                if (loaded.NotAfter.ToUniversalTime() <= now)
                {
                    throw new InvalidOperationException(
                        $"Cert mới đã hết hạn (NotAfter={loaded.NotAfter:o}).");
                }
                if (loaded.NotBefore.ToUniversalTime() > now.AddMinutes(5))
                {
                    throw new InvalidOperationException(
                        $"Cert mới có NotBefore ở tương lai ({loaded.NotBefore:o}) — token CSR có vấn đề?");
                }
            }
            finally
            {
                loaded.Dispose();
            }

            // Step 3: atomic swap. Nếu isReplace=false (initial install), file gốc có thể
            // chưa tồn tại → dùng Move(overwrite:true) là atomic trên cùng FS.
            // Nếu isReplace=true, file gốc tồn tại → cũng atomic swap (rename unlink old + link new).
            File.Move(certStaging, certPath, overwrite: true);
            File.Move(keyStaging, keyPath, overwrite: true);

            // Step 4: reload từ file gốc để verify lần cuối + cập nhật thumbprint.
            using var verify = X509Certificate2.CreateFromPemFile(certPath, keyPath);
            config.ClientCertThumbprint = verify.Thumbprint;
            config.CertStoreLocation = "File";
            _logger.LogInformation(
                "{Action} client cert (Linux file) thumbprint {Thumb}",
                isReplace ? "Đã thay" : "Đã cài",
                verify.Thumbprint);
        }
        catch
        {
            // Đảm bảo cleanup staging bất kỳ exception nào.
            TryDelete(certStaging);
            TryDelete(keyStaging);
            throw;
        }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { /* best-effort */ }
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