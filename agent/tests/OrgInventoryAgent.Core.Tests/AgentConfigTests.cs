using System.IO;
using System.Text.Json;
using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>
/// Round-trip test cho <see cref="AgentConfig"/> JSON serialization.
/// </summary>
public class AgentConfigTests : IDisposable
{
    private readonly string _tempDir;

    public AgentConfigTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "AgentConfigCoreTest_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
        AppPaths.Initialize(_tempDir);
    }

    public void Dispose()
    {
        try { if (Directory.Exists(_tempDir)) Directory.Delete(_tempDir, true); } catch { }
    }

    [Fact]
    public void RoundTrip_PreservesScalarFields()
    {
        var cfg = new AgentConfig
        {
            Endpoints = new[] { "https://a.example.gov.vn", "https://b.example.gov.vn" },
            HeartbeatIntervalSeconds = 45,
            HeartbeatJitterSeconds = 12,
            InventoryIntervalHours = 24,
            RenewBeforePercent = 70,
            Enrolled = true,
            MachineId = "test-uuid-001",
            ClientCertThumbprint = "ABC123",
            CertStoreLocation = "LocalMachine",
            RenewAfter = "2027-01-01T00:00:00Z",
            ConfigVersion = 2,
        };

        var json = JsonSerializer.Serialize(cfg, AgentConfigJsonContext.DefaultOptions);
        var back = JsonSerializer.Deserialize<AgentConfig>(json, AgentConfigJsonContext.DefaultOptions);

        Assert.NotNull(back);
        Assert.Equal(cfg.Endpoints, back!.Endpoints);
        Assert.Equal(cfg.HeartbeatIntervalSeconds, back.HeartbeatIntervalSeconds);
        Assert.Equal(cfg.HeartbeatJitterSeconds, back.HeartbeatJitterSeconds);
        Assert.Equal(cfg.InventoryIntervalHours, back.InventoryIntervalHours);
        Assert.Equal(cfg.RenewBeforePercent, back.RenewBeforePercent);
        Assert.Equal(cfg.Enrolled, back.Enrolled);
        Assert.Equal(cfg.MachineId, back.MachineId);
        Assert.Equal(cfg.ClientCertThumbprint, back.ClientCertThumbprint);
        Assert.Equal(cfg.CertStoreLocation, back.CertStoreLocation);
        Assert.Equal(cfg.RenewAfter, back.RenewAfter);
        Assert.Equal(cfg.ConfigVersion, back.ConfigVersion);
    }

    [Fact]
    public void Normalize_FiltersEmptyAndDuplicates()
    {
        var cfg = new AgentConfig { Endpoints = new[] { "https://a.example.gov.vn/", "", "  ", "https://a.example.gov.vn", "https://b.example.gov.vn" } };
        cfg.Normalize();
        // Sau Normalize: trim trailing slash, drop empty/whitespace, drop duplicates (case-insensitive).
        Assert.Equal(new[] { "https://a.example.gov.vn", "https://b.example.gov.vn" }, cfg.Endpoints);
    }
}
