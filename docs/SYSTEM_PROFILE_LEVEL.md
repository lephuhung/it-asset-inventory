# HỒ SƠ CẤP ĐỘ HỆ THỐNG THÔNG TIN (System Security Level Profile)

> Tài liệu mô tả tính năng **hồ sơ cấp độ hệ thống thông tin** — khớp implementation thực tế trên branch `feat/system-info-level-profile`.
> Code tham chiếu: `server/app/db/models.py`, `server/app/api/routes/system_profiles.py`, `portal/app/(portal)/system-profiles/`.

---

## 1. Tổng quan nghiệp vụ

Theo quy định về bảo đảm an toàn hệ thống thông tin, mỗi hệ thống thông tin phải:
1. Đơn vị **tự xây dựng hồ sơ** xác định **cấp độ** (1–3) kèm bức tranh toàn cảnh tổ chức + hạ tầng kỹ thuật.
2. **Trình cơ quan có thẩm quyền** ra **quyết định** xác nhận hệ thống đúng theo cấp độ đã đề xuất.
3. Sau khi có quyết định, đơn vị **mua sắm trang thiết bị, đáp ứng đủ các yêu cầu an toàn** theo đúng hồ sơ đã xây dựng.
4. Đơn vị phải **đáp ứng đủ n yêu cầu an toàn** của cấp độ; mỗi yêu cầu hoàn thành đều phải qua **thẩm định** của quản trị viên hệ thống (Super Admin) mới được tính là đạt.

Tính năng này trên portal quản lý trọn vẹn chu trình: **soạn hồ sơ → trình duyệt → phê duyệt (số quyết định) → khai báo hoàn thành yêu cầu → thẩm định → thống kê/đáp ứng cấp độ**.

### 1.1. Vai trò & quyền hạn

| Vai trò | Quyền |
|---|---|
| **Viewer** | Chỉ **xem** hồ sơ trong phạm vi tổ chức của mình (và cấp dưới) |
| **Org Admin (Admin)** | Tạo / sửa / xóa hồ sơ **của đơn vị mình**, quản lý thiết bị – máy – ứng dụng – vùng mạng, **trình duyệt** hồ sơ, **khai báo hoàn thành** yêu cầu an toàn |
| **Super Admin** | Toàn quyền mọi đơn vị + **phê duyệt / từ chối hồ sơ**, **thẩm định yêu cầu an toàn**, **quản trị catalog yêu cầu theo cấp độ**; tạo hồ sơ kèm số quyết định → duyệt ngay |

---

## 2. Mô hình dữ liệu

### 2.1. `system_profiles` — Hồ sơ cấp độ

| Trường | Kiểu | Mô tả |
|---|---|---|
| `org_id` | UUID FK organizations | Đơn vị sở hữu hồ sơ (unique theo cặp `org_id` + `code`) |
| `code` | String(64) | Mã hồ sơ, do đơn vị tự đặt (vd `HTTT-2026-01`) |
| `name` | String(255) | Tên hệ thống thông tin |
| `level` | Integer 1–3 | Cấp độ đề xuất / được công nhận (CHECK constraint) |
| `description` | Text | Mô tả phạm vi, chức năng |
| `status` | String(32) | `drafted` → `pending_review` → `approved` / `rejected` |
| `decision_number` | String(255) | Số quyết định phê duyệt |
| `decision_date` | DateTime | Ngày quyết định |
| `decision_agency` | String(255) | Cơ quan ban hành quyết định |
| `reviewed_by` / `reviewed_at` / `review_note` | — | Ai duyệt, khi nào, ghi chú (lý do từ chối…) |
| `diagram_mermaid` | Text | Code Mermaid **sơ đồ lô-gic** |
| `physical_diagram_mermaid` | Text | Code Mermaid **sơ đồ vật lý** |
| `physical_location` | Text | Phạm vi vật lý — địa điểm lắp đặt thiết bị |
| `user_accounts` | Integer | Quy mô người dùng (số lượng tài khoản) |
| `data_volume` | Text | Lượng dữ liệu xử lý (mô tả) |
| `service_audience` | String(32) | Đối tượng sử dụng: `internal` / `citizens` / `businesses` / `mixed` |
| `created_by` / `created_at` / `updated_at` | — | — |

