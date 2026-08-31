using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>STUB tạm — Task 7 thay bằng implementation thật.</summary>
public sealed class InventoryService : BackgroundService
{
    public InventoryService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        OfflineCache cache, AgentState state, ILogger<InventoryService> logger) { }
    public void TriggerRescan() { }
    protected override Task ExecuteAsync(CancellationToken ct) => Task.CompletedTask;
}