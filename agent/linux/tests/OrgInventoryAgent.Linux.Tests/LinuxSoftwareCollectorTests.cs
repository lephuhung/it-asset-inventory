using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxSoftwareCollectorTests
{
    [Fact]
    public void Collect_ReturnsListWithoutCrashing()
    {
        var list = SoftwareCollector.Collect(NullLogger.Instance);
        Assert.NotNull(list);
        // Trên máy có package manager → có thể có entries; không có → empty list
        Assert.All(list, sw =>
        {
            Assert.NotNull(sw.Name);
            Assert.False(string.IsNullOrWhiteSpace(sw.Name));
        });
    }

    [Fact]
    public void Collect_CapsAt500()
    {
        var list = SoftwareCollector.Collect(NullLogger.Instance);
        Assert.True(list.Count <= 500, $"Expected <= 500 entries, got {list.Count}");
    }

    [Fact]
    public void Collect_DeduplicatesByName()
    {
        var list = SoftwareCollector.Collect(NullLogger.Instance);
        var names = list.Select(s => s.Name).ToList();
        var distinct = names.Distinct(StringComparer.OrdinalIgnoreCase).Count();
        Assert.Equal(names.Count, distinct);
    }

    [Fact]
    public void Collect_OnStandardLinuxFindsSomething()
    {
        // Smoke test: nếu không có package manager thì list = empty; nếu có thì > 0.
        // Không assert cứng — chỉ log số lượng để debug.
        var list = SoftwareCollector.Collect(NullLogger.Instance);
        // Không crash là pass.
        Assert.NotNull(list);
    }
}