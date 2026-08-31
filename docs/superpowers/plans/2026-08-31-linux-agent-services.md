# Linux Agent Services + Install 2-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện Linux agent (config-driven BackgroundServices mirror Windows, payload v4 đầy đủ) + install 2-agent một lệnh với smart reinstall (config-only merge, `--force` để cài đè).

**Architecture:** Linux agent chuyển từ Program.cs stub sang Generic Host + 5 services (`EnrollCoordinator`, `HeartbeatService`, `InventoryService`, `ConfigSyncService`, `RenewService`), tái dùng Core (`AgentConfig`, `EndpointManager`, `ApiClient`, `EnrollClient`, `OfflineCache`, `AgentState`, `CsrGenerator`), tạo mới `OrgInventoryAgent.Linux.Crypto.KeyStore` (PEM-backed, mirror Windows API). `install.sh.j2` thành canonical: cài mới đủ 2 agent; reinstall = merge config (giữ identity) + restart; `--force` = cài đè.

**Tech Stack:** C# .NET 8, Microsoft.Extensions.Hosting, xUnit, bash + jinja2 template (server), python3 (config merge).

**Spec:** `docs/superpowers/specs/2026-08-31-linux-agent-services-design.md`

## Global Constraints

- C# project: `agent/linux/OrgInventoryAgent.Linux.sln`, target net8.0, nullable enable, LangVersion 12.
- Solution hiện build FAIL (7 lỗi) — test scaffold tham chiếu namespace chưa tồn tại. Task 1 sửa.
- Version bump: `agent/linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj` `<Version>1.1.0</Version>` (Task 9).
- Tái dùng Core — KHÔNG duplication: `EndpointManager`, `OfflineCache`, `CsrGenerator`, `AgentConfig`, `AgentState`, `ApiClient`, `EnrollClient` dùng từ `OrgInventoryAgent.Core.*`.
- Test scaffold là contract: `MtlsAndKeyStoreTests` định nghĩa API `KeyStore(ILogger<KeyStore>)`, `InstallCertificate(certPem, key, config)`, `FindClientCertificate(config)`, `ReplaceCertificate(certPem, newKey, config)`; `RenewServiceTests` định nghĩa static `RenewService.RemainingLifePercent(cert, now)`.
- Install: cài bắt buộc đủ 2 agent; reinstall KHÔNG ghi đè toàn bộ config (tránh re-enroll tạo máy trùng) — merge bằng python3, giữ `enrolled`/`machineId`/`clientCertThumbprint`.
- Xóa `install-both.sh` + route `/download/install-both.sh`.
- Commit message tiếng Việt có prefix `feat:`/`fix:`/`test:`/`docs:` (theo git log hiện tại).

---

### Task 1: Sửa test scaffold — build solution xanh

**Files:**
- Modify: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/EndpointManagerTests.cs:3`
- Modify: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/OfflineCacheTests.cs:2-3`
- Modify: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/MtlsAndKeyStoreTests.cs:1-6`
- Modify: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/RenewServiceTests.cs:3`
- Modify: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/AgentConfigTests.cs:1`

**Interfaces:**
- Consumes: Core types `OrgInventoryAgent.Core.Net.EndpointManager`, `OrgInventoryAgent.Core.Services.OfflineCache`, `OrgInventoryAgent.Core.Crypto.CsrGenerator`, `OrgInventoryAgent.Core.AgentConfig`, `OrgInventoryAgent.Core.AppPaths` (đều đã tồn tại).
- Produces: solution `agent/linux/OrgInventoryAgent.Linux.sln` build xanh. Các task sau dựa trên nền này.

- [ ] **Step 1: Sửa usings trong 5 test files**

`EndpointManagerTests.cs` — đổi namespace `Net` sang Core:
```csharp
// dòng 2-3:
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Core.Net;   // thay OrgInventoryAgent.Linux.Net
```

`OfflineCacheTests.cs` — đổi namespace `Services` sang Core:
```csharp
// dòng 2-3:
using OrgInventoryAgent.Core;          // thay OrgInventoryAgent.Linux
using OrgInventoryAgent.Core.Services; // thay OrgInventoryAgent.Linux.Services
```

`MtlsAndKeyStoreTests.cs` — giữ `using OrgInventoryAgent.Linux.Crypto;` (KeyStore sẽ tạo ở Task 2), thêm Core usings, bỏ `Services`:
```csharp
// dòng 1-6:
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging.Abstractions;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;   // CsrGenerator
using OrgInventoryAgent.Linux.Crypto;  // KeyStore (tạo ở Task 2)
// BỎ: using OrgInventoryAgent.Linux.Services;
```

`RenewServiceTests.cs` — đổi namespace `Services` sang `OrgInventoryAgent.Linux.Services` (giữ — RenewService tạo ở Task 4):
```csharp
// dòng 3: giữ nguyên using OrgInventoryAgent.Linux.Services; — namespace này sẽ tồn tại ở Task 4
```

`AgentConfigTests.cs` — thêm `using OrgInventoryAgent.Core;` cho rõ ràng:
```csharp
// dòng 1:
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Linux;
```

- [ ] **Step 2: Build để xác nhận lỗi còn lại chỉ ở MtlsAndKeyStoreTests + RenewServiceTests**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -E "error CS" | sort -u`
Expected: còn lỗi `KeyStore` không tìm thấy (MtlsAndKeyStoreTests.cs:21) + `RenewService` (RenewServiceTests.cs). AgentConfig/EndpointManager/OfflineCache tests hết lỗi.

- [ ] **Step 3: Commit**

```bash
git add agent/linux/tests/OrgInventoryAgent.Linux.Tests/
git commit -m "test: sửa test scaffold trỏ Core namespaces (EndpointManager, OfflineCache, CsrGenerator)"
```

---

### Task 2: `OrgInventoryAgent.Linux.Crypto.KeyStore` — PEM-backed, mirror Windows API

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Crypto/KeyStore.cs`
- Test (có sẵn): `agent/linux/tests/OrgInventoryAgent.Linux.Tests/MtlsAndKeyStoreTests.cs`

**Interfaces:**
- Consumes: `AgentConfig` (Core), `AppPaths.CertFile`/`KeyFile` (Core), `IKeyStore` (Core).
- Produces: `OrgInventoryAgent.Linux.Crypto.KeyStore` — ctor `KeyStore(ILogger<KeyStore>)`; `HasClientCertificate(AgentConfig)`, `FindClientCertificate(AgentConfig)`, `InstallCertificate(string certPem, ECDsa key, AgentConfig config)`, `ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config)`, + `IKeyStore` machineId-based methods. Các services (Task 3-7) dùng class này.

- [ ] **Step 1: Chạy test scaffold để thấy fail**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~MtlsAndKeyStore" 2>&1 | tail -5`
Expected: FAIL — CS0246 `KeyStore` not found.

- [ ] **Step 2: Tạo `KeyStore.cs`**

```csharp
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;

namespace OrgInventoryAgent.Linux.Crypto;

/// <summary>
/// Linux KeyStore — lưu client cert + private key dạng PEM files tại AppPaths.CertFile/KeyFile
/// (data dir). API mirror Windows KeyStore (config-based: thumbprint + CertStoreLocation="File")
/// để EnrollCoordinator/RenewService dùng chung logic. Implement đủ IKeyStore contract.
/// </summary>
public sealed class KeyStore : IKeyStore
{
    private readonly ILogger<KeyStore> _logger;

    public KeyStore(ILogger<KeyStore> logger) => _logger = logger;

    public bool HasClientCertificate(AgentConfig config) =>
        FindClientCertificate(config) is not null;

    public X509Certificate2? FindClientCertificate(AgentConfig config)
    {
        try
        {
            if (File.Exists(AppPaths.CertFile) && File.Exists(AppPaths.KeyFile))
            {
                var cert = X509Certificate2.CreateFromPemFile(AppPaths.CertFile, AppPaths.KeyFile);
                if (cert.HasPrivateKey)
                {
                    config.ClientCertThumbprint ??= cert.Thumbprint;
                    return cert;
                }
                cert.Dispose();
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Load client cert (Linux file) lỗi: {Msg}", ex.Message);
        }
        return null;
    }

    public void InstallCertificate(string certPem, ECDsa key, AgentConfig config)
    {
        certPem = certPem.Trim();
        File.WriteAllText(AppPaths.CertFile, certPem + "\n");
        File.WriteAllText(AppPaths.KeyFile, key.ExportPkcs8PrivateKeyPem());
        try
        {
            File.SetUnixFileMode(AppPaths.KeyFile, UnixFileMode.UserRead | UnixFileMode.UserWrite); // 0600
            File.SetUnixFileMode(AppPaths.CertFile, UnixFileMode.UserRead | UnixFileMode.UserWrite); // 0600
        }
        catch { }
        using var loaded = X509Certificate2.CreateFromPemFile(AppPaths.CertFile, AppPaths.KeyFile);
        config.ClientCertThumbprint = loaded.Thumbprint;
        config.CertStoreLocation = "File";
        _logger.LogInformation("Đã lưu client cert (Linux file) thumbprint {Thumb}", loaded.Thumbprint);
    }

    public void ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config)
    {
        try
        {
            if (File.Exists(AppPaths.CertFile)) File.Delete(AppPaths.CertFile);
            if (File.Exists(AppPaths.KeyFile)) File.Delete(AppPaths.KeyFile);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Xóa PEM cũ lỗi: {Msg}", ex.Message);
        }
        InstallCertificate(certPem, newKey, config);
    }

    // ── IKeyStore contract mới (machineId-based) — delegate Core LinuxKeyStore ──
    private readonly LinuxKeyStore _legacy = new();
    public bool HasPrivateKey(string machineId) => _legacy.HasPrivateKey(machineId);
    public string? GetPrivateKeyPem(string machineId) => _legacy.GetPrivateKeyPem(machineId);
    public string? GetCertificatePem(string machineId) => _legacy.GetCertificatePem(machineId);
    public void InstallCertificate(string machineId, string certPem, string? keyPem) =>
        _legacy.InstallCertificate(machineId, certPem, keyPem);
    public void DeleteCertificate(string machineId) => _legacy.DeleteCertificate(machineId);
}
```

