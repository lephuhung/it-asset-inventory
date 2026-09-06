"use client";

/**
 * Sinh code Mermaid gợi ý từ danh mục thiết bị của hồ sơ.
 *
 * Icon theo loại thiết bị lấy từ catalog động `/api/device-types` (Super Admin
 * quản trị, icon là emoji do người dùng đặt). Nếu loại chưa có trong catalog
 * hoặc không truyền meta thì fallback về map chuẩn bên dưới. Dùng emoji thay
 * vì `fa:fa-*` vì portal render Mermaid ở `securityLevel: "strict"` (đã verify
 * trong Chromium: emoji hiển thị đúng, `fa:` cần Font Awesome CSS + htmlLabels).
 *
 * Thứ tự nối mô hình truyền điển hình: Internet → firewall → router →
 * switch → máy chủ / máy trạm; storage/UPS/khác nối vào node cuối.
 */
import type { SystemProfileDevice } from "@/lib/types";

/** Icon fallback theo loại thiết bị chuẩn (seed migration d4e5f6a7b8c9). */
export const DEVICE_TYPE_ICON: Record<string, string> = {
  firewall: "🛡️",
  router: "📡",
  switch: "🔀",
  server: "🖥️",
  workstation: "💻",
  storage: "💾",
  ups: "🔋",
  other: "📦",
};

/** Nhãn fallback theo loại chuẩn. */
export const DEVICE_TYPE_LABEL: Record<string, string> = {
  firewall: "Firewall",
  router: "Router",
  switch: "Switch",
  server: "Máy chủ",
  workstation: "Máy trạm",
  storage: "Hệ thống lưu trữ",
  ups: "UPS",
  other: "Khác",
};

/** Meta loại thiết bị truyền từ catalog động (code → icon/label). */
export interface DeviceTypeMeta {
  icons?: Record<string, string>;
  labels?: Record<string, string>;
}

/** Thứ tự tầng kết nối trong mô hình triển khai điển hình. */
const LAYER_ORDER: string[] = ["firewall", "router", "switch", "server", "workstation", "storage", "ups", "other"];

function iconFor(type: string, meta?: DeviceTypeMeta): string {
  return meta?.icons?.[type] ?? DEVICE_TYPE_ICON[type] ?? "📦";
}

export function labelFor(type: string, meta?: DeviceTypeMeta): string {
  return meta?.labels?.[type] ?? DEVICE_TYPE_LABEL[type] ?? type;
}

function nodeLine(id: string, icon: string, label: string): string {
  return `    ${id}["${icon} ${label.replace(/"/g, "'")}"]`;
}

export function generateDevicesMermaid(
  devices: SystemProfileDevice[],
  meta?: DeviceTypeMeta,
): string {
  if (devices.length === 0) {
    return "flowchart LR\n    Internet((\"🌐 Internet\")) --> FW[\"🛡️ Firewall biên giới\"]\n    FW --> SW[\"🔀 Core Switch\"]\n    SW --> SRV[\"🖥️ Máy chủ\"]";
  }

  const sorted = [...devices].sort((a, b) => a.sort_order - b.sort_order);
  // Gom thiết bị theo tầng kết nối
  const byLayer = new Map<string, SystemProfileDevice[]>();
  for (const d of sorted) {
    const list = byLayer.get(d.device_type) ?? [];
    list.push(d);
    byLayer.set(d.device_type, list);
  }

  const lines: string[] = ["flowchart LR", "    Internet((\"🌐 Internet\"))"];
  const chainIds: string[] = ["Internet"];
  let seq = 0;
  const nextId = () => `N${++seq}`;

  for (const layer of LAYER_ORDER) {
    const items = byLayer.get(layer);
    if (!items || items.length === 0) continue;
    for (const d of items) {
      const id = nextId();
      const label = [d.name, d.device_code ? `(${d.device_code})` : null].filter(Boolean).join(" ");
      lines.push(nodeLine(id, iconFor(layer, meta), label));
      chainIds.push(id);
    }
    byLayer.delete(layer);
  }
  // Thiết bị còn sót (loại ngoài thứ tự chuẩn) — nối vào cuối
  for (const [type, items] of byLayer) {
    for (const d of items) {
      const id = nextId();
      lines.push(nodeLine(id, iconFor(type, meta), d.name));
      chainIds.push(id);
    }
  }

  for (let i = 0; i < chainIds.length - 1; i++) {
    lines.push(`    ${chainIds[i]} --> ${chainIds[i + 1]}`);
  }
  return lines.join("\n");
}
