using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace OrgInventoryAgent;

/// <summary>
/// Cấu hình agent — config-driven. Thứ tự ưu tiên:
/// default biên dịch &lt; config local (%ProgramData%\OrgInventory\config.json)
/// &lt; (Phase 3) config ký số đẩy từ server. Hành vi binary cố định, mọi tham số
/// (endpoint, heartbeat interval/jitter, inventory interval, renew threshold) đều
/// từ config này và được đồng bộ từ server (enroll response / heartbeat response /
/// GET /api/agent/config).
/// </summary>
public sealed class AgentConfig
{
    private static readonly object SaveLock = new();

    // ── Cấu hình server điều khiển (đồng bộ từ enroll / heartbeat / agent/config) ──
    public string[] Endpoints { get; set; } = Array.Empty<string>();
    public int HeartbeatIntervalSeconds { get; set; } = 30;
    public int HeartbeatJitterSeconds { get; set; } = 8;
    public int InventoryIntervalHours { get; set; } = 24;
    public int? InventoryIntervalSeconds { get; set; }
    public int RenewBeforePercent { get; set; } = 70;

    // ── Trạng thái enrollment ──
    public bool Enrolled { get; set; }
    public string? MachineId { get; set; }
    public string? Token { get; set; } // enroll token 1 lần; xóa ngay sau enroll thành công
    public string? ClientCertThumbprint { get; set; }
    public string? CertStoreLocation { get; set; } // Windows: "LocalMachine" | "CurrentUser"
    public string? RenewAfter { get; set; } // ISO 8601 UTC — thời điểm server khuyến nghị renew
    public DateTimeOffset? LastEnrolledAt { get; set; }

    // ── Khác ──
    public string? CaThumbprint { get; set; }
    public string? HttpProxy { get; set; }
    public string? CsrCnPlaceholder { get; set; } // CN dùng cho CSR lúc enroll (chưa biết machine_id)
    public int ConfigVersion { get; set; } = 1;

    // ─────────────────────────────────────────────────────────────

    public static AgentConfig Load(string? file = null)
    {
        var path = file ?? AppPaths.ConfigFile;
        try
        {
            if (File.Exists(path))
            {
                var json = File.ReadAllText(path);
                var cfg = JsonSerializer.Deserialize<AgentConfig>(json, Json.Options)
                          ?? new AgentConfig();
                cfg.Normalize();
                return cfg;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[config] Không đọc được {path}: {ex.Message} — dùng config mặc định.");
        }
        var fresh = new AgentConfig();
        TryBootstrapFromRegistry(fresh);
        return fresh;
    }

    /// <summary>
    /// Bootstrap khi chưa có config.json (cài mới qua MSI): MSI ghi registry
    /// HKLM\SOFTWARE\OrgInventory (Endpoints, EnrollToken, HttpProxy) → đọc vào config.
    /// </summary>
    private static void TryBootstrapFromRegistry(AgentConfig cfg)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\OrgInventory");
            if (key is null) return;
            var endpoints = key.GetValue("Endpoints")?.ToString();
            if (!string.IsNullOrWhiteSpace(endpoints))
            {
                foreach (var e in endpoints.Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries))
                    cfg.AddBackupEndpoint(e.Trim());
            }
            cfg.Token ??= key.GetValue("EnrollToken")?.ToString();
            cfg.HttpProxy ??= key.GetValue("HttpProxy")?.ToString();
            cfg.Normalize();
        }
        catch { }
    }

    public void Save(string? file = null)
    {
        var path = file ?? AppPaths.ConfigFile;
        lock (SaveLock)
        {
            Normalize();
            var json = JsonSerializer.Serialize(this, new JsonSerializerOptions(Json.Options)
            {
                WriteIndented = true,
            });
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, json, new UTF8Encoding(false));
            if (!OperatingSystem.IsWindows())
            {
                try { File.SetUnixFileMode(tmp, UnixFileMode.UserRead | UnixFileMode.UserWrite); }
                catch { /* best-effort */ }
            }
            File.Move(tmp, path, true);
        }
    }

    public void Normalize()
    {
        Endpoints ??= Array.Empty<string>();
        Endpoints = Endpoints
            .Where(e => !string.IsNullOrWhiteSpace(e))
            .Select(e => e.Trim().TrimEnd('/'))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        HeartbeatIntervalSeconds = Math.Clamp(HeartbeatIntervalSeconds, 5, 3600);
        HeartbeatJitterSeconds = Math.Clamp(HeartbeatJitterSeconds, 0, HeartbeatIntervalSeconds - 1);
        InventoryIntervalHours = Math.Clamp(InventoryIntervalHours, 1, 24 * 30);
        if (InventoryIntervalSeconds.HasValue && InventoryIntervalSeconds.Value < 5)
            InventoryIntervalSeconds = 5;
        RenewBeforePercent = Math.Clamp(RenewBeforePercent, 1, 99);
    }

    /// <summary>Endpoint chính (primary). Endpoints[0] là server ưu tiên.</summary>
    [JsonIgnore]
    public string? PrimaryEndpoint => Endpoints.Length > 0 ? Endpoints[0] : null;

    public void SetPrimaryEndpoint(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        url = url.Trim().TrimEnd('/');
        Normalize();
        if (Endpoints.Length > 0 && string.Equals(Endpoints[0], url, StringComparison.OrdinalIgnoreCase)) return;
        var rest = Endpoints.Where(e => !string.Equals(e, url, StringComparison.OrdinalIgnoreCase)).ToArray();
        Endpoints = new[] { url }.Concat(rest).ToArray();
    }

    public void AddBackupEndpoint(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        url = url.Trim().TrimEnd('/');
        Normalize();
        if (Endpoints.Any(e => string.Equals(e, url, StringComparison.OrdinalIgnoreCase))) return;
        Endpoints = Endpoints.Concat(new[] { url }).ToArray();
    }

    /// <summary>
    /// Áp dụng config từ server (enroll response / heartbeat / GET agent/config).
    /// Trả về true nếu có thay đổi cần lưu.
    /// </summary>
    public bool ApplyServerSettings(string? serverUrl, int? heartbeatIntervalSec, int? heartbeatJitterSec,
        int? inventoryIntervalHours, int? renewBeforePercent)
    {
        bool changed = false;
        if (!string.IsNullOrWhiteSpace(serverUrl) && PrimaryEndpoint != serverUrl.Trim().TrimEnd('/'))
        {
            SetPrimaryEndpoint(serverUrl);
            changed = true;
        }
        if (heartbeatIntervalSec is > 0 && HeartbeatIntervalSeconds != heartbeatIntervalSec.Value)
        {
            HeartbeatIntervalSeconds = heartbeatIntervalSec.Value;
            changed = true;
        }
        if (heartbeatJitterSec is >= 0 && HeartbeatJitterSeconds != heartbeatJitterSec.Value)
        {
            HeartbeatJitterSeconds = heartbeatJitterSec.Value;
            changed = true;
        }
        if (inventoryIntervalHours is > 0 && InventoryIntervalHours != inventoryIntervalHours.Value)
        {
            InventoryIntervalHours = inventoryIntervalHours.Value;
            changed = true;
        }
        if (renewBeforePercent is > 0 && RenewBeforePercent != renewBeforePercent.Value)
        {
            RenewBeforePercent = renewBeforePercent.Value;
            changed = true;
        }
        Normalize();
        return changed;
    }

    /// <summary>
    /// Hash cấu hình (canonical JSON, khóa sắp xếp) — server dùng để phát hiện
    /// cấu hình agent thay đổi → yêu cầu inventory lại.
    /// </summary>
    public string ComputeConfigHash()
    {
        var node = new System.Text.Json.Nodes.JsonObject
        {
            ["endpoints"] = new System.Text.Json.Nodes.JsonArray(Endpoints.Select(e => (System.Text.Json.Nodes.JsonNode?)e).ToArray()),
            ["heartbeat_interval_seconds"] = HeartbeatIntervalSeconds,
            ["heartbeat_jitter_seconds"] = HeartbeatJitterSeconds,
            ["inventory_interval_hours"] = InventoryIntervalHours,
            ["renew_before_percent"] = RenewBeforePercent,
        };
        var canonical = CanonicalJson.Sort(node)?.ToJsonString() ?? "{}";
        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }
}

