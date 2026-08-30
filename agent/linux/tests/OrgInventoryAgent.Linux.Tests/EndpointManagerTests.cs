using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Linux;
using OrgInventoryAgent.Linux.Net;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class EndpointManagerTests
{
    [Fact]
    public void Failover_SwitchesToBackupAfter5ConsecutiveFailures()
    {
        var config = new AgentConfig
        {
            Endpoints = new[] { "https://primary.local", "https://backup1.local", "https://backup2.local" },
        };
        var manager = new EndpointManager(config, NullLogger<EndpointManager>.Instance);

        Assert.Equal("https://primary.local", manager.Current);

        // 4 failures -> still primary
        for (int i = 0; i < 4; i++)
        {
            manager.OnFailure();
            Assert.Equal("https://primary.local", manager.Current);
        }

        // 5th failure -> switches to backup1
        manager.OnFailure();
        Assert.Equal("https://backup1.local", manager.Current);

        // Success resets failure count
        manager.OnSuccess();
        Assert.Equal("https://backup1.local", manager.Current);
    }

    [Fact]
    public void BuildUrl_AppendsPathToBaseUrl()
    {
        var config = new AgentConfig
        {
            Endpoints = new[] { "https://server.local/api-base" },
        };
        var manager = new EndpointManager(config, NullLogger<EndpointManager>.Instance);

        var url = manager.BuildUrl("/api/heartbeat");
        Assert.Equal("https://server.local/api-base/api/heartbeat", url);
    }
}