- [ ] **Step 3: Chạy test scaffold**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~MtlsAndKeyStore" 2>&1 | tail -5`
Expected: PASS (4 tests: CsrGenerator, InstallAndFind, Replace, PemPermissions).

- [ ] **Step 4: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/Crypto/KeyStore.cs
git commit -m "feat(agent/linux): KeyStore PEM-backed mirror Windows API (config-based)"
```

---

### Task 3: `OrgInventoryAgent.Linux.Services.RenewService` — static RemainingLifePercent + BackgroundService

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Services/RenewService.cs`
- Test (có sẵn): `agent/linux/tests/OrgInventoryAgent.Linux.Tests/RenewServiceTests.cs`

**Interfaces:**
- Consumes: `AgentConfig`, `ApiClient`, `EndpointManager`, `CsrGenerator`, `KeyStore` (Task 2), `EnrollCoordinator` (Task 5 — khai báo trước, implement sau).
- Produces: `OrgInventoryAgent.Linux.Services.RenewService : BackgroundService` — static `double RemainingLifePercent(X509Certificate2 cert, DateTimeOffset now)`; ctor `RenewService(AgentConfig, ApiClient, EnrollCoordinator, KeyStore, ILogger<RenewService>)`. Program.cs (Task 8) register.

- [ ] **Step 1: Chạy test scaffold RenewServiceTests để thấy fail**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~RenewService" 2>&1 | tail -5`
Expected: FAIL — CS0234 `Services` namespace không tồn tại trong `OrgInventoryAgent.Linux`.

- [ ] **Step 2: Tạo `Services/RenewService.cs`** (mirror Windows, dùng `KeyStore` Linux)

```csharp
using System.Security.Cryptography.X509Certificates;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Linux.Crypto;

namespace OrgInventoryAgent.Linux.Services;

public sealed class RenewRequest
{
    [System.Text.Json.Serialization.JsonPropertyName("csr_pem")]
    public string? CsrPem { get; set; }
}

/// <summary>
/// Tự gia hạn client cert: kiểm tra định kỳ (6h + lúc khởi động) — khi cert còn
/// &lt; renew_before_percent (70%) vòng đời → CSR mới (CN=machine-&lt;machine_id&gt;)
/// → POST /api/renew (mTLS bằng cert cũ) → thay cert PEM.
/// </summary>
public sealed class RenewService : BackgroundService
{
    private static readonly TimeSpan CheckInterval = TimeSpan.FromHours(6);

    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollCoordinator _enroll;
    private readonly KeyStore _keyStore;
    private readonly ILogger<RenewService> _logger;

    public RenewService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        KeyStore keyStore, ILogger<RenewService> logger)
    {
        _config = config;
        _api = api;
        _enroll = enroll;
        _keyStore = keyStore;
        _logger = logger;
    }

    /// <summary>Phần trăm vòng đời cert còn lại (NotBefore→NotAfter).</summary>
    public static double RemainingLifePercent(X509Certificate2 cert, DateTimeOffset now)
    {
        var notBefore = cert.NotBefore.ToUniversalTime();
        var notAfter = cert.NotAfter.ToUniversalTime();
        var total = (notAfter - notBefore).TotalSeconds;
        if (total <= 0) return 0;
        var remaining = (notAfter - now.UtcDateTime).TotalSeconds;
        return Math.Clamp(remaining / total * 100.0, 0, 100);
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(20), ct); }
            catch (OperationCanceledException) { return; }
        }
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (AgentIdentity.IsEnrolled(_config))
                    await CheckAndRenewAsync(ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Chu kỳ kiểm tra renew lỗi."); }
            try { await Task.Delay(CheckInterval, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task CheckAndRenewAsync(CancellationToken ct)
    {
        X509Certificate2? cert;
        try { cert = _keyStore.FindClientCertificate(_config); }
        catch (Exception ex) { _logger.LogWarning("Không load được client cert: {Msg}", ex.Message); return; }
        if (cert is null) { _logger.LogWarning("Không thấy client cert — chờ re-enroll."); return; }

        using (cert)
        {
            var now = DateTimeOffset.UtcNow;
            var remaining = RemainingLifePercent(cert, now);
            if (DateTimeOffset.TryParse(_config.RenewAfter, out var renewAfter) && now >= renewAfter)
            {
                _logger.LogInformation("Đến hạn renew (renew_after={RenewAfter}).", _config.RenewAfter);
                await RenewAsync(ct);
                return;
            }
            if (remaining < _config.RenewBeforePercent)
            {
                _logger.LogInformation("Cert còn {Pct:0.0}% vòng đời (< {Threshold}%) → renew.",
                    remaining, _config.RenewBeforePercent);
                await RenewAsync(ct);
            }
        }
    }

    private async Task RenewAsync(CancellationToken ct)
    {
        using var newKey = CsrGenerator.CreateKeyPair();
        var csrPem = CsrGenerator.CreateCsrPem(newKey, $"machine-{_config.MachineId}");
        try
        {
            var resp = await _api.PostJsonAsync("/api/renew", new RenewRequest { CsrPem = csrPem }, ct,
                useClientCert: true, timeoutSeconds: 45);
            if (!resp.Ok)
            {
                _logger.LogError("Renew thất bại HTTP {StatusCode}: {Detail}", (int)resp.Status, resp.Detail);
                return;
            }
            var certPem = resp.Body?["client_cert_pem"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(certPem))
            {
                _logger.LogError("Renew response thiếu client_cert_pem.");
                return;
            }
            _keyStore.ReplaceCertificate(certPem, newKey, _config);
            _config.RenewAfter = resp.Body?["renew_after"]?.GetValue<string>() ?? _config.RenewAfter;
            _config.Save();
            _logger.LogInformation("Renew thành công — cert mới thumbprint={Thumb}.", _config.ClientCertThumbprint);
        }
        catch (ApiTransportException ex)
        {
            _logger.LogWarning("Không gọi được /api/renew: {Msg}", ex.Message);
        }
    }
}
```

- [ ] **Step 3: Chạy test scaffold**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~RenewService" 2>&1 | tail -5`
Expected: PASS. Lưu ý: file tham chiếu `EnrollCoordinator` (Task 5) — nếu lỗi "missing", tạo stub rỗng tạm trong file này rồi Task 5 thay thật (xem Step 4).

- [ ] **Step 4: (Chỉ nếu Step 3 fail vì thiếu EnrollCoordinator) Tạo stub tạm**

Thêm cuối file (Task 5 sẽ thay thật):
```csharp
// TODO Task 5: thay bằng EnrollCoordinator thật
public sealed class EnrollCoordinator
{
    public Task<bool> EnsureEnrolledAsync(CancellationToken ct) => Task.FromResult(true);
}
```

- [ ] **Step 5: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/Services/RenewService.cs
git commit -m "feat(agent/linux): RenewService (RemainingLifePercent + renew <70%)"
```

---

### Task 4: `EnrollCoordinator` Linux — enroll idempotent + tải config sau enroll

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Services/EnrollCoordinator.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Collectors/LinuxPrimaryIp.cs` (helper nhỏ)

**Interfaces:**
- Consumes: `AgentConfig`, `ApiClient`, `EnrollClient`, `EndpointManager`, `KeyStore` (Task 2), `CsrGenerator`, `AgentState`, `LinuxFingerprintCollector`, `EnrollRequestPayload`/`EnrollResponse` (Core).
- Produces: `OrgInventoryAgent.Linux.Services.EnrollCoordinator` — ctor `(AgentConfig, ApiClient, EnrollClient, EndpointManager, KeyStore, LinuxFingerprintCollector, AgentState, ILogger<EnrollCoordinator>)`; `Task<bool> EnsureEnrolledAsync(CancellationToken)`. HeartbeatService (Task 6) + RenewService (Task 3) gọi. **Thay stub Task 3 Step 4 nếu có.**

- [ ] **Step 1: Tạo `LinuxPrimaryIp.cs`**

```csharp
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
```

- [ ] **Step 2: Tạo `EnrollCoordinator.cs`** (mirror Windows, thay `_inventory`/`_fingerprint` Windows bằng Linux)

