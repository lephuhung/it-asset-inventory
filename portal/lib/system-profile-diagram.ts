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

/**
 * Kiểm tra sơ đồ Mermaid do người dùng nhập có khớp với thiết bị đã khai báo.
 *
 * Parse các label node dạng `id["..."]` (bỏ node Internet/cụm `((...))`), so
 * với danh sách thiết bị theo tên. Trả về danh sách cảnh báo (rỗng = khớp):
 * số node khác số thiết bị, thiết bị chưa xuất hiện trên sơ đồ, node lạ.
 */
export function validateDevicesMermaid(
  code: string,
  devices: SystemProfileDevice[],
): string[] {
  const warnings: string[] = [];
  // Node định nghĩa: `ID["label"]` hoặc `ID(label)` — bỏ edge `-->`
  const nodeDefs = [...code.matchAll(/(^|\n)\s*([A-Za-z0-9_]+)\s*(?:\["([^"]*)"?\]|\["([^"]*)"|"([^"]*)"\]|\(([^)]*)\))/g)];
  const labels = nodeDefs
    .map((m) => (m[3] ?? m[4] ?? m[5] ?? m[6] ?? "").trim())
    .filter((l) => l && !/^internet$/i.test(l) && !/🌐/.test(l));
  // Loại node khai báo không nhãn (vd `A --> B` cuối) — đếm cả dạng trần
  const bareNodes = [...code.matchAll(/(^|\n)\s*([A-Za-z0-9_]+)\s*$/g)].map((m) => m[2]);
  const nodeCount = labels.length + bareNodes.length;

  if (devices.length === 0) return warnings;
  if (nodeCount === 0) {
    warnings.push("Không tìm thấy node thiết bị nào trong sơ đồ.");
    return warnings;
  }
  if (nodeCount !== devices.length) {
    warnings.push(
      `Sơ đồ có ${nodeCount} node thiết bị nhưng hồ sơ đã khai ${devices.length} thiết bị.`,
    );
  }
  const lower = (s: string) => s.toLowerCase().replace(/\s+/g, " ");
  const missing = devices.filter((d) => {
    const codeNorm = lower(d.device_code ?? "");
    const nameNorm = lower(d.name);
    return !labels.some((l) => {
      const ll = lower(l);
      return ll.includes(nameNorm) || nameNorm.includes(ll) ||
        (!!codeNorm && (ll.includes(codeNorm) || codeNorm.includes(ll)));
    });
  });
  if (missing.length > 0) {
    warnings.push(
      `Thiết bị đã khai nhưng chưa thấy trên sơ đồ: ${missing.map((d) => d.name).join(", ")}.`,
    );
  }
  const knownLabels = devices.map((d) => lower(d.name)).concat(devices.map((d) => lower(d.device_code ?? "")));
  const unknown = labels.filter(
    (l) => !knownLabels.some((k) => k && (lower(l).includes(k) || k.includes(lower(l)))),
  );
  if (unknown.length > 0) {
    warnings.push(
      `Có node trên sơ đồ không trùng thiết bị nào đã khai: ${unknown.join(", ")} (có thể là node nhóm — bỏ qua nếu cố ý).`,
    );
  }
  return warnings;
}
