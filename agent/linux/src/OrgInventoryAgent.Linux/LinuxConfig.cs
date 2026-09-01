using System.Text.Json;
using OrgInventoryAgent.Core;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Load/save AgentConfig cho Linux.
///
/// Có 2 file config (giống Windows: bootstrap + state):
/// - Bootstrap (--config / mặc định /etc/orginventory/config.json): install script ghi
///   endpoints + enroll_token (snake_case). Là điểm khởi đầu cho máy mới.
/// - State (AppPaths.ConfigFile = {data-dir}/config.json): agent TỰ lưu sau khi enroll
///   (identity: enrolled/machineId/clientCertThumbprint + intervals server trả về).
///
/// Load merge CẢ HAI: bootstrap làm nền (endpoints/token), state ghi đè khi có
/// (identity + intervals đã sync) — đảm bảo restart KHÔNG bị mất identity và
/// không re-enroll tạo máy trùng / 401 token đã dùng.
/// </summary>
public static class LinuxConfig
{
    public const string DefaultConfigPath = "/etc/orginventory/config.json";

    public static AgentConfig Load(string? path = null)
    {
        var resolved = path ?? DefaultConfigPath;
        var cfg = AgentConfig.Load(resolved);

        // Merge state đã lưu (AppPaths.ConfigFile — nơi services _config.Save() ghi).
        // Ưu tiên identity + server-synced intervals từ state khi tồn tại.
        var statePath = AppPaths.ConfigFile;
        if (!PathsEqual(statePath, resolved) && File.Exists(statePath))
        {
            try
            {
                var state = AgentConfig.Load(statePath);
                MergeState(state, cfg);
            }
            catch { /* bootstrap-only nếu state hỏng */ }
        }

        // Compat: install script ghi key cũ "enroll_token" (snake_case).
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

        // Đồng bộ state vào AppPaths.ConfigFile — nơi services đọc/ghi khi restart
        // (đảm bảo bootstrap + state cùng identity; load sau merge được).
        var statePath = AppPaths.ConfigFile;
        if (!PathsEqual(statePath, resolved))
        {
            try { Directory.CreateDirectory(Path.GetDirectoryName(statePath)!); } catch { }
            cfg.Save(statePath);
        }
    }

    private static void MergeState(AgentConfig state, AgentConfig cfg)
    {
        // Identity — state là nguồn chân lý sau khi enroll
        if (state.Enrolled) cfg.Enrolled = true;
        if (!string.IsNullOrWhiteSpace(state.MachineId)) cfg.MachineId = state.MachineId;
        if (!string.IsNullOrWhiteSpace(state.ClientCertThumbprint)) cfg.ClientCertThumbprint = state.ClientCertThumbprint;
        if (!string.IsNullOrWhiteSpace(state.CertStoreLocation)) cfg.CertStoreLocation = state.CertStoreLocation;
        if (!string.IsNullOrWhiteSpace(state.RenewAfter)) cfg.RenewAfter = state.RenewAfter;
        if (state.LastEnrolledAt is not null) cfg.LastEnrolledAt = state.LastEnrolledAt;

        // Server-synced intervals — chỉ ghi đè khi state có giá trị khác default
        // (bootstrap không có các field này; state mang giá trị server trả về).
        var defaults = new AgentConfig();
        if (state.HeartbeatIntervalSeconds != defaults.HeartbeatIntervalSeconds)
            cfg.HeartbeatIntervalSeconds = state.HeartbeatIntervalSeconds;
        if (state.HeartbeatJitterSeconds != defaults.HeartbeatJitterSeconds)
            cfg.HeartbeatJitterSeconds = state.HeartbeatJitterSeconds;
        if (state.InventoryIntervalHours != defaults.InventoryIntervalHours)
            cfg.InventoryIntervalHours = state.InventoryIntervalHours;
        if (state.InventoryIntervalSeconds.HasValue)
            cfg.InventoryIntervalSeconds = state.InventoryIntervalSeconds;
        if (state.RenewBeforePercent != defaults.RenewBeforePercent)
            cfg.RenewBeforePercent = state.RenewBeforePercent;
    }

    private static bool PathsEqual(string a, string b)
    {
        try { return Path.GetFullPath(a) == Path.GetFullPath(b); }
        catch { return a == b; }
    }
}
