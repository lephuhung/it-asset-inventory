# Logo - Quản trị tài nguyên máy tính

Bộ logo cho hệ thống **Quản trị tài nguyên máy tính**, thiết kế theo phong cách **Modern Geometric** với bảng màu **Blue Indigo** chuyên nghiệp.

## 🎨 4 Phương án logo

| # | Tên | Phong cách | Tốt nhất cho |
|---|-----|------------|--------------|
| 1 | **Minimal Q Monogram** | Chữ "Q" trong hexagon | ⭐ Favicon (16x16) — đọc rõ ở mọi kích thước |
| 2 | **Hexagonal Network** | Hexagon với node mạng lưới | Logo chính, app icon |
| 3 | **Isometric Cube** | Khối 3D server | Dashboard, marketing |
| 4 | **Resource Grid** | Lưới 3x3 ô | Dashboard, web portal |

## 📐 Bảng màu (Blue Indigo Palette)

- **Primary:** `#1E3A8A` (Navy Blue — uy tín, chuyên nghiệp)
- **Secondary:** `#2563EB` / `#3B82F6` (Blue — công nghệ, tin cậy)
- **Accent:** `#60A5FA` / `#93C5FD` (Light Blue — tươi mới)
- **Highlight:** `#DBEAFE` (Very Light Blue)
- **Text/Border:** `#0F172A` (Slate Dark)

## 📁 Cấu trúc thư mục

```
logo-output/
├── preview.html                ← Mở file này để xem tất cả logo
├── README.md                   ← File này
│
├── logo-minimal.svg            ← Logo 1: Minimal Q (source vector)
├── logo-hexagonal.svg          ← Logo 2: Hexagonal Network (source vector)
├── logo-cube.svg               ← Logo 3: Isometric Cube (source vector)
├── logo-grid.svg               ← Logo 4: Resource Grid (source vector)
│
├── favicons-minimal/
│   ├── favicon.ico             ← Favicon đa phân giải
│   ├── favicon-16x16.png       ← Favicon tab trình duyệt
│   ├── favicon-32x32.png       ← Favicon bookmark
│   ├── favicon-48x48.png
│   ├── favicon-64x64.png
│   ├── favicon-128x128.png
│   ├── favicon-180x180.png     ← Apple Touch Icon
│   ├── favicon-192x192.png     ← Android Chrome
│   ├── favicon-256x256.png     ← Windows tile
│   └── favicon-512x512.png     ← High-res
│
├── favicons-hexagonal/
│   └── (cùng cấu trúc)
│
├── favicons-cube/
│   └── (cùng cấu trúc)
│
└── favicons-grid/
    └── (cùng cấu trúc)
```

## 🚀 Cách sử dụng làm Favicon

### Bư�c 1: Chọn logo
Mở `preview.html` trong trình duyệt để xem và so sánh các logo.

### Bước 2: Copy file vào thư mục gốc website
```bash
cp favicons-minimal/favicon.ico /your-website/
cp favicons-minimal/favicon-16x16.png /your-website/
cp favicons-minimal/favicon-32x32.png /your-website/
cp favicons-minimal/apple-touch-icon.png /your-website/  # rename from 180x180
```

### Bước 3: Thêm HTML vào `<head>`
```html
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
```

### Bước 4 (tùy chọn): Tạo `site.webmanifest`
```json
{
  "name": "Quản trị tài nguyên máy tính",
  "short_name": "QTRTN",
  "icons": [
    { "src": "/favicon-192x192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/favicon-512x512.png", "sizes": "512x512", "type": "image/png" }
  ],
  "theme_color": "#1E3A8A",
  "background_color": "#FFFFFF"
}
```

## � Gợi ý

- **Logo minimal** (`logo-minimal.svg`) được khuyến nghị cho favicon vì đơn giản, đọc rõ ở 16x16.
- **Logo hexagonal** phù hợp làm logo chính trên website, app icon mobile.
- **Logo cube/grid** dùng cho marketing, slides, dashboard.
- Tất cả logo dùng SVG vector nguồn → có thể chỉnh sửa dễ dàng bằng Figma, Illustrator hoặc text editor.

## 🛠 Chỉnh sửa logo SVG

Mở file `.svg` trong text editor và thay đổi:
- `fill="#1E3A8A"` → đ�i màu
- `width="22"` → đổi độ dày viền
- `viewBox="0 0 512 512"` → giữ nguyên tỉ lệ

Sau đó chạy lại convert:
```bash
convert -background none -density 300 logo-minimal.svg -resize 512x512 favicons-minimal/favicon-512x512.png
```