### 2.2. `system_devices` — Thiết bị trong hệ thống

Thiết bị hạ tầng khai báo tay (firewall, switch, máy chủ…) — agent chỉ thu thập được máy tính:

| Trường | Mô tả |
|---|---|
| `name`, `device_code`, `tag` | Tên, mã thiết bị, mã tag (do đơn vị tự đặt) |
| `device_type` | Mã loại thiết bị — tham chiếu catalog **`device_types`** (quản trị động, §2.9) |
| `model` | Hãng sản xuất / chủng loại |
| `location` | Vị trí triển khai thực tế |
| `purpose` | Mục đích sử dụng trong hệ thống |
| `ip` | Địa chỉ IP |
| `machine_id` (nullable) | Liên kết tới 1 Machine đã enroll (tùy chọn, phải cùng đơn vị) |

### 2.3. `system_profile_machines` — Máy tính thuộc hệ thống

Bảng join nhiều–nhiều (composite PK `profile_id` + `machine_id`): gắn các máy tính agent đã enroll vào hồ sơ phục vụ thống kê và sơ đồ. Chỉ gắn được máy **cùng đơn vị** với hồ sơ.

### 2.4. `system_profile_parties` — Chủ quản & Đơn vị vận hành

| Trường | Mô tả |
|---|---|
| `role` | `owner` (chủ quản) / `operator` (đơn vị vận hành) — **unique theo cặp `profile_id` + `role`** |
| `name` | Tên đơn vị |
| `mandate_document` | Văn bản quy định chức năng, nhiệm vụ, quyền hạn |
| `legal_representative` / `representative_title` | Người đại diện pháp luật + chức vụ |
| `address` / `phone` / `email` | Địa chỉ và thông tin liên hệ |

### 2.5. `system_profile_applications` — Ứng dụng / dịch vụ

| Trường | Mô tả |
|---|---|
| `name` | Tên ứng dụng/dịch vụ cung cấp |
| `machine_id` (nullable) | Máy chủ cài đặt — liên kết Machine đã enroll (lấy hostname tự động); phải cùng đơn vị |
| `server_name` / `os_name` | Nhập tay khi máy chủ chưa được agent quản lý |
| `role` | Vai trò / nhiệm vụ của dịch vụ |
| `url` / `note` | URL truy cập, ghi chú |

### 2.6. `system_profile_ip_ranges` — Quy hoạch vùng mạng & IP

| Trường | Mô tả |
|---|---|
| `zone` | Tên vùng mạng: nội bộ / biên mạng / DMZ… |
| `zone_description` | Mô tả vùng |
| `cidr` | Dải địa chỉ IP (vd `10.10.1.0/24`) |
| `ip_kind` | `private` (IP nội bộ) / `public` (IP công khai) |
| `gateway` | Gateway của dải (tùy chọn) |

### 2.7. `level_requirements` — Catalog yêu cầu an toàn theo cấp độ

Mỗi cấp độ (1–3) có **n yêu cầu**; đơn vị phải đáp ứng **đủ n yêu cầu** của cấp độ hồ sơ đã chọn mới được coi là đảm bảo an toàn theo cấp độ đó.

| Trường | Mô tả |
|---|---|
| `level` | Cấp độ 1–3 (CHECK constraint) |
| `code` | Mã yêu cầu, unique (vd `L1-SAO_LUU`) |
| `title` / `description` | Tên + mô tả chi tiết yêu cầu |
| `sort_order` / `is_active` | Thứ tự hiển thị; tắt bật (yêu cầu `is_active=false` không sinh vào hồ sơ mới nhưng giữ nguyên ở hồ sơ cũ) |

Migration seed sẵn ~16 yêu cầu mẫu chia theo 3 cấp độ (phân quyền, mật khẩu, sao lưu ở cấp 1 → firewall biên giới, ghi log, phục hồi khẩn cấp ở cấp 2 → MFA, mã hóa, pentest, bảo vệ vật lý ở cấp 3). **Super Admin chỉnh sửa catalog** theo quy định thực tế; catalog chỉ mang tính seed — nội dung yêu cầu phải được rà soát theo văn bản pháp lý hiện hành.

