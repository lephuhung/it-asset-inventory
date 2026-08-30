using System.IO;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Tests;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>Contract test cho Linux PEM KeyStore.</summary>
public class LinuxKeyStoreContract : IKeyStoreContract
{
    protected override string KeyDir => System.IO.Path.Combine(System.IO.Path.GetTempPath(), "LinuxKeyStoreContract");
    protected override IKeyStore CreateKeyStore(string dataDir) => new LinuxKeyStore(dataDir);

    [Fact]
    public void InstallCertificate_WritesPEMFilesAndSets0600()
    {
        var dir = System.IO.Path.Combine(KeyDir, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(dir);
        var ks = new LinuxKeyStore(dir);

        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var req = new CertificateRequest("CN=machine-test-abc", key, HashAlgorithmName.SHA256);
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(365));
        var certPem = cert.ExportCertificatePem();
        var keyPem = key.ExportPkcs8PrivateKeyPem();

        ks.InstallCertificate("test-abc", certPem, keyPem);

        Assert.True(ks.HasPrivateKey("test-abc"));
        Assert.NotNull(ks.GetCertificatePem("test-abc"));
        Assert.NotNull(ks.GetPrivateKeyPem("test-abc"));
    }

    [Fact]
    public void InstallCertificate_RejectsMissingKeyPem()
    {
        var dir = System.IO.Path.Combine(KeyDir, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(dir);
        var ks = new LinuxKeyStore(dir);

        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var req = new CertificateRequest("CN=machine-x", key, HashAlgorithmName.SHA256);
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddDays(30));

        Assert.Throws<ArgumentException>(() =>
            ks.InstallCertificate("x", cert.ExportCertificatePem(), null));
    }

    [Fact]
    public void FindClientCertificate_ReturnsLoadedCert()
    {
        var dir = System.IO.Path.Combine(KeyDir, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(dir);
        var ks = new LinuxKeyStore(dir);

        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var req = new CertificateRequest("CN=machine-xyz", key, HashAlgorithmName.SHA256);
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddDays(7));
        ks.InstallCertificate("xyz", cert.ExportCertificatePem(), key.ExportPkcs8PrivateKeyPem());

        var cfg = new AgentConfig { MachineId = "xyz" };
        Assert.True(ks.HasClientCertificate(cfg));
        using var found = ks.FindClientCertificate(cfg);
        Assert.NotNull(found);
        Assert.True(found!.HasPrivateKey);
    }

    [Fact]
    public void DeleteCertificate_RemovesBothFiles()
    {
        var dir = System.IO.Path.Combine(KeyDir, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(dir);
        var ks = new LinuxKeyStore(dir);

        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var req = new CertificateRequest("CN=machine-del", key, HashAlgorithmName.SHA256);
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow, DateTimeOffset.UtcNow.AddDays(7));
        ks.InstallCertificate("del", cert.ExportCertificatePem(), key.ExportPkcs8PrivateKeyPem());
        Assert.True(ks.HasPrivateKey("del"));

        ks.DeleteCertificate("del");
        Assert.False(ks.HasPrivateKey("del"));
        Assert.Null(ks.GetCertificatePem("del"));
        Assert.Null(ks.GetPrivateKeyPem("del"));
    }
}
