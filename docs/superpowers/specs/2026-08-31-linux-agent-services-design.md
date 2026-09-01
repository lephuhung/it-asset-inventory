# Linux Agent Services — Hoàn thiện agent Linux + Install 2-agent + Reinstall

> **Dự án:** IT Asset Inventory (Hệ thống Quản lý Tài sản CNTT & ATTT)
> **Nhánh:** `feature/linux-agent`
> **Ngày:** 2026-08-31
> **Trạng thái:** Chờ review spec
> **Kế thừa:** `docs/superpowers/specs/2026-08-30-linux-agent-design.md` (thiết kế nền), `docs/INVENTORY_V4_SCHEMA.md` (checklist payload v4)

---

## 1. Mục tiêu

Hoàn thiện Linux agent theo 3 trục:

1. **Thu thập đủ dữ liệu schema v4** — payload inventory gửi lên server phải là **envelope v4 đầy đủ** (`agent` + `os` + `security` + flat fields), không còn hard-code rời rạc.
2. **Config-driven loop** — agent chạy nền (systemd), gửi **heartbeat + inventory định kỳ** theo chu kỳ lấy từ **config tải từ server** (enroll response / heartbeat response / `GET /api/agent/config`), mirror agent Windows.
3. **Install 2-agent hoàn chỉnh + xử lý reinstall** — cài bắt buộc đủ OrgInventory + Velociraptor; khi cài lại (đã có sẵn 2 agent) **chỉ thay file config** + restart service, **không** xóa/cài đè binary/package.

---

## 2. Hiện trạng

### 2.1. Linux agent (`agent/linux`) — stub, chưa có services

| Thành phần | Hiện trạng |
|---|---|
| `LinuxInventoryProvider.Collect()` | ✅ Build envelope v4 (`agent`, `os`, `security`) |
| `LinuxInventoryProvider.CollectSnapshot()` | ✅ Flat snapshot (CPU/RAM/disk/network/software...) |
| `Program.cs` | ❌ Stub: enroll+heartbeat 1 lần, `--send-inventory` 1 lần, rồi sleep vô hạn |
| Vòng lặp định kỳ | ❌ Không có (comment "Phase 3 sẽ thay thế") |
| Arg parsing | ❌ Chỉ parse `--data-dir` (args[0]), `--print-inventory`, `--send-inventory` (IndexOf). **Không parse** `--config`, `--enroll-token`, `--endpoint`, `--once` |
| Payload `SendInventoryOnceAsync` | ❌ Hard-code object `agent`/`os` rời rạc: thiếu `name`, `runtime`, `architecture`, `kernel_version`; hard-code `package_type="deb"` (sai trên RHEL) |
| Config read | ❌ Đọc tay `/etc/orginventory/config.json` (key `enroll_token`, `endpoints`) — không dùng `AgentConfig` |
| Build | ⚠️ Solution **build FAIL** — test scaffold tham chiếu namespace `OrgInventoryAgent.Linux.{Net,Crypto,Services}` chưa tồn tại (7 lỗi) |

### 2.2. Core (`agent/src/OrgInventoryAgent.Core`) — đã có sẵn, tái dùng

| Type | Namespace | Ghi chú |
|---|---|---|
| `AgentConfig` | `OrgInventoryAgent.Core` | Config-driven, `Normalize()` clamp, `ApplyServerSettings()`, `ComputeConfigHash()`, `Save()`. JSON camelCase |
| `AgentState` | `OrgInventoryAgent.Core.Services` | `LastInventoryAt`, `LastInventoryConfigHash`, `LastAgentConfigHash` |
| `EndpointManager` | `OrgInventoryAgent.Core.Net` | Failover sau 5 lỗi liên tiếp, `BuildUrl(path)` |
| `ApiClient` | `OrgInventoryAgent.Core.Net` | mTLS, `GetJsonAsync`/`PostJsonAsync`, `useClientCert` |
| `EnrollClient` | `OrgInventoryAgent.Core.Net` | Gọi `/api/enroll` |
| `OfflineCache` | `OrgInventoryAgent.Core.Services` | SQLite cache, dedupe, `MaxAttempts=10` |
| `CsrGenerator` | `OrgInventoryAgent.Core.Crypto` | `CreateKeyPair()` (ECDSA P-256), `CreateCsrPem(key, cn)` |
| `LinuxKeyStore` | `OrgInventoryAgent.Core.Crypto` | PEM files theo machineId — **API khác** với KeyStore test mong đợi |
| `IKeyStore` | `OrgInventoryAgent.Core.Crypto` | 2 contract: mới (machineId) + cũ (config-based) |
| `AppPaths` | `OrgInventoryAgent.Core` | `ConfigFile`, `StateFile`, `CertFile`, `KeyFile`, `LogsDir` |

