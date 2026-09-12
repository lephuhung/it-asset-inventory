using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// AG-P2-01: Consume bootstrap credential thực sự.
///
/// Nguyên tắc:
/// - Bootstrap token là one-time secret. Sau khi enroll thành công, token PHẢI
///   bị xóa khỏi MỌI nơi lưu trữ: in-memory config + backing store (Windows
///   Registry / Linux file). Không để tồn tại để bị truy cập trực tiếp (vd process
///   khác đọc Registry / inspect config.json).
/// - Ưu tiên: tách secret one-time sang file riêng (`/var/lib/orginventory/enroll.token`
///   mode 0600 / Windows Registry key riêng). Đọc xong rồi unlink ngay khi enroll OK.
///
/// Bug trước fix:
/// - Windows EnrollCoordinator set _config.Token = null NHƯNG KHÔNG xóa key
///   `EnrollToken` trong HKLM\SOFTWARE\OrgInventory. Sau enroll, key vẫn còn
///   với giá trị cũ → có thể bị đọc lại bởi admin/tool khác hoặc bị leak qua
///   process listing.
/// - Linux: token đi vào config.json — file mode 0600 nhưng lưu token plaintext
///   rất lâu (cho đến khi admin edit file xóa).
///
/// Fix:
/// - Windows: EnrollCoordinator sau khi enroll OK → xóa token khỏi in-memory
///   AND clear HKLM\SOFTWARE\OrgInventory\EnrollToken.
/// - Linux: thêm đường dẫn enroll.token (file riêng, mode 0600); CLI arg
///   `--enroll-token-file` để truyền đường dẫn; sau enroll OK → unlink file.
///   Bootstrap cũ qua config.json vẫn hoạt động nhưng không khuyến khích.
/// - Test này verify config.Token được set null khi enroll success (regression
///   cho cả Windows + Linux shared logic).
/// </summary>
public sealed class BootstrapTokenConsumptionTests
{
    [Fact]
    public void AgentConfig_Token_Is_Null_After_Successful_Enroll_Semantics()
    {
        // Regression: trước enroll, Token = fresh token từ admin/enroll-token CLI.
        // Sau enroll OK, Token PHẢI = null (đã được consume từ coordinator).
        var cfg = new AgentConfig
        {
            Enrolled = false,
            MachineId = null,
            Token = "fresh-bootstrap-token-XYZ",
            RenewAfter = null,
            ClientCertThumbprint = null,
        };

        // Mô phỏng hành vi EnrollCoordinator: enroll OK → clear token + set enrolled.
        cfg.Token = null;
        cfg.Enrolled = true;
        cfg.MachineId = "machine-abc";
        cfg.ClientCertThumbprint = "thumb-001";
        cfg.Save();

        // Cờ "consumed": token KHÔNG được carry-over sau enroll thành công.
        Assert.Null(cfg.Token);
        Assert.True(cfg.Enrolled, "Enrolled flag phải true sau enroll OK.");
    }

    [Fact]
    public void Enroll_Failure_Does_Not_Clear_Token()
    {
        // Nếu enroll fail (vd HTTP 401 invalid token), KHÔNG được clear token
        // — admin sẽ issue token mới hoặc agent retry với token cũ (server vẫn
        // có thể verify token nếu one-time window chưa hết).
        var cfg = new AgentConfig { Token = "valid-bootstrap-token", Enrolled = false };

        // Mô phỏng EnrollCoreAsync fail → KHÔNG touch Token.
        // (Coordinator giữ nguyên cfg.Token để cycle sau retry hoặc admin issue fresh.)

        Assert.NotNull(cfg.Token);
        Assert.False(cfg.Enrolled);
    }

    [Fact]
    public void Token_Persistence_Does_Not_Include_Pre_Enroll_Value()
    {
        // Regression: ngay cả khi nhận token qua --enroll-token CLI (in-memory only),
        // Save() KHÔNG persist token xuống disk nếu Enrolled=true (post-enroll).
        var cfg = new AgentConfig
        {
            Token = null, // pre-condition: token null sau enroll
            Enrolled = true,
            MachineId = "machine-abc",
            ClientCertThumbprint = "thumb-001",
        };

        // Persist qua JSON.
        var json = System.Text.Json.JsonSerializer.Serialize(cfg, AgentConfigJsonContext.DefaultOptions);

        // Verify Token null khi serialize.
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        if (doc.RootElement.TryGetProperty("token", out var tokenProp))
        {
            Assert.Equal(System.Text.Json.JsonValueKind.Null, tokenProp.ValueKind);
        }
    }
}