```csharp
using System.Net;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux.Crypto;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>
/// Điều phối enrollment: token + fingerprint + CSR → server ký → cài cert PEM → lưu config.
/// Idempotent: đã enroll (cert + machine_id) → bỏ qua. Retry 1 lần/60s.
/// </summary>
public sealed class EnrollCoordinator
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollClient _enrollClient;
    private readonly EndpointManager _endpoints;
    private readonly KeyStore _keyStore;
    private readonly LinuxFingerprintCollector _fingerprint;
    private readonly AgentState _state;
    private readonly ILogger<EnrollCoordinator> _logger;
    private readonly object _lock = new();
    private bool _inFlight;
    private DateTimeOffset _lastAttempt = DateTimeOffset.MinValue;

    public EnrollCoordinator(AgentConfig config, ApiClient api, EnrollClient enrollClient,
        EndpointManager endpoints, KeyStore keyStore, LinuxFingerprintCollector fingerprint,
        AgentState state, ILogger<EnrollCoordinator> logger)
    {
        _config = config; _api = api; _enrollClient = enrollClient; _endpoints = endpoints;
        _keyStore = keyStore; _fingerprint = fingerprint; _state = state; _logger = logger;
    }

    public async Task<bool> EnsureEnrolledAsync(CancellationToken ct)
    {
        if (AgentIdentity.IsEnrolled(_config)) return true;
        lock (_lock)
        {
            if (_inFlight) return false;
            if (DateTimeOffset.UtcNow - _lastAttempt < TimeSpan.FromSeconds(60)) return false;
            _inFlight = true;
            _lastAttempt = DateTimeOffset.UtcNow;
        }
        try { return await EnrollCoreAsync(ct); }
        finally { lock (_lock) _inFlight = false; }
    }

    private async Task<bool> EnrollCoreAsync(CancellationToken ct)
    {
        var token = _config.Token;
        if (string.IsNullOrWhiteSpace(token))
        {
            _logger.LogCritical("Chưa có enroll token — ghi config.json (field \"token\" hoặc \"enroll_token\").");
            return false;
        }
        if (_endpoints.Current is null)
        {
            _logger.LogCritical("Chưa có endpoint server — truyền --endpoint hoặc ghi config.json (field \"endpoints\").");
            return false;
        }

        _logger.LogInformation("Bắt đầu enroll tới {Endpoint}...", _endpoints.Current);
        using var key = CsrGenerator.CreateKeyPair();
        _config.CsrCnPlaceholder ??= "machine-" + Guid.NewGuid();
        var csrPem = CsrGenerator.CreateCsrPem(key, _config.CsrCnPlaceholder);
        var fingerprint = _fingerprint.Collect();
        var request = new EnrollRequestPayload
        {
            Token = token,
            Hostname = SafeHostname(),
            Fingerprint = fingerprint,
            CsrPem = csrPem,
        };

        EnrollResponse? response;
        try { response = await _enrollClient.EnrollAsync(request, ct); }
        catch (ApiTransportException ex) { _logger.LogError("Không kết nối được server enroll: {Msg}", ex.Message); return false; }

        if (response is null || string.IsNullOrWhiteSpace(response.MachineId) || string.IsNullOrWhiteSpace(response.ClientCertPem))
        {
            _logger.LogError("Enroll không thành công — thử lại ở chu kỳ sau.");
            return false;
        }

        _keyStore.InstallCertificate(response.ClientCertPem, key, _config);
        _config.MachineId = response.MachineId;
        _config.Enrolled = true;
        _config.RenewAfter = response.RenewAfter;
        _config.LastEnrolledAt = DateTimeOffset.UtcNow;
        var changed = _config.ApplyServerSettings(
            response.AgentServerUrl, response.HeartbeatIntervalSeconds,
            response.HeartbeatJitterSeconds, response.InventoryIntervalHours, null);
        if (!string.IsNullOrWhiteSpace(response.CaCertPem))
        {
            try { File.WriteAllText(Path.Combine(AppPaths.DataDir, "ca-cert.pem"), response.CaCertPem); }
            catch { }
        }
        _config.Token = null; // token 1 lần — xóa ngay
        _config.Save();
        _logger.LogInformation("Enroll thành công: machine_id={MachineId}, is_new={IsNew}, status={Status}",
            response.MachineId, response.IsNewMachine, response.Status);

        try
        {
            var cfgResp = await _api.GetJsonAsync("/api/agent/config", ct, useClientCert: true, timeoutSeconds: 30);
            if (cfgResp.Ok && cfgResp.Body is not null)
            {
                var sUrl = cfgResp.Body["server_url"]?.GetValue<string>();
                int? hb = TryGetInt(cfgResp.Body["heartbeat_interval_seconds"]);
                int? jit = TryGetInt(cfgResp.Body["heartbeat_jitter_seconds"]);
                int? inv = TryGetInt(cfgResp.Body["inventory_interval_hours"]);
                int? renew = TryGetInt(cfgResp.Body["renew_before_percent"]);
                if (_config.ApplyServerSettings(sUrl, hb, jit, inv, renew)) _config.Save();
                var serverHash = cfgResp.Body["agent_config_hash"]?.GetValue<string>();
                if (!string.IsNullOrWhiteSpace(serverHash)) { _state.LastAgentConfigHash = serverHash; _state.Save(); }
            }
        }
        catch (Exception ex) { _logger.LogWarning("Không tải được /api/agent/config sau enroll: {Msg}", ex.Message); }
        return true;
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try { var v = node?.GetValue<int>(); return v is > 0 ? v : null; }
        catch { return null; }
    }

    private string? SafeHostname()
    {
        try { return Dns.GetHostName(); } catch { return Environment.MachineName; }
    }
}
```

- [ ] **Step 3: Nếu Task 3 có stub — thay bằng class thật**

Xóa stub `EnrollCoordinator` ở cuối `RenewService.cs` (nếu Step 4 Task 3 đã tạo).

- [ ] **Step 4: Build + test toàn solution**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS"` và `dotnet test OrgInventoryAgent.Linux.sln -c Release --nologo 2>&1 | tail -3`
Expected: 0 error; tests pass (AgentConfig, EndpointManager, OfflineCache, Fingerprint, Software, Mtls, Renew).

- [ ] **Step 5: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/
git commit -m "feat(agent/linux): EnrollCoordinator enroll idempotent + tải config sau enroll"
```

---

### Task 5: `ConfigSyncService` Linux — GET /api/agent/config mỗi 6h

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Services/ConfigSyncService.cs`

**Interfaces:**
- Consumes: `AgentConfig`, `ApiClient`, `EnrollCoordinator` (Task 4), `AgentState`.
- Produces: `OrgInventoryAgent.Linux.Services.ConfigSyncService : BackgroundService` — ctor `(AgentConfig, ApiClient, EnrollCoordinator, AgentState, ILogger<ConfigSyncService>)`; `Task<bool> SyncAsync(CancellationToken)`; `Task<bool> SyncAndSaveHashAsync(CancellationToken)`. HeartbeatService (Task 6) dùng.

- [ ] **Step 1: Tạo `ConfigSyncService.cs`** (mirror Windows nguyên văn, đổi namespace + `_enroll` type)

```csharp
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Net;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>Đồng bộ cấu hình từ server: GET /api/agent/config (mTLS) định kỳ mỗi 6h.</summary>
public sealed class ConfigSyncService : BackgroundService
{
    private static readonly TimeSpan SyncInterval = TimeSpan.FromHours(6);
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EnrollCoordinator _enroll;
    private readonly AgentState _state;
    private readonly ILogger<ConfigSyncService> _logger;

    public ConfigSyncService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        AgentState state, ILogger<ConfigSyncService> logger)
    {
        _config = config; _api = api; _enroll = enroll; _state = state; _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(30), ct); }
            catch (OperationCanceledException) { return; }
        }
        while (!ct.IsCancellationRequested)
        {
            try { if (AgentIdentity.IsEnrolled(_config)) await SyncAsync(ct); }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Đồng bộ cấu hình lỗi."); }
            try { await Task.Delay(SyncInterval, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    public async Task<bool> SyncAsync(CancellationToken ct)
    {
        try
        {
            var resp = await _api.GetJsonAsync("/api/agent/config", ct, useClientCert: true, timeoutSeconds: 30);
            if (!resp.Ok) { _logger.LogWarning("GET /api/agent/config thất bại HTTP {Status}: {Detail}", (int)resp.Status, resp.Detail); return false; }
            var body = resp.Body;
            if (body is null) return false;
            var serverUrl = body["server_url"]?.GetValue<string>();
            int? interval = TryGetInt(body["heartbeat_interval_seconds"]);
            int? jitter = TryGetInt(body["heartbeat_jitter_seconds"]);
            int? invHours = TryGetInt(body["inventory_interval_hours"]);
            int? renewPct = TryGetInt(body["renew_before_percent"]);
            var changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct);
            if (changed)
            {
                _config.Save();
                _logger.LogInformation("Đã đồng bộ cấu hình từ server: server={Server}, interval={I}s, jitter={J}s, inventory={H}h, renew={P}%",
                    _config.PrimaryEndpoint, _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds,
                    _config.InventoryIntervalHours, _config.RenewBeforePercent);
            }
            return true;
        }
        catch (ApiTransportException ex) { _logger.LogWarning("Không lấy được cấu hình từ server: {Msg}", ex.Message); return false; }
    }

    public async Task<bool> SyncAndSaveHashAsync(CancellationToken ct)
    {
        try
        {
            var resp = await _api.GetJsonAsync("/api/agent/config", ct, useClientCert: true, timeoutSeconds: 30);
            if (!resp.Ok) { _logger.LogWarning("GET /api/agent/config thất bại HTTP {Status}: {Detail}", (int)resp.Status, resp.Detail); return false; }
            var body = resp.Body;
            if (body is null) return false;
            var serverUrl = body["server_url"]?.GetValue<string>();
            int? interval = TryGetInt(body["heartbeat_interval_seconds"]);
            int? jitter = TryGetInt(body["heartbeat_jitter_seconds"]);
            int? invHours = TryGetInt(body["inventory_interval_hours"]);
            int? renewPct = TryGetInt(body["renew_before_percent"]);
            var changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct);
            if (changed) { _config.Save(); _logger.LogInformation("Đã đồng bộ cấu hình từ server (qua SyncAndSaveHashAsync)."); }
            var serverHash = body["agent_config_hash"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(serverHash))
            {
                _state.LastAgentConfigHash = serverHash;
                _state.Save();
                _logger.LogInformation("Đã cập nhật LastAgentConfigHash={Hash}", serverHash);
            }
            return true;
        }
        catch (ApiTransportException ex) { _logger.LogWarning("Không lấy được cấu hình từ server: {Msg}", ex.Message); return false; }
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try { var v = node?.GetValue<int>(); return v is > 0 ? v : null; }
        catch { return null; }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS"`
