using System.IO;
using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// Test cho pattern <c>AppPaths.Initialize(string?)</c> — contract hiện tại đã được
/// 5+ callers sử dụng (chính sửa của Task 2 ruling F-2, không dùng brief
/// <c>GetDataDirForOs(string, string)</c> API).
/// </summary>
public class AppPathsTests : IDisposable
{
    private readonly string _tempDir;

    public AppPathsTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "AppPathsCoreTest_" + Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        // Reset để không ảnh hưởng test khác.
        try { AppPaths.Initialize(null); } catch { /* OK nếu user profile không có sẵn */ }
        try { if (Directory.Exists(_tempDir)) Directory.Delete(_tempDir, true); } catch { }
    }

    [Fact]
    public void Initialize_WithOverrideDir_SetsDataDirExactly()
    {
        Directory.CreateDirectory(_tempDir);
        AppPaths.Initialize(_tempDir);

        Assert.Equal(_tempDir, AppPaths.DataDir);
        Assert.Equal(Path.Combine(_tempDir, "config.json"), AppPaths.ConfigFile);
        Assert.Equal(Path.Combine(_tempDir, "cache.db"), AppPaths.CacheDbFile);
        Assert.Equal(Path.Combine(_tempDir, "state.json"), AppPaths.StateFile);
        Assert.Equal(Path.Combine(_tempDir, "logs"), AppPaths.LogsDir);
    }

    [Fact]
    public void Initialize_CreatesLogsDirectory()
    {
        Directory.CreateDirectory(_tempDir);
        AppPaths.Initialize(_tempDir);

        Assert.True(Directory.Exists(AppPaths.LogsDir));
    }

    [Fact]
    public void CertFile_AndKeyFile_AreInsideDataDir()
    {
        Directory.CreateDirectory(_tempDir);
        AppPaths.Initialize(_tempDir);

        Assert.Equal(Path.Combine(_tempDir, "client-cert.pem"), AppPaths.CertFile);
        Assert.Equal(Path.Combine(_tempDir, "client-key.pem"), AppPaths.KeyFile);
    }

    [Fact]
    public void Initialize_WithEmptyOverride_UsesEnvOrDefault()
    {
        // Không truyền override → AppPaths dùng env hoặc mặc định.
        // Đặt env trước.
        Environment.SetEnvironmentVariable("ORGINVENTORY_DATA_DIR", _tempDir);
        try
        {
            Directory.CreateDirectory(_tempDir);
            AppPaths.Initialize();
            Assert.Equal(_tempDir, AppPaths.DataDir);
        }
        finally
        {
            Environment.SetEnvironmentVariable("ORGINVENTORY_DATA_DIR", null);
        }
    }
}
