using OrgInventoryAgent.Core.Crypto;

namespace OrgInventoryAgent.Core;

/// <summary>Trạng thái enrollment để phân biệt các case xử lý khác nhau.</summary>
public enum EnrollStatus
{
    /// <summary>Chưa enroll — chưa có machine_id hoặc cert. Cần enroll mới.</summary>
    NotEnrolled,
    /// <summary>Đã enroll theo config nhưng cert không tìm thấy trong store.
    /// Khả năng OS được cài lại hoặc store bị xóa — cần re-enroll.</summary>
    CertMissing,
    /// <summary>Đã enroll đầy đủ, cert có private key, sẵn sàng gửi mTLS request.</summary>
    Enrolled,
}

/// <summary>
/// Quyết định trạng thái enrollment + idempotency.
/// - Đã enroll: config.Enrolled + machine_id + client cert (có private key) trong store.
/// - Idempotent install: cài lại trên máy đã enroll → cert + machine_id còn đó → bỏ qua
///   enroll, chỉ repair/update (server fuzzy-match nếu phải enroll lại).
/// </summary>
public static class AgentIdentity
{
    /// <summary>
    /// Kiểm tra nhanh từ config — KHÔNG xác nhận cert thực tế trong store.
    /// Dùng cho kiểm tra tốc độ cao (heartbeat loop, etc.).
    /// </summary>
    public static bool IsEnrolled(AgentConfig config)
    {
        if (config is null) return false;
        if (!config.Enrolled || string.IsNullOrWhiteSpace(config.MachineId)) return false;
        if (string.IsNullOrWhiteSpace(config.ClientCertThumbprint)) return false;
        return true;
    }

    /// <summary>
    /// Kiểm tra đầy đủ bao gồm xác nhận cert còn tồn tại trong store (có private key).
    /// Dùng khi cần chắc chắn có thể gửi mTLS request.
    /// </summary>
    public static bool HasUsableCertificate(AgentConfig config, IKeyStore keyStore)
    {
        if (!IsEnrolled(config)) return false;
        using var cert = keyStore.FindClientCertificate(config);
        return cert is not null;
    }

    /// <summary>
    /// Validate đầy đủ trạng thái enrollment. Phân biệt "chưa enroll" vs "cert mất".
    /// Gọi định kỳ (ví dụ mỗi 10 chu kỳ heartbeat) để phát hiện sớm.
    /// </summary>
    public static EnrollStatus Validate(AgentConfig config, IKeyStore keyStore)
    {
        if (!IsEnrolled(config)) return EnrollStatus.NotEnrolled;
        using var cert = keyStore.FindClientCertificate(config);
        return cert is not null ? EnrollStatus.Enrolled : EnrollStatus.CertMissing;
    }
}

