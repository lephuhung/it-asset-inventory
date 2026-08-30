using System.Text.Json;

namespace OrgInventoryAgent.Core.Tests;

/// <summary>Shared JsonSerializerOptions cho tests — match <see cref="OrgInventoryAgent.Core.AgentConfig.Json"/>.</summary>
internal static class AgentConfigJsonContext
{
    public static JsonSerializerOptions DefaultOptions { get; } = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };
}
