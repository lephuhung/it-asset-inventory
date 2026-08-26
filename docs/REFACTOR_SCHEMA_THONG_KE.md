# Đánh giá & Đề xuất Refactor Schema — Thống kê dữ liệu máy tính

> Ngày: 2026-08-26 · Phạm vi: `server/app/db/models.py`, `server/app/api/routes/inventory.py`,
> `stats.py`, `reports.py`, `machines.py`, agent C# (`InventoryCollector.cs`), `docs/API_CONTRACT.md`.
> Căn cứ yêu cầu: thống kê nhiều chiều trên dữ liệu machines — app cài đặt nhiều nhất,
> số máy bật Windows Update, firewall, số máy Windows 10/11.

## ✅ Trạng thái triển khai (2026-08-26)

**Phần server ĐÃ TRIỂN KHAI** (78/78 test pass, migration up/down đã verify trên PostgreSQL):

| Hạng mục | File |
|---|---|
| Models `MachineCurrent` + `MachineSoftware` + cột OS chuẩn hóa cho `MachineSpec` | `server/app/db/models.py` |
| Migration `d7e8f9a0b1c2` (2 bảng mới + cột + GIN/functional index) | `server/alembic/versions/d7e8f9a0b1c2_stats_normalized_schema.py` |
| Chuẩn hóa OS/security/software phía server (agent KHÔNG đổi) | `server/app/services/inventory_normalize.py` |
| Upsert `machine_current` + replace `machine_software` (cùng transaction) | `server/app/services/inventory_sync.py` + `inventory.py` + `offline_import.py` |
| Endpoint `GET /api/stats/inventory` (GROUP BY SQL, RBAC, org_id filter) | `server/app/api/routes/stats.py` + `schemas/__init__.py` |
| `machines.py` đọc `logged_user` từ `machine_current` (bỏ DISTINCT ON) | `server/app/api/routes/machines.py` |
| Script backfill dữ liệu cũ (specs → current + software) | `server/scripts/backfill_machine_current.py` |
| Tests | `server/tests/test_stats_inventory.py` (5 test) |

**Agent CHƯA sửa** (theo yêu cầu — agent đang thiết lập ở máy khác; payload v1/v2/v3 vẫn
được chấp nhận nguyên vẹn). Hệ quả cần lưu ý: `firewall_enabled` / `windows_update_status`
vẫn trả `unknown` trong thống kê cho tới khi agent release mới bổ sung collector (mục 6).

**Còn lại (đề xuất làm tiếp):** portal (KPI + trang thống kê đọc `/api/stats/inventory`),
bổ sung collector agent (mục 6), cập nhật sheet "Thống kê" trong báo cáo Excel.

---

## 1. Kết luận ngắn

**Lưu hiện tại CHƯA phù hợp cho mục tiêu thống kê** (dù đúng cho mục tiêu "lịch sử cấu hình").

- Mọi trường cần thống kê (`installed_software`, `security`, `os_name`…) đang **chôn trong
  JSONB của bảng lịch sử `machine_specs`** — muốn đếm phải: (1) tìm snapshot mới nhất của
  từng máy (`DISTINCT ON`), (2) unnest/móc JSONB, (3) gộp trong Python. Không index được,
  không GROUP BY được ở SQL, tải toàn bộ máy về bộ nhớ mỗi request.
- **Không có "trạng thái hiện tại" denormalized** — `machine_specs` là bảng lịch sử (nhiều
  dòng/máy), nên mọi câu "có bao nhiêu máy đang X" đều phải tính lại snapshot mới nhất.
- **Agent không thu thập dữ liệu cho 2 trong 3 thống kê người dùng nêu**: `windows_update_status`,
  `bitlocker` khai báo trong DTO nhưng `GetSecurity()` không bao giờ gán; `firewall_enabled`
  không có trong agent. Refactor schema mà không sửa agent → thống kê vẫn rỗng.
- **OS không chuẩn hóa**: `os_version` luôn là `10.0.xxxx` cho CẢ Windows 10 lẫn Windows 11
  (cùng NT kernel); chỉ `DisplayVersion`/`ProductName` mới phân biệt được — hiện nằm lẫn
  trong chuỗi tự do `os_name` ("Windows 11 Pro 25H2") nên đếm Win10/Win11 phải parse chuỗi.

