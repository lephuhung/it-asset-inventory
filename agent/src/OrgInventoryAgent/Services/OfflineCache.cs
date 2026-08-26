using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Services;

/// <summary>
/// Offline cache — SQLite tại %ProgramData%\OrgInventory\cache.db.
/// Lưu payload (JSON) chưa gửi được; flush khi online giữ NGUYÊN nội dung (không
/// có ts trong payload flat Phase 1, nhưng cấu trúc body không đổi → server xử lý
/// idempotent theo nội dung). Cap số lần thử, quá hạn thì bỏ + log.
/// </summary>
public sealed class OfflineCache : IDisposable
{
    public const int MaxAttempts = 10;

    private readonly ILogger<OfflineCache> _logger;
    private readonly object _lock = new();
    private Microsoft.Data.Sqlite.SqliteConnection? _conn;
    private bool _disposed;

    public OfflineCache(ILogger<OfflineCache> logger)
    {
        _logger = logger;
        try
        {
            var csb = new Microsoft.Data.Sqlite.SqliteConnectionStringBuilder
            {
                DataSource = AppPaths.CacheDbFile,
                Mode = Microsoft.Data.Sqlite.SqliteOpenMode.ReadWriteCreate,
                Cache = Microsoft.Data.Sqlite.SqliteCacheMode.Shared,
            };
            _conn = new Microsoft.Data.Sqlite.SqliteConnection(csb.ToString());
            _conn.Open();
            using var cmd = _conn.CreateCommand();
            cmd.CommandText = """
                CREATE TABLE IF NOT EXISTS pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    body TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_body ON pending(url, body_hash);
                """;
            cmd.ExecuteNonQuery();
        }
        catch (Exception ex)
        {
            _logger.LogError("Không mở được SQLite cache ({Path}): {Msg}", AppPaths.CacheDbFile, ex.Message);
            try { _conn?.Dispose(); } catch { }
            _conn = null;
        }
    }

    public bool Available => _conn is not null;

    /// <summary>Thêm bản ghi chờ gửi (dedupe theo url+body hash).</summary>
    public void Enqueue(string url, string body)
    {
        lock (_lock)
        {
            if (_conn is null) return;
            try
            {
                var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(body))).ToLowerInvariant();
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = """
                    INSERT OR IGNORE INTO pending (url, body, body_hash, attempts, created_at)
                    VALUES ($url, $body, $hash, 0, $created)
                    """;
                cmd.Parameters.AddWithValue("$url", url);
                cmd.Parameters.AddWithValue("$body", body);
                cmd.Parameters.AddWithValue("$hash", hash);
                cmd.Parameters.AddWithValue("$created", DateTimeOffset.UtcNow.ToString("o"));
                cmd.ExecuteNonQuery();
                _logger.LogInformation("Đã lưu offline cache: {Url} ({Hash})", url, hash[..8]);
            }
            catch (Exception ex)
            {
                _logger.LogError("Enqueue offline cache lỗi: {Msg}", ex.Message);
            }
        }
    }

    public List<PendingItem> GetAll()
    {
        lock (_lock)
        {
            var result = new List<PendingItem>();
            if (_conn is null) return result;
            try
            {
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = "SELECT id, url, body, attempts FROM pending ORDER BY id";
                using var reader = cmd.ExecuteReader();
                while (reader.Read())
                {
                    result.Add(new PendingItem
                    {
                        Id = reader.GetInt64(0),
                        Url = reader.GetString(1),
                        Body = reader.GetString(2),
                        Attempts = reader.GetInt32(3),
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.LogError("Đọc offline cache lỗi: {Msg}", ex.Message);
            }
            return result;
        }
    }

    public int Count()
    {
        lock (_lock)
        {
            if (_conn is null) return 0;
            try
            {
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = "SELECT COUNT(*) FROM pending";
                return Convert.ToInt32(cmd.ExecuteScalar());
            }
            catch { return 0; }
        }
    }

    /// <summary>Tăng số lần thử; trả true nếu đã vượt cap (nên bỏ).</summary>
    public bool IncrementAttempts(long id)
    {
        lock (_lock)
        {
            if (_conn is null) return true;
            try
            {
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = "UPDATE pending SET attempts = attempts + 1 WHERE id = $id";
                cmd.Parameters.AddWithValue("$id", id);
                cmd.ExecuteNonQuery();

                cmd.CommandText = "SELECT attempts FROM pending WHERE id = $id";
                var attempts = Convert.ToInt32(cmd.ExecuteScalar());
                return attempts >= MaxAttempts;
            }
            catch { return true; }
        }
    }

    public void Delete(long id)
    {
        lock (_lock)
        {
            if (_conn is null) return;
            try
            {
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = "DELETE FROM pending WHERE id = $id";
                cmd.Parameters.AddWithValue("$id", id);
                cmd.ExecuteNonQuery();
            }
            catch { }
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        try { _conn?.Dispose(); } catch { }
        _conn = null;
    }
}

public sealed class PendingItem
{
    public long Id { get; init; }
    public string Url { get; init; } = "";
    public string Body { get; init; } = "";
    public int Attempts { get; init; }
}

/// <summary>Trạng thái nội bộ agent (thời điểm gửi inventory cuối, config hash đã gửi).</summary>
public sealed class AgentState
{
    private static readonly object Lock = new();
    public string? LastInventoryAt { get; set; }
    public string? LastInventoryConfigHash { get; set; }

    public static AgentState Load()
    {
        try
        {
            if (File.Exists(AppPaths.StateFile))
                return JsonSerializer.Deserialize<AgentState>(File.ReadAllText(AppPaths.StateFile), Json.Options) ?? new AgentState();
        }
        catch { }
        return new AgentState();
    }

    public void Save()
    {
        lock (Lock)
        {
            try
            {
                var json = JsonSerializer.Serialize(this, new JsonSerializerOptions(Json.Options) { WriteIndented = true });
                var tmp = AppPaths.StateFile + ".tmp";
                File.WriteAllText(tmp, json, new UTF8Encoding(false));
                File.Move(tmp, AppPaths.StateFile, true);
            }
            catch { }
        }
    }
}
