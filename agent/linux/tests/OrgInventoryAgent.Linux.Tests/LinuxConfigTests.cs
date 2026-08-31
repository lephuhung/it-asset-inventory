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
}