---

## 2. Cách lưu hiện tại (thực tế trong code)

| Bảng | Vai trò | Ghi chú |
|---|---|---|
| `machines` | 1 dòng/1 máy — định danh, status, lifecycle | `fingerprint` JSONB, không chứa cấu hình |
| `machine_specs` | **Lịch sử snapshot** — nhiều dòng/máy, chỉ insert khi `config_hash` đổi | `os_*` là cột riêng; `cpu, disks, gpu, mainboard, bios, network, installed_software, security` là **JSONB** |
| `heartbeats` | Partition theo ngày — trạng thái online/offline | Không liên quan thống kê cấu hình |

Quy trình ghi: `POST /api/inventory` → so hash với snapshot mới nhất → nếu đổi thì `INSERT
machine_specs` (`inventory.py:57-82`). Không có bảng nào khác lưu trạng thái "hiện tại".

Thống kê hiện tại (`stats.py`, `machines.py /stats`, `report.py`):
- **Load toàn bộ** `machines` (và cả `specs` qua `selectinload`) vào RAM rồi đếm bằng vòng
  lặp Python — `stats.py:27-42`, `report.py:_latest_spec`.
- Không có endpoint nào trả "top phần mềm", "máy bật update", "máy bật firewall", "Win10/Win11".

---

## 3. Vì sao lưu hiện tại không phù hợp (bằng chứng)

### 3.1. Dữ liệu thống kê nằm trong JSONB của bảng lịch sử

- `installed_software: JSONB` — danh sách app của MỘT máy tại MỘT thời điểm.
  Câu "app nào cài nhiều nhất toàn cơ quan" về bản chất là:
  `GROUP BY app_name → COUNT(DISTINCT machine_id)` — nhưng với JSONB thì phải
  `SELECT ... FROM machine_specs s JOIN LATERAL jsonb_array_elements(s.installed_software)`
  kèm điều kiện "chỉ lấy snapshot mới nhất/máy". PostgreSQL không có index thường giúp
  đếm tần suất phần tử mảng; GIN trên JSONB chỉ giúp "có/không", không giúp "đếm".
- `security: JSONB` — `firewall_enabled`, `windows_update_status`, `bitlocker`… nằm trong 1
  dict lồng; đếm theo từng trường = query `->>` + ép kiểu thủ công, không type-safe.
  `test_inventory_new_payload.py` đã thể hiện payload v1/v2/v3 trộn tên field
  (`displayName`/`name`, `enabled`/`status`, `size_bytes`/`size_gb`…) — JSONB chấp nhận
  mọi thứ, không ai đảm bảo kiểu dữ liệu ở tầng lưu trữ.

### 3.2. Không có "trạng thái hiện tại" denormalized

Mọi thống kê "hiện có bao nhiêu máy…" đều phải lặp lại phép tính:
`DISTINCT ON (machine_id) ... ORDER BY collected_at DESC` (đã lặp ở `machines.py:56-64`
cho `logged_user`, `get_machine`, `report._latest_spec`, alert…). Khi số máy × số snapshot
lớn, mỗi request thống kê quét cả lịch sử.

### 3.3. Agent thiếu collector (chặn cứng 2/4 thống kê người dùng cần)

`InventoryCollector.cs:599-608` — `GetSecurity()` chỉ gán `Antivirus, RdpEnabled, LocalAccounts`;
`WindowsUpdateStatus`/`Bitlocker` (dòng 70-71) **không bao giờ được set**; `firewall_enabled`
không tồn tại ở agent (chỉ có ở schema server + test payload). ⇒
"Số máy bật update" và "số máy bật firewall" hiện **không tính được dù schema có cột nào đi nữa**.

### 3.4. OS không chuẩn hóa để đếm

- `os_version` = `10.0.<build>` — Win10 và Win11 **cùng giá trị** (cùng NT 10.0).
- `os_name` = `ProductName + " " + DisplayVersion` (agent `GetOsName()`:167) → "Windows 11 Pro 25H2".
  Phân biệt Win10/Win11 phải parse chuỗi tự do từng dòng — không index, dễ vỡ khi Microsoft
  đổi cách đặt tên. Không có trường `os_family`/`os_release` chuẩn.

### 3.5. Thống kê làm bằng Python, không bằng SQL

