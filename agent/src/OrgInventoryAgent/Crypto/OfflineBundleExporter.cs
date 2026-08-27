using System.IO.Compression;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Collectors;

namespace OrgInventoryAgent.Crypto;

/// <summary>
/// Xuất gói dữ liệu tài sản 1-Click cho máy cách ly (Offline USB).
/// - Thu thập thông số phần cứng, phần mềm, bảo mật, fingerprint.
/// - Ký số ECDSA P-256 (SHA-256, RFC 3279 DER Sequence).
/// - Mã hóa lai AES-256-GCM + Server RSA-2048 OAEP(SHA-256).
/// - Đóng gói vào 1 file ZIP duy nhất: manifest.json, encrypted_payload.bin, encrypted_key.bin, iv.bin, tag.bin, signature.sig, public_key.pem.
/// </summary>
public static class OfflineBundleExporter
{
    public static async Task<bool> ExportBundleAsync(
        string outputZipPath,
        string? serverKeyPath,
        string? orgId,
        AgentConfig config,
        ILogger logger)
    {
        try
        {
            logger.LogInformation("Bắt đầu tiến trình thu thập tài sản offline...");

            // 1. Thu thập cấu hình
            using var loggerFactory = LoggerFactory.Create(b => b.AddSimpleConsole());
            var fpCollector = new FingerprintCollector(loggerFactory.CreateLogger<FingerprintCollector>());
            var fingerprint = fpCollector.Collect();

            var invCollector = new InventoryCollector(loggerFactory.CreateLogger<InventoryCollector>());
            var spec = invCollector.Collect();

            var machineUuid = config.MachineId ?? fingerprint.SmbiosUuid ?? Guid.NewGuid().ToString();
            var exportedAt = DateTime.UtcNow.ToString("o");

            var payload = new Dictionary<string, object?>
            {
                ["machine_uuid"] = machineUuid,
                ["hostname"] = Environment.MachineName,
                ["fingerprint"] = fingerprint,
                ["spec"] = spec,
                ["exported_at"] = exportedAt,
            };
            if (!string.IsNullOrWhiteSpace(orgId))
            {
                payload["org_id"] = orgId;
            }

            // 2. Lấy hoặc sinh cặp khóa ECDSA P-256 của máy trạm
            var keyStore = new KeyStore(loggerFactory.CreateLogger<KeyStore>());
            var cert = keyStore.FindClientCertificate(config);
            ECDsa? ecdsa = cert?.GetECDsaPrivateKey();
            bool disposeEcdsa = false;

            if (ecdsa == null)
            {
                logger.LogInformation("Chưa có client cert trong store — sinh cặp khóa ECDSA P-256 mới cho máy...");
                ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
                disposeEcdsa = true;

                try
                {
                    var req = new CertificateRequest($"CN=machine-{machineUuid}", ecdsa, HashAlgorithmName.SHA256);
                    using var selfSigned = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(10));
                    keyStore.InstallCertificate(selfSigned.ExportCertificatePem(), ecdsa, config);
                    config.Save();
                }
                catch (Exception ex)
                {
                    logger.LogWarning("Không thể lưu cert tự ký vào Windows store: {Msg}", ex.Message);
                }
            }

            // 3. Chuẩn hóa Canonical JSON và Ký số
            logger.LogInformation("Ký số ECDSA trên payload cấu hình...");
            byte[] canonicalBytes = CanonicalJson.ToCanonicalBytes(payload);
            byte[] signature = ecdsa.SignData(canonicalBytes, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence);
            string signatureB64 = Convert.ToBase64String(signature);
            string agentPubKeyPem = ecdsa.ExportSubjectPublicKeyInfoPem();

            if (disposeEcdsa)
            {
                ecdsa.Dispose();
            }

            // 4. Tìm khóa công khai Server RSA
            string? serverKeyPem = ResolveServerPublicKey(serverKeyPath, outputZipPath, logger);
            if (string.IsNullOrWhiteSpace(serverKeyPem))
            {
                logger.LogError("Không tìm thấy server_public_key.pem! Vui lòng copy file này từ Portal vào cùng thư mục USB.");
                return false;
            }

            // 5. Mã hóa lai (AES-256-GCM + RSA OAEP)
            logger.LogInformation("Mã hóa gói dữ liệu bằng Server Public Key (AES-256-GCM + RSA-OAEP)...");
            byte[] sessionKey = RandomNumberGenerator.GetBytes(32); // 256 bits
            byte[] iv = RandomNumberGenerator.GetBytes(12); // 96 bits for GCM
            byte[] ciphertext = new byte[canonicalBytes.Length];
            byte[] tag = new byte[16]; // 128 bits

            using (var aesGcm = new AesGcm(sessionKey, 16))
            {
                aesGcm.Encrypt(iv, canonicalBytes, ciphertext, tag);
            }

            byte[] encryptedKey;
            using (var rsa = RSA.Create())
            {
                rsa.ImportFromPem(serverKeyPem);
                encryptedKey = rsa.Encrypt(sessionKey, RSAEncryptionPadding.OaepSHA256);
            }

            // 6. Đóng gói ZIP
            logger.LogInformation("Nén file ZIP kết quả tại: {Path}", outputZipPath);
            var manifest = new
            {
                machine_uuid = machineUuid,
                hostname = Environment.MachineName,
                fingerprint = fingerprint,
                exported_at = exportedAt,
                org_id = orgId,
            };
            string manifestJson = JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true });

            var dir = Path.GetDirectoryName(Path.GetFullPath(outputZipPath));
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }
            if (File.Exists(outputZipPath))
            {
                File.Delete(outputZipPath);
            }

            // ⚠️ ZIP kết quả KHÔNG đặt password (yêu cầu nghiệp vụ — operator copy qua
            // USB dễ dàng; tính bí mật dựa vào mã hóa hybrid AES-256-GCM + RSA-OAEP bên
            // trong các entry). Tuyệt đối KHÔNG dùng ZipArchive.CreateEntry với
            // ZipArchiveEntry... với password.
            using (var zipStream = new FileStream(outputZipPath, FileMode.Create, FileAccess.Write))
            using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Create))
            {
                AddEntry(archive, "manifest.json", Encoding.UTF8.GetBytes(manifestJson));
                AddEntry(archive, "encrypted_payload.bin", ciphertext);
                AddEntry(archive, "encrypted_key.bin", encryptedKey);
                AddEntry(archive, "iv.bin", iv);
                AddEntry(archive, "tag.bin", tag);
                AddEntry(archive, "signature.sig", Encoding.UTF8.GetBytes(signatureB64));
                AddEntry(archive, "public_key.pem", Encoding.UTF8.GetBytes(agentPubKeyPem));
            }

            logger.LogInformation("✔ Đã xuất gói ZIP mã hóa thành công: {Path}", outputZipPath);
            return true;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Lỗi khi đóng gói xuất dữ liệu offline: {Msg}", ex.Message);
            return false;
        }
    }

    private static void AddEntry(ZipArchive archive, string entryName, byte[] data)
    {
        // KHÔNG đặt password cho entry — tính bí mật dựa vào mã hóa hybrid trong data.
        var entry = archive.CreateEntry(entryName, CompressionLevel.Optimal);
        using var stream = entry.Open();
        stream.Write(data, 0, data.Length);
    }

    private static string? ResolveServerPublicKey(string? explicitPath, string outputZipPath, ILogger logger)
    {
        if (!string.IsNullOrWhiteSpace(explicitPath) && File.Exists(explicitPath))
        {
            return File.ReadAllText(explicitPath);
        }

        // Tìm trong thư mục chứa file zip đầu ra (thường là ổ USB)
        var zipDir = Path.GetDirectoryName(Path.GetFullPath(outputZipPath));
        if (!string.IsNullOrEmpty(zipDir))
        {
            var usbKey = Path.Combine(zipDir, "server_public_key.pem");
            if (File.Exists(usbKey)) return File.ReadAllText(usbKey);
        }

        // Tìm trong thư mục chạy của Agent
        var appKey = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "server_public_key.pem");
        if (File.Exists(appKey)) return File.ReadAllText(appKey);

        // Tìm trong AppPaths.DataDir
        var dataKey = Path.Combine(AppPaths.DataDir, "server_public_key.pem");
        if (File.Exists(dataKey)) return File.ReadAllText(dataKey);

        return null;
    }
}
