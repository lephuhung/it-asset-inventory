namespace OrgInventoryAgent.Core;

/// <summary>
/// Đường dẫn dữ liệu agent. Windows: %ProgramData%\OrgInventory.
/// Linux (dev/test): ~/.local/share/OrgInventory. Có thể ghi đè bằng env
/// ORGINVENTORY_DATA_DIR hoặc arg --data-dir (tiện cho CI).
/// </summary>
public static class AppPaths
{
    private static string _dataDir = string.Empty;

    public static string DataDir => _dataDir;

    public static string ConfigFile => Path.Combine(DataDir, "config.json");
    public static string StateFile => Path.Combine(DataDir, "state.json");
    public static string CacheDbFile => Path.Combine(DataDir, "cache.db");
    public static string LogsDir => Path.Combine(DataDir, "logs");

    /// <summary>Linux dev only: cert + private key dạng PEM file (Windows dùng Certificate Store).</summary>
    public static string CertFile => Path.Combine(DataDir, "client-cert.pem");
    public static string KeyFile => Path.Combine(DataDir, "client-key.pem");

    public static void Initialize(string? overrideDir = null)
    {
        _dataDir = overrideDir
            ?? Environment.GetEnvironmentVariable("ORGINVENTORY_DATA_DIR")
            ?? (OperatingSystem.IsWindows()
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "OrgInventory")
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "OrgInventory"));

        if (string.IsNullOrWhiteSpace(_dataDir))
            throw new InvalidOperationException("Không xác định được thư mục dữ liệu agent.");

        Directory.CreateDirectory(DataDir);
        Directory.CreateDirectory(LogsDir);
    }
}
