using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace OrgInventoryAgent.Core.Crypto;

/// <summary>
/// Abstraction over platform certificate store.
/// - Windows impl dùng Windows Certificate Store (LocalMachine\My hoặc CurrentUser\My).
/// - Linux impl dùng PEM files trong data dir (vd /var/lib/orginventory/client-*.pem).
///
/// Hỗ trợ CẢ HAI contract:
/// 1. Legacy: <c>HasClientCertificate(AgentConfig)</c> / <c>FindClientCertificate(AgentConfig)</c>
///    — dùng cho Windows, tra theo thumbprint/location lưu trong config.
/// 2. Mới (Linux PEM path): HasPrivateKey / GetPrivateKeyPem / GetCertificatePem /
///    InstallCertificate(string machineId, string certPem, string? keyPem) / DeleteCertificate.
///    Trên Windows, các method mới có thể trả null/throw cho keyPem (Windows dùng store).
/// </summary>
public interface IKeyStore
{
    // ── Contract mới (Linux PEM path) ───────────────────────────────
    /// <summary>Có private key cho machine này không? PEM path hoặc Windows store.</summary>
    bool HasPrivateKey(string machineId);

    /// <summary>Trả private key dạng PEM string (Linux only). Windows trả null.</summary>
    string? GetPrivateKeyPem(string machineId);

    /// <summary>Trả certificate dạng PEM string (đọc từ PEM file hoặc Windows store).</summary>
    string? GetCertificatePem(string machineId);

    /// <summary>Cài cert (và key nếu có) cho machine.</summary>
    void InstallCertificate(string machineId, string certPem, string? keyPem);

    /// <summary>Xóa cert của machine.</summary>
    void DeleteCertificate(string machineId);

    // ── Contract cũ (Windows back-compat) ──────────────────────────
    bool HasClientCertificate(AgentConfig config);
    X509Certificate2? FindClientCertificate(AgentConfig config);
}
