using OrgInventoryAgent.Core;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using OrgInventoryAgent.Services;
using Xunit;

namespace OrgInventoryAgent.Tests;

public class RenewServiceTests
{
    [Fact]
    public void RemainingLifePercent_CalculatesAccurately()
    {
        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest("CN=test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);

        var notBefore = DateTimeOffset.UtcNow.AddDays(-30);
        var notAfter = DateTimeOffset.UtcNow.AddDays(70);

        using var cert = req.Create(new X500DistinguishedName("CN=test"), X509SignatureGenerator.CreateForRSA(rsa, RSASignaturePadding.Pkcs1), notBefore, notAfter, new byte[] { 1 });

        // Currently 70 days left out of 100 days total = 70%
        var pct = RenewService.RemainingLifePercent(cert, DateTimeOffset.UtcNow);

        Assert.True(pct >= 69.0 && pct <= 71.0, $"Expected ~70%, got {pct}%");
    }

    [Fact]
    public void RemainingLifePercent_ExpiredCert_ReturnsZero()
    {
        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest("CN=test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);

        var notBefore = DateTimeOffset.UtcNow.AddDays(-100);
        var notAfter = DateTimeOffset.UtcNow.AddDays(-10);

        using var cert = req.Create(new X500DistinguishedName("CN=test"), X509SignatureGenerator.CreateForRSA(rsa, RSASignaturePadding.Pkcs1), notBefore, notAfter, new byte[] { 1 });

        var pct = RenewService.RemainingLifePercent(cert, DateTimeOffset.UtcNow);
        Assert.Equal(0, pct);
    }
}
