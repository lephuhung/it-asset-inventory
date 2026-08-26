# OrgInventory Agent (Phase 1 MVP)

Agent Windows (.NET 8, C#) cho hệ thống IT Asset Inventory. Khớp **API thực tế của server**
(`/home/windowsId/server/`, verify 67/67 test) theo `docs/API_CONTRACT.md` v1.3.

## Tính năng Phase 1

- **Enroll** (`POST /api/enroll`, không mTLS): token + fingerprint 3 nguồn + CSR ECDSA P-256
  → server trả `machine_id` + client cert + cấu hình (endpoint/interval/jitter/inventory interval).
- **Heartbeat** (`POST /api/heartbeat`, mTLS): chu kỳ ngẫu nhiên `[interval−jitter, interval+jitter]`
  (mặc định **30±8s ≈ 22–38s**); đồng bộ interval/jitter/renew_after từ response; `rescan_requested`
  → chạy inventory ngay.
- **Inventory** (`POST /api/inventory`, mTLS): OS/CPU/RAM/disk/GPU/mainboard/BIOS/network/logged_user/
  software/security/is_vm + `config_hash`; gửi lần đầu, khi config_hash đổi, định kỳ 24h, khi rescan.
- **Renew** (`POST /api/renew`, mTLS): kiểm tra mỗi 6h — cert còn < `renew_before_percent` (70%)
  → CSR mới (CN=`machine-<machine_id>`) → thay cert trong store.
- **Config sync** (`GET /api/agent/config`, mTLS): mỗi 6h đồng bộ server_url/interval/jitter/
  inventory interval/renew threshold — **binary không đổi, hành vi do server điều chỉnh**.
- **Fingerprint đa nguồn**: SMBIOS UUID (thô), MachineGuid + mainboard serial (SHA-256 hex) — gửi
  3 nguồn riêng, server tính hash có trọng số. Nguồn thiếu → null (không crash).
- **mTLS**: client cert (CN=`machine-<uuid>`) cài vào Windows Certificate Store
  (LocalMachine\My, fallback CurrentUser\My); **private key không bao giờ rời máy**.
  Trên Linux dev: PEM file trong data dir.
- **Offline cache**: SQLite `cache.db` — gửi thất bại → lưu; flush khi có mạng (giữ nguyên body),
  dedupe theo (url, body_hash), cap 10 lần thử.
- **Failover endpoint**: primary lỗi 5 lần liên tiếp → backup; thử lại primary mỗi 10 chu kỳ.
- **Idempotent install**: cert + machine_id còn trong config → bỏ qua enroll, chỉ repair/update.
- **Chống AV**: metadata assembly đầy đủ (Company/Product/Description/Copyright/Icon), User-Agent
  rõ ràng `OrgInventoryAgent/1.0.0`, heartbeat jitter, gzip > 8KB, zero-GUI, read-only WMI/Registry.

## Cấu trúc

```
agent/
├── OrgInventoryAgent.sln
├── src/OrgInventoryAgent/
│   ├── OrgInventoryAgent.csproj     # net8.0 (build được trên Linux), packages: System.Management,
│   │                                #   Microsoft.Win32.Registry, Microsoft.Data.Sqlite,
│   │                                #   Microsoft.Extensions.Hosting(+WindowsServices)
│   ├── Program.cs                   # Host builder + CLI flags; UseWindowsService khi Windows
│   ├── AppPaths.cs                  # %ProgramData%\OrgInventory | ~/.local/share/OrgInventory
│   ├── AgentConfig.cs               # config-driven + đồng bộ từ server + hash cấu hình
│   ├── AgentIdentity.cs             # đã enroll? idempotent install
│   ├── Collectors/
│   │   ├── FingerprintCollector.cs  # 3 nguồn, WMI + registry + fallback Linux sysfs
│   │   ├── InventoryCollector.cs    # snapshot đầy đủ (flat, khớp schema server)
│   │   └── SoftwareCollector.cs     # registry Uninstall keys (64/32-bit)
│   ├── Crypto/
│   │   ├── KeyStore.cs              # cert store Windows / PEM file Linux
│   │   └── CsrGenerator.cs          # CSR ECDSA P-256
│   ├── Net/
│   │   ├── ApiClient.cs             # mTLS, retry, gzip, UA, failover
│   │   ├── EnrollClient.cs          # POST /api/enroll
│   │   └── EndpointManager.cs       # failover 5 lỗi → backup; thử primary mỗi 10 chu kỳ
│   ├── Services/
│   │   ├── EnrollCoordinator.cs     # enroll + retry (60s) + lưu config từ response
│   │   ├── HeartbeatService.cs      # 30±8s, flush offline cache trước khi gửi
│   │   ├── InventoryService.cs      # lần đầu / config_hash đổi / 24h / rescan
│   │   ├── RenewService.cs          # <70% vòng đời → renew
│   │   ├── ConfigSyncService.cs     # GET /api/agent/config mỗi 6h
│   │   └── OfflineCache.cs          # SQLite pending queue + AgentState
│   └── Logging/FileLogger.cs        # log xoay vòng 5MB × 2
├── installer/
│   ├── Product.wxs                  # WiX v4: MSI + service SCM + registry bootstrap
│   └── build-msi.ps1                # publish win-x64 → wix build → (tùy chọn) ký Authenticode
├── Assets/agent.ico                 # icon (metadata assembly + ARP)
└── tools/
    ├── make_icon.py                 # sinh agent.ico (không cần PIL)
    └── mock_server.py               # mock server test agent end-to-end trên Linux
```

## Build trên Linux (dev/test)

```bash
cd /home/windowsId/agent
dotnet restore        # cần network NuGet (đã verify OK)
dotnet build -c Release
```

- Build **PASS** trên Linux (net8.0, mọi API Windows-only bọc `OperatingSystem.IsWindows()`).
- Nếu máy không có network: packages đã cache tại `agent/.nuget-packages` (restore offline được).

## Chạy thử trên Linux (console — không cần Windows)

```bash
# fingerprint 3 nguồn (đọc /sys dmi-id + /etc/machine-id)
dotnet run --project src/OrgInventoryAgent -c Release -- --data-dir /tmp/agent-test --print-fingerprint

# cấu hình hiện tại (token che)
dotnet run --project src/OrgInventoryAgent -c Release -- --data-dir /tmp/agent-test --print-config

# end-to-end với mock server (validate payload bằng schema Pydantic thật của server):
python3 tools/mock_server.py --port 8787 --schema-dir /home/windowsId/server &
dotnet run --project src/OrgInventoryAgent -c Release --no-build -- \
  --data-dir /tmp/agent-test --endpoint http://127.0.0.1:8787 \
  --enroll-token t_testtoken123456 --once
# → enroll → heartbeat → inventory; mock log ghi rõ từng payload VALID/INVALID theo schema server.

# chạy liên tục như service (Ctrl+C để dừng):
dotnet run --project src/OrgInventoryAgent -c Release -- \
  --data-dir /tmp/agent-test --endpoint http://127.0.0.1:8787 --enroll-token t_testtoken123456
```

CLI flags: `--data-dir`, `--enroll-token`, `--endpoint`, `--print-config`, `--print-fingerprint`,
`--version`, `--once`, `--help`.

## Cài đặt trên Windows

### 1. Build MSI (trên Windows)

```powershell
cd agent
.\installer\build-msi.ps1                      # cần WiX (tự cài qua dotnet tool nếu thiếu)
# hoặc ký Authenticode:
.\installer\build-msi.ps1 -Sign -CertificateThumbprint "<thumb EV cert>"
```

Output: `installer\OrgInventoryAgent.msi` + `.msi.sha256`. **Yêu cầu:** Windows 10/11 x64,
.NET SDK 8 (chỉ để build), WiX v4+ (tự cài), Windows SDK (nếu ký).

### 2. Cài đặt (admin)

```powershell
# qua endpoint /i/{token} của portal (script động render sẵn) hoặc trực tiếp:
msiexec /i OrgInventoryAgent.msi /qn ENROLL_TOKEN="t_Ab3xK9mQ2vR8nL4p" ENDPOINTS="https://agent.gov.vn,https://backup.gov.vn"
```

- MSI đăng ký service `OrgInventoryAgent` (SCM chuẩn, LocalSystem, auto-start) và ghi
  `HKLM\SOFTWARE\OrgInventory` (Endpoints/EnrollToken/HttpProxy). Agent đọc registry này ở
  lần chạy đầu khi chưa có `config.json`, enroll xong xóa token khỏi config.
- Log: `%ProgramData%\OrgInventory\logs\agent.log` · Config: `%ProgramData%\OrgInventory\config.json`
- Kiểm tra: `sc query OrgInventoryAgent`, xem log, `Get-Content %ProgramData%\OrgInventory\config.json`.

### 3. Gỡ cài đặt

```powershell
msiexec /x OrgInventoryAgent.msi /qn     # xóa service + file + registry (giữ lại ProgramData theo mặc định)
```

## Cấu hình (`config.json` — %ProgramData%\OrgInventory)

| Trường | Mặc định | Nguồn |
|---|---|---|
| `endpoints[]` | — | enroll response `agent_server_url` / MSI ENDPOINTS / `--endpoint` |
| `heartbeatIntervalSeconds` | 30 | enroll/heartbeat/agent-config |
| `heartbeatJitterSeconds` | 8 | enroll/heartbeat/agent-config |
| `inventoryIntervalHours` | 24 | enroll/agent-config |
| `renewBeforePercent` | 70 | agent-config |
| `machineId` / `enrolled` / `clientCertThumbprint` / `certStoreLocation` | — | sau enroll |
| `httpProxy` | — | MSI HTTP_PROXY |

## Giả định & điểm còn thiếu (Phase 2/3)

1. **CN của cert lúc enroll**: agent chưa biết `machine_id` khi tạo CSR → dùng CN tạm
   `machine-<uuid>` (contract cho phép). Server prod (step-ca) ép CN=`machine-<id>` qua template;
   với LocalCaService (dev) cert giữ CN theo CSR — mTLS thật cần nginx + CA trỏ đúng CN.
   **Khi renew** agent luôn dùng CN=`machine-<machine_id>`.
2. **Enroll lại khi token hết hạn/revoked**: không tự xử lý (token 1 lần); máy bị 401 heartbeat →
   log lỗi rõ, cần ops cấp token mới + xóa config (cài lại). Phase 2 có thể bổ sung re-enroll có kiểm soát.
3. **Config ký số đẩy từ server (signed config push)** — Phase 3; Phase 1 chỉ failover tĩnh
   (endpoints[]) + đồng bộ qua GET /api/agent/config (mTLS — an toàn).
4. **Security posture đầy đủ** (BitLocker/WU/SMART) — Phase 2; Phase 1: antivirus + RDP + local accounts.
5. **install.ps1 động** render từ server (`GET /i/{token}`) — không nằm trong repo agent.
6. **ACL config.json** trên Windows: dùng ACL kế thừa ProgramData; nếu cần chặt hơn bổ sung
   `icacls` trong CustomAction MSI (chưa thêm).
7. Icon `agent.ico` là hình vẽ đơn giản (màn hình) — thay bằng logo thật của đơn vị khi có.
8. `os_build`/`os_version` trên Linux là kernel release (chỉ để dev; Windows đọc registry đúng).
9. Renew response `ca_cert_pem`/`cert_serial` có thể null (LocalCa) — agent chỉ cần `client_cert_pem`.

## Bảo mật (đã tuân thủ)

- Read-only tuyệt đối: chỉ đọc WMI/Registry; không hook/inject/đọc process khác; không ghi ngoài
  ProgramData + cert store.
- Private key sinh local (ECDSA P-256), lưu cert store, **không gửi lên server**.
- Verify server TLS theo hệ thống trust — không tắt xác thực.
- Token 1 lần: xóa khỏi config ngay sau enroll thành công.
- gzip > 8KB, User-Agent rõ ràng, heartbeat jitter chống pattern C2.
