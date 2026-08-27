# Hướng dẫn chỉnh sửa code Agent (Phase 4 — Config Sync tức thì)

> Tài liệu này dành cho dev muốn chỉnh sửa flow đồng bộ cấu hình giữa Agent ↔ Backend.
> Đọc xong bạn sẽ biết: cách agent đọc cấu hình từ server, khi nào trigger refresh, và cách
> thêm field mới mà không phá vỡ backward-compat.

## 1. Tổng quan flow đồng bộ

Agent nhận cấu hình từ server qua **3 nguồn**:

```
            ┌──────────────────────────┐
            │ GET /api/agent/config    │ ← mTLS, gọi mỗi 6h (ConfigSyncService)
            │ (đầy đủ các trường)      │
            └──────────────────────────┘
                          ↑
                          │ đồng bộ khi có agent_config_hash khác
                          │
┌────────────┐    ┌────────────────────────┐    ┌──────────────────────────┐
│ POST       │ →  │ /api/heartbeat         │ →  │ Phase 4: response trả    │
│ heartbeat  │    │ response               │    │ agent_config_hash        │
│ mỗi 30±8s  │    │ (interval/jitter/      │    │ → so sánh với state;     │
└────────────┘    │  inventory/renew/...)  │    │   khác → gọi ConfigSync  │
                  └────────────────────────┘    └──────────────────────────┘
                          ↑
            ┌──────────────────────────┐
            │ POST /api/enroll         │ ← 1 lần (sau khi cài đặt)
            │ (cấu hình ban đầu)       │
            └──────────────────────────┘
```

**Mục đích:** Admin chỉnh cấu hình trên Portal (VD: tăng `inventory_interval_hours` từ 24h
lên 48h) → agent nhận được trong vòng **~30s** (qua heartbeat) thay vì **6h** (qua ConfigSync 6h).

## 2. Cấu trúc state lưu trên agent

`agent/src/OrgInventoryAgent/Services/OfflineCache.cs` — class `AgentState`:

```csharp
public sealed class AgentState
{
    public string? LastInventoryAt { get; set; }
    public string? LastInventoryConfigHash { get; set; }

    /// <summary>Phase 4: hash SHA-256 hex của cấu hình server trả về lần cuối.
    /// HeartbeatService so sánh với `agent_config_hash` server trả về:
    /// nếu KHÁC → gọi ngay ConfigSyncService.SyncAndSaveHashAsync() để refresh;
    /// nếu khớp → heartbeat bình thường, không gọi thêm request.</summary>
    public string? LastAgentConfigHash { get; set; }
}
```

File lưu tại `%ProgramData%\OrgInventory\state.json` (Windows) hoặc
`~/.local/share/OrgInventory/state.json` (Linux dev).

## 3. Cách server tính hash

File `server/app/services/agent_settings.py`:

```python
def compute_agent_config_hash(cfg: dict) -> str:
    """SHA-256 hex của canonical JSON (sort_keys, ensure_ascii=False) của 5 trường."""
    payload = {
        "endpoints": [cfg.get("agent_server_url")],   # server chỉ biết URL chính
        "heartbeat_interval_seconds": cfg["heartbeat_interval_seconds"],
        "heartbeat_jitter_seconds": cfg["heartbeat_jitter_seconds"],
        "inventory_interval_hours": cfg["inventory_interval_hours"],
        "renew_before_percent": cfg["renew_before_percent"],
    }
    payload = {k: v for k, v in payload.items() if v is not None}  # loại None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Hash này trả về trong **2 endpoint**:
- `POST /api/heartbeat` → trường `agent_config_hash`
- `GET /api/agent/config` → trường `agent_config_hash`

## 4. Quy tắc so sánh hash (agent side)

File `agent/src/OrgInventoryAgent/Services/HeartbeatService.cs`:

```csharp
public static bool ShouldResyncConfig(string? serverHash, string? localHash)
{
    if (string.IsNullOrWhiteSpace(serverHash)) return false;  // server cũ → fallback 6h
    if (string.IsNullOrWhiteSpace(localHash)) return true;    // lần đầu → sync
    return !string.Equals(serverHash, localHash, StringComparison.OrdinalIgnoreCase);
}
```

| `serverHash` | `localHash` | `ShouldResync` | Hành động |
|---|---|---|---|
| null/"" | (bất kỳ) | false | server cũ → đợi ConfigSync 6h |
| (bất kỳ) | null/"" | true | lần đầu gặp → sync |
| "abc" | "abc" | false | khớp → heartbeat bình thường |
| "abc" | "xyz" | true | admin đổi config → sync ngay |

## 5. Cách thêm field cấu hình mới

Ví dụ: muốn thêm `log_level` vào config agent.

### Bước 1: Thêm trường vào schema server

```python
# server/app/schemas/__init__.py
class AgentConfigResponse(BaseModel):
    server_url: str
    heartbeat_interval_seconds: int
    heartbeat_jitter_seconds: int
    online_ttl_seconds: int
    inventory_interval_hours: int
    renew_before_percent: int
    server_time: datetime
    agent_config_hash: str | None = None
    log_level: str | None = None  # ← MỚI
