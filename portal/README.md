# Portal — Hệ thống quản lý tài sản máy tính (IT Asset Inventory)

Front-end portal viết bằng **Next.js (App Router) + TypeScript + Tailwind CSS v4**,
theo `KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md` (v1.0) và `PLAN_THUC_HIEN.md` (v1.1).

> Kế hoạch gốc chọn "React + Vite"; dự án này dùng **Next.js** theo yêu cầu, với kiến
> trúc **BFF proxy**: mọi REST API đi qua route handler Next.js, JWT nằm trong
> **httpOnly cookie** (trình duyệt không đọc được token), tự động refresh + retry khi hết hạn.

---

## Cấu trúc

```
portal/
├── app/
│   ├── api/                      # ── BFF (route handlers, chạy phía server Next.js)
│   │   ├── auth/login|refresh|logout|session|ws-token|totp/*/
│   │   └── proxy/[...path]/      #   proxy tổng → FastAPI, tự refresh token
│   ├── login/                    # Đăng nhập JWT + 2FA TOTP (2 bước)
│   ├── (portal)/                 # Khu vực có sidebar (guard đăng nhập)
│   │   ├── dashboard/            # KPI + realtime WebSocket + máy gần đây
│   │   ├── machines/             # Danh sách máy (lọc org/status/tìm kiếm)
│   │   ├── machines/[id]/        # Chi tiết máy (specs, mạng, bảo mật, fingerprint)
│   │   ├── ghost-machines/       # Máy ma (> 30/60/90 ngày mất liên lạc)
│   │   ├── tokens/               # Sinh token + lệnh cài 1 dòng + phễu triển khai
│   │   ├── reports/              # Xuất Excel (mask ĐT mặc định)
│   │   ├── eol/                  # Báo cáo Windows EOL (tính client-side)
│   │   ├── audit/                # Audit log read-only (chờ GET /api/audit)
│   │   ├── security/             # Bật 2FA TOTP (QR + backup codes)
│   │   └── compliance/           # Thông báo tuân thủ pháp lý (mục 7.4)
│   └── layout.tsx / globals.css
├── components/                   # ui primitives, sidebar, auth/realtime context, compliance gate
├── lib/
│   ├── api.ts                    # API client trình duyệt (⇒ /api/proxy)
│   ├── backend.ts                # Helpers server: cookie, upstream, refresh, proxy
│   ├── types.ts                  # Kiểu dữ liệu phản chiếu schema backend
│   ├── format.ts                 # Nhãn trạng thái, màu, định dạng thời gian, mask ĐT
│   └── eol.ts                    # Bảng Windows EOL (os_name + os_build → ngày EOL)
```

## Chạy

```bash
npm install
# Sao chép cấu hình dev
cp .env.local.example .env.local
npm run dev        # http://localhost:3000
```

Cần backend FastAPI đang chạy (thư mục `server/`):
`API_BASE` mặc định trỏ `http://localhost:8000` — chỉnh trong `.env.local` nếu khác.

| Biến | Vai trò | Mặc định |
|---|---|---|
| `API_BASE` | URL backend (chỉ dùng phía server) | `http://localhost:8000` |
| `NEXT_PUBLIC_WS_BASE` | Địa chỉ WebSocket backend. Bỏ trống = cùng origin với portal (`/api/ws`) | `ws://localhost:8000` |

Tài khoản admin mặc định (backend tự seed trong môi trường dev):
`admin@example.gov.vn` / `ChangeMe!123` (xem `SEED_ADMIN_*` trong `.env` của server).

## Phân cấp tổ chức & người dùng (điều chỉnh theo yêu cầu)

- **1 máy thuộc 1 cá nhân** — máy gán `assigned_user_id`; chi tiết máy hiển thị
  "Cá nhân sở hữu" + tổ chức (`assigned_user_name`, `org_name`).
- **Cây tổ chức**: `UBND cấp xã` (`ubnd_xa`) / `Sở ban ngành` (`so_ban_nganh`)
  + cấp dưới `phong` / `don_vi` (phòng ban, đơn vị trực thuộc). Trang
  **"Cây tổ chức"** (`/organizations`) có nút "Thêm UBND cấp xã" / "Thêm Sở ban ngành"
  (Super Admin) và thêm cấp con (Org Admin trong phạm vi của mình).