Expected: 0.

- [ ] **Step 3: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/Services/ConfigSyncService.cs
git commit -m "feat(agent/linux): ConfigSyncService đồng bộ cấu hình server mỗi 6h"
```

---

### Task 6: `HeartbeatService` Linux — loop interval±jitter + config sync từ response

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Services/HeartbeatService.cs`

**Interfaces:**
- Consumes: `AgentConfig`, `ApiClient`, `EndpointManager`, `EnrollCoordinator` (Task 4), `OfflineCache` (Core), `ConfigSyncService` (Task 5), `AgentState`, `InventoryService` (Task 7 — khai báo trước, implement sau), `LinuxPrimaryIp` (Task 4 Step 1).
- Produces: `OrgInventoryAgent.Linux.Services.HeartbeatService : BackgroundService` — ctor `(AgentConfig, ApiClient, EndpointManager, EnrollCoordinator, OfflineCache, InventoryService, KeyStore, ConfigSyncService, AgentState, ILogger<HeartbeatService>)`; `Task<bool> SendOnceAsync(CancellationToken)`; static `bool ShouldResyncConfig(string?, string?)`. Program.cs (Task 8) register.

- [ ] **Step 1: Tạo `HeartbeatService.cs`** (mirror Windows, payload dùng `Environment.UserName` + `LinuxPrimaryIp.Get()`)

```csharp
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux.Crypto;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>
/// Heartbeat định kỳ: chu kỳ ngẫu nhiên trong [interval - jitter, interval + jitter]
/// (mặc định 30±8s). Đồng bộ interval/jitter/renew_after từ response; agent_config_hash
/// thay đổi → gọi ConfigSync ngay; rescan_requested → TriggerRescan.
/// Trước khi gửi: flush offline cache.
/// </summary>
public sealed class HeartbeatService : BackgroundService
{
    private const int CertCheckEvery = 20;
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EndpointManager _endpoints;
    private readonly EnrollCoordinator _enroll;
    private readonly OfflineCache _cache;
    private readonly InventoryService _inventoryService;
    private readonly KeyStore _keyStore;
    private readonly ConfigSyncService _configSync;
    private readonly ILogger<HeartbeatService> _logger;
    private readonly AgentState _state;
    private int _cycleCount;

    public HeartbeatService(AgentConfig config, ApiClient api, EndpointManager endpoints,
        EnrollCoordinator enroll, OfflineCache cache, InventoryService inventoryService,
        KeyStore keyStore, ConfigSyncService configSync, AgentState state, ILogger<HeartbeatService> logger)
    {
        _config = config; _api = api; _endpoints = endpoints; _enroll = enroll; _cache = cache;
        _inventoryService = inventoryService; _keyStore = keyStore; _configSync = configSync;
        _state = state; _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        _logger.LogInformation("HeartbeatService khởi động (interval={I}s, jitter={J}s).",
            _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds);
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (!AgentIdentity.IsEnrolled(_config))
                {
                    await _enroll.EnsureEnrolledAsync(ct);
                }
                else
                {
                    _cycleCount++;
                    if (_cycleCount % CertCheckEvery == 0)
                    {
                        var status = AgentIdentity.Validate(_config, _keyStore);
                        if (status == EnrollStatus.CertMissing)
                        {
                            _logger.LogCritical("Client cert không còn trong PEM files — đặt lại enrollment để tự re-enroll.");
                            _config.Enrolled = false;
                            _config.ClientCertThumbprint = null;
                            _config.Save();
                        }
                    }
                }
                if (AgentIdentity.IsEnrolled(_config))
                {
                    await FlushOfflineCacheAsync(ct);
                    await SendHeartbeatAsync(ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Chu kỳ heartbeat lỗi."); }
            var delay = NextDelay();
            try { await Task.Delay(delay, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private TimeSpan NextDelay()
    {
        var interval = _config.HeartbeatIntervalSeconds;
        var jitter = Math.Min(_config.HeartbeatJitterSeconds, interval - 1);
        var min = Math.Max(5, interval - jitter);
        var max = Math.Max(min + 1, interval + jitter);
        var seconds = min + (Random.Shared.NextDouble() * (max - min));
        return TimeSpan.FromSeconds(seconds);
    }

    public async Task<bool> SendOnceAsync(CancellationToken ct)
    {
        if (!AgentIdentity.IsEnrolled(_config)) return false;
        return await SendHeartbeatAsync(ct);
    }

    private async Task<bool> SendHeartbeatAsync(CancellationToken ct)
    {
        var payload = new
        {
            logged_user = Environment.UserName,
            uptime_sec = (long)(Environment.TickCount64 / 1000),
            ip = LinuxPrimaryIp.Get(),
        };
        try
        {
            var resp = await _api.PostJsonAsync("/api/heartbeat", payload, ct, useClientCert: true, timeoutSeconds: 20);
            if (!resp.Ok)
            {
                _logger.LogWarning("Heartbeat thất bại HTTP {StatusCode}: {Detail}", (int)resp.Status, resp.Detail);
                return false;
            }
            var body = resp.Body;
            var serverUrl = body?["server_url"]?.GetValue<string>() ?? body?["agent_server_url"]?.GetValue<string>();
            int? interval = TryGetInt(body?["heartbeat_interval_seconds"]);
            int? jitter = TryGetInt(body?["heartbeat_jitter_seconds"]);
            int? invHours = TryGetInt(body?["inventory_interval_hours"]);
            int? renewPct = TryGetInt(body?["renew_before_percent"]);
            bool changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct);
            var renewAfter = body?["renew_after"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(renewAfter) && _config.RenewAfter != renewAfter)
            {
                _config.RenewAfter = renewAfter;
                changed = true;
            }
            if (changed)
            {
                _config.Save();
                _logger.LogInformation("Đã cập nhật cấu hình từ heartbeat response: server={Server}, interval={I}s, jitter={J}s, inv={H}h",
                    _config.PrimaryEndpoint, _config.HeartbeatIntervalSeconds, _config.HeartbeatJitterSeconds, _config.InventoryIntervalHours);
            }
            var serverCfgHash = body?["agent_config_hash"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(serverCfgHash)
                && !string.Equals(serverCfgHash, _state.LastAgentConfigHash, StringComparison.OrdinalIgnoreCase))
            {
                _logger.LogInformation("Server báo hash cấu hình thay đổi ({Old} → {New}) → gọi ConfigSync để refresh.",
                    _state.LastAgentConfigHash ?? "(none)", serverCfgHash);
                var refreshed = await _configSync.SyncAndSaveHashAsync(ct);
                if (refreshed) _state.LastAgentConfigHash = serverCfgHash;
            }
            if (body?["rescan_requested"]?.GetValue<bool>() == true)
            {
                _logger.LogInformation("Server yêu cầu rescan → chạy inventory ngay.");
                _inventoryService.TriggerRescan();
            }
            return true;
        }
        catch (ApiTransportException ex) { _logger.LogWarning("Heartbeat không gửi được: {Msg}", ex.Message); return false; }
    }

    private static int? TryGetInt(System.Text.Json.Nodes.JsonNode? node)
    {
        try { var v = node?.GetValue<int>(); return v is > 0 ? v : null; }
        catch { return null; }
    }

    public static bool ShouldResyncConfig(string? serverHash, string? localHash)
    {
        if (string.IsNullOrWhiteSpace(serverHash)) return false;
        if (string.IsNullOrWhiteSpace(localHash)) return true;
        return !string.Equals(serverHash, localHash, StringComparison.OrdinalIgnoreCase);
    }

    private async Task FlushOfflineCacheAsync(CancellationToken ct)
    {
        var pending = _cache.GetAll();
        if (pending.Count == 0) return;
        _logger.LogInformation("Flush offline cache: {Count} bản ghi đang chờ.", pending.Count);
        foreach (var item in pending)
        {
            try
            {
                var resp = await _api.PostRawJsonAsync(item.Url, item.Body, ct, useClientCert: true, timeoutSeconds: 30);
                if (resp.Ok) { _cache.Delete(item.Id); _logger.LogInformation("Đã gửi bù offline bản ghi #{Id}", item.Id); }
                else
                {
                    var drop = _cache.IncrementAttempts(item.Id);
                    if (drop) _cache.Delete(item.Id);
                }
            }
            catch (Exception ex)
            {
                var drop = _cache.IncrementAttempts(item.Id);
                _logger.LogWarning("Gửi bù #{Id} lỗi: {Msg}{Drop}", item.Id, ex.Message, drop ? " — quá số lần thử, bỏ." : "");
                if (drop) _cache.Delete(item.Id);
            }
        }
    }
}
```

- [ ] **Step 2: Tạo stub tạm `InventoryService` (Task 7 sẽ thay thật)**

Thêm file mới `agent/linux/src/OrgInventoryAgent.Linux/Services/InventoryService.cs` (stub tạm):
```csharp
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>STUB tạm — Task 7 thay bằng implementation thật.</summary>
public sealed class InventoryService : BackgroundService
{
    public InventoryService(AgentConfig config, ApiClient api, EnrollCoordinator enroll,
        OfflineCache cache, AgentState state, ILogger<InventoryService> logger) { }
    public void TriggerRescan() { }
    protected override Task ExecuteAsync(CancellationToken ct) => Task.CompletedTask;
}
```
(Thêm usings `OrgInventoryAgent.Core.Net` + `OrgInventoryAgent.Core.Services` nếu cần.)

- [ ] **Step 3: Build**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS"`
Expected: 0.

