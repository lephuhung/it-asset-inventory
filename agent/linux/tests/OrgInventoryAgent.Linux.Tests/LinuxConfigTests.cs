using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxConfigTests
{
    [Fact]
    public void Load_ReadsLegacyEnrollToken_IntoToken()
    {
        var dir = Path.Combine(Path.GetTempPath(), "LinuxCfg_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        AppPaths.Initialize(dir);
        var cfgPath = Path.Combine(dir, "config.json");
        File.WriteAllText(cfgPath, """{"endpoints":["https://agent.local"],"enroll_token":"t_abc","data_dir":"/var/lib/orginventory"}""");

        var cfg = LinuxConfig.Load(cfgPath);

        Assert.Equal("t_abc", cfg.Token);
        Assert.Equal("https://agent.local", cfg.PrimaryEndpoint);
        Directory.Delete(dir, recursive: true);
    }

    [Fact]
    public void Load_MergesIdentityFromStateFile_WhenBootstrapLacksIt()
    {
        // Bootstrap (--config) chỉ có endpoints + enroll_token — không có identity.
        // State (AppPaths.ConfigFile) có identity agent đã lưu sau enroll.
        // Load phải MERGE: identity từ state, endpoints/token từ bootstrap.
        var dir = Path.Combine(Path.GetTempPath(), "LinuxCfgMerge_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        AppPaths.Initialize(dir);

        var bootstrapPath = Path.Combine(dir, "bootstrap.json");
        File.WriteAllText(bootstrapPath, """{"endpoints":["https://agent.local"],"enroll_token":"t_abc"}""");

        // State file agent tự lưu (AppPaths.ConfigFile = {dir}/config.json)
        File.WriteAllText(AppPaths.ConfigFile, """
        {
          "endpoints": ["https://agent.local"],
          "heartbeatIntervalSeconds": 60,
          "heartbeatJitterSeconds": 8,
          "inventoryIntervalHours": 1,
          "renewBeforePercent": 70,
          "enrolled": true,
          "machineId": "30b056f4-bb51-4a12-90cf-3e0d7e245bd6",
          "clientCertThumbprint": "1CA9F067FF6BC8DC42E179D19667B25A8EEBA183",
          "certStoreLocation": "File",
          "renewAfter": "2027-05-14T01:22:25.459527Z"
        }
        """);

        var cfg = LinuxConfig.Load(bootstrapPath);

        Assert.True(cfg.Enrolled);
        Assert.Equal("30b056f4-bb51-4a12-90cf-3e0d7e245bd6", cfg.MachineId);
        Assert.Equal("1CA9F067FF6BC8DC42E179D19667B25A8EEBA183", cfg.ClientCertThumbprint);
        Assert.Equal("File", cfg.CertStoreLocation);
        Assert.Equal(60, cfg.HeartbeatIntervalSeconds);
        Assert.Equal(1, cfg.InventoryIntervalHours);
        Assert.Equal("t_abc", cfg.Token); // từ bootstrap
        Assert.Equal("https://agent.local", cfg.PrimaryEndpoint); // từ bootstrap
        Directory.Delete(dir, recursive: true);
    }
}