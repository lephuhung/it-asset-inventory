using System.Text.Json;
using OrgInventoryAgent.LinuxHelper;
using OrgInventoryAgent.LinuxHelper.Services;

string? input;
try
{
    using var sr = new StreamReader(Console.OpenStandardInput());
    input = sr.ReadToEnd();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"stdin read error: {ex.Message}");
    return 1;
}

if (string.IsNullOrWhiteSpace(input) || input.Length > 1_000_000) return 2;

HelperRequest? req;
try { req = JsonSerializer.Deserialize<HelperRequest>(input); }
catch { return 3; }

if (req is null || string.IsNullOrWhiteSpace(req.Operation)) return 4;

// Operation allowlist — KHÔNG có dynamic dispatch.
object? data = req.Operation switch
{
    "smartctl" => SmartCollector.Collect(req.Args?.GetValueOrDefault("device")),
    "dmi" => DmiCollector.Collect(req.Args?.GetValueOrDefault("field") ?? ""),
    "luks" => LUKSCollector.Collect(req.Args?.GetValueOrDefault("device") ?? ""),
    _ => null,
};

var resp = new HelperResponse { Ok = data is not null, Data = data };
Console.WriteLine(JsonSerializer.Serialize(resp));
return 0;