### 2.8. `system_profile_requirements` — Trạng thái đáp ứng từng yêu cầu (kèm thẩm định)

Tự sinh khi **tạo hồ sơ** hoặc **đổi cấp độ** (đồng bộ theo catalog của cấp độ, giữ trạng thái các hàng còn hiệu lực, gỡ hàng thuộc cấp độ khác):

| Trường | Mô tả |
|---|---|
| `status` | `pending` → `requested` → `verified` / `rejected` (chi tiết §3.2) |
| `evidence` | Cách đơn vị đáp ứng (bằng chứng, tài liệu…) |
| `requested_by` / `requested_at` | Ai khai báo hoàn thành |
| `reviewed_by` / `reviewed_at` / `review_note` | Kết quả thẩm định |

**Đáp ứng cấp độ** (`level_compliant`) = `requirements_verified == requirements_total` và `requirements_total > 0`.

### 2.9. `device_types` — Catalog loại thiết bị (quản trị động)

Super Admin **thêm mới / cập nhật** loại thiết bị ngay trên portal, không cần sửa code:

| Trường | Mô tả |
|---|---|
| `code` | Mã loại, unique, tự normalize về chữ thường (vd `camera`) — **không đổi được sau khi tạo** vì `system_devices.device_type` tham chiếu theo code |
| `label` | Tên hiển thị (vd "Camera giám sát") |
| `icon` | **Emoji gắn vào node trên sơ đồ Mermaid** (vd 📷) — hiển thị được cả ở `securityLevel: strict` (đã verify trong Chromium; cú pháp `fa:fa-*` của Font Awesome không dùng được vì portal không tải FA CSS) |
| `sort_order` / `is_active` | Thứ tự dropdown; tắt bật — loại `is_active=false` ẩn khỏi form nhập nhưng giữ nguyên ở dữ liệu/hồ sơ cũ |

Migration seed 8 loại chuẩn: firewall 🛡️, router 📡, switch 🔀, server 🖥️, workstation 💻, storage 💾, UPS 🔋, other 📦. Xóa bị chặn (`409`) nếu đã có thiết bị dùng → dùng `is_active=false`. Generator sơ đồ (`lib/system-profile-diagram.ts`) nhận icon/label động từ catalog, fallback về map chuẩn; node nối theo tầng điển hình `Internet → firewall → router → switch → server/workstation → …` (loại ngoài danh sách tầng nối vào cuối).

---

## 3. Quy trình nghiệp vụ

### 3.1. Quy trình phê duyệt hồ sơ

```
                        ┌──────────── Super Admin tạo kèm số quyết định ────────────┐
                        ▼                                                            │
  Admin tạo hồ sơ ──► drafted ──(Admin: Trình duyệt)──► pending_review ──(Super Admin duyệt)──► approved
                        ▲                                        │
                        │                                        ├─ reject ──► rejected
                        │                                        │                │
                        └──── Admin sửa nội dung (về drafted,    └─ approve: bắt buộc
                              xóa review_note) ◄───────────────────── nhập số quyết định
```

- Hồ sơ `approved`: Admin **không sửa/xóa được** (Super Admin vẫn sửa được); danh sách hiển thị trạng thái "chưa đáp ứng" cho đến khi có quyết định.
- Hồ sơ `rejected`: Admin sửa nội dung → tự về `drafted`, xóa ghi chú từ chối → trình lại.
- Admin chỉ xóa được hồ sơ `drafted` / `rejected`; Super Admin xóa được mọi trạng thái.
- **Super Admin tạo hồ sơ kèm `decision_number`** → hồ sơ ở trạng thái `approved` ngay (phục vụ nhập hồ sơ đã có quyết định từ trước).

### 3.2. Quy trình thẩm định yêu cầu an toàn

