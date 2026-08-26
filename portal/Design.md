# Design System — Asset Inventory Portal (AssetManager theme)

Tài liệu thiết kế & quy tắc CSS cho portal Next.js. Mục tiêu: **desktop-first, giao diện đồng nhất, không lăn ngang toàn trang**.

> Căn cứ: `KE_HOACH_HE_THONG_QUAN_LY_MAY_TINH.md` + `PLAN_THUC_HIEN.md`.
> Theme tái tạo từ **Stitch project người dùng**: "AssetManager — Enterprise Infrastructure"
> (`https://stitch.withgoogle.com/projects/1399479754615558603`).
> Nguồn sự thật token nằm ở `app/globals.css` (CSS variables `:root`).

---

## 1. Nguyên tắc thiết kế

| Nguyên tắc | Ý nghĩa thực tiễn |
|---|---|
| **Desktop-first** | Tối ưu màn hình máy tính (≥ 1280px). Mobile phụ, không hy sinh desktop. |
| **Không lăn ngang toàn trang** | Nội dung rộng chỉ cuộn **bên trong card** (`.tbl-wrap`). Xem mục 6. |
| **Một nguồn sự thật** | Màu/khoảng cách/bo tròn lấy từ CSS variables trong `globals.css`. |
| **Đồng nhất qua primitive** | Mọi trang dùng chung `components/ui.tsx`. Không tự viết style riêng. |
| **Read-only agent** | Palette chuyên nghiệp, sidebar tối, accent trầm — không chói lóa. |

---

## 2. Bảng màu (theo Stitch AssetManager)

Định nghĩa trong `app/globals.css` `:root`.

### Brand (primary — xám nâu trầm, theo Stitch)
| Token | Giá trị | Dùng cho |
|---|---|---|
| `--brand-600` | `#635a5a` | Nút primary, link, active nav, focus ring |
| `--brand-700` | `#4f4848` | Hover primary |
| `--brand-50/100` | `#f5f5f5 / #e8e8e8` | Nền active nhẹ |