- **Vai trò**:
  | Vai trò | Quyền |
  |---|---|
  | `super_admin` | Xem/quản lý **tất cả** tổ chức, máy, token |
  | `org_admin` | Admin của 1 tổ chức — xem được **tổ chức của mình + toàn bộ cấp dưới**; sinh token, xuất báo cáo trong phạm vi |
  | `viewer` | Xem read-only trong phạm vi tổ chức (+ cấp dưới) |
- Backend thực thi ở tầng cuối: `visible_org_ids()` (cây con) áp cho
  `GET /api/machines`, `/stats`, `/tokens`, `/reports/export`, `GET/POST /api/orgs`;
  cố gắng đụng org ngoài phạm vi → `403`.
- `admin_global` / `admin_org` (dữ liệu cũ) được chấp nhận như alias legacy
  của super_admin / org_admin — không phá dữ liệu đang tồn tại.

## Luồng bảo mật

- **Login**: `POST /api/auth/login` (BFF) → nếu user đã bật 2FA, nhận `requires_2fa=true`
  → nhập mã TOTP → server cấp JWT → Next.js ghi **httpOnly cookie** (`ai_access_token`,
  `ai_refresh_token`, sameSite=lax).
- **Mọi API** trong app gọi `/api/proxy/...` → route handler gắn `Authorization`,
  gặp 401 thì refresh (rotation) và retry 1 lần; 401 kéo dài → xóa cookie → về login.
- **WebSocket** `/api/ws?token=...` cần token ở query (trình duyệt không set header được)
  → route `auth/ws-token` trả access token ngắn hạn (30 phút) cho kết nối WS; reconnect
  backoff tối đa 30s.
- **RBAC**: sidebar ẩn nhóm theo vai trò (`super_admin` / `org_admin` / `viewer`);
  endpoint backend vẫn là tầng chặn cuối.

## Khớp với kế hoạch

| Sprint trong PLAN_THUC_HIEN.md | Đã làm trong portal |
|---|---|
| S1: khung + login JWT + danh sách máy | ✅ layout, login, `/machines` |
| S2: thêm máy mới (chế độ A) + phễu triển khai | ✅ `/tokens` — sinh token, one-liner copy, revoke |
| S3: dashboard realtime WS + bật 2FA + xác nhận tuân thủ | ✅ `/dashboard`, `/security`, compliance gate khi đăng nhập |
| S4: xuất báo cáo + audit log | ✅ `/reports` (Excel + PDF), `/audit` (lọc + phân trang + kiểm tra hash chain) |
| **Phase 2** | ✅ timeline bật/tắt (chi tiết máy), `/alerts` (rules + events), chế độ B `/enroll/[code]`, bulk CSV trong `/tokens`, rule tự gán tổ chức (trang tổ chức), máy ma, EOL |
| **Phase 3** | ✅ vòng đời tài sản + duyệt máy + rescan (chi tiết máy), `/approvals`, `/drifts` (fingerprint), `/diff` (so sánh cấu hình), `/offline-import` (file ký số, verify ECDSA) |
| **Phase 4** | ✅ `/leadership` (dashboard lãnh đạo), `/api-keys` (API mở + `GET /api/public/machines` với `X-API-Key`), báo cáo PDF (WeasyPrint) |

**Còn lại (chờ backend hoặc Phase sau):**

- SSO OIDC / AD-LDAP (Phase 4 — cần hạ tầng AD; backend chưa có endpoint).
- Alert "phần mềm lạ / phần cứng đổi" (cần cơ chế diff snapshot nhiều thời điểm).

**Audit log (đã hoàn thiện):**

- `GET /api/audit` — bảng nhật ký read-only với lọc (action/actor/q/máy/khoảng thời gian) + phân trang.
  RBAC: Super Admin xem mọi dòng; Org Admin chỉ xem dòng gắn máy trong cây tổ chức của mình; Viewer → 403.
- `GET /api/audit/actions` — danh sách action cho bộ lọc.
- `GET /api/audit/verify` — kiểm tra toàn bộ **hash chain** (prev_hash/content_hash, mục 7.2): phát hiện
  chính xác dòng đầu tiên bị sửa/xóa; trang `/audit` có nút "Kiểm tra" hiển thị kết quả + anchor hash.

## Lệnh

```bash
npm run dev        # dev server (Turbopack)
npm run build      # build production
npm run start      # chạy bản build
npm run typecheck  # tsc --noEmit
```