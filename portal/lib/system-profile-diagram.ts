"use client";

/**
 * Dữ liệu sơ đồ mạng cho canvas React Flow (thay thế Mermaid cũ).
 *
 * Icon theo loại thiết bị lấy từ catalog động `/api/device-types` (Super Admin
 * quản trị, icon là emoji do người dùng đặt). Nếu loại chưa có trong catalog
 * hoặc không truyền meta thì fallback về map chuẩn bên dưới.
 *
 * Thứ tự nối tự sinh theo mô hình truyền điển hình: Internet → firewall →
 * router → switch → máy chủ / máy trạm; storage/UPS/khác nối vào node cuối.
 * Người dùng có thể kéo node và tự nối/xóa đường, bố cục lưu vào layout JSON.
 */
import type { SystemProfileDevice } from "@/lib/types";

/** Icon fallback theo loại thiết bị chuẩn (seed migration d4e5f6a7b8c9 + d8e9f0a1b2c4). */
export const DEVICE_TYPE_ICON: Record<string, string> = {
  firewall: "🛡️",
  router: "📡",
  switch: "🔀",
  server: "🖥️",
  workstation: "💻",
  storage: "💾",
  ups: "🔋",
  other: "📦",
  website: "🌐",
  load_balancer: "⚖️",
  access_point: "📶",
  printer: "🖨️",
  camera: "📷",
  ip_phone: "☎️",
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
  website: "Website / Web app",
  load_balancer: "Load Balancer",
  access_point: "Access Point (Wi-Fi)",
  printer: "Máy in",
  camera: "Camera giám sát",
  ip_phone: "Điện thoại IP",
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

/* ── Topology cho React Flow ──────────────────────────────── */

/** Id node Internet cố định trên canvas (không phải thiết bị thật). */
export const INTERNET_NODE_ID = "__internet__";

/** Id node "Máy trạm" mặc định — luôn có trên sơ đồ làm đầu mút người dùng. */
export const DEFAULT_WORKSTATION_NODE_ID = "__workstation__";

export interface TopologyNodeData extends Record<string, unknown> {
  name: string;
  deviceCode: string | null;
  deviceType: string;
  /** Nhãn loại thiết bị (từ catalog hoặc fallback) — hiện khi hover. */
  typeLabel?: string;
  /** Emoji icon của loại thiết bị (từ catalog hoặc fallback). */
  icon: string;
  /** Ghi chú hiển thị dưới tên (IP của thiết bị, hoặc note người dùng tự đặt). */
  note?: string;
  /* Thông tin khai báo chi tiết — hiện trong tooltip khi hover */
  ip?: string | null;
  model?: string | null;
  location?: string | null;
  purpose?: string | null;
}

export interface TopologyNode {
  id: string;
  position: { x: number; y: number };
  data: TopologyNodeData;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
}

/** Một cạnh nối người dùng tự vẽ (id runtime không lưu; label hiển thị trên line). */
export interface DiagramLayoutEdge {
  source: string;
  target: string;
  /** Nhãn trên đường nối (vlan, mô tả link…). */
  label?: string;
}

/** Node tự do người dùng thêm trực tiếp trên canvas (không thuộc danh mục thiết bị). */
export interface DiagramLayoutCustomNode {
  id: string;
  name: string;
  /** Loại thiết bị người dùng chọn khi thêm (code từ catalog) — quyết định icon. */
  deviceType: string;
}

/**
 * Bố cục lưu DB — vị trí node theo id (kèm node Internet), danh sách cạnh nối
 * và các node tự do. Nếu `edges` vắng mặt/rỗng thì client dùng chain tự sinh
 * theo tầng; khi người dùng đã tự nối/chỉnh đường thì lưu danh sách cạnh tường minh.
 */
export interface DiagramLayout {
  version: 1;
  nodes: Record<string, { x: number; y: number }>;
  edges?: DiagramLayoutEdge[];
  customNodes?: DiagramLayoutCustomNode[];
  /** Ghi chú trên node theo id (IP, dải IP, vlan…) — đè lên IP tự động của thiết bị. */
  notes?: Record<string, string>;
}

/**
 * Bố cục lưu DB — vị trí node theo id (kèm node Internet / Máy trạm mặc định),
 * danh sách cạnh nối, node tự do và ghi chú. Sơ đồ KHÔNG tự sinh đường nối:
 * thiết bị được load vào để người dùng tự vẽ liên kết; khi đã lưu layout thì
 * dùng đúng danh sách cạnh người dùng đã vẽ.
 */
export interface DiagramLayout {
  version: 1;
  nodes: Record<string, { x: number; y: number }>;
  edges?: DiagramLayoutEdge[];
  customNodes?: DiagramLayoutCustomNode[];
  /** Ghi chú trên node theo id (IP, dải IP, vlan…) — đè lên IP tự động của thiết bị. */
  notes?: Record<string, string>;
}

/** Bậc dọc giữa các tầng khi tự xếp layout (px). */
const LAYER_GAP_X = 280;
/** Khoảng cách dọc giữa các thiết bị cùng tầng (px). */
const DEVICE_GAP_Y = 120;

/**
 * Sinh node sơ đồ từ danh mục thiết bị (KHÔNG sinh cạnh — người dùng tự nối),
 * kèm vị trí tự xếp theo tầng: Internet → firewall → router → switch → …
 * Luôn có node Internet và node "Máy trạm" mặc định làm 2 đầu mút (node máy
 * trạm chỉ thêm khi danh mục chưa có thiết bị loại workstation).
 * Vị trí đây là bản auto — client sẽ đè bằng layout đã lưu (nếu có).
 */
export function buildDevicesTopology(
  devices: SystemProfileDevice[],
  meta?: DeviceTypeMeta,
): { nodes: TopologyNode[]; edges: TopologyEdge[] } {
  const nodes: TopologyNode[] = [
    {
      id: INTERNET_NODE_ID,
      position: { x: 0, y: 0 },
      data: { name: "Internet", deviceCode: null, deviceType: "internet", icon: "🌐" },
    },
  ];
  if (devices.length === 0) {
    // Rỗng: chỉ có Internet + Máy trạm mặc định — người dùng thêm thiết bị ở
    // tab Thiết bị rồi quay lại vẽ liên kết
    nodes.push({
      id: DEFAULT_WORKSTATION_NODE_ID,
      position: { x: LAYER_GAP_X, y: 0 },
      data: {
        name: "Máy trạm",
        deviceCode: null,
        deviceType: "workstation",
        icon: iconFor("workstation", meta),
      },
    });
    return { nodes, edges: [] };
  }

  const sorted = [...devices].sort((a, b) => a.sort_order - b.sort_order);
  const byLayer = new Map<string, SystemProfileDevice[]>();
  for (const d of sorted) {
    const list = byLayer.get(d.device_type) ?? [];
    list.push(d);
    byLayer.set(d.device_type, list);
  }

  // Thứ tự xếp cột: theo tầng chuẩn rồi đến loại ngoài danh sách
  const ordered: SystemProfileDevice[] = [];
  const layers: string[] = [...LAYER_ORDER];
  for (const layer of layers) {
    ordered.push(...(byLayer.get(layer) ?? []));
    byLayer.delete(layer);
  }
  for (const [, items] of byLayer) {
    ordered.push(...items);
  }

  // Tính vị trí: cột theo tầng (theo thứ tự xuất hiện), hàng theo thứ tự trong tầng
  const layerIndexOf = new Map<string, number>();
  let col = 1;
  for (const d of ordered) {
    if (!layerIndexOf.has(d.device_type)) layerIndexOf.set(d.device_type, col++);
  }
  const rowCount = new Map<number, number>();
  for (const d of ordered) {
    const c = layerIndexOf.get(d.device_type)!;
    const r = rowCount.get(c) ?? 0;
    rowCount.set(c, r + 1);
    nodes.push({
      id: d.id,
      position: { x: c * LAYER_GAP_X, y: r * DEVICE_GAP_Y },
      data: {
        name: d.name,
        deviceCode: d.device_code,
        deviceType: d.device_type,
        typeLabel: labelFor(d.device_type, meta),
        icon: iconFor(d.device_type, meta),
        note: d.ip ?? undefined,
        ip: d.ip,
        model: d.model,
        location: d.location,
        purpose: d.purpose,
      },
    });
  }

  // Máy trạm mặc định: chỉ thêm khi danh mục chưa có thiết bị workstation,
  // đặt ở cột cuối để làm điểm kết thúc của sơ đồ
  if (!devices.some((d) => d.device_type === "workstation")) {
    nodes.push({
      id: DEFAULT_WORKSTATION_NODE_ID,
      position: { x: col * LAYER_GAP_X, y: 0 },
      data: {
        name: "Máy trạm",
        deviceCode: null,
        deviceType: "workstation",
        icon: iconFor("workstation", meta),
      },
    });
  }

  // Không tự sinh đường nối — người dùng tự vẽ liên kết và lưu vào layout
  return { nodes, edges: [] };
}

/** G đè vị trí auto bằng layout đã lưu; thiết bị mới (chưa có trong layout) giữ vị trí auto. */
export function applyDiagramLayout(
  nodes: TopologyNode[],
  layout: DiagramLayout | null | undefined,
): TopologyNode[] {
  if (!layout?.nodes) return nodes;
  return nodes.map((n) => {
    const saved = layout.nodes[n.id];
    return saved ? { ...n, position: { x: saved.x, y: saved.y } } : n;
  });
}
