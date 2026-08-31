using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxFingerprintTests
{
    [Fact]
    public void Collect_ReturnsPayload()
    {
        var collector = new LinuxFingerprintCollector(NullLogger<LinuxFingerprintCollector>.Instance);
        var fp = collector.Collect();
        Assert.NotNull(fp);
        // Trên máy test hiện tại có thể có hoặc không có /sys/class/dmi/id, không assert required
    }

    [Fact]
    public void Collect_HandlesMissingDmiGracefully()
    {
        // Nếu /sys/class/dmi/id/product_uuid không tồn tại → smbios_uuid = null
        var collector = new LinuxFingerprintCollector(NullLogger<LinuxFingerprintCollector>.Instance);
        var fp = collector.Collect();
        // Không crash, có thể null hoặc có giá trị
        Assert.True(fp.SmbiosUuid is null || fp.SmbiosUuid.Length > 0);
    }

    [Fact]
    public void Collect_MachineGuid_NeverRaw()
    {
        // Quy ước bảo mật: machine_guid phải là SHA-256 hex, KHÔNG phải raw
        var collector = new LinuxFingerprintCollector(NullLogger<LinuxFingerprintCollector>.Instance);
        var fp = collector.Collect();
        if (fp.MachineGuid is not null)
        {
            Assert.Equal(64, fp.MachineGuid.Length);
            Assert.Matches("^[0-9a-f]+$", fp.MachineGuid);
        }
    }

    [Fact]
    public void Collect_MainboardSerial_NeverRaw()
    {
        // Quy ước bảo mật: mainboard_serial phải là SHA-256 hex, KHÔNG phải raw
        var collector = new LinuxFingerprintCollector(NullLogger<LinuxFingerprintCollector>.Instance);
        var fp = collector.Collect();
        if (fp.MainboardSerial is not null)
        {
            Assert.Equal(64, fp.MainboardSerial.Length);
            Assert.Matches("^[0-9a-f]+$", fp.MainboardSerial);
        }
    }
}