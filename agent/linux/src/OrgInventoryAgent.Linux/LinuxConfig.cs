using System.Text.Json;
using OrgInventoryAgent.Core;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Load/save AgentConfig cho Linux. Compat: install script ghi key cũ "enroll_token"
/// (snake_case) — nếu AgentConfig.Token null và JSON có "enroll_token" → gán vào Token.
/// Config path mặc định: /etc/orginventory/config.json (production, theo unit file).
/// </summary>
public static class LinuxConfig
{
    public const string DefaultConfigPath = "/etc/orginventory/config.json";

    public static AgentConfig Load(string? path = null)
    {
        var resolved = path ?? DefaultConfigPath;
        var cfg = AgentConfig.Load(resolved);
        if (string.IsNullOrEmpty(cfg.Token) && File.Exists(resolved))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(resolved));
                if (doc.RootElement.TryGetProperty("enroll_token", out var t) && t.ValueKind == JsonValueKind.String)
                    cfg.Token = t.GetString();
            }
            catch { }
        }
        return cfg;
    }

    public static void Save(AgentConfig cfg, string? path = null)
    {
        var resolved = path ?? DefaultConfigPath;
        try { Directory.CreateDirectory(Path.GetDirectoryName(resolved)!); } catch { }
        cfg.Save(resolved);
    }
}