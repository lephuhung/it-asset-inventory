# Velociraptor Server (DFIR)

Triển khai [Velociraptor](https://github.com/velocidex/velociraptor) Server bằng Docker — chạy **độc lập** với Inventory Server, chỉ giao tiếp qua REST API (port 8889).

> **Phạm vi:** Script này CHỈ dựng Velociraptor Server. Inventory Server đã có sẵn ở `server/deploy/` và tự kết nối tới Velociraptor khi cấu hình xong ở portal `/dfir/settings`.

## 1. Khởi động nhanh

```bash
cd deploy/velociraptor

# Tạo thư mục datastore + etc + chown cho non-root user trong container (UID 1000)
mkdir -p datastore etc
sudo chown -R 1000:1000 datastore etc    # bỏ qua nếu user hiện tại đã UID 1000

docker compose up -d
docker compose logs -f velociraptor   # Ctrl+C khi thấy "All done!" hoặc "Starting frontend"
```

Sau ~30–60s (lần đầu — generate config), healthcheck sẽ xanh. Verify:

```bash
docker compose ps                 # STATUS = healthy
docker inspect --format '{{.State.Health.Status}}' velociraptor   # healthy
```

## 2. Login

Password mặc định đặt ở `.env` (`VELOCIRAPTOR_ADMIN_PASSWORD`). Nếu chưa đổi:

```
user: admin
password: ChangeMe!Velociraptor2026
```

Mở GUI: **https://localhost:8889** (HTTPS self-signed → trình duyệt cảnh báo → bấm **Advanced → Proceed**).

> Nếu deploy trên host khác, thay `localhost` b�ng IP/hostname server (vd `https://10.10.0.241:8889`). **KHÔNG** dùng HTTP — Velociraptor luôn HTTPS.

**ĐỔI PASSWORD NGAY** ở menu trên cùng bên phải → Reset Password.

> Lưu ý: password đặt trong `.env` chỉ áp dụng khi **lần đầu** generate config. Nếu container đã từng chạy (đã có `etc/server.config.yaml`), đổi password phải làm trong GUI hoặc `velociraptor user reset_password`.


## 3. Kết nối Inventory Server qua gRPC/mTLS (không cần Docker socket)

Inventory Server dùng API automation chính thức của Velociraptor qua gRPC. Có thể
đặt Velociraptor trên máy riêng; backend chỉ cần reach được cổng API và không cần
truy cập Docker daemon hay filesystem Velociraptor.

Trên Velociraptor Server, cấu hình API trước khi sinh credential:

```yaml
API:
  hostname: velociraptor.example.gov.vn
  bind_address: 0.0.0.0
  bind_port: 8001
  bind_scheme: tcp
```

Restart server, giới hạn firewall port `8001` chỉ cho IP Inventory Backend, rồi
sinh `api_client.yaml` có `api_connection_string: velociraptor.example.gov.vn:8001`.
Trong portal, Super Admin nhập GUI URL (`https://...:8889`) và tải file YAML này
lên; portal mã hoá file trong DB và backend dùng mTLS để sync, lookup, collect và
đọc flow qua gRPC.

## 4. Cấu hình trên Inventory Server portal

Velociraptor có HTTP Basic cho GUI/REST compatibility. Inventory Server dùng gRPC
API mTLS cho sync, lookup, collect và đọc flow; các API hunt cũ vẫn dùng REST.

### Cách A: HTTP Basic (chỉ GUI/compatibility)

Velociraptor default authenticator = Basic. Trên portal `/dfir/settings`:
- Nhập **Username** (mặc định: `admin`)
- Nhập **Password** (giá trị `VELOCIRAPTOR_INITIAL_ADMIN_PASSWORD` lúc khởi động container, vd `ChangeMe!Velociraptor2026`)

HTTP Basic không thay thế `api_client.yaml`; backend sẽ không chạy các automation
gRPC nếu chưa tải YAML.

### Cách B: mTLS API client (bắt buộc cho Inventory automation)

Velociraptor client dùng mTLS + CA-pinned. Cấu hình phía Velociraptor Server:

```yaml
# /etc/velociraptor/server.config.yaml — section API:
API:
  hostname: velociraptor.example.gov.vn
  bind_address: 0.0.0.0
  bind_port: 8001
  bind_scheme: tcp
```

(Cần restart Velociraptor Server để áp dụng.)

Sinh client config:

```bash
bash generate-client-config.sh "inventory-portal"
```

Script sẽ in ra YAML (~3KB) chứa `ca_certificate` + `client_cert` + `client_private_key`.

→ Tải YAML lên portal `/dfir/settings`. Nếu dùng màn hình tạo hunt cũ qua REST,
cấu hình thêm `GUI.authenticator.type: Certs`; nếu không, giữ Basic cho GUI.

Login Super Admin → **/dfir/settings**:

| Trường | Giá trị |
|---|---|
| Bật Velociraptor | ✅ Enabled |
| Server URL | `https://<host>:8889` (cùng URL admin truy cập GUI) |
| API Client YAML | `api_client.yaml` cho gRPC/mTLS (bắt buộc cho automation) |
| Allowlist | giữ mặc định (13 artifact read-only) hoặc chỉnh |

Bấm **Lưu** → **Test kết nối** → OK → backend sẽ sync hostname ↔ client_id trong vòng 5 phút.

Xem trạng thái sync ở **/dfir** (panel "Số máy đã link Velociraptor").

## 5. Cài Velociraptor Client lên máy trạm

Velociraptor Client **không** qua agent inventory — cài theo cách riêng của đơn vị (GPO, MSI deploy thủ công, …).

> ✅ **Cài gộp 2 agent bằng 1 lệnh:** Windows dùng `install-both.ps1`; Linux dùng one-liner
> `curl -fsSL <portal>/i/<token> | sudo bash` (template `install.sh.j2` — cài đủ
> OrgInventory Agent + Velociraptor Client, reinstall chỉ merge config) — xem
> [`docs/INSTALL_BOTH_AGENTS.md`](../docs/INSTALL_BOTH_AGENTS.md). Script được Inventory Server
> phục vụ tại `/download/install-both.ps1` (Windows).

Trong Velociraptor GUI:
1. **Settings → Clients → Add new client** (hoặc download cấu hình + binary từ nút Download ở góc).
2. Copy file `client.config.yaml` tới từng máy Windows → cài Velociraptor client (Windows MSI có sẵn ở `https://<host>:8889/#/host/...` → download tab).
3. Sau khi client enroll, tối đa 5 phút sẽ thấy mapping xuất hiện ở **/dfir** của Inventory Server.

> 💡 **Khuyến nghị:** dùng artifact `Server.Utils.CreateMSI` (Windows) và
> `Server.Utils.CreateLinuxPackages` (deb/rpm) trên Velociraptor GUI để tạo gói cài **đã nhúng
> sẵn `client.config.yaml`** — máy trạm chỉ cần cài 1 file, không phải copy config riêng
> (xem `docs/INSTALL_BOTH_AGENTS.md` mục 4).

## 6. Chạy hunt / collect artifact

Trên Inventory Server portal, Super Admin / Org Admin có thể:
- **/dfir** → bấm "Chạy Hunt / Collect" → chọn artifact (phải nằm trong allowlist).
- **/machines/[id]** → bấm "Collect Artifact" trên 1 máy cụ thể đã link.

Kết quả lưu trên **Velociraptor Server** — portal chỉ deep-link sang GUI (`/#/hunts/{id}` hoặc `/#/host/{client_id}`).

## 7. Cổng & network

| Port | Vai trò | Cần expose? |
|---|---|---|
| **8889** | GUI + REST API `/api/v1/` | ✅ Bắt buộc — Inventory Server + admin truy cập |
| **8000** (container) / **8888** (host) | gRPC cho Velociraptor Client enroll | ✅ Cần nếu muốn client từ máy khác kết nối. KHI ENROLL client Windows tr� URL `https://<host>:8888`. |
| 8001, 8002 | Frontend/debug nội bộ | ❌ Không cần |

> ⚠️ **Lưu ý về cổng 8000:**
> - Host 8000 = Inventory backend (uvicorn) — KHÔNG động vào.
> - Container Velociraptor dùng 8000 (gRPC client enroll) nhưng map ra host port **8888** (tránh nhầm với backend).
> - KHI ENROLL Velociraptor Client trên Windows: trỏ URL `https://<host>:8888` (host port), KHÔNG phải `https://<host>:8000` (đó là backend Inventory).

Nếu chạy sau **nginx reverse proxy** (khuyến nghị cho prod): forward path `/api/v1/` + WebSocket upgrade header + `proxy_ssl_verify off` cho Velociraptor self-signed (hoặc dùng TLS h�p lệ).

## 8. Backup

Toàn bộ dữ liệu nằm trong `./datastore/` (file datastore) và `./etc/server.config.yaml` (cấu hình, có thể lộ secret).

```bash
tar -czf velociraptor-backup-$(date +%Y%m%d).tar.gz datastore/ etc/
```

## 9. Troubleshooting

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| Container restart liên tục, log "permission denied" | `./datastore` hoặc `./etc` không writable cho UID 1000 | `sudo chown -R 1000:1000 ./datastore ./etc` |
| Healthcheck fail timeout | Lần đầu init chậm (~60s), `start_period: 60s` | Đợi thêm 30s, kiểm tra `docker logs velociraptor` |
| Không kết nối từ Inventory Server | Firewall chặn port 8889, hoặc Velociraptor bind 127.0.0.1 | Verify: `curl -k https://<host>:8889/api/v1/SearchClients -H "Authorization: Bearer xxx"` từ server inventory |
| `last_sync_error: HTTP 401` | API key sai / bị revoke | Tạo key mới ở Velociraptor GUI → `bash create-api-key.sh`, paste vào portal |
| Muốn đổi port 8889 | Sửa `ports:` + restart | Sau đó cập nhật `server_url` ở portal `/dfir/settings` |
| Reset toàn bộ | Xoài `./datastore` + `./etc` + recreate container | **MẤT HẾT** cấu hình + datastore + API key |

## 10. KHÔNG ĐƯỢC LÀM

- **KHÔNG** commit `datastore/` + `etc/` + `.env` (chứa secret + datastore) — đã có `.gitignore`.
- **KHÔNG** lộ API key qua kênh không mã hoá (email, chat). Lưu trong Vault/KMS.
- **KHÔNG** tắt healthcheck để "khỏi restart khi lỗi" — healthcheck giúp detect Velociraptor đứng.
- **KHÔNG** mount `datastore` ra nhiều nơi (NFS/SMB) khi chưa test k� — Velociraptor datastore ghi nhiều, mount mạng có thể gây race condition.
- **KHÔNG** dùng `image: latest` cho prod — pin version cụ thể (vd `velocidex/velociraptor:v0.7.0`) sau khi đã test.
