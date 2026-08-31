using OrgInventoryAgent.Core.Collectors.Schema;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class InventoryPayloadBuilderTests
{
    [Fact]
    public void Build_IncludesFullV4Envelope()
    {
        var provider = new LinuxInventoryProvider(
            Microsoft.Extensions.Logging.Abstractions.NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "testuser");

        var json = System.Text.Json.JsonSerializer.Serialize(payload);
        var doc = System.Text.Json.JsonDocument.Parse(json);

        Assert.Equal(4, doc.RootElement.GetProperty("inventory_schema_version").GetInt32());
        Assert.Equal("linux", doc.RootElement.GetProperty("agent").GetProperty("platform").GetString());
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("agent").GetProperty("architecture").GetString()));
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("agent").GetProperty("package_type").GetString()));
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("os").GetProperty("kernel_version").GetString()));
        Assert.Equal("linux", doc.RootElement.GetProperty("os").GetProperty("platform").GetString());
        Assert.True(doc.RootElement.TryGetProperty("security", out _));
        Assert.True(doc.RootElement.TryGetProperty("cpu", out _));
    }

    [Fact]
    public void Build_PackageType_MatchesDistro()
    {
        var provider = new LinuxInventoryProvider(
            Microsoft.Extensions.Logging.Abstractions.NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "u");
        var json = System.Text.Json.JsonSerializer.Serialize(payload);
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var pkg = doc.RootElement.GetProperty("agent").GetProperty("package_type").GetString();
        Assert.True(pkg == "deb" || pkg == "rpm", $"package_type={pkg}");
    }
}