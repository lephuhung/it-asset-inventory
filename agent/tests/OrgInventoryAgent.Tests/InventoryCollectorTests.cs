using OrgInventoryAgent.Core;
using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Collectors;
using Xunit;
using Xunit.Abstractions;

namespace OrgInventoryAgent.Tests;

public class InventoryCollectorTests
{
    private readonly ITestOutputHelper _output;

    public InventoryCollectorTests(ITestOutputHelper output)
    {
        _output = output;
    }

    [Fact]
    public void Collect_ReturnsSecurityPosture()
    {
        var collector = new InventoryCollector(NullLogger<InventoryCollector>.Instance);
        var snapshot = collector.Collect();

        Assert.NotNull(snapshot);
        Assert.NotNull(snapshot.Security);

        var secJson = JsonSerializer.Serialize(snapshot.Security, new JsonSerializerOptions { WriteIndented = true });
        _output.WriteLine("SECURITY JSON:\n" + secJson);

        Assert.NotNull(snapshot.Security.FirewallEnabled);
        Assert.NotNull(snapshot.Security.UacEnabled);
    }

    [Fact]
    public void Collect_ReturnsV4EnvelopeAndMetadata()
    {
        var collector = new InventoryCollector(NullLogger<InventoryCollector>.Instance);
        var snapshot = collector.Collect();

        Assert.NotNull(snapshot);
        Assert.Equal(4, snapshot.InventorySchemaVersion);

        // Agent metadata
        Assert.NotNull(snapshot.Agent);
        Assert.Equal("windows", snapshot.Agent.Platform);
        Assert.Equal("msi", snapshot.Agent.PackageType);
        Assert.False(string.IsNullOrWhiteSpace(snapshot.Agent.Version));
        Assert.False(string.IsNullOrWhiteSpace(snapshot.Agent.Architecture));

        // OS metadata
        Assert.NotNull(snapshot.Os);
        Assert.Equal("windows", snapshot.Os.Platform);
        Assert.Equal("windows", snapshot.Os.Distribution);
        Assert.False(string.IsNullOrWhiteSpace(snapshot.Os.Architecture));

        // Security v4 objects
        Assert.NotNull(snapshot.Security);
        Assert.NotNull(snapshot.Security.Update);
        Assert.NotNull(snapshot.Security.DiskEncryption);
        Assert.NotNull(snapshot.Security.RemoteAccess);
        Assert.NotNull(snapshot.Security.PrivilegeControl);

        if (OperatingSystem.IsWindows())
        {
            Assert.Equal("bitlocker", snapshot.Security.DiskEncryption.Technology);
        }

        var fullJson = JsonSerializer.Serialize(snapshot, new JsonSerializerOptions { WriteIndented = true });
        _output.WriteLine("FULL V4 SNAPSHOT JSON:\n" + fullJson);
    }
}
