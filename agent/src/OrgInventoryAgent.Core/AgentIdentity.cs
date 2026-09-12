using OrgInventoryAgent.Core.Crypto;

namespace OrgInventoryAgent.Core;

/// <summary>Trạng thái enrollment để phân biệt các case xử lý khác nhau.</summary>
public enum EnrollStatus
{
    /// <summary>Chưa enroll — chưa có machine_id hoặc cert. Cần enroll mới.</summary>
    NotEnrolled,
    /// <summary>Đã enroll theo config nhưng cert không tìm thấy trong store.
    /// Khả năng OS được cài lại hoặc store bị xóa — cần re-enroll.
    /// (legacy — dùng <see cref="ReenrollRequired"/> cho state machine mới).</summary>
    CertMissing,
    /// <summary>Đã enroll đầy đủ, cert có private key, sẵn sàng gửi mTLS request.</summary>
    Enrolled,
    /// <summary>
    /// AG-P1-02: đã enroll trước đó nhưng cert đã biến mất khỏi store (vd OS cài lại
    /// hoặc admin xóa cert). Agent KHÔNG retry enroll khi chưa có fresh bootstrap token —
    /// chờ admin issue token mới. Phân biệt với <see cref="NotEnrolled"/> để Coordinator
    /// không spam và không "fresh enroll" máy cũ (giữ machine_id gốc).
    /// </summary>
    ReenrollRequired,
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
    ///
    /// AG-P1-02: Khi <c>config.ReenrollRequired = true</c> mà cert vẫn còn, vẫn trả
    /// <see cref="ReenrollRequired"/> để Coordinator biết cần fresh token. Khi cert
    /// biến mất mà config còn đánh dấu enrolled → trả <see cref="ReenrollRequired"/>
    /// thay vì <see cref="CertMissing"/> (đã có machine_id, không cần fresh enroll,
    /// chỉ cần fresh token).
    /// </summary>
    public static EnrollStatus Validate(AgentConfig config, IKeyStore keyStore)
    {
        // AG-P1-02: Nếu config đã được đánh dấu reenroll_required trước (sau khi cert
        // biến mất lần trước) → giữ trạng thái ReenrollRequired cho đến khi:
        //   (a) admin cấp fresh token + Coordinator enroll thành công → ReenrollRequired=false.
        //   (b) cert xuất hiện lại + machine_id present → cũng báo ReenrollRequired để
        //       Coordinator biết rằng state machine này vẫn cần fresh bootstrap (vd admin
        //       cài cert mới thủ công nhưng chưa enroll).
        if (config.ReenrollRequired) return EnrollStatus.ReenrollRequired;

        // Chưa enroll hoặc thông tin chưa đầy đủ.
        if (!IsEnrolled(config)) return EnrollStatus.NotEnrolled;

        // Đã enroll theo config nhưng cert thực sự không có → chuyển sang ReenrollRequired
        // (KHÔNG dùng CertMissing deprecated nữa). Distinguishing enables Coordinator
        // distinguish "first-time enroll" vs "reenroll with fresh token".
        using var cert = keyStore.FindClientCertificate(config);
        return cert is not null ? EnrollStatus.Enrolled : EnrollStatus.ReenrollRequired;
    }

    /// <summary>
    /// AG-P1-02: Coordinator KHÔNG retry enroll khi chưa có fresh token. Helper này xác
    /// định xem có nên thử <c>EnrollCoreAsync</c> hay KHÔNG.
    ///
    /// <c>true</c>: reenroll đang chờ fresh token từ admin. Coordinator return false
    /// ngay, KHÔNG làm gì thêm (không tăng rate-limit, không log CRITICAL liên tục).
    /// </summary>
    public static bool IsReenrollPending(AgentConfig config)
    {
        if (config is null) return false;
        // Đã enrolled hoàn chỉnh → không pending.
        if (IsEnrolled(config)) return false;
        // ReenrollRequired + đã có fresh token → admin vừa issue → chờ Coordinator
        // thực hiện enroll; lúc đó KHÔNG coi là pending.
        if (config.ReenrollRequired && !string.IsNullOrWhiteSpace(config.Token))
            return false;
        return config.ReenrollRequired;
    }
}