- [ ] **Step 4: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/Services/HeartbeatService.cs agent/linux/src/OrgInventoryAgent.Linux/Services/InventoryService.cs
git commit -m "feat(agent/linux): HeartbeatService config-driven + flush offline cache"
```

---

### Task 7: `InventoryService` Linux — payload v4 đầy đủ + gửi định kỳ + offline cache

**Files:**
- Create: `agent/linux/src/OrgInventoryAgent.Linux/Services/InventoryService.cs` (thay stub Task 6)
- Create: `agent/linux/src/OrgInventoryAgent.Linux/InventoryPayloadBuilder.cs`
- Create: `agent/linux/tests/OrgInventoryAgent.Linux.Tests/InventoryPayloadBuilderTests.cs`

**Interfaces:**
- Consumes: `AgentConfig`, `ApiClient`, `EndpointManager`, `EnrollCoordinator`, `OfflineCache`, `AgentState`, `LinuxInventoryProvider`, `InventorySnapshot`/`InventoryEnvelope` (Core schema).
- Produces: `InventoryPayloadBuilder.Build(LinuxInventoryProvider, string loggedUser)` → anonymous object v4 (flat + envelope); `InventoryService : BackgroundService` — ctor `(AgentConfig, ApiClient, EndpointManager, EnrollCoordinator, OfflineCache, LinuxInventoryProvider, AgentState, ILogger<InventoryService>)`; `void TriggerRescan()`; `Task<bool> SendOnceAsync(CancellationToken)`.

- [ ] **Step 1: Tạo test `InventoryPayloadBuilderTests.cs`** (TDD — fail trước)

```csharp
using OrgInventoryAgent.Core.Collectors.Schema;
using OrgInventoryAgent.Linux.Collectors;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class InventoryPayloadBuilderTests
{
    [Fact]
    public void Build_IncludesFullV4Envelope()
    {
        var provider = new LinuxInventoryProvider(
            Microsoft.Extensions.Logging.Abstractions.NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "testuser");

        var json = System.Text.Json.JsonSerializer.Serialize(payload);
        var doc = System.Text.Json.JsonDocument.Parse(json);

        Assert.Equal(4, doc.RootElement.GetProperty("inventory_schema_version").GetInt32());
        Assert.Equal("linux", doc.RootElement.GetProperty("agent").GetProperty("platform").GetString());
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("agent").GetProperty("architecture").GetString()));
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("agent").GetProperty("package_type").GetString()));
        Assert.False(string.IsNullOrEmpty(doc.RootElement.GetProperty("os").GetProperty("kernel_version").GetString()));
        Assert.Equal("linux", doc.RootElement.GetProperty("os").GetProperty("platform").GetString());
        Assert.True(doc.RootElement.TryGetProperty("security", out _));
        Assert.True(doc.RootElement.TryGetProperty("cpu", out _));
    }

    [Fact]
    public void Build_PackageType_MatchesDistro()
    {
        var provider = new LinuxInventoryProvider(
            Microsoft.Extensions.Logging.Abstractions.NullLogger<LinuxInventoryProvider>.Instance);
        var payload = InventoryPayloadBuilder.Build(provider, "u");
        var json = System.Text.Json.JsonSerializer.Serialize(payload);
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var pkg = doc.RootElement.GetProperty("agent").GetProperty("package_type").GetString();
        Assert.True(pkg == "deb" || pkg == "rpm", $"package_type={pkg}");
    }
}
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~InventoryPayloadBuilder" 2>&1 | tail -4`
Expected: FAIL — CS0246 `InventoryPayloadBuilder` not found.

- [ ] **Step 3: Tạo `InventoryPayloadBuilder.cs`**

```csharp
using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Build payload inventory v4: hợp nhất flat snapshot (os_name, cpu, ram_gb, ...)
/// + envelope v4 từ LinuxInventoryProvider.Collect() (agent, os, security) +
/// inventory_schema_version = 4. KHÔNG hard-code field envelope.
/// </summary>
public static class InventoryPayloadBuilder
{
    public static object Build(LinuxInventoryProvider provider, string loggedUser)
    {
        var envelope = provider.Collect();
        var snapshot = provider.CollectSnapshot();
        return new
        {
            os_name = snapshot.OsName,
            os_version = snapshot.OsVersion,
            os_build = snapshot.OsBuild,
            os_arch = snapshot.OsArch,
            is_vm = snapshot.IsVm,
            logged_user = loggedUser,
            cpu = snapshot.Cpu,
            ram_gb = snapshot.RamGb,
            disks = snapshot.Disks,
            gpu = snapshot.Gpu,
            mainboard = snapshot.Mainboard,
            bios = snapshot.Bios,
            network = snapshot.Network,
            installed_software = snapshot.InstalledSoftware,
            security = envelope.Security,
            agent = envelope.Agent,
            os = envelope.Os,
            inventory_schema_version = 4,
        };
    }
}
```

- [ ] **Step 4: Chạy test — pass**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~InventoryPayloadBuilder" 2>&1 | tail -4`
Expected: PASS (2 tests).

- [ ] **Step 5: Thay stub `InventoryService.cs` bằng implementation thật** (mirror Windows, collector = `LinuxInventoryProvider`, payload = `InventoryPayloadBuilder.Build`)

```csharp
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;

namespace OrgInventoryAgent.Linux.Services;

/// <summary>
/// Gửi inventory v4 đầy đủ: lần đầu sau enroll, config_hash thay đổi, định kỳ
/// inventory_interval_hours (24h), rescan_requested. Thất bại → offline cache.
/// </summary>
public sealed class InventoryService : BackgroundService
{
    private readonly AgentConfig _config;
    private readonly ApiClient _api;
    private readonly EndpointManager _endpoints;
    private readonly EnrollCoordinator _enroll;
    private readonly OfflineCache _cache;
    private readonly LinuxInventoryProvider _collector;
    private readonly ILogger<InventoryService> _logger;
    private readonly AgentState _state;
    private readonly object _sendLock = new();
    private volatile bool _rescanRequested;
    private bool _sending;

    public InventoryService(AgentConfig config, ApiClient api, EndpointManager endpoints,
        EnrollCoordinator enroll, OfflineCache cache, LinuxInventoryProvider collector,
        AgentState state, ILogger<InventoryService> logger)
    {
        _config = config; _api = api; _endpoints = endpoints; _enroll = enroll; _cache = cache;
        _collector = collector; _state = state; _logger = logger;
    }

    public void TriggerRescan() => _rescanRequested = true;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && !AgentIdentity.IsEnrolled(_config))
        {
            await _enroll.EnsureEnrolledAsync(ct);
            try { await Task.Delay(TimeSpan.FromSeconds(15), ct); }
            catch (OperationCanceledException) { return; }
        }
        var intervalDesc = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
            ? $"{_config.InventoryIntervalSeconds.Value}s" : $"{_config.InventoryIntervalHours}h";
        _logger.LogInformation("InventoryService khởi động (interval={Interval}).", intervalDesc);
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (AgentIdentity.IsEnrolled(_config) && IsDue())
                {
                    _rescanRequested = false;
                    await SendInventoryAsync(ct);
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (Exception ex) { _logger.LogError(ex, "Chu kỳ inventory lỗi."); }
            var delaySec = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
                ? Math.Clamp(_config.InventoryIntervalSeconds.Value, 5, 30) : 30;
            try { await Task.Delay(TimeSpan.FromSeconds(delaySec), ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private bool IsDue()
    {
        if (_rescanRequested) return true;
        var configHash = _config.ComputeConfigHash();
        if (_state.LastInventoryConfigHash != configHash) return true;
        if (_state.LastInventoryAt is null) return true;
        if (DateTimeOffset.TryParse(_state.LastInventoryAt, out var last))
        {
            var interval = _config.InventoryIntervalSeconds.HasValue && _config.InventoryIntervalSeconds.Value > 0
                ? TimeSpan.FromSeconds(_config.InventoryIntervalSeconds.Value)
                : TimeSpan.FromHours(Math.Max(1, _config.InventoryIntervalHours));
            return DateTimeOffset.UtcNow - last >= interval;
        }
        return true;
    }

    public async Task<bool> SendOnceAsync(CancellationToken ct)
    {
        if (!AgentIdentity.IsEnrolled(_config)) return false;
        return await SendInventoryAsync(ct);
    }

    private async Task<bool> SendInventoryAsync(CancellationToken ct)
    {
        lock (_sendLock) { if (_sending) return false; _sending = true; }
        try
        {
            var configHash = _config.ComputeConfigHash();
            var payload = InventoryPayloadBuilder.Build(_collector, Environment.UserName);
            var url = _endpoints.BuildUrl("/api/inventory");
            try
            {
                var resp = await _api.PostJsonAsync("/api/inventory", payload, ct, useClientCert: true, timeoutSeconds: 60);
                if (resp.Ok)
                {
                    _state.LastInventoryAt = DateTimeOffset.UtcNow.ToString("o");
                    _state.LastInventoryConfigHash = configHash;
                    _state.Save();
                    _logger.LogInformation("Đã gửi inventory (config_changed={C}).", resp.Body?["config_changed"]?.GetValue<bool>());
                    return true;
                }
                _logger.LogWarning("Inventory thất bại HTTP {StatusCode}: {Detail} → lưu offline cache.", (int)resp.Status, resp.Detail);
                EnqueueOffline(url, payload);
                return false;
            }
            catch (ApiTransportException ex)
            {
                _logger.LogWarning("Inventory không gửi được: {Msg} → lưu offline cache.", ex.Message);
                EnqueueOffline(url, payload);
                return false;
            }
        }
        finally { lock (_sendLock) _sending = false; }
    }

    private void EnqueueOffline(string url, object payload)
    {
        try
        {
            var body = System.Text.Json.JsonSerializer.Serialize(payload, OrgInventoryAgent.Core.Json.Options);
            _cache.Enqueue(url, body);
        }
        catch (Exception ex) { _logger.LogError("Lưu offline cache inventory lỗi: {Msg}", ex.Message); }
    }
}
```