/// <summary>Các tiện ích JSON dùng chung.</summary>
public static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };
}

/// <summary>Serialize canonical (khóa sắp xếp, không khoảng trắng) — dùng cho hash.</summary>
public static class CanonicalJson
{
    public static System.Text.Json.Nodes.JsonNode? Sort(System.Text.Json.Nodes.JsonNode? node)
    {
        if (node is System.Text.Json.Nodes.JsonObject obj)
        {
            var sorted = new System.Text.Json.Nodes.JsonObject();
            foreach (var kv in obj.OrderBy(k => k.Key, StringComparer.Ordinal))
                sorted[kv.Key] = Sort(kv.Value);
            return sorted;
        }
        if (node is System.Text.Json.Nodes.JsonArray arr)
        {
            var items = arr.Select(v => Sort(v)).ToArray();
            return new System.Text.Json.Nodes.JsonArray(items!);
        }
        return node?.DeepClone();
    }

    /// <summary>SHA-256 hex (thường) của canonical JSON của object (bỏ qua 1 property nếu cần).</summary>
    public static string Hash(object? payload, string? excludeProperty = null)
    {
        var node = System.Text.Json.Nodes.JsonNode.Parse(
            System.Text.Json.JsonSerializer.Serialize(payload, Json.Options));
        if (excludeProperty != null && node is System.Text.Json.Nodes.JsonObject obj)
            obj.Remove(excludeProperty);
        var canonical = Sort(node)?.ToJsonString() ?? "null";
        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
    }

    /// <summary>Trả về bytes UTF-8 của canonical JSON (khớp python json.dumps sort_keys=True separators=(',', ':') ensure_ascii=False).</summary>
    public static byte[] ToCanonicalBytes(object? payload)
    {
        var node = System.Text.Json.Nodes.JsonNode.Parse(
            System.Text.Json.JsonSerializer.Serialize(payload, Json.Options));
        var sorted = Sort(node);
        var opt = new JsonSerializerOptions
        {
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = false,
        };
        return Encoding.UTF8.GetBytes(JsonSerializer.Serialize(sorted, opt));
    }
}
