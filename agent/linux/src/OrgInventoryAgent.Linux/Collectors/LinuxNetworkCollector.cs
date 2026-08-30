using System.Net.NetworkInformation;
using OrgInventoryAgent.Core.Collectors.Schema;

namespace OrgInventoryAgent.Linux.Collectors;

public static class LinuxNetworkCollector
{
    public static List<NetworkInterfaceInfo>? Collect()
    {
        try
        {
            var result = new List<NetworkInterfaceInfo>();
            var distinctSubnets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var entries = new List<(NetworkInterface Ni, string? Ip, string? Mac, string? NetGroup)>();

            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback) continue;
                if (ni.OperationalStatus != OperationalStatus.Up) continue;

                string? ip = null;
                string? netGroup = null;

                foreach (var addr in ni.GetIPProperties().UnicastAddresses)
                {
                    if (addr.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                    {
                        ip = addr.Address.ToString();
                        var ipBytes = addr.Address.GetAddressBytes();
                        try
                        {
                            var mask = addr.IPv4Mask;
                            if (mask is not null && mask.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork)
                            {
                                var maskBytes = mask.GetAddressBytes();
                                var netBytes = new byte[4];
                                for (int i = 0; i < 4; i++)
                                    netBytes[i] = (byte)(ipBytes[i] & maskBytes[i]);
                                int prefix = CountPrefixBits(maskBytes);
                                netGroup = $"{netBytes[0]}.{netBytes[1]}.{netBytes[2]}.{netBytes[3]}/{prefix}";
                            }
                        }
                        catch { }
                        netGroup ??= $"{ipBytes[0]}.{ipBytes[1]}.0.0/16";
                        break;
                    }
                }

                var macBytes = ni.GetPhysicalAddress().GetAddressBytes();
                var mac = macBytes.Length == 0 ? null : string.Join("-", macBytes.Select(b => b.ToString("X2")));

                if (!string.IsNullOrEmpty(netGroup))
                    distinctSubnets.Add(netGroup);

                entries.Add((ni, ip, mac, netGroup));
            }

            bool hasDualHomed = distinctSubnets.Count >= 2;
            string? firstSubnet = null;

            foreach (var (ni, ip, mac, netGroup) in entries)
            {
                bool isSecondary = false;
                if (hasDualHomed && netGroup is not null)
                {
                    firstSubnet ??= netGroup;
                    isSecondary = !string.Equals(firstSubnet, netGroup, StringComparison.OrdinalIgnoreCase);
                }

                result.Add(new NetworkInterfaceInfo
                {
                    Name = ni.Name,
                    Ip = ip,
                    Mac = mac,
                    IsDualHomed = hasDualHomed && isSecondary,
                });
            }

            return result.Count > 0 ? result : null;
        }
        catch
        {
            return null;
        }
    }

    private static int CountPrefixBits(byte[] maskBytes)
    {
        int count = 0;
        foreach (var b in maskBytes)
        {
            var v = b;
            while (v != 0) { count += v & 1; v >>= 1; }
        }
        return count;
    }
}