- [ ] **Step 6: Build + test toàn solution**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS" && dotnet test OrgInventoryAgent.Linux.sln -c Release --nologo 2>&1 | tail -3`
Expected: 0 error; tất cả tests pass.

- [ ] **Step 7: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/ agent/linux/tests/OrgInventoryAgent.Linux.Tests/
git commit -m "feat(agent/linux): InventoryService payload v4 đầy đủ + định kỳ + offline cache"
```

---

### Task 8: `Program.cs` — Generic Host + CLI + service mode + `--once`

**Files:**
- Rewrite: `agent/linux/src/OrgInventoryAgent.Linux/Program.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/CliArgs.cs`
- Create: `agent/linux/src/OrgInventoryAgent.Linux/LinuxConfig.cs`

**Interfaces:**
- Consumes: tất cả services Task 3-7, Core (`AgentConfig`, `AgentState`, `ApiClient`, `EndpointManager`, `EnrollClient`, `OfflineCache`, `LinuxFingerprintCollector`, `LinuxInventoryProvider`, `AppPaths`).
- Produces: executable hoàn chỉnh: service mode (default) + CLI `--data-dir/--config/--enroll-token/--endpoint/--inventory-seconds/--once/--send-inventory/--print-inventory/--print-security/--print-config/--version/--about/--help`.

- [ ] **Step 1: Tạo `CliArgs.cs`** (mirror Windows CliArgs)

```csharp
namespace OrgInventoryAgent.Linux;

/// <summary>Parse CLI args đơn giản (--key value / --flag).</summary>
internal sealed class CliArgs
{
    public string? DataDir { get; private set; }
    public string? ConfigPath { get; private set; }
    public string? EnrollToken { get; private set; }
    public string? Endpoint { get; private set; }
    public int? InventorySeconds { get; private set; }
    public bool PrintConfig { get; private set; }
    public bool PrintFingerprint { get; private set; }
    public bool PrintInventory { get; private set; }
    public bool PrintSecurity { get; private set; }
    public bool PrintAbout { get; private set; }
    public bool PrintVersion { get; private set; }
    public bool Once { get; private set; }
    public bool SendInventory { get; private set; }
    public bool ShowHelp { get; private set; }

    public static CliArgs Parse(string[] args)
    {
        var cli = new CliArgs();
        for (int i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            string? Next() => i + 1 < args.Length ? args[++i] : null;
            switch (arg)
            {
                case "--data-dir": cli.DataDir = Next(); break;
                case "--config": cli.ConfigPath = Next(); break;
                case "--enroll-token": cli.EnrollToken = Next(); break;
                case "--endpoint": cli.Endpoint = Next(); break;
                case "--inventory-seconds":
                case "--inventory-interval":
                    if (int.TryParse(Next(), out var sec)) cli.InventorySeconds = sec;
                    break;
                case "--print-config": cli.PrintConfig = true; break;
                case "--print-fingerprint": cli.PrintFingerprint = true; break;
                case "--print-inventory": cli.PrintInventory = true; break;
                case "--print-security": cli.PrintSecurity = true; break;
                case "--about":
                case "--info": cli.PrintAbout = true; break;
                case "--version":
                case "-v": cli.PrintVersion = true; break;
                case "--once": cli.Once = true; break;
                case "--send-inventory": cli.SendInventory = true; break;
                case "--help":
                case "-h": cli.ShowHelp = true; break;
                default:
                    Console.Error.WriteLine($"[warn] Bỏ qua tham số không biết: {arg}");
                    break;
            }
        }
        return cli;
    }
}
```

- [ ] **Step 2: Tạo `LinuxConfig.cs`** — load + compat `enroll_token` → `Token`

```csharp
using System.Text.Json;
using OrgInventoryAgent.Core;

namespace OrgInventoryAgent.Linux;

/// <summary>
/// Load/save AgentConfig cho Linux. Compat: install script ghi key cũ "enroll_token"
/// (snake_case) — nếu AgentConfig.Token null và JSON có enroll_token → gán vào Token.
/// Config path mặc định: /etc/orginventory/config.json (production, theo unit file).
/// </summary>
public static class LinuxConfig
{
    public const string DefaultConfigPath = "/etc/orginventory/config.json";

    public static AgentConfig Load(string? path = null)
    {
        var resolved = path ?? DefaultConfigPath;
        var cfg = AgentConfig.Load(resolved);
        if (string.IsNullOrEmpty(cfg.Token) && File.Exists(resolved))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(resolved));
                if (doc.RootElement.TryGetProperty("enroll_token", out var t) && t.ValueKind == JsonValueKind.String)
                    cfg.Token = t.GetString();
            }
            catch { }
        }
        return cfg;
    }

    public static void Save(AgentConfig cfg, string? path = null)
    {
        var resolved = path ?? DefaultConfigPath;
        try { Directory.CreateDirectory(Path.GetDirectoryName(resolved)!); } catch { }
        cfg.Save(resolved);
    }
}
```

- [ ] **Step 3: Viết test cho LinuxConfig compat** — `agent/linux/tests/OrgInventoryAgent.Linux.Tests/LinuxConfigTests.cs`

```csharp
using OrgInventoryAgent.Core;
using Xunit;

namespace OrgInventoryAgent.Linux.Tests;

public class LinuxConfigTests
{
    [Fact]
    public void Load_ReadsLegacyEnrollToken_IntoToken()
    {
        var dir = Path.Combine(Path.GetTempPath(), "LinuxCfg_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        AppPaths.Initialize(dir);
        var cfgPath = Path.Combine(dir, "config.json");
        File.WriteAllText(cfgPath, """{"endpoints":["https://agent.local"],"enroll_token":"t_abc","data_dir":"/var/lib/orginventory"}""");

        var cfg = LinuxConfig.Load(cfgPath);

        Assert.Equal("t_abc", cfg.Token);
        Assert.Equal("https://agent.local", cfg.PrimaryEndpoint);
        Directory.Delete(dir, recursive: true);
    }
}
```

- [ ] **Step 4: Chạy test LinuxConfig — fail rồi pass**

Run: `cd /home/windowsId/agent/linux && dotnet test tests/OrgInventoryAgent.Linux.Tests/OrgInventoryAgent.Linux.Tests.csproj -c Release --filter "FullyQualifiedName~LinuxConfig" 2>&1 | tail -4`
Expected lần 1: FAIL (CS0246 LinuxConfig not found — trước khi tạo class). Sau Step 2 đã tạo class → PASS.

- [ ] **Step 5: Rewrite `Program.cs`** — Generic Host + CLI + service mode + once mode

```csharp
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OrgInventoryAgent.Core;
using OrgInventoryAgent.Core.Crypto;
using OrgInventoryAgent.Core.Logging;
using OrgInventoryAgent.Core.Net;
using OrgInventoryAgent.Core.Services;
using OrgInventoryAgent.Linux.Collectors;
using OrgInventoryAgent.Linux.Crypto;
using OrgInventoryAgent.Linux.Services;
using System.Text.Json;

namespace OrgInventoryAgent.Linux;

public class Program
{
    public static async Task<int> Main(string[] args)
    {
        var cli = CliArgs.Parse(args);

        // AppPaths phải Initialize TRƯỚC khi bất kỳ code nào dùng AppPaths.*
        var dataDir = cli.DataDir
            ?? Environment.GetEnvironmentVariable("ORGINV_DATA_DIR")
            ?? (Directory.Exists("/var/lib/orginventory") ? "/var/lib/orginventory"
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "OrgInventory"));
        try { AppPaths.Initialize(dataDir); }
        catch (Exception ex) { Console.Error.WriteLine($"Không thể khởi tạo data dir '{dataDir}': {ex.Message}"); return 10; }

