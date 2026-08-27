using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent;
using OrgInventoryAgent.Services;
using Xunit;

namespace OrgInventoryAgent.Tests;

public class OfflineCacheTests : IDisposable
{
    private readonly string _tempDir;

    public OfflineCacheTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "OrgInventoryTests_" + Guid.NewGuid().ToString("N"));
        AppPaths.Initialize(_tempDir);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDir))
                Directory.Delete(_tempDir, true);
        }
        catch { }
    }

    [Fact]
    public void Enqueue_And_GetAll_ReturnsItemsCorrectly()
    {
        using var cache = new OfflineCache(NullLogger<OfflineCache>.Instance);
        Assert.True(cache.Available);

        cache.Enqueue("http://localhost/api/inventory", "{\"test\": 1}");
        cache.Enqueue("http://localhost/api/inventory", "{\"test\": 2}");

        // Duplicate enqueue of exact same URL and body should be deduplicated
        cache.Enqueue("http://localhost/api/inventory", "{\"test\": 1}");

        var items = cache.GetAll();
        Assert.Equal(2, items.Count);
        Assert.Equal(2, cache.Count());

        Assert.Equal("http://localhost/api/inventory", items[0].Url);
        Assert.Contains("{\"test\": 1}", items[0].Body);
    }

    [Fact]
    public void IncrementAttempts_ReachesMax_ReturnsTrue()
    {
        using var cache = new OfflineCache(NullLogger<OfflineCache>.Instance);
        cache.Enqueue("http://localhost/api/inventory", "{\"test\": 123}");

        var items = cache.GetAll();
        Assert.Single(items);
        var id = items[0].Id;

        for (int i = 1; i < OfflineCache.MaxAttempts; i++)
        {
            var drop = cache.IncrementAttempts(id);
            Assert.False(drop);
        }

        // 10th attempt exceeds/reaches max -> drop = true
        var shouldDrop = cache.IncrementAttempts(id);
        Assert.True(shouldDrop);
    }

    [Fact]
    public void Delete_RemovesItemFromCache()
    {
        using var cache = new OfflineCache(NullLogger<OfflineCache>.Instance);
        cache.Enqueue("http://localhost/api/inventory", "{\"delete_me\": true}");

        var items = cache.GetAll();
        Assert.Single(items);

        cache.Delete(items[0].Id);
        Assert.Empty(cache.GetAll());
    }
}
