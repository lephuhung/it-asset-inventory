using System.Security.Cryptography.X509Certificates;

namespace OrgInventoryAgent.Core.Crypto;

/// <summary>
/// Abstraction over platform certificate store — Windows impl dùng Windows Certificate Store,
/// Linux impl sẽ dùng PEM file trong data dir (sẽ triển khai ở task sau).
/// </summary>
public interface IKeyStore
{
    bool HasClientCertificate(OrgInventoryAgent.Core.AgentConfig config);
    X509Certificate2? FindClientCertificate(OrgInventoryAgent.Core.AgentConfig config);
}
