using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Net;

// ── DTO khớp EnrollRequest / EnrollResponse của server ──────────────────────

public sealed class EnrollRequestPayload
{
    [JsonPropertyName("token")] public string? Token { get; set; }
    [JsonPropertyName("hostname")] public string? Hostname { get; set; }
    [JsonPropertyName("fingerprint")] public Collectors.FingerprintPayload? Fingerprint { get; set; }
    [JsonPropertyName("csr_pem")] public string? CsrPem { get; set; }
}

public sealed class EnrollResponse
{
    [JsonPropertyName("machine_id")] public string? MachineId { get; set; }
    [JsonPropertyName("client_cert_pem")] public string? ClientCertPem { get; set; }
    [JsonPropertyName("ca_cert_pem")] public string? CaCertPem { get; set; }
    [JsonPropertyName("renew_after")] public string? RenewAfter { get; set; }
    [JsonPropertyName("is_new_machine")] public bool IsNewMachine { get; set; }
    [JsonPropertyName("status")] public string? Status { get; set; }
    [JsonPropertyName("agent_server_url")] public string? AgentServerUrl { get; set; }
    [JsonPropertyName("heartbeat_interval_seconds")] public int? HeartbeatIntervalSeconds { get; set; }
    [JsonPropertyName("heartbeat_jitter_seconds")] public int? HeartbeatJitterSeconds { get; set; }
    [JsonPropertyName("inventory_interval_hours")] public int? InventoryIntervalHours { get; set; }
}

/// <summary>Client gọi POST /api/enroll (không mTLS — dùng token).</summary>
public sealed class EnrollClient
{
    private readonly ApiClient _api;
    private readonly ILogger<EnrollClient> _logger;

    public EnrollClient(ApiClient api, ILogger<EnrollClient> logger)
    {
        _api = api;
        _logger = logger;
    }

    /// <summary>Gửi enroll. Trả null khi thất bại (đã log lý do).</summary>
    public async Task<EnrollResponse?> EnrollAsync(EnrollRequestPayload request, CancellationToken ct)
    {
        var resp = await _api.PostJsonAsync("/api/enroll", request, ct, useClientCert: false, timeoutSeconds: 45);
        if (resp.Ok && resp.Body is not null)
        {
            try
            {
                var parsed = JsonSerializer.Deserialize<EnrollResponse>(resp.Body, Json.Options);
                return parsed;
            }
            catch (Exception ex)
            {
                _logger.LogError("Parse enroll response lỗi: {Msg}", ex.Message);
                return null;
            }
        }

        switch ((int)resp.Status)
        {
            case 401:
                _logger.LogError("Enroll thất bại 401 (token sai/hết hạn/đã dùng/revoked): {Detail}", resp.Detail);
                break;
            case 422:
                _logger.LogError("Enroll thất bại 422 (payload không hợp lệ): {Detail}", resp.Detail);
                break;
            case 429:
                _logger.LogWarning("Enroll bị rate-limit (429) — thử lại sau.");
                break;
            default:
                _logger.LogError("Enroll thất bại HTTP {(int)Status}: {Detail}", resp.Status, resp.Detail);
                break;
        }
        return null;
    }
}
