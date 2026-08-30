using System.Text.Json;
using OrgInventoryAgent;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Services;
using Xunit;

[assembly: CollectionBehavior(DisableTestParallelization = true)]

namespace OrgInventoryAgent.Tests;

/// <summary>
/// Test cho Phase 4: heartbeat phát hiện hash cấu hình thay đổi và trigger ConfigSync.
///
/// Quy ước (xem HeartbeatService.ShouldResyncConfig):
/// - serverHash null/rỗng → false (server cũ không hỗ trợ → đợi ConfigSync 6h)
/// - localHash null (lần đầu) → true (luôn sync để lấy hash)
/// - khác nhau → true
/// - giống nhau → false
/// </summary>
public class HeartbeatConfigSyncTests
{
    [Theory]
    [InlineData(null, "abc123", false)]
    [InlineData("", "abc123", false)]
    [InlineData("   ", "abc123", false)]
    [InlineData("abc123", null, true)]
    [InlineData("abc123", "", true)]
    [InlineData("abc123", "xyz789", true)]
    [InlineData("abc123", "abc123", false)]
    [InlineData("ABC123", "abc123", false)]
    [InlineData("xyz789", "abc123", true)]
    public void ShouldResyncConfig_ReturnsExpected(string? serverHash, string? localHash, bool expected)
    {
        var actual = HeartbeatService.ShouldResyncConfig(serverHash, localHash);
        Assert.Equal(expected, actual);
    }
}

/// <summary>
/// Test cho AgentState: thêm trường LastAgentConfigHash (Phase 4).
/// </summary>
public class AgentStateConfigHashTests : IDisposable
{
    private readonly string _dataDir;

    public AgentStateConfigHashTests()
    {
        _dataDir = Path.Combine(Path.GetTempPath(), "OrgInvTest_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dataDir);
        AppPaths.Initialize(_dataDir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_dataDir, true); } catch { }
    }

    [Fact]
    public void LastAgentConfigHash_DefaultsToNull()
    {
        var state = new AgentState();
        Assert.Null(state.LastAgentConfigHash);
    }

    [Fact]
    public void LastAgentConfigHash_PersistsAcrossLoad()
    {
        var hash = "f1e2d3c4b5a69788776655443322110099aabbccddeeff001122334455667788";
        var state = new AgentState { LastAgentConfigHash = hash };
        state.Save();

        var loaded = AgentState.Load();
        Assert.Equal(hash, loaded.LastAgentConfigHash);
    }

    [Fact]
    public void LastAgentConfigHash_DoesNotAffectOtherStateFields()
    {
        var state = new AgentState
        {
            LastInventoryAt = "2026-01-15T00:00:00Z",
            LastInventoryConfigHash = "inv_hash_abc",
            LastAgentConfigHash = "cfg_hash_xyz",
        };
        state.Save();

        var loaded = AgentState.Load();
        Assert.Equal("2026-01-15T00:00:00Z", loaded.LastInventoryAt);
        Assert.Equal("inv_hash_abc", loaded.LastInventoryConfigHash);
        Assert.Equal("cfg_hash_xyz", loaded.LastAgentConfigHash);
    }

    [Fact]
    public void AgentState_Load_ReturnsDefault_WhenFileMissing()
    {
        var loaded = AgentState.Load();
        Assert.Null(loaded.LastInventoryAt);
        Assert.Null(loaded.LastInventoryConfigHash);
        Assert.Null(loaded.LastAgentConfigHash);
    }
}

/// <summary>
/// Test tính nhất quán của CanonicalJson.Hash với Unicode tiếng Việt và ký tự đặc biệt.
/// </summary>
public class CanonicalJsonHashConsistencyTests
{
    [Fact]
    public void CanonicalJson_Hash_HandlesUnicodeAndSymbols_MatchesPythonStandard()
    {
        var payload = new Dictionary<string, object?>
        {
            ["name"] = "Nguyễn Văn A",
            ["tool"] = "C++"
        };
        var hash = CanonicalJson.Hash(payload);
        // Khớp chính xác với Python:
        // json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        // -> {"name":"Nguyễn Văn A","tool":"C++"} -> SHA-256
        Assert.Equal("d9ebfe161361a4a8c49d31ee0642ed7f5baca46cd622560a671465eeeee15e6e", hash);
    }
}