```
  pending ──(Admin khai báo hoàn thành + evidence, trình thẩm định)──► requested
                                                                          │
                                     ┌──────────── (Super Admin thẩm định) ────────────┤
                                     ▼                                                  ▼
                                 verified (đạt)                                     rejected (không đạt, kèm review_note)
                                     ▲                                                  │
                                     └──── (chỉ verified mới tính vào level_compliant)  └── Admin trình lại được
```

- Hồ sơ chỉ **đáp ứng cấp độ** khi **tất cả** yêu cầu của cấp độ ở trạng thái `verified`.
- `verified` không thể trình thẩm định lại; `rejected` có thể trình lại sau khi bổ sung.

---

## 4. API

Prefix chung: `/api/system-profiles` (router `system_profiles.router`) và `/api/level-requirements` (router `system_profiles.catalog_router`). Phân trang kiểu `Page<T>` (`items/total/limit/offset`). Scoped theo tổ chức: Admin chỉ thấy/thao tác trong cây tổ chức của mình; các endpoint trả `403` nếu ngoài phạm vi, `404` nếu không tồn tại, `409` nếu trùng, `422` nếu sai định dạng enum/pattern.

### 4.1. Hồ sơ

| Method | Endpoint | Vai trò | Mô tả |
|---|---|---|---|
| `GET` | `/api/system-profiles` | mọi user (scoped) | Danh sách. Query: `org_id`, `level`, `status`, `q`, `limit`, `offset` |
| `POST` | `/api/system-profiles` | admin | Tạo hồ sơ. Body: `org_id`, `code`, `name`, `level`, `description?`, `diagram_mermaid?`; Super Admin thêm `decision_number?`, `decision_date?`, `decision_agency?` → approved ngay |
| `GET` | `/api/system-profiles/{id}` | mọi user (scoped) | Chi tiết đầy đủ: devices, machines, requirements, parties, applications, ip_ranges, counters (`requirements_total/verified`, `level_compliant`) |
| `PATCH` | `/api/system-profiles/{id}` | admin | Sửa: `name`, `level` (tự đồng bộ lại yêu cầu), `description`, `diagram_mermaid`, `physical_diagram_mermaid`, `physical_location`, `user_accounts`, `data_volume`, `service_audience`. Chặn khi `approved` (trừ Super Admin); hồ sơ `rejected` sửa xong về `drafted` |
| `DELETE` | `/api/system-profiles/{id}` | admin | Xóa (Admin: chỉ `drafted`/`rejected`) |
| `POST` | `/api/system-profiles/{id}/submit` | admin | Trình duyệt: `drafted`/`rejected` → `pending_review` |
| `POST` | `/api/system-profiles/{id}/review` | super admin | Duyệt: `action=approve` (bắt buộc `decision_number`, optional `decision_date`, `decision_agency`) hoặc `action=reject` (kèm `review_note`). Chỉ duyệt được hồ sơ `pending_review` |

### 4.2. Thiết bị & máy tính

| Method | Endpoint | Vai trò | Mô tả |
|---|---|---|---|
| `POST` | `/{id}/devices` | admin | Thêm thiết bị. Body: `name`*, `device_type`* (enum `DeviceKind`), `device_code?`, `tag?`, `ip?`, `model?`, `location?`, `purpose?`, `machine_id?`, `sort_order?` |
| `PUT` / `DELETE` | `/{id}/devices/{device_id}` | admin | Sửa / xóa thiết bị |
| `POST` | `/{id}/machines?machine_id={mid}` | admin | Gắn Machine đã enroll (cùng đơn vị; trùng → `409`) |
| `DELETE` | `/{id}/machines/{machine_id}` | admin | Gỡ máy |

### 4.3. Chủ quản / vận hành, ứng dụng, vùng mạng

| Method | Endpoint | Body chính |
|---|---|---|
| `POST` / `PUT` / `DELETE` | `/{id}/parties[/{party_id}]` | `role` (`owner`\|`operator`), `name`*, `mandate_document?`, `legal_representative?`, `representative_title?`, `address?`, `phone?`, `email?` |
| `POST` / `PUT` / `DELETE` | `/{id}/applications[/{app_id}]` | `name`*, `machine_id?`, `server_name?`, `os_name?`, `role?`, `url?`, `note?` |
| `POST` / `PUT` / `DELETE` | `/{id}/ip-ranges[/{range_id}]` | `zone`*, `cidr`*, `ip_kind` (`private`\|`public`), `zone_description?`, `gateway?`, `note?` |

