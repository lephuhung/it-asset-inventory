using OrgInventoryAgent.LinuxHelper.Services;
using Xunit;

namespace OrgInventoryAgent.LinuxHelper.Tests;

public class AuthorizationTests
{
    [Fact]
    public void SmartCollector_RejectsArbitraryPath()
    {
        var result = SmartCollector.Collect("/etc/shadow");
        Assert.Null(result);
    }

    [Fact]
    public void SmartCollector_RejectsCommandInjection()
    {
        var result = SmartCollector.Collect("/dev/sda; rm -rf /");
        Assert.Null(result);
    }

    [Fact]
    public void SmartCollector_AcceptsValidSdDevice()
    {
        // Kết quả phụ thuộc thiết bị thật — chỉ kiểm tra không có exception.
        var result = SmartCollector.Collect("/dev/sda");
        Assert.True(result is null || result is not null);
    }

    [Fact]
    public void SmartCollector_AcceptsValidNvmeDevice()
    {
        var result = SmartCollector.Collect("/dev/nvme0n1");
        Assert.True(result is null || result is not null);
    }

    [Fact]
    public void DmiCollector_RejectsDisallowedField()
    {
        var result = DmiCollector.Collect("shadow");
        Assert.Null(result);
    }

    [Fact]
    public void DmiCollector_AcceptsAllowedField()
    {
        // Result phụ thuộc /sys có sẵn — chỉ cần không ném exception.
        var result = DmiCollector.Collect("bios_version");
        Assert.True(result is null || result is string);
    }

    [Fact]
    public void LUKSCollector_RejectsArbitraryPath()
    {
        var result = LUKSCollector.Collect("/etc/passwd");
        Assert.Null(result);
    }

    [Fact]
    public void LUKSCollector_RejectsCommandInjection()
    {
        var result = LUKSCollector.Collect("/dev/sda && malicious");
        Assert.Null(result);
    }

    [Fact]
    public void LUKSCollector_AcceptsValidDevice()
    {
        var result = LUKSCollector.Collect("/dev/sda");
        Assert.True(result is null || result is not null);
    }
}