`stats.py` load toàn bộ `machines` + `tokens` về Python để đếm (O(n) RAM/request);
`reports.py` kéo `selectinload(Machine.specs)` — càng thêm chỉ số thống kê, càng nặng.
Không có GROUP BY/index nào tận dụng được ở DB.

---

## 4. Schema đề xuất

Nguyên tắc: **giữ `machine_specs` làm lịch sử** (audit/trend/diff), **thêm lớp "hiện tại"
denormalized + chuẩn hóa** để thống kê là những câu GROUP BY đơn giản, index được.

### 4.1. Bảng mới `machine_current` — trạng thái hiện tại 1:1 với machines

Upsert mỗi lần nhận inventory mới (cùng transaction với insert `machine_specs`).

```python
class MachineCurrent(Base):
    """Snapshot MỚI NHẤT của mỗi máy — nguồn duy nhất cho thống kê 'hiện tại'."""
    __tablename__ = "machine_current"

    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # OS — chuẩn hóa để đếm (không parse chuỗi)
    os_name: Mapped[str | None] = mapped_column(String(128))          # raw, hiển thị
    os_product: Mapped[str | None] = mapped_column(String(128))       # "Windows 11 Pro" (ProductName)
    os_release: Mapped[str | None] = mapped_column(String(32))        # DisplayVersion "25H2"
    os_family: Mapped[str | None] = mapped_column(String(32), index=True)  # windows_10|windows_11|windows_server_*|linux|other
    os_version: Mapped[str | None] = mapped_column(String(64))
    os_build: Mapped[str | None] = mapped_column(String(32))
    os_arch: Mapped[str | None] = mapped_column(String(16))
    os_installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activation_status: Mapped[str | None] = mapped_column(String(32))

    # Phần cứng — ít thống kê, giữ JSONB gọn
    cpu: Mapped[dict | None] = mapped_column(JSONB)
    ram_gb: Mapped[float | None] = mapped_column(Float)
    disks: Mapped[list | None] = mapped_column(JSONB)
    gpu: Mapped[dict | None] = mapped_column(JSONB)
    mainboard: Mapped[dict | None] = mapped_column(JSONB)
    bios: Mapped[dict | None] = mapped_column(JSONB)
    network: Mapped[list | None] = mapped_column(JSONB)
    is_vm: Mapped[bool | None] = mapped_column(Boolean)
    logged_user: Mapped[str | None] = mapped_column(String(255))

    # Bảo mật — tách CỘT có kiểu rõ ràng (đếm được, index được)
    antivirus_enabled: Mapped[bool | None] = mapped_column(Boolean, index=True)  # ≥1 sản phẩm enabled
    antivirus_up_to_date: Mapped[bool | None] = mapped_column(Boolean, index=True)
    windows_update_enabled: Mapped[bool | None] = mapped_column(Boolean, index=True)  # auto-update bật
    windows_update_status: Mapped[str | None] = mapped_column(String(32), index=True)  # up-to-date|pending|paused|unknown
    bitlocker: Mapped[str | None] = mapped_column(String(16))       # on|off|unknown
    firewall_enabled: Mapped[bool | None] = mapped_column(Boolean, index=True)
    uac_enabled: Mapped[bool | None] = mapped_column(Boolean)
    secure_boot_enabled: Mapped[bool | None] = mapped_column(Boolean)
    rdp_enabled: Mapped[bool | None] = mapped_column(Boolean)
    usb_storage_blocked: Mapped[bool | None] = mapped_column(Boolean)
    antivirus: Mapped[list | None] = mapped_column(JSONB)           # chi tiết đầy đủ, hiển thị
```

> **Phương án thay thế** (nếu muốn tránh 1 join): đổ các cột trên thẳng vào `machines`.
> Khuyến nghị giữ bảng riêng — `machines` nhẹ, identity/lifecycle tách biệt, thống kê quét
> đúng 1 bảng hẹp `machine_current`.

### 4.2. Bảng mới `machine_software` — phần mềm đã cài (chuẩn hóa, đếm được)

```python
class MachineSoftware(Base):
    """App hiện tại của mỗi máy — 1 dòng/app/máy (upsert theo (machine_id, name))."""
    __tablename__ = "machine_software"
    __table_args__ = (
        UniqueConstraint("machine_id", "name", name="uq_machine_software_name"),
        Index("ix_machine_software_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    machine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machines.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    publisher: Mapped[str | None] = mapped_column(String(255))
    install_date: Mapped[str | None] = mapped_column(String(16))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC))
```