### 2.3. Windows agent (`agent/src/OrgInventoryAgent`) — pattern để mirror

Generic Host + 5 BackgroundServices (DI via `RegisterServices`):

| Service | Chu kỳ | Nguồn chu kỳ |
|---|---|---|
| `EnrollCoordinator` | enroll khi chưa có cert | — |
| `HeartbeatService` | `heartbeat_interval_seconds ± jitter` (mặc định 30±8s) | config từ heartbeat response; `agent_config_hash` khác → gọi config sync ngay |
| `InventoryService` | khi due: sau enroll / config hash đổi / mỗi `inventory_interval_hours` (24h) / rescan_requested; fail → offline cache | config |
| `ConfigSyncService` | `GET /api/agent/config` mỗi 6h | server |
| `RenewService` | kiểm tra 6h + lúc khởi động; renew khi cert < `renew_before_percent` (70%) | config |

### 2.4. Test scaffold Linux (TDD contract)

Các test đã commit định nghĩa API mong đợi — một số **trùng API Core**, một số **Linux-specific**:

| Test file | Mong đợi | Type thực tế |
|---|---|---|
| `AgentConfigTests.cs` | `AgentConfig` (resolve từ Core qua project ref) | ✅ Core |
| `EndpointManagerTests.cs` | `OrgInventoryAgent.Linux.Net.EndpointManager` | Core có `OrgInventoryAgent.Core.Net.EndpointManager` (API trùng) |
| `MtlsAndKeyStoreTests.cs` | `OrgInventoryAgent.Linux.Crypto.KeyStore` — ctor `(ILogger<KeyStore>)`, `InstallCertificate(certPem, key, config)`, `FindClientCertificate(config)`, `ReplaceCertificate(...)`; `OrgInventoryAgent.Linux.Crypto.CsrGenerator` | Core `LinuxKeyStore` API **khác** (machineId-based) |
| `OfflineCacheTests.cs` | `OrgInventoryAgent.Linux.Services.OfflineCache` | Core có `OrgInventoryAgent.Core.Services.OfflineCache` (API trùng) |
| `RenewServiceTests.cs` | `OrgInventoryAgent.Linux.Services.RenewService.RemainingLifePercent(cert, now)` static | ❌ Chưa có (Windows có `OrgInventoryAgent.Services.RenewService`) |

### 2.5. Install scripts

| Script | Hiện trạng |
|---|---|
| `server/app/templates/install.sh.j2` | ⚠️ Chạy được nhưng: luôn tải lại binary (~60MB) + package VR (~100MB) dù đã cài; có flag `SKIP_VELOCIRAPTOR` (trái yêu cầu "bắt buộc đủ 2 agent"); **không xử lý reinstall smart**; unit file có `--config /etc/orginventory/config.json` nhưng agent **không parse** `--config` |
| `server/app/templates/install-both.sh` | ❌ **Broken**: `local` ở top-level (3 chỗ) → chết với `set -e`; `vr_use_config_only` unbound (`set -u`); 2 flags ghi trong usage nhưng không parse; không ghi `/etc/orginventory/config.json` → enroll fail |
| `agent/installer/linux/install-online.sh` | Standalone installer (chỉ OrgInventory, tải .deb/.rpm có SHA256) — giữ nguyên |
| `server/app/templates/install.ps1.j2` + `install-both.ps1` | Windows — ngoài phạm vi |

### 2.6. Server (đã đủ cho Linux services)

- `POST /api/enroll` → `machine_id`, `client_cert_pem`, `renew_after`, `heartbeat_interval_seconds`, `inventory_interval_hours`
- `POST /api/heartbeat` → `heartbeat_interval_seconds`, `heartbeat_jitter_seconds`, `server_url`, `inventory_interval_hours`, `renew_before_percent`, `agent_config_hash`, `rescan_requested`
- `GET /api/agent/config` → `server_url`, `heartbeat_interval_seconds`, `heartbeat_jitter_seconds`, `inventory_interval_hours`, `renew_before_percent`, `agent_config_hash`
- `GET /download/install-both.sh` → serve template (sẽ xóa)

