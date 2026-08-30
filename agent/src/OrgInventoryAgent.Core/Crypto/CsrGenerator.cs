using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace OrgInventoryAgent.Core.Crypto;

/// <summary>
/// Tạo CSR (PKCS#10) — ECDSA P-256, Subject CN theo yêu cầu.
/// Lúc enroll agent chưa biết machine_id → CN = machine-&lt;uuid tạm&gt; (contract cho phép
/// CN=machine-&lt;uuid&gt; bất kỳ; server ký theo CSR, prod dùng step-ca template ép CN=machine-&lt;id&gt;).
/// Khi renew agent đã biết machine_id → CN = machine-&lt;machine_id&gt; (khớp X-SSL-Client-CN).
/// </summary>
public static class CsrGenerator
{
    public static string CreateCsrPem(ECDsa key, string commonName)
    {
        var req = new CertificateRequest($"CN={commonName}", key, HashAlgorithmName.SHA256);

        // CA=false + chỉ dùng để xác thực client (chống lạm dụng cert)
        req.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        req.CertificateExtensions.Add(new X509KeyUsageExtension(
            X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));

        var der = req.CreateSigningRequest();
        return PemEncode("CERTIFICATE REQUEST", der);
    }

    /// <summary>Sinh keypair ECDSA P-256 mới.</summary>
    public static ECDsa CreateKeyPair() =>
        ECDsa.Create(ECCurve.NamedCurves.nistP256);

    private static string PemEncode(string label, byte[] der)
    {
        var sb = new StringBuilder();
        sb.Append("-----BEGIN ").Append(label).Append("-----\n");
        sb.Append(Convert.ToBase64String(der, Base64FormattingOptions.InsertLineBreaks));
        sb.Append('\n').Append("-----END ").Append(label).Append("-----\n");
        return sb.ToString();
    }
}