```

### Bước 2: Cập nhật `effective_agent_config()` (server)

```python
# server/app/services/agent_settings.py
async def effective_agent_config(db: AsyncSession) -> dict:
    cfg = settings.agent_config_payload()
    ov = await get_override(db)
    # ... giữ logic cũ ...
    payload["log_level"] = (
        ov.log_level if ov is not None and ov.log_level else settings.log_level
    )
    return payload
```

### Bước 3: Cập nhật `compute_agent_config_hash()` — QUAN TRỌNG

```python
# server/app/services/agent_settings.py
def compute_agent_config_hash(cfg: dict) -> str:
    payload = {
        "endpoints": [cfg.get("agent_server_url")],
        "heartbeat_interval_seconds": cfg["heartbeat_interval_seconds"],
        "heartbeat_jitter_seconds": cfg["heartbeat_jitter_seconds"],
        "inventory_interval_hours": cfg["inventory_interval_hours"],
        "renew_before_percent": cfg["renew_before_percent"],
        "log_level": cfg.get("log_level"),  # ← THÊM VÀO HASH
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**KHÔNG thêm trường mới vào hash** nếu:
- Trường đó là secret (token, password) — không muốn lộ qua debug log
- Trường đó không ảnh hưởng hành vi agent (vd: `server_time` chỉ là thông tin, không điều khiển)

### Bước 4: Thêm trường vào `AgentConfig` (agent)

```csharp
// agent/src/OrgInventoryAgent/AgentConfig.cs
public sealed class AgentConfig
{
    // ... các trường cũ ...
    public string LogLevel { get; set; } = "Information";  // ← MỚI

    public bool ApplyServerSettings(string? serverUrl, int? heartbeatIntervalSec,
        int? heartbeatJitterSec, int? inventoryIntervalHours, int? renewBeforePercent,
        string? logLevel = null)  // ← MỚI (optional, default null = không đổi)
    {
        bool changed = false;
        // ... logic cũ ...
        if (!string.IsNullOrWhiteSpace(logLevel) && LogLevel != logLevel)
        {
            LogLevel = logLevel;
            changed = true;
        }
        Normalize();
        return changed;
    }
}
```

### Bước 5: Thêm vào `ConfigSyncService.SyncAsync` và `SyncAndSaveHashAsync`

```csharp
// agent/src/OrgInventoryAgent/Services/ConfigSyncService.cs
public async Task<bool> SyncAsync(CancellationToken ct)
{
    // ... đoạn đầu giữ nguyên ...
    var logLevel = body["log_level"]?.GetValue<string>();  // ← MỚI
    var changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct, logLevel);
    // ...
}
```

### Bước 6: Thêm vào heartbeat response (server) — optional

Nếu muốn agent nhận field mới qua heartbeat (không cần đợi 6h):

```python
# server/app/api/routes/heartbeat.py
return HeartbeatResponse(
    # ... các trường cũ ...
    log_level=agent_cfg.get("log_level"),  # ← MỚI
)
```

Và agent đọc:

```csharp
// agent/src/OrgInventoryAgent/Services/HeartbeatService.cs - SendHeartbeatAsync
var logLevel = body?["log_level"]?.GetValue<string>();
bool changed = _config.ApplyServerSettings(serverUrl, interval, jitter, invHours, renewPct, logLevel);
```

### Bước 7: Tests

Server:
```python
# server/tests/test_agent_config.py
async def test_heartbeat_returns_log_level(client, seeded_env):
    """Heartbeat trả log_level để agent đồng bộ nhanh qua heartbeat (~30s)."""
    mid, _ = await _enroll_machine(client, seeded_env)
    r = await client.post("/api/heartbeat", json={"logged_user": "u"}, headers={"X-SSL-Client-CN": mid})
    assert r.json().get("log_level") == "Information"

async def test_compute_agent_config_hash_includes_log_level():
    cfg = {"agent_server_url": "http://x", "heartbeat_interval_seconds": 30,
           "heartbeat_jitter_seconds": 8, "inventory_interval_hours": 24,
           "renew_before_percent": 70, "log_level": "Debug"}
    h1 = compute_agent_config_hash(cfg)
    cfg2 = dict(cfg, log_level="Warning")
    h2 = compute_agent_config_hash(cfg2)
    assert h1 != h2
```

Agent:
```csharp
// agent/tests/OrgInventoryAgent.Tests/HeartbeatConfigSyncTests.cs
[Theory]
[InlineData("hash_v1", "hash_v2", true)]   // log_level đổi → sync
[InlineData("hash_v1", "hash_v1", false)]  // không đổi → bình thường
public void ShouldResyncConfig_AfterLogLevelChange(string server, string local, bool expected)
{
    Assert.Equal(expected, HeartbeatService.ShouldResyncConfig(server, local));
}
```

## 6. Lưu ý quan trọng

### 6.1. KHÔNG thêm field không cần đồng bộ

Nếu field chỉ mang tính thông tin (không điều khiển hành vi agent), KHÔNG thêm vào hash.
Lý do: hash thay đổi → trigger ConfigSync không cần thiết → tốn request + CPU.

Ví dụ KHÔNG thêm:
- `server_time` (chỉ để sync clock, không điều khiển)
- `notice_version` (chỉ hiển thị, không điều khiển)
- `version`, `issued_at` (metadata envelope, không điều khiển)

### 6.2. KHÔNG thêm secret vào hash

Hash được log ở log level Information:
```csharp
_logger.LogInformation("Server báo hash cấu hình thay đổi ({Old} → {New})...", ...);
```
→ KHÔNG đưa token, password, secret vào hash.

### 6.3. Backward compatibility

- Agent cũ KHÔNG đọc `agent_config_hash` → fallback ConfigSync 6h (vẫn chạy đúng).
- Server cũ KHÔNG trả `agent_config_hash` → agent nhận null → fallback ConfigSync 6h.
- Thêm field mới vào `AgentConfigResponse` (server) → không phá client cũ (extra fields OK).

### 6.4. Canonical JSON phải khớp giữa C# và Python

- **Python**: `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
- **C#**: `JsonSerializer.Serialize(node)` với `JavaScriptEncoder.UnsafeRelaxedJsonEscaping` (không escape Unicode)
- **Test consistency**: `server/tests/test_config_hash_consistency.py` đảm bảo `_config_hash()` khớp với client tính tay.

## 7. Debug

Bật log debug để xem hash flow:

```json
{
  "Logging": {
    "LogLevel": {
      "OrgInventoryAgent.Services.HeartbeatService": "Debug"
    }
  }
}
```

Sẽ thấy:
```
[Debug] Hash cấu hình khớp (a1b2c3d4...) → heartbeat bình thường.
```
hoặc:
```
[Information] Server báo hash cấu hình thay đổi (xyz789 → abc123) → gọi ConfigSync để refresh.
[Information] Đã refresh cấu hình từ server và cập nhật LastAgentConfigHash=abc123
```

## 8. File liên quan

| File | Vai trò |
|---|---|
| `server/app/services/agent_settings.py` | `compute_agent_config_hash()` + `effective_agent_config()` |
| `server/app/api/routes/heartbeat.py` | Trả `agent_config_hash` + `renew_before_percent` trong heartbeat |
| `server/app/api/routes/agent_config.py` | Trả `agent_config_hash` trong GET /api/agent/config |
| `server/app/schemas/__init__.py` | `AgentConfigResponse`, `HeartbeatResponse` |
| `agent/src/OrgInventoryAgent/Services/HeartbeatService.cs` | `ShouldResyncConfig()`, áp dụng trong `SendHeartbeatAsync` |
| `agent/src/OrgInventoryAgent/Services/ConfigSyncService.cs` | `SyncAsync()`, `SyncAndSaveHashAsync()` |
| `agent/src/OrgInventoryAgent/Services/OfflineCache.cs` | `AgentState.LastAgentConfigHash` |
| `agent/src/OrgInventoryAgent/AgentConfig.cs` | `ApplyServerSettings()` |
| `server/tests/test_agent_config.py` | Test heartbeat + config + hash |
| `server/tests/test_config_hash_consistency.py` | Test hash server khớp với client |
| `agent/tests/.../HeartbeatConfigSyncTests.cs` | Test `ShouldResyncConfig` + `AgentState` |
| `docs/API_CONTRACT.md` (mục 3.2, 3.6) | Mô tả response |