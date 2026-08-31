using Xunit;

// AppPaths là global static state (Initialize ghi đè _dataDir). Các test class
// khác nhau dùng tempDir riêng → phải chạy tuần tự để tránh race (giống Windows
// tests: agent/tests/OrgInventoryAgent.Tests/HeartbeatConfigSyncTests.cs).
[assembly: CollectionBehavior(DisableTestParallelization = true)]
