using Microsoft.Extensions.Logging;

namespace OrgInventoryAgent.Core.Logging;

/// <summary>
/// File logger đơn giản: log xoay vòng tại %ProgramData%\OrgInventory\logs\agent.log
/// (5MB/file, giữ 2 file cũ). Zero-GUI — log + config là giao diện duy nhất của agent.
/// </summary>
public sealed class FileLoggerProvider : ILoggerProvider
{
    private const long MaxFileBytes = 5 * 1024 * 1024;

    private readonly string _dir;
    private readonly object _lock = new();
    private StreamWriter? _writer;

    public FileLoggerProvider(string dir)
    {
        _dir = dir;
        Directory.CreateDirectory(dir);
    }

    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);

    internal void Write(string line)
    {
        lock (_lock)
        {
            try
            {
                EnsureWriter();
                _writer?.WriteLine(line);
                _writer?.Flush();
            }
            catch
            {
                // không làm crash service khi disk đầy
            }
        }
    }

    private void EnsureWriter()
    {
        if (_writer is not null)
        {
            var path = Path.Combine(_dir, "agent.log");
            if (new FileInfo(path).Length < MaxFileBytes) return;
            _writer.Dispose();
            _writer = null;
        }
        Rotate();
        var target = Path.Combine(_dir, "agent.log");
        _writer = new StreamWriter(new FileStream(target, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
        {
            AutoFlush = false,
        };
    }

    private void Rotate()
    {
        try
        {
            var f2 = Path.Combine(_dir, "agent.log.2");
            var f1 = Path.Combine(_dir, "agent.log.1");
            var f0 = Path.Combine(_dir, "agent.log");
            if (File.Exists(f2)) File.Delete(f2);
            if (File.Exists(f1)) File.Move(f1, f2, true);
            if (File.Exists(f0)) File.Move(f0, f1, true);
        }
        catch { }
    }

    public void Dispose()
    {
        lock (_lock)
        {
            try { _writer?.Dispose(); } catch { }
            _writer = null;
        }
    }
}

public sealed class FileLogger : ILogger
{
    private readonly FileLoggerProvider _provider;
    private readonly string _category;

    public FileLogger(FileLoggerProvider provider, string category)
    {
        _provider = provider;
        _category = category;
    }

    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

    public bool IsEnabled(LogLevel logLevel) => true;

    public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception,
        Func<TState, Exception?, string> formatter)
    {
        var level = logLevel switch
        {
            LogLevel.Trace => "TRC",
            LogLevel.Debug => "DBG",
            LogLevel.Information => "INF",
            LogLevel.Warning => "WRN",
            LogLevel.Error => "ERR",
            LogLevel.Critical => "CRT",
            _ => "INF",
        };
        var cat = _category.Length > 48 ? _category[^48..] : _category;
        var line = $"{DateTime.UtcNow:yyyy-MM-dd'T'HH:mm:ss'Z'} [{level}] {cat}: {formatter(state, exception)}";
        if (exception is not null)
            line += $" | {exception.GetType().Name}: {exception.Message}";
        _provider.Write(line);
    }
}