### 4.4. Catalog loại thiết bị

| Method | Endpoint | Vai trò | Mô tả |
|---|---|---|---|
| `GET` | `/api/device-types?active_only=` | mọi user | Danh sách loại (mặc định chỉ loại đang bật) |
| `POST` | `/api/device-types` | super admin | Thêm loại: `code`*, `label`*, `icon?` (emoji), `sort_order?`, `is_active?`. Trùng code → `409`; code tự normalize chữ thường |
| `PATCH` | `/api/device-types/{id}` | super admin | Sửa `label` / `icon` / `sort_order` / `is_active` (không đổi `code`) |
| `DELETE` | `/api/device-types/{id}` | super admin | Xóa; đang được dùng → `409` |

### 4.5. Yêu cầu an toàn theo cấp độ

| Method | Endpoint | Vai trò | Mô tả |
|---|---|---|---|
| `GET` | `/api/level-requirements?level=` | mọi user | Catalog yêu cầu (filter theo cấp độ) |
| `POST` / `PATCH` / `DELETE` | `/api/level-requirements[/{rid}]` | super admin | Quản trị catalog. Xóa bị chặn (`409`) nếu đã có hồ sơ dùng → dùng `is_active=false` |
| `POST` | `/{id}/requirements/{row_id}/request` | admin | Khai báo hoàn thành + trình thẩm định. Body: `evidence`* (bắt buộc). `verified`/`requested` → `400` |
| `POST` | `/{id}/requirements/{row_id}/review` | super admin | Thẩm định: `action=verify` \| `reject` (kèm `review_note?`). Chỉ thẩm định được hàng `requested` |

> Toàn bộ thao tác ghi `audit_log` với action `system_profile.*` / `level_requirement.*`.

---

## 5. Portal

Nhóm menu **"Tổ chức" → "Hồ sơ cấp độ HTTT"** (chỉ hiện với Admin; route `portal/app/(portal)/system-profiles/`).

### 5.1. Danh sách (`/system-profiles`)

- Thống kê nhanh: tổng hồ sơ, đã phê duyệt, chờ duyệt, phân bổ theo cấp độ.
- Filter: đơn vị (Super Admin), cấp độ, trạng thái, tìm theo tên.
- Bảng: tên/mã hồ sơ, đơn vị, badge cấp độ, badge trạng thái, số quyết định (hoặc "— chưa đáp ứng —"), số thiết bị/máy.

### 5.2. Chi tiết (`/system-profiles/[id]`) — 6 tab

| Tab | Nội dung |
|---|---|
| **Thông tin** | Thuộc tính hồ sơ + khối quyết định phê duyệt; badge **Đáp ứng cấp độ X** / **Chưa đủ yêu cầu (m/n)**; khối *Phạm vi & quy mô* (modal sửa: địa điểm, số tài khoản, lượng dữ liệu, đối tượng sử dụng); thẻ *Chủ quản & đơn vị vận hành* (modal thêm/sửa đầy đủ trường pháp lý) |
| **Thiết bị** | Bảng CRUD thiết bị (loại — dropdown từ catalog động, mã, IP, chủng loại, vị trí + modal có mục đích sử dụng). Super Admin có nút **"Quản lý loại thiết bị"**: bảng thêm/sửa/xóa loại kèm icon emoji |
| **Máy tính** | Gắn/gỡ máy đã enroll qua select danh sách máy của đơn vị |
| **Yêu cầu ATTT (m/n)** | Bảng yêu cầu theo cấp độ: trạng thái, bằng chứng, ghi chú thẩm định. Admin: "Trình thẩm định" (modal nhập bằng chứng). Super Admin (khi `requested`): "Đạt / Không đạt" (modal xem bằng chứng + ghi chú) |
| **Ứng dụng** | Bảng CRUD ứng dụng/dịch vụ (máy chủ = chọn Machine hoặc nhập tay server/OS) |
| **Vùng mạng & IP** | Bảng CRUD dải IP theo vùng (badge Private/Public, gateway) |
| **Sơ đồ** | 2 khối render code Mermaid: *lô-gic* và *vật lý* — vẽ ở ngoài (mermaid.live), dán code vào ô chỉnh sửa, lưu và xem trong app (package `mermaid`, dynamic import). Nút **"Gợi ý từ danh mục thiết bị"** tự sinh code Mermaid từ tab Thiết bị: node nối theo tầng điển hình `Internet → firewall → router → switch → máy chủ/máy trạm → …`, mỗi node gắn **icon theo loại thiết bị** (emoji, hiển thị được cả ở `securityLevel: strict`): firewall 🛡️, router 📡, switch 🔀, server 🖥️, workstation 💻, storage 💾, UPS 🔋, khác 📦 (`lib/system-profile-diagram.ts`).

