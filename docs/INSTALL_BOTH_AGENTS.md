# Cài đồng thời OrgInventory Agent + Velociraptor Client — 1 lệnh duy nhất

> Kết quả nghiên cứu + hướng dẫn triển khai: cài **2 agent** (kiểm kê tài sản CNTT & DFIR) trên
> cùng một máy trạm chỉ với **1 command**, trên cả Windows và Linux.
>
> **Tài liệu tham khảo chính thức (Velociraptor):**
> - [Deploying Clients — docs.velociraptor.app](https://docs.velociraptor.app/docs/deployment/clients/)
> - [docs/wix/README.md — MSI & service "Velociraptor"](https://gitlab.com/velocidex/velociraptor/-/blob/master/docs/wix/README.md)
> - [Client Deployment Issues (troubleshooting)](https://docs.velociraptor.app/docs/troubleshooting/deployment/client/)

---

## 1. Tóm tắt kết quả nghiên cứu

Velociraptor **không có binary client riêng** — 1 binary duy nhất, chạy chế độ client khi được
cấp một **file cấu hình client** (`client.config.yaml`, chứa `server_urls` + CA cert + nonce org).
Có 2 cách cài client (xem [Deploying Clients](https://docs.velociraptor.app/docs/deployment/clients/)):

| Cách | Windows | Linux | Ưu điểm |
|---|---|---|---|
| **A. Gói cài nhúng config** *(khuyên dùng)* | MSI repack qua artifact `Server.Utils.CreateMSI` → `msiexec /i velociraptor_xxx.msi /qn` | `.deb`/`.rpm` qua artifact `Server.Utils.CreateLinuxPackages` → `dpkg -i` / `rpm -i` | Máy trạm **không cần config riêng** — chỉ cần 1 file cài |
| **B. Cài thủ công** | Tải binary + `client.config.yaml`, chạy `velociraptor.exe --config client.config.yaml client` (hoặc dựng service thủ công) | Tương tự + tạo systemd unit | Linh hoạt nhưng thủ công |

Kết quả cài đặt (đã xác nhận từ docs chính thức + repo):

- **Windows MSI** → cài vào `C:\Program Files\Velociraptor\`, tạo + chạy service
  **"Velociraptor"** (display name "Velociraptor Service", Local System, Auto delayed start).
  Lệnh silent: `msiexec /i velociraptor_custom.msi /qn /norestart`.
- **Linux .deb/.rpm** → tạo service systemd **`velociraptor_client`** (`systemctl status velociraptor_client`).
  Lệnh cài: `sudo dpkg -i velociraptor_client_amd64.deb` hoặc `sudo rpm -i velociraptor_client_amd64.rpm`.

> Trong Velociraptor GUI, gói cài client được tạo bằng server artifacts
> `Server.Utils.CreateMSI` / `Server.Utils.CreateLinuxPackages` (mục **Server Artifacts**,
> hoặc nút download trên trang **Welcome**). Các gói này tự tải binary khớp version server và
> **nhúng sẵn client config của org hiện tại** — sau đó tải về từ tab **Uploaded Files**.

### Hiện trạng repo (trước khi thay đổi)

Repo đã có sẵn hạ tầng phục vụ Velociraptor (xem `deploy/velociraptor/README.md`):

- Velociraptor **Server** chạy Docker riêng (GUI/REST `:8889`, client enroll `:8888`).
- Inventory **Server** serve các file cài qua `/download/*` (`server/app/api/routes/downloads.py`):
  - `/download/agent.msi` + `.sha256` — OrgInventoryAgent MSI.
  - `/download/velociraptor-agent-windows.zip`, `velociraptor-windows-amd64.msi`,
    `velociraptor-client.config.yaml`, `install-velociraptor.bat` — theo cách **B** (MSI stock +
    copy config đè sau khi cài).
- One-liner cài OrgInventoryAgent đã có: `irm <portal>/i/<token> | iex` → render
  `install.ps1.j2` (token nhúng, verify SHA256 + chữ ký, `msiexec /qn`).

→ **Khoảng trống:** Velociraptor vẫn cài thủ công từng máy; chưa có 1 lệnh gộp cả 2 agent,
và chưa có gói Linux cho Velociraptor client.

---

## 2. Giải pháp: 1 command cài cả 2 agent

### 2.1. Windows — `install-both.ps1`

**1 lệnh duy nhất** (tải script từ portal và chạy, token + URL truyền qua biến môi trường):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$env:ORGINVENTORY_TOKEN="t_xxx";$env:ORGINVENTORY_PORTAL_URL="https://portal.gov.vn";irm https://portal.gov.vn/download/install-both.ps1|iex'
```

> ⚠️ Bắt buộc dùng **nháy đơn** cho `-Command` — nếu dùng nháy kép, PowerShell ngoài sẽ tự
> expand `$env:...` trước khi chạy, làm lệnh hỏng.

Hoặc chạy file trực tiếp (có tham số):

```powershell
.\install-both.ps1 -Token t_xxx -PortalUrl https://portal.gov.vn -Endpoint https://agent.gov.vn
```

**Luồng xử lý** (file: `agent/install-both.ps1`, bản serve: `server/app/templates/install-both.ps1`):

1. Kiểm tra quyền Administrator (tự nâng UAC nếu chạy từ file).
2. Thêm Defender exclusion (chống false-positive, giống `install.ps1` hiện có).
3. **OrgInventory Agent**: tải `/download/agent.msi` → verify **SHA256** (so với
   `/download/agent.msi.sha256`) + **chữ ký Authenticode** (chỉ cho phép MSI chưa ký khi
   `ORGINV_ALLOW_UNSIGNED=1` — test) → `msiexec /i ... /qn ENROLL_TOKEN=... ENDPOINTS=...`.
4. **Velociraptor Client**: tải MSI + `client.config.yaml` → `msiexec /i ... /qn` → **ghi đè
   config** vào `C:\Program Files\Velociraptor\client.config.yaml` → restart service
   (cơ chế giống `install-velociraptor.bat` hiện có).
5. Verify cả 2 service (`OrgInventoryAgent`, `Velociraptor`).

> **Tối ưu hơn (khuyến nghị cho sản xuất):** dùng **cách A** — tạo MSI đã nhúng config bằng
> artifact `Server.Utils.CreateMSI`, đặt vào `agent_dist/`, rồi gọi script với
> `-VelociraptorMsiUrl https://portal.gov.vn/download/velociraptor-windows-amd64.msi`
> (script sẽ bỏ qua bước ghi đè config nếu MSI đã nhúng).

### 2.2. Linux — canonical `install.sh.j2`

**1 lệnh duy nhất** (server render `install.sh.j2`, token nhúng sẵn trong URL):

```bash
curl -fsSL https://portal.gov.vn/i/<token> | sudo bash
```

> Lệnh này là **canonical** — thay thế hoàn toàn `install-both.sh` (đã xóa): template
> `server/app/templates/install.sh.j2` tự cài đủ **2 agent trong 1 lần** (OrgInventory +
> Velociraptor). Nếu agent đã cài → **smart reinstall**: chỉ merge config + restart
> (giữ identity), không tải lại binary/package; `--force` để cài đè hoàn toàn.

**Luồng xử lý** (template: `server/app/templates/install.sh.j2`):

1. Phát hiện distro (Debian/Ubuntu ↔ `.deb`, RHEL/Rocky ↔ `.rpm`) + architecture.
2. **OrgInventory Agent**:
   - Tải binary self-contained từ `/download/agent-linux-x64` + SHA256 → verify.
   - Tạo user `orginventory`, data dir `/var/lib/orginventory`, helper socket
     `/run/orginventory/helper.sock`.
   - Ghi `/etc/orginventory/config.json` với token + endpoints; tạo + enable systemd unit
     `orginventory-agent.service`.
3. **Velociraptor Client**: tải gói từ `/download/velociraptor-linux-amd64.{deb,rpm}` →
   `dpkg -i` / `dnf install` → `systemctl enable --now velociraptor_client`; đè
   `client.config.yaml` từ `/download/velociraptor-client.config.yaml` → restart.
4. Verify cả 2 service (OrgInventory + Velociraptor).

> ⚠️ Gói `.deb`/`.rpm` phải là gói **đã nhúng `client.config.yaml`** (tạo bằng
> `Server.Utils.CreateLinuxPackages` hoặc `velociraptor debian client --config client.config.yaml`
> trên Velociraptor Server), nếu không client sẽ không kết nối được. Sau khi tạo, copy vào
> `agent_dist/` trên Inventory Server với đúng tên `velociraptor_client_amd64.deb` / `.rpm` để
> route `/download/velociraptor-linux-amd64.deb` (`.rpm`) phục vụ.

---

## 3. Route server mới (đã thêm)

Trong `server/app/api/routes/downloads.py`:

| Route | Nội dung |
|---|---|
| `GET /download/install-both.ps1` | Script Windows (serve từ `app/templates/install-both.ps1`) |
| `GET /download/agent-linux-x64` | Binary Linux OrgInventoryAgent (từ `agent_dist/OrgInventoryAgent-linux-x64`) |
| `GET /download/velociraptor-linux-amd64.deb` | Gói `.deb` từ `agent_dist/velociraptor_client_amd64.deb` |
| `GET /download/velociraptor-linux-amd64.rpm` | Gói `.rpm` từ `agent_dist/velociraptor_client_amd64.rpm` |

Đã thêm test trong `server/tests/test_downloads.py` (13 tests pass).

---

## 4. Chuẩn bị package (làm 1 lần trên Velociraptor Server)

```text
1. Mở Velociraptor GUI https://<vr-host>:8889 → Server Artifacts
2. Chạy collection:
     - Windows: Server.Utils.CreateMSI            → tải MSI từ tab "Uploaded Files"
     - Linux:   Server.Utils.CreateLinuxPackages  → tải .deb + .rpm
   (Hoặc CLI trong container: velociraptor debian client / rpm client --config ...)
3. Build binary Linux của OrgInventoryAgent (máy có .NET 8 SDK):
     cd agent && dotnet publish src/OrgInventoryAgent -c Release -r linux-x64 \
         --self-contained -p:PublishSingleFile=true -p:DebugType=none -o publish/linux-x64
4. Đặt tất cả file vào thư mục agent_dist của Inventory Server:
     agent_dist/
     ├── OrgInventoryAgent.msi               (đã có sẵn)
     ├── OrgInventoryAgent-linux-x64         (binary Linux, bước 3)
     ├── velociraptor-windows-amd64.msi      (nếu dùng MSI repack, đặt tên này để
     │                                        /download/velociraptor-windows-amd64.msi phục vụ)
     ├── velociraptor_client_amd64.deb
     └── velociraptor_client_amd64.rpm
```

> Lưu ý cổng: config client phải trỏ `server_urls` về **`wss://<host>:8888/`** (host port
> Velociraptor Frontend) — không phải `:8000` (đã bị Inventory backend chiếm), xem
> `deploy/velociraptor/README.md` mục 7.

---

## 5. Verify sau khi cài

**Windows:**

```powershell
Get-Service OrgInventoryAgent, Velociraptor
Get-Content "$env:ProgramData\OrgInventory\logs\agent.log" -Wait -Tail 30
Get-Content "$env:ProgramFiles\Velociraptor\logs\velociraptor.log" -Wait -Tail 30
```

**Linux:**

```bash
systemctl status orginventory-agent velociraptor_client
tail -f /var/lib/orginventory/logs/agent.log
```

Sau ~30s thấy client trong Velociraptor GUI (tab **Clients**); sau tối đa ~5 phút thấy mapping
hostname ↔ client_id ở portal **/dfir** (do Inventory Server sync mỗi 5 phút).

---

## 6. Bảo mật & lưu ý

- **Token OrgInventory là token 1 lần** — agent tự xóa khỏi config sau khi enroll thành công.
  Trên Linux, nếu enroll thất bại lúc cài (máy offline), token nằm trong unit file để retry;
  sau khi enroll OK nên xóa dòng `--enroll-token` trong `/etc/systemd/system/orginventory-agent.service`
  rồi `systemctl daemon-reload && systemctl restart orginventory-agent`.
- **Client config Velociraptor** chứa CA cert + nonce — nên phát qua HTTPS; không gửi qua
  email/chat.
- **MSI OrgInventory chưa ký** chỉ cài được khi `ORGINV_ALLOW_UNSIGNED=1` (test) — sản xuất
  phải ký Authenticode (xem `agent/installer/build-msi.ps1 -Sign`).
- Trên Linux, agent thu thập hardware/OS qua sysfs; các collector dùng WMI (security posture,
  danh sách phần mềm Windows) trả về null — đã được guard bằng `OperatingSystem.IsWindows()`.
- Giữ bản `agent/install-both.*` và `server/app/templates/install-both.*` **đồng bộ** (bản
  template là bản serve cho one-liner).
