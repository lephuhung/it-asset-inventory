using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// Contract test cho <see cref="IKeyStore"/>. Tất cả concrete impl (Windows store / Linux PEM)
/// phải có cùng behavior cho:
/// - HasPrivateKey / HasClientCertificate trả false khi chưa cài.
/// - GetCertificatePem trả null khi chưa có cert.
/// - InstallCertificate xong thì HasPrivateKey / GetCertificatePem phải trả non-null.
/// - DeleteCertificate xong thì phải trở về trạng thái "chưa có".
///
/// Windows-only tests (WMI cert store, registry, PFX) nằm trong OrgInventoryAgent.Tests.
/// </summary>
public abstract class IKeyStoreContract
{
    protected abstract IKeyStore CreateKeyStore(string dataDir);
    protected abstract string KeyDir { get; }

    [Fact]
    public void BeforeInstall_HasPrivateKey_IsFalse()
    {
        var dir = MakeDir();
        var ks = CreateKeyStore(dir);
        Assert.False(ks.HasPrivateKey("test-machine"));
    }

    [Fact]
    public void BeforeInstall_GetCertificatePem_IsNull()
    {
        var dir = MakeDir();
        var ks = CreateKeyStore(dir);
        Assert.Null(ks.GetCertificatePem("test-machine"));
    }

    [Fact]
    public void BeforeInstall_HasClientCertificate_WithNullConfig_IsFalse()
    {
        var dir = MakeDir();
        var ks = CreateKeyStore(dir);
        Assert.False(ks.HasClientCertificate(new AgentConfig()));
    }

    [Fact]
    public void BeforeInstall_FindClientCertificate_WithNullConfig_IsNull()
    {
        var dir = MakeDir();
        var ks = CreateKeyStore(dir);
        Assert.Null(ks.FindClientCertificate(new AgentConfig()));
    }

    [Fact]
    public void DeleteCertificate_WhenAbsent_DoesNotThrow()
    {
        var dir = MakeDir();
        var ks = CreateKeyStore(dir);
        // Idempotent — không throw khi cert không tồn tại.
        var ex = Record.Exception(() => ks.DeleteCertificate("never-existed"));
        Assert.Null(ex);
    }

    protected string MakeDir()
    {
        var d = System.IO.Path.Combine(KeyDir, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(d);
        return d;
    }
}
