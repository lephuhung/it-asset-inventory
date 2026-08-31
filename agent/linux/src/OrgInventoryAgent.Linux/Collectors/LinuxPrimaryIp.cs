using System.Net.NetworkInformation;

namespace OrgInventoryAgent.Linux.Collectors;

/// <summary>Lấy IP đầu tiên của interface up (không phải loopback) — cho heartbeat payload.</summary>
public static class LinuxPrimaryIp
{
    public static string Get()
    {
        try
        {
            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.OperationalStatus != OperationalStatus.Up) continue;
                if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback) continue;
                foreach (var ua in ni.GetIPProperties().UnicastAddresses)
                {
                    if (ua.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                        return ua.Address.ToString();
                }
            }
        }
        catch { }
        return "127.0.0.1";
    }
}