---

## 3. Quyết định kiến trúc

### 3.1. Tái dùng Core — không duplication

Linux project **đã reference Core** (`OrgInventoryAgent.Core.csproj`). Toàn bộ hạ tầng dùng chung lấy từ Core:

- `AgentConfig`, `AgentState`, `EndpointManager`, `ApiClient`, `EnrollClient`, `OfflineCache`, `CsrGenerator`, `AppPaths`.

**Sửa test scaffold** (test là của chúng ta, đã commit): đổi `using` sang Core namespaces cho các type Core đã có với đúng API:

| Test | Sửa |
|---|---|
| `EndpointManagerTests.cs` | `using OrgInventoryAgent.Linux.Net;` → `using OrgInventoryAgent.Core.Net;` |
| `OfflineCacheTests.cs` | `using OrgInventoryAgent.Linux.Services;` → `using OrgInventoryAgent.Core.Services;` |
| `MtlsAndKeyStoreTests.cs` | `using OrgInventoryAgent.Linux.Crypto;` → giữ nếu tạo KeyStore Linux; `CsrGenerator` dùng Core |

### 3.2. KeyStore Linux — tạo mới (mirror Windows, PEM-backed)

Test mong đợi **config-based KeyStore** (giống Windows `KeyStore`), không phải Core's `LinuxKeyStore` (machineId-based):

```csharp
// OrgInventoryAgent.Linux.Crypto
public sealed class KeyStore : IKeyStore
{
    public KeyStore(ILogger<KeyStore> logger);
    // config-based (mirror Windows, PEM files tại AppPaths.CertFile/KeyFile)
    public bool HasClientCertificate(AgentConfig config);
    public X509Certificate2? FindClientCertificate(AgentConfig config);
    public void InstallCertificate(string certPem, ECDsa key, AgentConfig config); // set ClientCertThumbprint, CertStoreLocation="File"
    public void ReplaceCertificate(string certPem, ECDsa newKey, AgentConfig config);
    // IKeyStore contract mới (machineId-based) — cần cho compatibility
    public bool HasPrivateKey(string machineId);
    public string? GetPrivateKeyPem(string machineId);
    public string? GetCertificatePem(string machineId);
    public void InstallCertificate(string machineId, string certPem, string? keyPem);
    public void DeleteCertificate(string machineId);
}
```

- PEM file mode: cert `0644`, key `0600` (đúng test `KeyStore_PemFilesHaveRestrictedPermissions_OnLinux` dùng `AppPaths.KeyFile`).
- `AgentConfig.CertStoreLocation = "File"` (test assert).
- Giữ Core's `LinuxKeyStore` nguyên vẹn (đang được dùng bởi Program.cs cũ — sẽ thay bằng KeyStore mới trong services).

### 3.3. Linux services — mirror Windows, đặt trong `OrgInventoryAgent.Linux.Services`

Generic Host + DI, mirror đúng `RegisterServices` của Windows nhưng dùng `KeyStore` Linux:

```
OrgInventoryAgent.Linux.Services/
├── EnrollCoordinator.cs      # enroll idempotent (đã enroll → bỏ qua); token từ config; CSR ECDSA P-256
├── HeartbeatService.cs       # loop interval±jitter; áp config từ response; agent_config_hash ≠ → ConfigSyncService; flush offline cache
├── InventoryService.cs       # gửi payload v4 đầy đủ khi due; offline cache khi fail; TriggerRescan()
├── ConfigSyncService.cs      # GET /api/agent/config mỗi 6h; SyncAsync + SyncAndSaveHashAsync
└── RenewService.cs           # static RemainingLifePercent(cert, now); loop 6h; renew < 70% → POST /api/renew
```

`OrgInventoryAgent.Linux.Net` — **không tạo** (dùng Core `EndpointManager` trực tiếp; sửa test).

### 3.4. Program.cs — Generic Host + CLI

