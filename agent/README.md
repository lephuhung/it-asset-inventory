# OrgInventory Agent (Production Ready)

Agent Windows (.NET 8, C#) cho hệ thống IT Asset Inventory. Khớp **API thực tế của server** theo `docs/API_CONTRACT.md` v1.3.

## Tính năng

- **Enroll** (`POST /api/enroll`, không mTLS): token + fingerprint 3 nguồn + CSR ECDSA P-256
  → server trả `machine_id` + client cert + cấu hình (endpoint/interval/jitter/inventory interval).
- **Heartbeat** (`POST /api/heartbeat`, mTLS): chu kỳ ngẫu nhiên `[interval−jitter, interval+jitter]`
  (mặc định **30±8s ≈ 22–38s**); đồng bộ interval/jitter/renew_after từ response; `rescan_requested`
  → chạy inventory ngay. Định kỳ kiểm tra cert trong store, phát hiện cert bị xóa/mất để tự re-enroll.
- **Inventory** (`POST /api/inventory`, mTLS): OS/CPU/RAM/disk/GPU/mainboard/BIOS/network/logged_user/
  software/security/is_vm + `config_hash`; gửi lần đầu, khi config_hash đổi, định kỳ 24h, khi rescan.
- **Security Posture đầy đủ**:
  - **Antivirus**: Tên + trạng thái (enabled/disabled) qua WMI `root\SecurityCenter2`.
  - **Windows Update Status**: `up-to-date` (≤ 30 ngày) / `outdated` qua Registry Auto Update.
  - **BitLocker**: Trạng thái bảo vệ ổ C: (`on`/`off`/`unknown`) qua WMI `Win32_EncryptableVolume`.
  - **RDP Status**: Trạng thái cho phép/chặn Remote Desktop qua Registry `fDenyTSConnections`.
  - **Local Accounts**: Danh sách tài khoản nội bộ + `has_password` qua WMI `PasswordRequired`.
  - **Dual-homed Detection**: Tự động tính subnet mask thực tế của từng interface để gắn cờ máy đa mạng.
- **Phần mềm đã cài đặt**:
  - Quét registry HKLM (64-bit + WOW6432Node) và HKCU (phần mềm per-user: VS Code, Teams, Spotify...).
  - Tự động deduplicate theo tên và giới hạn 500 ứng dụng để tối ưu payload.
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
  dedupe theo (url, body_hash), cap 10 lần thử, tự động dọn dẹp bản ghi cũ > 7 ngày.
- **Failover endpoint**: primary lỗi 5 lần liên tiếp → backup; thử lại primary mỗi 10 chu kỳ.
- **Idempotent install**: cert + machine_id còn trong config + store → bỏ qua enroll, chỉ repair/update.
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
│   ├── AgentIdentity.cs             # đã enroll? Validate cert trong store, EnrollStatus
│   ├── Collectors/
│   │   ├── FingerprintCollector.cs  # 3 nguồn, WMI + sysfs
│   │   ├── InventoryCollector.cs    # snapshot đầy đủ + SecurityPosture + Subnet Mask Dual-Homed
│   │   └── SoftwareCollector.cs     # registry Uninstall keys (HKLM 64/32-bit + HKCU per-user)
│   ├── Crypto/
│   │   ├── KeyStore.cs              # cert store Windows / PEM file Linux
│   │   └── CsrGenerator.cs          # CSR ECDSA P-256
│   ├── Net/
│   │   ├── ApiClient.cs             # mTLS, retry, gzip, UA, failover
│   │   ├── EnrollClient.cs          # POST /api/enroll
│   │   └── EndpointManager.cs       # failover 5 lỗi → backup; thử primary mỗi 10 chu kỳ
│   ├── Services/
│   │   ├── EnrollCoordinator.cs     # enroll + retry (60s) + lưu config từ response
│   │   ├── HeartbeatService.cs      # 30±8s, flush offline cache + cert missing check
│   │   ├── InventoryService.cs      # lần đầu / config_hash đổi / 24h / rescan
│   │   ├── RenewService.cs          # <70% vòng đời → renew
│   │   ├── ConfigSyncService.cs     # GET /api/agent/config mỗi 6h
│   │   └── OfflineCache.cs          # SQLite pending queue + auto cleanup TTL 7 ngày
│   └── Logging/FileLogger.cs        # log xoay vòng 5MB × 2
├── tests/
│   └── OrgInventoryAgent.Tests/     # Unit tests xUnit: config, endpoint failover, renew, offline cache
├── installer/
│   ├── Product.wxs                  # WiX v4: MSI + service SCM + registry bootstrap
│   └── build-msi.ps1                # publish win-x64 → wix build → (tùy chọn) ký Authenticode
├── Assets/agent.ico                 # icon (metadata assembly + ARP)
└── tools/
    ├── make_icon.py                 # sinh agent.ico (không cần PIL)
    └── mock_server.py               # mock server test agent end-to-end (auto-detect server schema)
```

## Unit Tests

```bash
cd agent
dotnet test
```

Bao gồm các test case cho:
- `AgentConfigTests`: Chuẩn hóa interval, sắp xếp endpoint, đồng bộ cài đặt server, băm cấu hình canonical JSON SHA-256.
- `EndpointManagerTests`: Cơ chế failover 5 lỗi liên tiếp sang backup, quay lại primary theo chu kỳ.
- `RenewServiceTests`: Tính toán phần trăm vòng đời cert còn lại chính xác, xử lý cert quá hạn.
- `OfflineCacheTests`: Hàng đợi offline SQLite, cơ chế deduplicate theo url + body_hash, giới hạn số lần thử, dọn dẹp TTL.
- `AgentIdentityTests`: Trạng thái kiểm tra enrollment và xác thực chứng chỉ.

## Build trên Linux / Windows

```bash
cd agent
dotnet restore
dotnet build -c Release
```

## Chạy thử (Console mode)

```bash
# fingerprint 3 nguồn
dotnet run --project src/OrgInventoryAgent -c Release -- --data-dir ./tmp-data --print-fingerprint

# cấu hình hiện tại (token che)
dotnet run --project src/OrgInventoryAgent -c Release -- --data-dir ./tmp-data --print-config

# Kết nối thử tới máy chủ với enroll token:
dotnet run --project src/OrgInventoryAgent -c Release -- \
  --data-dir ./tmp-data --endpoint https://agent.example.gov.vn \
  --enroll-token <TOKEN_CỦA_BẠN> --once
```

## Cài đặt trên Windows (MSI)

```powershell
# Build MSI
.\installer\build-msi.ps1

# Cài đặt qua msiexec trỏ về server quản trị
msiexec /i OrgInventoryAgent.msi /qn ENROLL_TOKEN="<TOKEN_CỦA_BẠN>" ENDPOINTS="https://agent.example.gov.vn"
```

## Cơ chế Cấu hình Động (Config-driven) & Chống Can Thiệp (Tamper-proof)

Agent hoàn toàn không dán cứng IP/domain hay tần suất heartbeat trong binary:
- **Cài đặt trực tuyến 1-click**: Lệnh `irm https://portal.../i/{token} | iex` tự động kết xuất endpoint hiệu lực từ server vào lệnh cài đặt MSI.
- **Enroll (`/api/enroll`)**: Server trả về `agent_server_url`, `heartbeat_interval_seconds`, `heartbeat_jitter_seconds`, `inventory_interval_hours`.
- **Tải cấu hình chi tiết (`GET /api/agent/config`)**: Ngay sau khi có client cert mTLS, agent nạp trọn bộ cấu hình hệ thống.
- **Đồng bộ qua Heartbeat (`POST /api/heartbeat`)**: Server trả kèm cấu hình mới nhất; mọi thay đổi từ Portal có hiệu lực trong vòng **1 chu kỳ heartbeat**, không cần cài lại agent.
- **Ký số chống thay đổi (Tamper-proof)**: File cấu hình và gói config từ server được ký số ECDSA-SHA256 (Server Private Key). Agent xác thực chữ ký bằng Server Public Key nhúng sẵn trước khi áp dụng; từ chối mọi thay đổi nếu chữ ký không khớp.
- **Chống Replay**: Envelope cấu hình sử dụng trường `version` tăng dần; agent chỉ chấp nhận gói cấu hình có version mới hơn cấu hình đang dùng.
- **Tự động Rollback**: Agent lưu bản sao `config.json.bak`. Nếu endpoint mới không phản hồi sau 5 chu kỳ, agent tự động khôi phục cấu hình trước đó.

## Bảo mật (đã tuân thủ)

- **Chống can thiệp file cấu hình (Tamper-proof & Access Control)**:
  - File cấu hình máy trạm `%ProgramData%\OrgInventory\config.json` được thiết lập Windows ACL nghiêm ngặt (chỉ `SYSTEM` và `Administrators` có quyền truy cập; chặn người dùng thường sửa đổi).
  - Dữ liệu nhạy cảm được mã hóa bảo vệ bằng **Windows DPAPI** (`DataProtectionScope.LocalMachine`).
- **Read-only tuyệt đối**: chỉ đọc WMI/Registry; không hook/inject/đọc process khác; không ghi ngoài `ProgramData` + cert store.
- **Khóa riêng an toàn**: Private key sinh local (ECDSA P-256), lưu Windows Certificate Store (`LocalMachine\My`), **không gửi lên server**.
- **Verify server TLS**: Kiểm tra theo hệ thống trust — không bao giờ tắt xác thực.
- **Token 1 lần**: Xóa khỏi config ngay sau enroll thành công.
- **Gzip & Jitter**: Gzip khi payload > 8KB, User-Agent rõ ràng `OrgInventoryAgent/1.0.0`, heartbeat jitter ±25% chống pattern C2.