Mỗi lần nhận inventory đổi hash: **xóa toàn bộ app cũ của máy + insert danh sách mới**
(trong 1 transaction) — kích thước ~50–200 dòng/máy, tần suất 24h/lần hoặc khi cấu hình đổi
nên rẻ. Bảng này kiêm luôn:
- "App cài nhiều nhất": `GROUP BY name → COUNT(DISTINCT machine_id)` (index `name`).
- "Máy nào thiếu app X" (độ phủ triển khai phần mềm).
- Alert `software_new` (hiện comment "Phase 3 khi có cơ chế so sánh" — `monitor.py:183`):
  diff giữa `machine_software` và allowlist trở nên tầm thường.

### 4.3. Thêm cột chuẩn hóa vào `machine_specs` (giữ lịch sử)

Giữ nguyên `machine_specs` + thêm `os_product`, `os_release`, `os_family` (server tính khi
nhận payload, không đợi agent) — để truy vấn lịch sử/trend cũng đếm được theo family.
Thêm index GIN cho `installed_software`/`security` **chỉ cho** truy vấn hiếm ("tìm máy có app X"):
```sql
CREATE INDEX ix_specs_sw_gin ON machine_specs USING GIN (installed_software jsonb_path_ops);
CREATE INDEX ix_specs_sec_gin ON machine_specs USING GIN (security jsonb_path_ops);
```

### 4.4. Quy tắc sinh `os_family` (server-side, 1 chỗ duy nhất)

| Điều kiện (ProductName / DisplayVersion) | os_family |
|---|---|
| `ProductName` chứa "Windows 11" | `windows_11` |
| `ProductName` chứa "Windows 10" | `windows_10` |
| `ProductName` chứa "Windows Server 2016/2019/2022" | `windows_server_2016/2019/2022` |
| `os_name` chứa "linux"/"ubuntu"/"debian"… | `linux` |
| khác / không xác định | `other` |

Trong tương lai thêm trường `os_release` số (VD 26000→25H2) làm chuẩn so sánh build.

### 4.5. Index tóm tắt

| Bảng / cột | Index |
|---|---|
| `machine_current.os_family` | BTree → `GROUP BY os_family` |
| `machine_current.firewall_enabled`, `windows_update_enabled`, `windows_update_status`, `antivirus_enabled` | BTree → đếm nhanh |
| `machine_software.name` | BTree → top apps |
| `machine_specs.installed_software`, `security` | GIN (jsonb_path_ops) — truy vấn hiếm |

---

## 5. Query trước / sau cho 4 thống kê người dùng yêu cầu

### 5.1. Số máy Windows 10 / 11

```sql
-- TRƯỚC: parse chuỗi os_name của snapshot mới nhất từng máy (không index, phải DISTINCT ON)
-- SAU:
SELECT os_family, count(*) FROM machine_current GROUP BY os_family;
```

### 5.2. Số máy bật Windows Update

```sql
-- TRƯỚC: không tính được (agent không gửi trường này)
-- SAU:
SELECT windows_update_status, windows_update_enabled, count(*)
FROM machine_current GROUP BY 1, 2;
```

### 5.3. Số máy bật firewall

```sql
-- TRƯỚC: không tính được (agent không gửi trường này)
-- SAU:
SELECT firewall_enabled, count(*) FROM machine_current GROUP BY 1;
```

### 5.4. App được cài nhiều nhất

```sql
-- TRƯỚC: unnest JSONB của mọi snapshot + DISTINCT ON máy (chậm, khó index)
-- SAU:
SELECT name, count(DISTINCT machine_id) AS machines
FROM machine_software
GROUP BY name
ORDER BY machines DESC
LIMIT 20;
```

### 5.5. (Bonus) Máy nào thiếu app X — độ phủ triển khai

```sql
SELECT m.hostname FROM machines m
LEFT JOIN machine_software s ON s.machine_id = m.id AND s.name ILIKE '%chrome%'
WHERE m.status IN ('online','offline') AND s.id IS NULL;
```

---

## 6. Agent cần sửa (bắt buộc — không có thì schema mới cũng rỗng)

