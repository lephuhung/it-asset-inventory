using System.Net.NetworkInformation;

namespace OrgInventoryAgent.Collectors;

/// <summary>
/// Thu thập danh sách cổng mạng đang lắng nghe (Listening Ports) trên thiết bị.
/// </summary>
public static class PortCollector
{
    public static List<ListeningPortInfo>? Collect()
    {
        try
        {
            var ipProps = IPGlobalProperties.GetIPGlobalProperties();
            var endpoints = ipProps.GetActiveTcpListeners();
            var list = endpoints
                .Select(ep => new ListeningPortInfo
                {
                    Port = ep.Port,
                    Address = ep.Address.ToString(),
                    Protocol = "TCP"
                })
                .GroupBy(p => p.Port)
                .Select(g => g.First())
                .OrderBy(p => p.Port)
                .Take(100)
                .ToList();
            return list.Count > 0 ? list : null;
        }
        catch
        {
            return null;
        }
    }
}