        if (cli.PrintVersion) { Console.WriteLine($"{AppInfo.Name} v{AppInfo.Version}"); return 0; }
        if (cli.PrintAbout) { Console.WriteLine(AppInfo.TransparencyAndSafetyCommitment); return 0; }
        if (cli.PrintConfig)
        {
            var cfg = LinuxConfig.Load(cli.ConfigPath);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                data_dir = AppPaths.DataDir,
                config_path = cli.ConfigPath ?? LinuxConfig.DefaultConfigPath,
                endpoints = cfg.Endpoints,
                heartbeat_interval_seconds = cfg.HeartbeatIntervalSeconds,
                heartbeat_jitter_seconds = cfg.HeartbeatJitterSeconds,
                inventory_interval_hours = cfg.InventoryIntervalHours,
                renew_before_percent = cfg.RenewBeforePercent,
                enrolled = cfg.Enrolled,
                machine_id = cfg.MachineId,
                token = cfg.Token is null ? null : (cfg.Token.Length > 12 ? cfg.Token[..4] + "…" : "***"),
                client_cert_thumbprint = cfg.ClientCertThumbprint,
                cert_store_location = cfg.CertStoreLocation,
            }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintInventory)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var provider = new LinuxInventoryProvider(lf.CreateLogger<LinuxInventoryProvider>());
            var snapshot = provider.CollectSnapshot();
            var envelope = provider.Collect();
            Console.WriteLine(JsonSerializer.Serialize(new { envelope, snapshot }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintSecurity)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var sec = LinuxSecurityCollector.Collect(lf.CreateLogger("Security"));
            Console.WriteLine(JsonSerializer.Serialize(sec, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        if (cli.PrintFingerprint)
        {
            using var lf = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true));
            var fp = new LinuxFingerprintCollector(lf.CreateLogger<LinuxFingerprintCollector>()).Collect();
            Console.WriteLine(JsonSerializer.Serialize(fp, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }

        var config = LinuxConfig.Load(cli.ConfigPath);
        if (!string.IsNullOrWhiteSpace(cli.Endpoint)) config.SetPrimaryEndpoint(cli.Endpoint);
        if (cli.InventorySeconds.HasValue) config.InventoryIntervalSeconds = cli.InventorySeconds.Value;
        if (!string.IsNullOrWhiteSpace(cli.EnrollToken)) { config.Token = cli.EnrollToken; LinuxConfig.Save(config, cli.ConfigPath); }

        if (cli.Once || cli.SendInventory)
            return await RunOnceAsync(config, cli);

        return await RunServiceAsync(config, cli);
    }

    // ── Service mode ────────────────────────────────────────────
    private static async Task<int> RunServiceAsync(AgentConfig config, CliArgs cli)
    {
        var builder = Host.CreateApplicationBuilder(Array.Empty<string>());
        builder.Logging.ClearProviders();
        builder.Logging.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' "; });
        try { builder.Logging.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); } catch { }

        RegisterServices(builder, config);

        using var host = builder.Build();
        var logger = host.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Startup");
        logger.LogInformation("================================================================================");
        logger.LogInformation("{Name} v{Version} — {FullTitle}", AppInfo.Name, AppInfo.Version, AppInfo.FullTitle);
        logger.LogInformation("Đơn vị phát triển: {Dev}", AppInfo.DeveloperShort);
        logger.LogInformation("DataDir={Dir} Config={Cfg}", AppPaths.DataDir, cli.ConfigPath ?? LinuxConfig.DefaultConfigPath);
        logger.LogInformation("================================================================================");

        var coordinator = host.Services.GetRequiredService<EnrollCoordinator>();
        _ = Task.Run(() => coordinator.EnsureEnrolledAsync(CancellationToken.None));

        await host.RunAsync();
        return 0;
    }

    private static void RegisterServices(HostApplicationBuilder builder, AgentConfig config)
    {
        builder.Services.AddSingleton(config);
        builder.Services.AddSingleton(AgentState.Load());
        builder.Services.AddSingleton<KeyStore>();
        builder.Services.AddSingleton<EndpointManager>();
        builder.Services.AddSingleton<OfflineCache>();
        builder.Services.AddSingleton<LinuxFingerprintCollector>();
        builder.Services.AddSingleton<LinuxInventoryProvider>();
        builder.Services.AddSingleton<ApiClient>();
        builder.Services.AddSingleton<EnrollClient>();
        builder.Services.AddSingleton<EnrollCoordinator>();
        builder.Services.AddSingleton<HeartbeatService>();
        builder.Services.AddSingleton<InventoryService>();
        builder.Services.AddSingleton<RenewService>();
        builder.Services.AddSingleton<ConfigSyncService>();
        builder.Services.AddHostedService(sp => sp.GetRequiredService<HeartbeatService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<InventoryService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<RenewService>());
        builder.Services.AddHostedService(sp => sp.GetRequiredService<ConfigSyncService>());
    }

    // ── Once mode (smoke test install / --send-inventory) ────────
    private static async Task<int> RunOnceAsync(AgentConfig config, CliArgs cli)
    {
        using var loggerFactory = LoggerFactory.Create(b =>
        {
            b.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss'Z' "; });
            try { b.AddProvider(new FileLoggerProvider(AppPaths.LogsDir)); } catch { }
        });
        var logger = loggerFactory.CreateLogger("Once");
        logger.LogInformation("Chế độ --once: enroll (nếu cần) → heartbeat → inventory.");

        var keyStore = new KeyStore(loggerFactory.CreateLogger<KeyStore>());
        var endpoints = new EndpointManager(config, loggerFactory.CreateLogger<EndpointManager>());
        var api = new ApiClient(config, endpoints, keyStore, loggerFactory.CreateLogger<ApiClient>());
        var enrollClient = new EnrollClient(api, loggerFactory.CreateLogger<EnrollClient>());
        var state = AgentState.Load();
        var fingerprint = new LinuxFingerprintCollector(loggerFactory.CreateLogger<LinuxFingerprintCollector>());
        var enroll = new EnrollCoordinator(config, api, enrollClient, endpoints, keyStore, fingerprint, state,
            loggerFactory.CreateLogger<EnrollCoordinator>());
        var cache = new OfflineCache(loggerFactory.CreateLogger<OfflineCache>());
        var provider = new LinuxInventoryProvider(loggerFactory.CreateLogger<LinuxInventoryProvider>());
        var inventory = new InventoryService(config, api, endpoints, enroll, cache, provider, state,
            loggerFactory.CreateLogger<InventoryService>());

        var ok = await enroll.EnsureEnrolledAsync(CancellationToken.None);
        if (!ok && !AgentIdentity.IsEnrolled(config)) { logger.LogWarning("Chưa enroll được — exit 0 (service sẽ retry)."); return 0; }
        await inventory.SendOnceAsync(CancellationToken.None);
        return 0;
    }
}
```

- [ ] **Step 6: Build + test toàn solution**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS"`
Expected: 0.

- [ ] **Step 7: Smoke test CLI**

Run: `cd /home/windowsId/agent/linux && dotnet run --project src/OrgInventoryAgent.Linux --no-build -c Release -- --version` và `dotnet run --project src/OrgInventoryAgent.Linux --no-build -c Release -- --print-inventory 2>&1 | head -20`
Expected: version in; JSON envelope + snapshot.

- [ ] **Step 8: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/
git commit -m "feat(agent/linux): Program.cs Generic Host + CLI (--once, --config, --enroll-token) + LinuxConfig compat"
```

---

### Task 9: Bump version 1.1.0 + build/publish Linux

**Files:**
- Modify: `agent/linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj` (Version/AssemblyVersion/FileVersion)

- [ ] **Step 1: Sửa version**

```xml
<Version>1.1.0</Version>
<AssemblyVersion>1.1.0.0</AssemblyVersion>
<FileVersion>1.1.0.0</FileVersion>
```

- [ ] **Step 2: Build + test**

Run: `cd /home/windowsId/agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release --nologo -v q 2>&1 | grep -cE "error CS" && dotnet test OrgInventoryAgent.Linux.sln -c Release --nologo 2>&1 | tail -3`
Expected: 0; pass.

- [ ] **Step 3: Publish linux-x64 (self-contained single-file)**

Run: `cd /home/windowsId/agent/linux && dotnet publish src/OrgInventoryAgent.Linux -c Release -r linux-x64 --self-contained -p:PublishSingleFile=true -p:DebugType=none -o dist/linux-x64 2>&1 | tail -3`
Expected: dist/linux-x64/OrgInventoryAgent.

- [ ] **Step 4: Commit**

```bash
git add agent/linux/src/OrgInventoryAgent.Linux/OrgInventoryAgent.Linux.csproj
git commit -m "feat(agent/linux): bump version 1.1.0"
```

---

### Task 10: `install.sh.j2` — smart reinstall + config merge + `--force` + bỏ SKIP_VELOCIRAPTOR

**Files:**
- Modify: `server/app/templates/install.sh.j2` (toàn bộ flow)

**Interfaces:**
- Consumes: `{portal_url}`, `{agent_server_url}`, `{token}` (jinja2 render từ `/i/<token>`).
- Produces: script một lệnh cài đủ 2 agent; reinstall = merge config (giữ identity) + restart; `--force` = cài đè.

- [ ] **Step 1: Thêm parsing args đầu script**

```bash
FORCE_REINSTALL=0
if [[ "${1:-}" == "--force" || "${INSTALL_FORCE:-0}" == "1" ]]; then
    FORCE_REINSTALL=1
fi
```

- [ ] **Step 2: Thêm hàm detect + merge config (sau phần khai báo log helpers)**

```bash
# ── Detect trạng thái ────────────────────────────────────────────
OI_INSTALLED=0
if [[ -x /opt/orginventory/OrgInventoryAgent ]] && systemctl list-unit-files orginventory-agent.service >/dev/null 2>&1; then
    OI_INSTALLED=1
fi
VR_INSTALLED=0
if (dpkg -l velociraptor-client >/dev/null 2>&1 || rpm -q velociraptor-client >/dev/null 2>&1) \
   && systemctl list-unit-files velociraptor_client.service >/dev/null 2>&1; then
    VR_INSTALLED=1
fi

# ── Merge config: giữ identity (enrolled/machineId/thumbprint), chỉ thay endpoints + enroll_token ──
merge_oi_config() {
    local cfg=/etc/orginventory/config.json
    mkdir -p /etc/orginventory
    if [[ -f "$cfg" ]] && command -v python3 >/dev/null 2>&1; then
        python3 - "$cfg" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    data = {}
data["endpoints"] = [__import__("os").environ.get("AGENT_SERVER_URL", data.get("endpoints", [""])[0] if data.get("endpoints") else "")]
# giữ identity: không đụng enrolled/machineId/clientCertThumbprint
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PYEOF
    else
        # fallback: ghi đè tối thiểu (không có python3 — chấp nhận rủi ro re-enroll)
        cat > "$cfg" <<EOF
{
  "endpoints": ["$AGENT_SERVER_URL"],
  "enroll_token": "$TOKEN",
  "data_dir": "$DATA_DIR"
}
EOF
    fi
    chmod 0640 "$cfg"
    chown root:orginventory "$cfg"
}
```

- [ ] **Step 3: Bọc phần OrgInventory (bước 3–8) vào nhánh reinstall**

Thay đoạn "── 3. Tải binary" đến hết "── 8. Enable + start" bằng:

```bash
if [[ $OI_INSTALLED -eq 1 && $FORCE_REINSTALL -eq 0 ]]; then
    log_step "OrgInventory Agent đã cài → chỉ MERGE config + restart (KHÔNG tải binary)."
    AGENT_SERVER_URL="$AGENT_SERVER_URL" merge_oi_config
    systemctl restart orginventory-agent.service || true
    sleep 2
    if systemctl is-active --quiet orginventory-agent.service; then
        log_ok "Service orginventory-agent đang chạy (config mới)"
    else
        log_warn "orginventory-agent start fail — xem: journalctl -u orginventory-agent -n 50"
    fi
else
    if [[ $FORCE_REINSTALL -eq 1 ]]; then
        log_warn "--force: cài đè binary OrgInventoryAgent"
        systemctl stop orginventory-agent.service 2>/dev/null || true
    fi
    # ... (giữ nguyên flow cài mới hiện tại: tải binary + SHA256 + user + units + config)
    AGENT_SERVER_URL="$AGENT_SERVER_URL" merge_oi_config
    # ... (giữ nguyên enable + start)
fi
```

- [ ] **Step 4: Bọc phần Velociraptor (bước 10) vào nhánh reinstall + bỏ SKIP_VELOCIRAPTOR**

Thay đoạn `SKIP_VELOCIRAPTOR="${SKIP_VELOCIRAPTOR:-0}" ... else ... fi` bằng:

```bash
if [[ $VR_INSTALLED -eq 1 && $FORCE_REINSTALL -eq 0 ]]; then
    log_step "Velociraptor Client đã cài → chỉ update client.config.yaml + restart (KHÔNG tải package)."
    VR_CFG_URL="$PORTAL_URL/download/velociraptor-client.config.yaml"
    if curl -fsSL --max-time 30 "$VR_CFG_URL" -o /etc/velociraptor/client.config.yaml 2>/dev/null; then
        chmod 0640 /etc/velociraptor/client.config.yaml 2>/dev/null || true
        log_ok "Đã cập nhật /etc/velociraptor/client.config.yaml"
    else
        log_warn "Không tải được client.config.yaml ($VR_CFG_URL)."
    fi
    systemctl restart velociraptor_client 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet velociraptor_client; then
        log_ok "Service velociraptor_client đang chạy (config mới)"
    else
        log_warn "velociraptor_client start fail — xem: journalctl -u velociraptor_client -n 50"
    fi
else
    if [[ $FORCE_REINSTALL -eq 1 ]]; then
        log_warn "--force: cài đè Velociraptor (remove + reinstall)"
        systemctl stop velociraptor_client 2>/dev/null || true
        if command -v dpkg >/dev/null 2>&1 && dpkg -l velociraptor-client >/dev/null 2>&1; then
            dpkg -r velociraptor-client || true
        elif rpm -q velociraptor-client >/dev/null 2>&1; then
            rpm -e velociraptor-client || true
        fi
    fi
    # ... (giữ nguyên flow cài mới hiện tại: download + apt/dnf install + config + enable)
fi
```

- [ ] **Step 5: Sửa phần kết luận — thông báo cài đủ 2 agent + cách force**

Đổi đoạn "Agent sẽ tự enroll..." thành:

```bash
echo "Cài đặt hoàn tất — cả 2 agent đã được kiểm tra:"
echo "  • OrgInventory: systemctl status orginventory-agent"
echo "  • Velociraptor:  systemctl status velociraptor_client"
echo "Cài lại (config-only): curl -fsSL $PORTAL_URL/i/$TOKEN | sudo bash"
echo "Cài đè binary/package:  curl -fsSL $PORTAL_URL/i/$TOKEN | sudo bash -s -- --force"
```

- [ ] **Step 6: Validate template syntax — render bằng jinja2 + bash -n**

```bash
cd /home/windowsId && server/.venv/bin/python - <<'EOF'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("server/app/templates"), autoescape=False)
s = env.get_template("install.sh.j2").render(token="t_test", portal_url="https://portal.gov.vn", agent_server_url="https://agent.gov.vn")
open("/tmp/install-rendered.sh", "w").write(s)
print("rendered", len(s), "bytes")
EOF
bash -n /tmp/install-rendered.sh && echo "SYNTAX OK"
```
Expected: rendered + `SYNTAX OK`.

- [ ] **Step 7: Commit**

```bash
git add server/app/templates/install.sh.j2
git commit -m "feat(server): install.sh.j2 smart reinstall (config-only merge) + --force, bỏ SKIP_VELOCIRAPTOR"
```

---

### Task 11: Xóa `install-both.sh` + route + references

**Files:**
- Delete: `server/app/templates/install-both.sh`
- Modify: `server/app/api/routes/downloads.py` (xóa `INSTALL_BOTH_SH`, route `/install-both.sh`)
- Modify: test nếu có tham chiếu

- [ ] **Step 1: Xóa template**

```bash
git rm server/app/templates/install-both.sh
```

- [ ] **Step 2: Xóa route trong `downloads.py`**

Xóa: dòng `INSTALL_BOTH_SH = "install-both.sh"`, hàm `download_install_both_sh` (GET `/install-both.sh`), comment khối 291-296 nếu còn, import nếu chỉ dùng cho route đó.

- [ ] **Step 3: Grep còn reference nào không**

```bash
cd /home/windowsId && grep -rn "install-both.sh" server/ agent/ docs/ portal/ --include="*.py" --include="*.md" --include="*.sh" --include="*.ps1" --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v ".venv"
```
Sửa hết reference còn lại (docs, code).

- [ ] **Step 4: Chạy server tests**

Run: `cd /home/windowsId/server && .venv/bin/pytest -q 2>&1 | tail -5`
Expected: pass (hoặc xác định test cần sửa — sửa nếu test cũ gọi route install-both.sh).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(server): xóa install-both.sh + route /download/install-both.sh (install.sh.j2 là canonical)"
```

