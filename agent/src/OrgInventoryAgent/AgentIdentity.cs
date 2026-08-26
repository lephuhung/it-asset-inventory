namespace OrgInventoryAgent;

/// <summary>
/// Quyết định trạng thái enrollment + idempotency.
/// - Đã enroll: config.Enrolled + machine_id + client cert (có private key) trong store.
/// - Idempotent install: cài lại trên máy đã enroll → cert + machine_id còn đó → bỏ qua
///   enroll, chỉ repair/update (server fuzzy-match nếu phải enroll lại).
/// </summary>
public static class AgentIdentity
{
    public static bool IsEnrolled(AgentConfig config)
    {
        if (config is null) return false;
        if (!config.Enrolled || string.IsNullOrWhiteSpace(config.MachineId)) return false;
        if (string.IsNullOrWhiteSpace(config.ClientCertThumbprint)) return false;
        return true;
    }

    /// <summary>Cert có thực sự tồn tại (kèm private key) không — kiểm tra đầy đủ qua KeyStore.</summary>
    public static bool HasUsableCertificate(AgentConfig config, Crypto.KeyStore keyStore)
    {
        if (!IsEnrolled(config)) return false;
        using var cert = keyStore.FindClientCertificate(config);
        return cert is not null;
    }
}