> Lưu ý: `overridePrimaryColor` trong Stitch là `#1e40af` (blue-800) nhưng các màn đã render
> dùng `primary: #635a5a` (xám nâu). Theme này bám theo **bản render thực tế** (#635a5a).

### Bề mặt
| Token | Giá trị | Dùng cho |
|---|---|---|
| `--bg` | `#f8fafc` | Nền trang chính |
| `--surface` | `#ffffff` | Card, input |
| `--surface-muted` | `#fff8f4` | Surface be ấm (header bảng) |
| `--surface-container` | `#f8ece0` | Container phụ |

### Sidebar tối (AssetManager)
- Nền: `bg-slate-900` (#0f172a), chữ `text-slate-300`, brand trắng.
- Nav active: `border-l-4 border-white bg-white/10 text-white font-bold`.
- Nav thường: `text-slate-400 hover:text-white hover:bg-white/5`.

### Viền
| Token | Giá trị |
|---|---|
| `--border` | `#c4c7c7` (outline-variant) |
| `--border-soft` | `#ede0d5` (surface-variant) |

### Chữ
| Token | Giá trị |
|---|---|
| `--ink` | `#201b13` (on-surface) |
| `--ink-muted` | `#444748` (on-surface-variant) |
| `--ink-subtle` | `#747878` (outline) |

### Trạng thái
`--ok` emerald-600 · `--warn` amber-600 · `--bad` `#ba1a1a` (error Stitch).
Badge theo `lib/format.ts` (không hardcode).

---

## 3. Typography

- Font: **Inter** (theo Stitch) — `--font-sans`.
- Scale (theo Stitch typography):
  - `headline-xl`: 30px/700/-0.02em — trang chính
  - `headline-lg`: 24px/600/-0.01em — H1 section
  - `headline-md`: 20px/600 — H2 card
  - `body-md`: 14px/400 — thân
  - `label-md`: 12px/600/+0.05em — label, KPI label (uppercase)
  - `data-mono`: 13px/500 — UUID, IP (mono)
- Bật antialiased + optimizeLegibility; số liệu `tabular-nums`.

---

## 4. Khoảng cách & bo tròn

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--r-sm` | 0.25rem | badge, code inline |
| `--r-md` | 0.5rem | input, button |
| `--r-lg` | 0.75rem | card, table wrap |
| `--r-xl` | 1rem | modal |

Spacing theo Stitch: `unit 8px`, `stack-md 12px`, `stack-lg 24px`, `container-padding 24px`, `gutter 16px`.

---

## 5. Shadow

`--shadow-card` (nhẹ) cho card/table · `--shadow-pop` cho modal. Không dùng shadow đậm mặc định.

---

## 6. Chống lăn ngang toàn trang (QUAN TRỌNG)

1. `html, body { max-width: 100%; overflow-x: hidden; }` — chặn cuối cùng.
2. Layout root: `<div className="flex min-h-screen overflow-x-clip">` + cột nội dung `min-w-0 flex-1`.
3. `main`: `min-w-0`, `max-w-[1320px]`.

### Quy tắc bắt buộc với bảng
- **Mọi `<table>` PHẢI** bọc `<div className={TABLE_WRAP}>` (= `.tbl-wrap`).
- `.tbl-wrap` = `overflow-x: auto` → bảng rộng cuộn NỘI BỘ.
- `TABLE` = `w-full` (co theo container). **KHÔNG dùng `min-w-max`**.
- Cột cần 1 dòng: `whitespace-nowrap` cho th/td.
- UUID dài → `shortUuid`/`break-all`; lệnh dài → `break-all`; flex item có `min-w-0`.

---

## 7. Components (`components/ui.tsx`)

| Component | Khi nào dùng |
|---|---|
| `PageHeader` | Đầu mỗi trang |
| `Card` | Khối nội dung chính |
| `Button` | variant: primary/secondary/outline/danger/success/ghost |
| `Input`, `Select`, `Textarea`, `Field` | Form |
| `Badge`, `StatusDot` | Trạng thái (màu từ `format.ts`) |
| `Spinner`, `EmptyState` | Loading / rỗng |
| `ErrorBanner` | Lỗi tải |
| `Modal` | Hộp thoại |
| `TABLE_WRAP`, `TABLE`, `THEAD`, `TH`, `TD`, `TR_HOVER` | Bảng |

---

## 8. Layout & shell (AssetManager)

```
┌───────────────────────────────────────────────────────────┐
│ Sidebar (w-[260px], TỐI bg-slate-900)   │ Header: title + │
│  - icon security + AssetManager         │  avatar user +  │
│  - nav: Dashboard / Assets / Agent Config / User Access / │
│        Installers / System Logs / Settings                │
│  - active: vạch trái trắng border-l-4                   │
├───────────────────────────────────────────────────────────┤
│ main (max-w-1320, min-w-0): PageHeader → Card(s) → table │
│ footer                                                    │
└───────────────────────────────────────────────────────────┘
```

---

## 9. KPI card (theo Stitch)

```css
.kpi-card { position: relative; overflow: hidden; border: 1px solid var(--border-soft);
            background: var(--surface); border-radius: var(--r-lg); }
.kpi-card::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0;
                    width: 4px; background: var(--brand-600); }
```
- Label: `text-[11px] uppercase tracking-wider text-slate-400` (label-md).
- Số: `text-2xl font-bold tabular-nums`.
- Grid: `grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-4` (dashboard), `grid-cols-4` (Stitch).

---

## 10. Checklist khi thêm trang/sửa UI

- [ ] Dùng `PageHeader` + `Card` + primitive `ui.tsx`.
- [ ] Mọi bảng bọc `TABLE_WRAP`; `TABLE` không có `min-w-max`.
- [ ] Flex/grid chứa bảng có `min-w-0`.
- [ ] Chuỗi dài có `break-all`/`shortUuid`/`truncate`.
- [ ] Badge màu từ `format.ts`.
- [ ] KPI dùng `.kpi-card` (vạch trái).
- [ ] Kiểm tra không lăn ngang toàn trang.
- [ ] Số liệu `tabular-nums`.

---

## 11. Quyết định thiết kế (log)

- **Sidebar tối** (bg-slate-900) theo Stitch AssetManager — người dùng yêu cầu tái tạo đúng.
- **Primary #635a5a** (xám nâu) theo bản render Stitch thực tế.
- **Font Inter**.
- **Bỏ `min-w-max` TABLE** → `.tbl-wrap` cuộn nội bộ.
- **KPI có vạch màu trái** (`.kpi-card`).

---

## 12. Tích hợp Stitch (Google MCP)

Script: `stitch_gen.py` (generate), `stitch_gen_multi.py` (hàng loạt),
`stitch_fetch_user.py` (tải HTML project người dùng về `stitch-ref/user-project/`).

Quy trình: `create_project` → `upload_design_md` → `create_design_system_from_design_md`
→ `generate_screen_from_text` (`designSystem: "assets/{id}"`, `deviceType: "DESKTOP"`).

Project người dùng: **1399479754615558603** — "AssetManager — Enterprise Infrastructure",
7 màn hình (Dashboard, Assets×2, Agent Config, User Access, Installers, Thống kê).
