using OrgInventoryAgent.Core;
using OrgInventoryAgent.Linux;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class AgentConfigTests
{
    [Fact]
    public void Normalize_ClampsIntervalsAndCleansEndpoints()
    {
        var config = new AgentConfig
        {
            Endpoints = new[] { "  https://server1.local/  ", "", "   ", "http://server2.local  " },
            HeartbeatIntervalSeconds = 1, // too small, min is 5
            HeartbeatJitterSeconds = 100, // too large, max is interval - 1
            InventoryIntervalHours = -5, // too small, min is 1
            RenewBeforePercent = 150, // too large, max is 99
        };

        config.Normalize();

        Assert.Equal(2, config.Endpoints.Length);
        Assert.Equal("https://server1.local", config.Endpoints[0]);
        Assert.Equal("http://server2.local", config.Endpoints[1]);
        Assert.Equal(5, config.HeartbeatIntervalSeconds);
        Assert.Equal(4, config.HeartbeatJitterSeconds);
        Assert.Equal(1, config.InventoryIntervalHours);
        Assert.Equal(99, config.RenewBeforePercent);
    }

    [Fact]
    public void Normalize_LeavesEmptyEndpointsUnchanged_WithoutHardcodedFallback()
    {
        var config = new AgentConfig
        {
            Endpoints = Array.Empty<string>(),
        };

        config.Normalize();

        Assert.Empty(config.Endpoints);
        Assert.Null(config.PrimaryEndpoint);
    }

    [Fact]
    public void SetPrimaryEndpoint_ReordersEndpoints()
    {
        var config = new AgentConfig
        {
            Endpoints = new[] { "https://old-primary.local", "https://backup.local" },
        };

        config.SetPrimaryEndpoint("https://new-primary.local/");

        Assert.Equal("https://new-primary.local", config.PrimaryEndpoint);
        Assert.Equal(3, config.Endpoints.Length);
        Assert.Equal("https://old-primary.local", config.Endpoints[1]);
        Assert.Equal("https://backup.local", config.Endpoints[2]);
    }

    [Fact]
    public void ApplyServerSettings_DetectsChangesCorrectly()
    {
        var config = new AgentConfig
        {
            Endpoints = new[] { "https://server1.local" },
            HeartbeatIntervalSeconds = 30,
            HeartbeatJitterSeconds = 8,
            InventoryIntervalHours = 24,
            RenewBeforePercent = 70,
        };

        bool changedNoop = config.ApplyServerSettings("https://server1.local", 30, 8, 24, 70);
        Assert.False(changedNoop);

        bool changed = config.ApplyServerSettings("https://server2.local", 60, 15, 12, 80);
        Assert.True(changed);
        Assert.Equal("https://server2.local", config.PrimaryEndpoint);
        Assert.Equal(60, config.HeartbeatIntervalSeconds);
        Assert.Equal(15, config.HeartbeatJitterSeconds);
        Assert.Equal(12, config.InventoryIntervalHours);
        Assert.Equal(80, config.RenewBeforePercent);
    }

    [Fact]
    public void ComputeConfigHash_IsDeterministicAndSorted()
    {
        var config1 = new AgentConfig
        {
            Endpoints = new[] { "https://a.local", "https://b.local" },
            HeartbeatIntervalSeconds = 30,
            HeartbeatJitterSeconds = 8,
        };

        var config2 = new AgentConfig
        {
            Endpoints = new[] { "https://a.local", "https://b.local" },
            HeartbeatIntervalSeconds = 30,
            HeartbeatJitterSeconds = 8,
        };

        var hash1 = config1.ComputeConfigHash();
        var hash2 = config2.ComputeConfigHash();

        Assert.NotNull(hash1);
        Assert.Equal(64, hash1.Length);
        Assert.Equal(hash1, hash2);

        config2.HeartbeatIntervalSeconds = 45;
        var hash3 = config2.ComputeConfigHash();
        Assert.NotEqual(hash1, hash3);
    }
}