- `--data-dir <path>`, `--config <path>` (mặc định `/etc/orginventory/config.json` trên production — mirror unit file install.sh.j2), `--enroll-token <token>`, `--endpoint <url>`, `--once` (enroll→heartbeat→inventory 1 lần rồi exit — smoke test install), `--send-inventory` (alias của once cho inventory), `--print-inventory`, `--print-config`, `--version`, `--help`.
- `AgentConfig.Load(configPath)` — **cần xử lý tương thích key cũ** `enroll_token` (install script đang ghi) vs camelCase `token` (AgentConfig). **Quyết định:** thêm bước migrate — khi load, nếu JSON có `enroll_token` mà `Token` null → gán `Token`. Không sửa AgentConfig Core (tránh ảnh hưởng Windows). Thực hiện trong Linux `Program.cs` hoặc 1 helper nhỏ `LinuxConfig.Load()`.
- Service mode (mặc định): `Host.CreateApplicationBuilder` + register services + `AddHostedService` × 4 (Heartbeat, Inventory, ConfigSync, Renew) — EnrollCoordinator không phải HostedService (Windows cũng vậy), gọi fire-and-forget lúc startup + services tự retry.
- Giữ `--print-inventory`/`--print-security`/`--about` (đã có ở Windows).

### 3.5. Payload inventory v4 — dùng envelope thay vì hard-code

`InventoryService` build payload:

```csharp
var envelope = provider.Collect();        // agent + os + security (đầy đủ)
var snapshot = provider.CollectSnapshot(); // flat fields
// Merge: flat fields (os_name, cpu, ram_gb, disks, ...) + envelope (agent, os, security) + inventory_schema_version = 4
```

- `agent` → từ `envelope.Agent` (name, version, runtime, platform, architecture, **package_type detect deb/rpm** — không hard-code).
- `os` → từ `envelope.Os` (platform, distribution, distribution_version, **kernel_version**, architecture, subscription).
- Bỏ object anonymous hard-code trong `SendInventoryOnceAsync` cũ.

### 3.6. Version

- Bump `OrgInventoryAgent.Linux.csproj`: `<Version>1.1.0</Version>` (+ AssemblyVersion/FileVersion) — khớp schema doc.

---

## 4. Install command — `install.sh.j2` canonical + smart reinstall

### 4.1. Nguyên tắc (theo yêu cầu user)

> Cài đặt bắt buộc đủ 2 agent. Khi cài lại: **chỉ thay file config**, không xóa, không cài đè binary/package.

### 4.2. Flow mới trong `install.sh.j2`

> `install.sh.j2` là **canonical** — one-liner `curl -fsSL <portal>/i/<token> | sudo bash` render template này và **đã cài đủ 2 agent trong 1 lần** (OrgInventory bước 1–9 + Velociraptor bước 10 mặc định bật). Do đó xóa `install-both.sh` (mục 4.4) **không mất khả năng cài 2 agent cùng lúc**.