`InventoryCollector.cs` — bổ sung vào `GetSecurity()` và `Collect()`:

| Trường | Nguồn thu thập (Windows) |
|---|---|
| `windows_update_enabled` + `windows_update_status` | Registry `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\AUOptions` (2=notify,3=auto) + `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings` (PauseUpdatesStartTime → paused) |
| `firewall_enabled` | Registry `HKLM\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\{StandardProfile,DomainProfile,PublicProfile}\EnableFirewall` (1=bật; tổng hợp 3 profile) |
| `bitlocker` | `Win32_EncryptableVolume` (WMI, cần admin — thất bại → null) |
| `uac_enabled` | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\EnableLUA` |
| `secure_boot_enabled` | `Confirm-SecureBootUEFI` / registry (admin; fail → null) |
| `os_product`, `os_release` | Đọc `ProductName` và `DisplayVersion` **riêng biệt** (hiện đang gộp vào `os_name`) |

Chú ý quyền: một số trường cần admin (BitLocker, Secure Boot) — agent chạy quyền user thường
sẽ trả null; schema đã để nullable + `unknown`, UI phải hiểu "null ≠ tắt".

---

## 7. Lộ trình triển khai (migration + backfill)

1. **Migration 1 — schema**: tạo `machine_current`, `machine_software`; thêm `os_product`,
   `os_release`, `os_family` vào `machine_specs`; thêm GIN index (4.3).
2. **Backfill 1 lần**: script quét `machine_specs`, lấy snapshot mới nhất/máy → insert
   `machine_current`; unnest `installed_software` → insert `machine_software`.
3. **Đổi `inventory.py`**: sau khi insert spec → upsert `machine_current` (tính `os_family`,
   tách security ra cột) + replace `machine_software` (delete+insert cùng transaction).
4. **Đổi route đọc**: `stats.py` (thêm `GET /api/stats/inventory` trả các nhóm 5.1–5.4, RBAC
   theo `visible_org_ids`), `reports.py` (đọc `machine_current` thay `selectinload(specs)`),
   `machines.py` (`logged_user` lấy từ `machine_current`, bỏ DISTINCT ON).
5. **Agent release mới** (mục 6) — binary cũ vẫn tương thích (mọi trường optional).
6. **Portal**: dashboard thêm KPI "Win10/Win11", "Bật update", "Firewall", "Top phần mềm"
   (trang thống kê mới hoặc mở rộng dashboard); đọc field chuẩn v2, fallback v1 như hiện tại.

Giữ `machine_specs` nguyên vẹn → rollback an toàn: chỉ cần drop 2 bảng mới + bỏ cột mới.

---

## 8. Tác động / rủi ro / điểm giữ nguyên

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| `machine_specs` | **Giữ nguyên** làm lịch sử | audit cấu hình, diff (alert `hardware_changed`), trend theo thời gian |
| `heartbeats` (partition ngày) | Giữ nguyên | online/offline + timeline, không liên quan thống kê cấu hình |
| `machines` | Giữ nguyên (không thêm cột cấu hình) | identity/lifecycle nhẹ; tránh phình bảng hot |
| Denormalization | Chấp nhận | chuẩn cho OLAP nhẹ; tính nhất quán đảm bảo bằng **upsert cùng transaction** với insert spec |
| `machine_software` delete+insert | Chấp nhận | tần suất thấp (24h/đổi config), kích thước nhỏ |
| Backward-compat payload v1/v2/v3 | Giữ | agent cũ vẫn chạy; server chuẩn hóa tại tầng nhận (inventory.py) — **không sửa contract agent** |
| Trường cần admin (BitLocker, Secure Boot) | Null → "unknown" | không ép agent chạy admin; UI phân biệt null/unknown |

---

## 9. Việc cần làm tiếp theo (đề xuất)

1. Nếu đồng ý hướng này: tôi triển khai **Migration 1 + models mới + sửa `inventory.py`
   (upsert current/software) + endpoint `GET /api/stats/inventory` + backfill script** — không
   đụng agent trước.
2. Song song: bổ sung collector firewall/update/bitlocker ở agent (mục 6) — release agent mới.
3. Sau cùng: portal (KPI + trang thống kê) và cập nhật `API_CONTRACT.md` (thêm nhóm stats).
