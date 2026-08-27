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
}