```
Bước 1 — Detect trạng thái:
  OI_INSTALLED = binary /opt/orginventory/OrgInventoryAgent tồn tại
                 AND service orginventory-agent tồn tại
  VR_INSTALLED = package velociraptor-client (dpkg/rpm) tồn tại
                 AND service velociraptor_client tồn tại
  FORCE_REINSTALL = 0 (mặc định); bật khi user truyền `--force` (hoặc env
                    INSTALL_FORCE=1) → buộc cài đè binary/package dù đã có

Bước 2 — OrgInventory:
  NẾU OI_INSTALLED VÀ KHÔNG force:
      KHÔNG tải binary, KHÔNG tạo lại user/unit (idempotent)
      Chỉ: MERGE /etc/orginventory/config.json — giữ nguyên identity (enrolled,
        machineId, clientCertThumbprint, certStoreLocation, các interval đã sync),
        chỉ cập nhật `endpoints` (+ ghi `enroll_token` mới nếu admin cung cấp).
        chmod 0640, chown root:orginventory
        systemctl restart orginventory-agent
      → Binary cũ vẫn chạy; agent thấy token mới nhưng ĐÃ enroll (enrolled=true,
        cert + machine_id còn trong config/state) → bỏ qua enroll, heartbeat/inventory
        tiếp tục bằng identity cũ. KHÔNG tạo máy trùng.

      ⚠️ KHÔNG được "ghi đè toàn bộ" config: AgentConfig.Load() mặc định `Enrolled=false`
      → ghi đè sẽ khiến agent re-enroll và tạo machine trùng. Merge bằng python3
      (có sẵn trên Ubuntu/RHEL): đọc JSON cũ → chỉ thay `endpoints` (+`enroll_token`)
      → giữ mọi field khác → ghi lại. Fallback jq nếu không có python3; nếu cả 2 đều
      không có → cảnh báo + ghi đè (chấp nhận re-enroll).
  NẾU CHƯA CÀI HOẶC force:
      Flow cài mới như hiện tại (download + SHA256 + systemd units + config)
      (force: stop service → thay binary mới → restart)

Bước 3 — Velociraptor:
  NẾU VR_INSTALLED VÀ KHÔNG force:
      KHÔNG tải package (~100MB), KHÔNG dpkg/dnf reinstall
      Chỉ: cập nhật /etc/velociraptor/client.config.yaml
            chmod 0640
            systemctl restart velociraptor_client
  NẾU CHƯA CÀI HOẶC force:
      Flow cài mới như hiện tại
      (force: stop service → remove package cũ → cài lại → update config)

Bước 4 — Bắt buộc đủ 2:
  BỎ flag SKIP_VELOCIRAPTOR (trái nguyên tắc "bắt buộc đủ 2 agent")
  Nếu 1 trong 2 fail → exit 1, log rõ agent nào fail

Cách dùng (1 lệnh):
  curl -fsSL <portal>/i/<token> | sudo bash            # cài mới / reinstall config-only
  curl -fsSL <portal>/i/<token> | sudo bash -s -- --force  # buộc cài đè binary/package
  curl -fsSL <portal>/i/<token> | sudo INSTALL_FORCE=1 bash  # tương đương --force
```

### 4.3. Edge cases reinstall

| Tình huống | Xử lý |
|---|---|
| Cả 2 đã cài, chạy lại script | Chỉ update 2 config files + restart. Không download. |
| Cả 2 đã cài, chạy lại với `--force` | Cài đè binary/package + merge config + restart (dùng khi binary/package hư) |
| OI cài rồi, VR chưa | Update config OI + cài mới VR |
| VR cài rồi, OI chưa | Cài mới OI + update config VR |
| OI đã enroll cũ (config có enrolled=true + cert còn) | Merge config giữ `enrolled`/`machineId`/`clientCertThumbprint`; token mới trong config **không kích hoạt re-enroll** (cert + machine_id còn → `IsEnrolled` true). Máy giữ identity. |
| Server DB bị xóa / machine_id lạ | Heartbeat 401/404 → agent tự re-enroll? (Cần kiểm tra behavior Windows EnrollCoordinator — mặc định: nếu cert còn, không re-enroll; để plan xác nhận, không thay đổi hành vi hiện tại) |

### 4.4. `install-both.sh` — XÓA

- Lý do: broken (3 lỗi bash), trùng 100% chức năng với `install.sh.j2` sau khi hoàn thiện.
- `install.sh.j2` **đã đảm bảo cài đủ 2 agent trong 1 lệnh** (OrgInventory + Velociraptor, mục 4.2) + smart reinstall (config-only, `--force` để cài đè) → không mất khả năng sau khi xóa.
- Xóa: `server/app/templates/install-both.sh`, route `GET /download/install-both.sh` trong `downloads.py`, references trong docs/code.

---

## 5. Server — thay đổi tối thiểu

- Không đổi API (enroll/heartbeat/agent/config đã đủ field).
- `downloads.py`: xóa route + template `install-both.sh` (mục 4.4).
- `tokens.py`: `_install_command_linux` giữ nguyên (`curl -fsSL {portal}/i/{token} | sudo bash`) — install.sh.j2 đã cài cả 2 + smart reinstall.
- Kiểm tra `_validate_install_urls` không liên quan.

---

## 6. Test plan

### 6.1. Agent unit tests (TDD scaffold là contract)

```
cd agent/linux && dotnet build OrgInventoryAgent.Linux.sln -c Release   # phải build xanh
cd agent/linux && dotnet test OrgInventoryAgent.Linux.sln -c Release    # tất cả pass
```

