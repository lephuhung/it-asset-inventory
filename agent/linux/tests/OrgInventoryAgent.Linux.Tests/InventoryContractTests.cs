using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Core.Collectors;
using OrgInventoryAgent.Core.Collectors.Schema;
using OrgInventoryAgent.Linux;
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

/// <summary>
/// AG-P1-04: Inventory contract drift giữa Windows và Linux.
///
/// Bug trước fix:
/// - Windows ghi `config_hash` trong payload, tính từ canonical snapshot
///   (CanonicalJson.Hash(snapshot, excludeProperty: "config_hash")).
/// - Linux KHÔNG ghi `config_hash` → server không thể dedupe / phát hiện thay đổi
///   payload dựa trên inventory content (chỉ dựa vào heartbeat interval).
/// - Cả 2 dùng `_config.ComputeConfigHash()` cho LOCAL change detection, nhưng hash
///   này là của agent settings (interval/jitter/...), KHÔNG phải của inventory
///   payload → KHÔNG dùng làm "inventory config_hash" semantic.
///
/// Fix:
/// - Linux payload phải INCLUDE `config_hash` tính từ canonical snapshot
///   (cùng semantic với Windows).
/// - Contract test này verify required fields giữa Windows/Linux:
///   schema version, hash, agent, OS, hardware identity, network, software, security.
/// </summary>
public sealed class InventoryContractTests
{
    /// <summary>In-memory IInventoryProvider stub — cho contract test deterministic,
    /// không cần Linux system call thật.</summary>
    private sealed class FakeProvider : IInventoryProvider
    {
        public InventorySnapshot Snapshot { get; init; } = new();
        public InventoryEnvelope Envelope { get; init; } = new();

        public InventoryEnvelope Collect() => Envelope;
    }

    private static (object Payload, FakeProvider Provider) BuildWithSnapshot(string cpuModel, int ramGb)
    {
        var snap = new InventorySnapshot
        {
            OsName = "Ubuntu 24.04",
            Cpu = new CpuInfo { Model = cpuModel },
            RamGb = ramGb,
        };
        var env = new InventoryEnvelope
        {
            Agent = new AgentMetadata { Name = "OrgInventoryAgent", Version = "1.1.0", Platform = "linux" },
            Os = new OsMetadata { Platform = "linux", Distribution = "Ubuntu", DistributionVersion = "24.04" },
            Security = new SecurityPostureV4(),
        };
        return (new { }, new FakeProvider());
    }

    private static JsonSerializerOptions JsonOpts()
    {
        var opts = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
        };
        return opts;
    }

    [Fact]
    public void Linux_Payload_Includes_ConfigHash()
    {
        // AG-P1-04 acceptance: Linux payload phải có field `config_hash` tính từ
        // canonical snapshot (KHÔNG dùng _config.ComputeConfigHash — đó là hash
        // của agent settings, không phải của payload).
        // Test qua real provider trên môi trường Linux (CI container hiện tại).
        var provider = new LinuxInventoryProvider(NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "root");

        var json = JsonSerializer.Serialize(payload, JsonOpts());

        Assert.True(json.Contains("\"config_hash\""),
            $"AG-P1-04 BUG: Linux payload thiếu 'config_hash' — server không thể dedupe " +
            $"theo inventory content. Payload = {json}");
    }

    [Fact]
    public void Linux_Payload_Includes_All_Required_Fields()
    {
        // Required field set theo AG-P1-04 (contract giữa Windows + Linux):
        // schema version, hash, agent, OS, hardware identity, network, software, security.
        var provider = new LinuxInventoryProvider(NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "root");

        var json = JsonSerializer.Serialize(payload, JsonOpts());
        using var doc = JsonDocument.Parse(json);

        Assert.True(doc.RootElement.TryGetProperty("inventory_schema_version", out _),
            $"Linux payload thiếu inventory_schema_version. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("config_hash", out _),
            $"Linux payload thiếu config_hash. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("agent", out _),
            $"Linux payload thiếu agent metadata. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("os", out _),
            $"Linux payload thiếu os metadata. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("os_name", out _),
            $"Linux payload thiếu os_name. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("cpu", out _),
            $"Linux payload thiếu cpu. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("ram_gb", out _),
            $"Linux payload thiếu ram_gb. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("network", out _),
            $"Linux payload thiếu network. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("installed_software", out _),
            $"Linux payload thiếu installed_software. JSON = {json}");
        Assert.True(doc.RootElement.TryGetProperty("security", out _),
            $"Linux payload thiếu security. JSON = {json}");
    }

    private static string? ExtractConfigHash(string json)
    {
        using var doc = JsonDocument.Parse(json);
        foreach (var prop in doc.RootElement.EnumerateObject())
        {
            if (prop.Name == "config_hash") return prop.Value.GetString();
        }
        return null;
    }
}