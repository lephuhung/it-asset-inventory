using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Core.Collectors;

/// <summary>
/// OS-specific collector that returns a full inventory snapshot as the v4 envelope.
/// Windows wrapper delegates to existing `InventoryCollector`.
/// Linux wrapper (Phase 2) reads /proc, /sys, dpkg/rpm, etc.
/// </summary>
public interface IInventoryProvider
{
    InventoryEnvelope Collect();
}