---

### Task 12: Cập nhật docs + chạy full test suite + final commit

**Files:**
- Modify: `docs/INVENTORY_V4_SCHEMA.md` (cập nhật trạng thái Linux agent + done checklist)
- Modify: `docs/superpowers/specs/2026-08-31-linux-agent-services-design.md` (đánh dấu hoàn thành nếu cần)

- [ ] **Step 1: Cập nhật `docs/INVENTORY_V4_SCHEMA.md`**

- Mục 3.1 (Linux agent): đổi "Còn thiếu (chưa cần fix ngay)" → "Đã hoàn thiện (commit ...)": services config-driven, payload envelope đầy đủ, `--once`/`--send-inventory` hoạt động, version 1.1.0.
- Mục 5 (Done Definition): tick các ô Linux agent liên quan.

- [ ] **Step 2: Chạy full test suite (agent + server)**

```bash
cd /home/windowsId/agent/linux && dotnet test OrgInventoryAgent.Linux.sln -c Release --nologo 2>&1 | tail -3
cd /home/windowsId/server && .venv/bin/pytest -q 2>&1 | tail -3
```
Expected: agent tests pass; server pytest pass.

- [ ] **Step 3: Final commit**

```bash
git add docs/
git commit -m "docs: cập nhật INVENTORY_V4_SCHEMA.md trạng thái Linux agent hoàn thiện"
```

---

## Self-Review

**Spec coverage:**
- §3.1 reuse Core → Task 1 (test usings) + toàn bộ services dùng Core types ✓
- §3.2 KeyStore Linux → Task 2 ✓
- §3.3 Linux services → Tasks 3-7 ✓
- §3.4 Program.cs + CLI + LinuxConfig compat → Task 8 ✓
- §3.5 Payload v4 đầy đủ → Task 7 (InventoryPayloadBuilder) ✓
- §3.6 Version 1.1.0 → Task 9 ✓
- §4.2 install.sh.j2 smart reinstall + merge + force → Task 10 ✓
- §4.4 Xóa install-both.sh → Task 11 ✓
- §5 Server minimal (xóa route) → Task 11 ✓
- §6 Test plan → Task 1, 2, 7, 8, 10 (bash -n), 11 (pytest), 12 ✓
- §7 Done Definition → Task 12 ✓

**Placeholder scan:** không có TBD/TODO (stub `InventoryService` ở Task 6 Step 2 được thay thật ở Task 7 Step 5 — có chỉ dẫn rõ; stub `EnrollCoordinator` Task 3 Step 4 có chỉ dẫn thay ở Task 4 Step 3). `/* TODO Task 5 */` trong Task 3 Step 4 là stub có chủ đích với chỉ dẫn thay — hợp lệ.

**Type consistency:**
- `KeyStore` ctor `(ILogger<KeyStore>)` — Task 2 define, Task 8 dùng `new KeyStore(...)` ✓
- `EnrollCoordinator` ctor — Task 4 define (8 params), Task 8 dùng đúng 8 params ✓
- `InventoryService` ctor 7 params — Task 7 define, Task 8 dùng đúng ✓
- `HeartbeatService` ctor 10 params — Task 6 define, Task 8 dùng ✓
- `RenewService` ctor 5 params — Task 3 define, Task 8 dùng ✓
- `ConfigSyncService` ctor 5 params — Task 5 define, Task 8 dùng ✓
- `LinuxPrimaryIp.Get()` — Task 4 define, Task 6 dùng ✓
- `InventoryPayloadBuilder.Build(provider, loggedUser)` — Task 7 define + test ✓
- `LinuxConfig.Load/Save(path?)` — Task 8 define + test ✓
- `AgentConfig.ApplyServerSettings(serverUrl, hb, jit, invHours, renewPct)` — Core, dùng nhất quán ✓
- `ApiClient.PostJsonAsync(path, payload, ct, useClientCert, timeoutSeconds)` — Core signature ✓