Sửa test scaffold (mục 3.1) + thêm test mới cho:
- `KeyStore` Linux: install/find/replace, PEM 0600/0644, thumbprint, `CertStoreLocation="File"`
- `RenewService.RemainingLifePercent`: ~70%, hết hạn → 0
- `AgentConfig` compat `enroll_token` → `Token`
- Inventory payload builder: envelope đầy đủ (agent có architecture/package_type đúng theo distro)
- CLI parser: `--config`, `--once`, `--enroll-token`, `--endpoint`

### 6.2. Install script test

- Render `install.sh.j2` (jinja2) với token/URL giả → `bash -n` (syntax OK) → kiểm tra bằng shellcheck nếu có.
- Test logic reinstall trong container/máy thật `AI` (Ubuntu 24.04):
  1. Cài lần 1 → cả 2 service active
  2. Chạy lại script → chỉ update config, không re-download (log "đã cài → update config")
  3. Chạy lại với `--force` → cài đè binary/package mới + config merge + restart
  4. Verify config sau merge: `enrolled`/`machineId`/`clientCertThumbprint` còn nguyên (không re-enroll)

### 6.3. Server tests

```
cd server && .venv/bin/pytest -q   # giữ xanh (sau khi xóa install-both.sh route)
```

---

## 7. Done Definition

- [x] `dotnet build` + `dotnet test` solution `agent/linux` xanh (test scaffold sửa + mới) — 27/27 passed
- [x] Linux agent chạy service mode: heartbeat ± jitter, inventory 24h (hoặc interval server trả), config sync 6h, renew <70%
- [x] Payload inventory: envelope v4 đầy đủ (agent.name/runtime/architecture/package_type đúng; os.kernel_version) — verify DB query trên máy `AI`
- [x] `install.sh.j2`: cài mới đủ 2 agent; reinstall chỉ merge config + restart; bỏ `SKIP_VELOCIRAPTOR`; hỗ trợ `--force` cài đè
- [x] `install-both.sh` + route `/download/install-both.sh` đã xóa; không còn reference
- [ ] `server/.venv/bin/pytest -q` xanh — chưa đạt: 15 failed / 164 passed, toàn bộ là pre-existing (velociraptor cần live server, ws Redis, agent_config portal_url, api full_enroll, phase2, sweep_lost/timeline ordering) — verify tại base commit 56671b8
- [x] `INVENTORY_V4_SCHEMA.md` cập nhật trạng thái (Linux agent hoàn thiện, done checklist) — Task 12
- [x] **Deploy thật trên máy AI (10.10.0.240)**: agent v1.1.0 cài + service active; DB verify `platform=linux`, `agent_version=1.1.0`, `inventory_schema_version=4`, `agent.package_type=deb`, `os.distribution=ubuntu 24.04`, `os.kernel_version=6.8.0-138-generic` (commit 988d5ff)
- [ ] Commit trên nhánh `feature/linux-agent` — controller commit sau review (Task 12)

**Bug phát hiện khi deploy thật (đã fix + commit):**
- DI `IKeyStore` không register → service mode crash `Unable to resolve IKeyStore` (fix `82a5d4f`; binary phải rebuild lại sau fix — binary publish trước đó chứa bug).
- `LinuxConfig.Load` không merge identity từ state file (`{data-dir}/config.json`) → restart mất `enrolled/machineId/thumbprint` → re-enroll với token đã dùng → 401 loop (fix `988d5ff`; test merge mới; verified 2 lần restart giữ identity).
- SQLite cache lỗi khi thiếu `libe_sqlite3.so` cạnh binary (single-file + `IncludeNativeLibrariesForSelfExtract=false`) → phải copy lib vào `/opt/orginventory/` cùng binary.

---

## 8. Liên quan

- Spec nền: `docs/superpowers/specs/2026-08-30-linux-agent-design.md`
- Checklist: `docs/INVENTORY_V4_SCHEMA.md`
- Pattern Windows: `agent/src/OrgInventoryAgent/Program.cs` (RegisterServices), `agent/src/OrgInventoryAgent/Services/*.cs`
- Core: `agent/src/OrgInventoryAgent.Core/` (AgentConfig, Net/, Services/, Crypto/)
- Install template: `server/app/templates/install.sh.j2`, `server/app/templates/install-both.sh` (xóa)
- Server routes: `server/app/api/routes/{enroll,heartbeat,agent_settings,downloads,tokens,install}.py`