> ✅ **Đã kiểm chứng render thật**: flowchart với icon emoji + `securityLevel: "strict"` được verify trong Chromium (node + nhãn hiển thị đúng, 4 node / 3 mũi tên). Lựa chọn emoji thay vì `fa:fa-*` của Font Awesome là chủ đích — cú pháp `fa:` cần Font Awesome CSS + `htmlLabels`, không có sẵn trong portal. |

Các nút hành động ở header: **Trình duyệt** (Admin, khi `drafted`/`rejected`), **Phê duyệt / Từ chối** (Super Admin, khi `pending_review` — modal duyệt bắt buộc nhập số quyết định), **Xóa**.

---

## 6. Migration & triển khai

Các migration trên branch (thứ tự):

| Revision | Nội dung |
|---|---|
| `a1b2c3d4e5f7` | `system_profiles`, `system_devices`, `system_profile_machines` |
| `b2c3d4e5f6a7` | `level_requirements` (seed catalog mẫu) + `system_profile_requirements` |
| `c3d4e5f6a7b8` | Dossier: `system_profile_parties/applications/ip_ranges` + cột phạm vi & quy mô + `system_devices.location/purpose` |
| `d4e5f6a7b8c9` | `device_types` (catalog loại thiết bị động, seed 8 loại chuẩn) |

```bash
docker compose exec api alembic upgrade head   # sau khi merge/deploy
```

> ⚠️ Test DB (`tests/conftest.py`) dùng `Base.metadata.create_all`, **không chạy alembic** → catalog yêu cầu phải seed trong test (xem `_seed_requirements`).

---

## 7. Kiểm thử

`server/tests/test_system_profiles.py` — 15 test:

- **Luồng phê duyệt hồ sơ**: tạo → submit → duyệt (bắt buộc số quyết định) → chặn sửa/xóa sau khi approved; Super Admin tạo approved trực tiếp; reject → sửa → về drafted; chặn trùng mã hồ sơ.
- **RBAC & scoping**: org_admin không thấy/sửa hồ sơ đơn vị khác; không được duyệt.
- **Yêu cầu an toàn**: tự sinh theo cấp độ; trình thẩm định (bắt buộc evidence); Admin không tự thẩm định; verify đủ n → `level_compliant=true`; reject → trình lại; đổi cấp độ → đồng bộ lại danh sách yêu cầu.
- **Catalog**: Super Admin CRUD + chặn trùng code + yêu cầu `is_active=false` không sinh vào hồ sơ mới + chặn xóa khi đang được dùng.
- **Dossier**: parties (chặn trùng role, sai role → 422), applications (validate máy cùng đơn vị), ip-ranges (sai `ip_kind` → 422), scope fields (sai `service_audience` → 400).
- **Catalog loại thiết bị**: CRUD Super Admin (normalize code, chặn trùng, chặn xóa khi đang dùng), loại mới dùng được ngay khi nhập thiết bị, `active_only` filter; test DB seed catalog trong `conftest.py` (không chạy alembic).

Portal: kiểm tra kiểu bằng `tsc --noEmit`; test unit theo `portal/__tests__/`.
