using OrgInventoryAgent;
using Xunit;

namespace OrgInventoryAgent.Tests;

public class AgentIdentityTests
{
    [Fact]
    public void IsEnrolled_ReturnsFalseWhenFieldsMissing()
    {
        var config = new AgentConfig();
        Assert.False(AgentIdentity.IsEnrolled(config));

        config.Enrolled = true;
        Assert.False(AgentIdentity.IsEnrolled(config)); // missing MachineId & Thumbprint

        config.MachineId = "machine-123";
        Assert.False(AgentIdentity.IsEnrolled(config)); // missing Thumbprint

        config.ClientCertThumbprint = "ABCDEF123456";
        Assert.True(AgentIdentity.IsEnrolled(config));
    }
}
