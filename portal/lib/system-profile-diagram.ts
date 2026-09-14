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
  /** Node mẫu (id `sample-*`) — người dùng xóa/thay được, không thuộc danh mục thiết bị. */
  virtual?: boolean;
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

/* ── Template mẫu theo cấp độ hồ sơ ───────────────────────── */

export type LevelTemplate = DiagramLayout;

/** Node thiết bị mẫu dùng để lấp vị trí còn thiếu trong sơ đồ mẫu theo cấp độ. */
const LEVEL_ESSENTIALS: Record<1 | 2 | 3, string[]> = {
  1: ["firewall", "switch"],
  2: ["firewall", "router", "switch", "server"],
  3: ["firewall", "router", "switch", "server", "load_balancer", "storage"],
};

/**
 * Sinh sơ đồ MẪU theo cấp độ để hiển thị mặc định khi hồ sơ chưa lưu bố cục:
 * thiết bị thật chiếm vị trí của chúng, các loại thiết bị trọng yếu còn thiếu
 * được lấp bằng node "(mẫu)" (id `sample-*`, người dùng xóa/thay được), và các
 * tầng được nối sẵn thành backbone Internet → … → máy trạm theo cấu trúc cấp độ.
 */
export function buildLevelSample(
  devices: SystemProfileDevice[],
  level: 1 | 2 | 3,
  meta?: DeviceTypeMeta,
): { nodes: TopologyNode[]; layout: DiagramLayout } {
  const topo = buildDevicesTopology(devices, meta);
  const tpl = buildLevelTemplate(devices, level, meta);
  const byType = new Map<string, SystemProfileDevice[]>();
  for (const d of [...devices].sort((a, b) => a.sort_order - b.sort_order)) {
    const list = byType.get(d.device_type) ?? [];
    list.push(d);
    byType.set(d.device_type, list);
  }

  // Node mẫu cho loại trọng yếu còn thiếu
  const sampleTypes = (LEVEL_ESSENTIALS[level] ?? []).filter((t) => !byType.get(t)?.length);
  const sampleNodes: TopologyNode[] = sampleTypes.map((type) => ({
    id: `sample-${type}`,
    position: { x: 0, y: 0 },
    data: {
      name: `${labelFor(type, meta)} (mẫu)`,
      deviceCode: null,
      deviceType: type,
      icon: iconFor(type, meta),
      note: "Node mẫu — xóa hoặc thay bằng thiết bị thật",
      virtual: true,
    },
  }));
  const nodes: TopologyNode[] = [
    ...topo.nodes.map((n) => ({ ...n, data: { ...n.data, virtual: false } })),
    ...sampleNodes,
  ];

  // Cột theo tầng: loại có thiết bị / có node mẫu (theo LAYER_ORDER + sample types) rồi đến loại ngoài
  const layerSeq: string[] = [];
  for (const t of [...LAYER_ORDER, ...sampleTypes]) {
    if ((byType.has(t) || sampleTypes.includes(t)) && !layerSeq.includes(t)) layerSeq.push(t);
  }
  for (const d of devices) if (!layerSeq.includes(d.device_type)) layerSeq.push(d.device_type);
  const colOf = new Map<string, number>();
  layerSeq.forEach((t, i) => colOf.set(t, i + 1));

  // Node id từng tầng (thứ tự khai báo, node mẫu đứng đầu tầng trống)
  const layerNodes = new Map<string, string[]>();
  for (const t of layerSeq) {
    layerNodes.set(t, byType.get(t)?.length ? byType.get(t)!.map((d) => d.id) : [`sample-${t}`]);
  }
  // Tầng máy trạm luôn có mặt (thiết bị hoặc node mặc định) để backbone khép kín
  if (!layerSeq.includes("workstation")) {
    if (byType.get("workstation")?.length) {
      layerNodes.set("workstation", byType.get("workstation")!.map((d) => d.id));
    } else if (topo.nodes.some((n) => n.id === DEFAULT_WORKSTATION_NODE_ID)) {
      layerNodes.set("workstation", [DEFAULT_WORKSTATION_NODE_ID]);
    }
    if (layerNodes.has("workstation")) layerSeq.push("workstation");
  }

  // Tính lại vị trí: Internet ở cột 0, thiết bị/node mẫu theo tầng, hàng theo thứ tự trong tầng
  const rowCount = new Map<number, number>();
  for (const n of nodes) {
    const c = n.data.deviceType === "internet" ? 0 : (colOf.get(n.data.deviceType) ?? layerSeq.length + 1);
    const r = rowCount.get(c) ?? 0;
    rowCount.set(c, r + 1);
    n.position = { x: c * LAYER_GAP_X, y: r * DEVICE_GAP_Y };
  }

  // Cạnh: template theo thiết bị thật (đã dedupe) + backbone nối đuôi tầng trước → đầu tầng sau.
  // Bỏ cạnh nối thẳng Internet → máy trạm của template — backbone sẽ nối qua các tầng.
  const edges: DiagramLayoutEdge[] = [];
  const seen = new Set<string>();
  const addEdge = (source: string, target: string, label?: string) => {
    if (source === target) return;
    const key = `${source}->${target}`;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push(label ? { source, target, label } : { source, target });
  };
  const workstationIds = layerNodes.get("workstation") ?? [];
  for (const e of tpl.edges ?? []) {
    if (e.source === INTERNET_NODE_ID && workstationIds.includes(e.target)) continue;
    addEdge(e.source, e.target, e.label);
  }
  for (let i = 0; i < layerSeq.length - 1; i++) {
    const cur = layerNodes.get(layerSeq[i]) ?? [];
    const next = layerNodes.get(layerSeq[i + 1]) ?? [];
    if (cur.length > 0 && next.length > 0) addEdge(cur[cur.length - 1], next[0]);
  }
  if (layerSeq.length > 0) {
    const first = layerNodes.get(layerSeq[0]) ?? [];
    if (first.length > 0) addEdge(INTERNET_NODE_ID, first[0]);
  }
  return {
    nodes,
    layout: {
      version: 1,
      nodes: Object.fromEntries(nodes.map((n) => [n.id, n.position])),
      edges,
    },
  };
}

/**
 * Sinh template bố cục + liên kết theo cấp độ hồ sơ (1/2/3), ánh xạ lên đúng
 * các thiết bị đã khai:
 *  - Cấp 1: chuỗi tuyến tính đơn giản Internet → fw → switch → (còn lại) → máy trạm.
 *  - Cấp 2: lõi Internet → fw → router → switch, các thiết bị còn lại nối vào switch (hub).
 *  - Cấp 3: lõi có dự phòng (fw/router/switch nối chuỗi hết), server nối qua load balancer
 *    nếu có, storage gắn server, UPS gắn storage/switch.
 */
export function buildLevelTemplate(
  devices: SystemProfileDevice[],
  level: 1 | 2 | 3,
  meta?: DeviceTypeMeta,
): LevelTemplate {
  const topo = buildDevicesTopology(devices, meta);
  const nodes = Object.fromEntries(topo.nodes.map((n) => [n.id, n.position]));
  const byType = new Map<string, SystemProfileDevice[]>();
  for (const d of [...devices].sort((a, b) => a.sort_order - b.sort_order)) {
    const list = byType.get(d.device_type) ?? [];
    list.push(d);
    byType.set(d.device_type, list);
  }
  const workstationIncluded = topo.nodes.some((n) => n.id === DEFAULT_WORKSTATION_NODE_ID);
  const ids = {
    internet: INTERNET_NODE_ID,
    firewalls: byType.get("firewall") ?? [],
    routers: byType.get("router") ?? [],
    switches: byType.get("switch") ?? [],
    servers: byType.get("server") ?? [],
    lbs: byType.get("load_balancer") ?? [],
    storages: byType.get("storage") ?? [],
    upses: byType.get("ups") ?? [],
    websites: byType.get("website") ?? [],
    rest: devices.filter(
      (d) => !["firewall", "router", "switch", "server", "load_balancer", "storage", "ups", "website"].includes(d.device_type),
    ),
    workstation: workstationIncluded ? [DEFAULT_WORKSTATION_NODE_ID] : (byType.get("workstation") ?? []).map((d) => d.id),
  };

  const edges: DiagramLayoutEdge[] = [];
  const link = (source: string | undefined | null, target: string | undefined | null, label?: string) => {
    if (source && target && source !== target) edges.push({ source, target, label });
  };
  const chain = (list: { id: string }[]) => list.map((d) => d.id);

  if (level === 1) {
    // Chuỗi tuyến tính: Internet → từng thiết bị → máy trạm
    const seq = [ids.internet, ...chain(devices), ...ids.workstation];
    for (let i = 0; i < seq.length - 1; i++) link(seq[i], seq[i + 1]);
    return { version: 1, nodes, edges };
  }

  // Lõi chung cho cấp 2/3: Internet → (fw chain) → (router chain) → (switch chain)
  const core: string[] = [ids.internet];
  if (level === 2) {
    core.push(...chain(ids.firewalls).slice(0, 1));
    core.push(...chain(ids.routers).slice(0, 1));
    core.push(...chain(ids.switches).slice(0, 1));
  } else {
    core.push(...chain(ids.firewalls));
    core.push(...chain(ids.routers));
    core.push(...chain(ids.switches));
  }
  for (let i = 0; i < core.length - 1; i++) link(core[i], core[i + 1]);
  const coreTail = core[core.length - 1] ?? ids.internet;
  const attachPoint = ids.switches[ids.switches.length - 1]?.id ?? coreTail;

  if (level === 2) {
    // Hub: mọi thiết bị còn lại nối vào switch cuối
    for (const d of [...ids.servers, ...ids.websites, ...ids.storages, ...ids.upses, ...ids.rest]) {
      link(attachPoint, d.id);
    }
    for (const ws of ids.workstation) link(attachPoint, ws);
  } else {
    // Cấp 3: LB → server; website vào DMZ qua fw; storage gắn server; UPS gắn storage/switch
    const serverTail = ids.servers[ids.servers.length - 1]?.id;
    if (ids.lbs.length > 0 && serverTail) {
      link(attachPoint, ids.lbs[0].id, "uplink");
      let prev = ids.lbs[0].id;
      for (const d of ids.servers) {
        link(prev, d.id);
        prev = d.id;
      }
    } else {
      for (const d of ids.servers) link(attachPoint, d.id);
    }
    for (const d of ids.websites) link(ids.firewalls[0]?.id ?? attachPoint, d.id, "DMZ");
    for (const d of ids.storages) link(ids.servers[0]?.id ?? attachPoint, d.id, "iSCSI/NFS");
    let upPrev = ids.storages[0]?.id ?? attachPoint;
    for (const d of ids.upses) {
      link(upPrev, d.id, "nguồn");
      upPrev = d.id;
    }
    for (const d of ids.rest) link(attachPoint, d.id);
    for (const ws of ids.workstation) link(attachPoint, ws);
  }
  return { version: 1, nodes, edges };
}

/* ── Vẽ sơ đồ bằng AI ─────────────────────────────────────── */

export interface AiDiagramPromptInput {
  /** Tên hồ sơ — đưa vào ngữ cảnh prompt. */
  profileTitle: string;
  /** Nhãn sơ đồ đang vẽ: "lô-gic" / "vật lý". */
  variant: string;
  devices: SystemProfileDevice[];
  meta?: DeviceTypeMeta;
  /** Layout hiện tại (nếu đã lưu) — AI cập nhật thay vì vẽ lại từ đầu. */
  layout: DiagramLayout | null;
}

/**
 * Sinh prompt gửi cho AI (ChatGPT/Gemini...) để nhờ vẽ sơ đồ mạng dưới dạng
 * JSON layout React Flow của hệ thống. Prompt gồm: quy cách JSON bắt buộc,
 * danh sách node hợp lệ (id thiết bị phải giữ nguyên), dữ liệu chi tiết từng
 * thiết bị và layout hiện tại (nếu có).
 */
export function buildAiDiagramPrompt(input: AiDiagramPromptInput): string {
  const { profileTitle, variant, devices, meta, layout } = input;
  const sorted = [...devices].sort((a, b) => a.sort_order - b.sort_order);
  const deviceLines = sorted
    .map(
      (d) =>
        `- id: ${d.id} | tên: ${d.name} | loại: ${labelFor(d.device_type, meta)} (${d.device_type}) |` +
        ` mã: ${d.device_code ?? "—"} | IP: ${d.ip ?? "—"} | model: ${d.model ?? "—"} |` +
        ` vị trí: ${d.location ?? "—"} | mục đích: ${d.purpose ?? "—"}`,
    )
    .join("\n") || "(hồ sơ chưa khai thiết bị nào)";

  const typeCatalog = Object.entries(meta?.labels && Object.keys(meta.labels).length ? meta.labels : DEVICE_TYPE_LABEL)
    .map(([code, label]) => `${code}="${label}"`)
    .join(", ");

  return `Bạn là chuyên gia thiết kế mạng. Hãy vẽ sơ đồ mạng ${variant} cho hồ sơ "${profileTitle}" và trả về DUY NHẤT một JSON (không giải thích, không bọc markdown) theo đúng quy cách bên dưới.

## Quy cách JSON (React Flow layout của hệ thống)
{
  "version": 1,
  "nodes": { "<nodeId>": { "x": 280, "y": 0 } },        // tọa độ pixel, bắt buộc cho MỌI node
  "edges": [ { "source": "<nodeId>", "target": "<nodeId>", "label": "VLAN 10 — trunk" } ],
  "customNodes": [ { "id": "custom-1", "name": "Tên node mới", "deviceType": "other" } ],
  "notes": { "<nodeId>": "ghi chú hiển thị trên node (IP, dải IP, vlan...)" }
}

## Quy tắc bắt buộc
1. "nodes" phải chứa đủ TẤT CẢ id dưới đây (copy nguyên xi, không đặt lại id):
   - "__internet__"  (node Internet — đầu nguồn, luôn có)
   - "__workstation__" (node Máy trạm mặc định — chỉ thêm khi danh sách thiết bị chưa có loại workstation)
   - id của từng thiết bị đã khai.
2. Muốn thêm node mới (nhóm, vùng mạng, dịch vụ...): khai trong "customNodes" với id mới dạng "custom-..." và khai tọa độ trong "nodes".
3. "edges": mỗi cạnh nối 2 id TỒN TẠI, không tự nối vào chính nó. Node có thể nối nhiều cạnh (firewall/router nhiều đường vật lý). Dùng "label" cho vlan/đường trunk.
4. Bố cục: luồng dữ liệu từ Internet (bên trái) sang máy trạm (bên phải); cách nhau ~280px theo ngang, ~120px theo dọc theo tầng: firewall → router → switch → server → workstation; storage/UPS/website... xếp tầng phụ. Không để node chồng lên nhau.
5. "notes": ghi chú rõ ràng cho các node quan trọng (IP, dải IP).

## Danh sách loại thiết bị hợp lệ (deviceType)
${typeCatalog}

## Thiết bị của hồ sơ (id phải giữ nguyên)
${deviceLines}

## Layout hiện tại (nếu có — ưu tiên chỉnh sửa/bổ sung thay vì vẽ lại)
${layout ? JSON.stringify(layout, null, 2) : "(chưa có — hãy vẽ mới)"}

Trả về JSON hoàn chỉnh theo quy cách trên.`;
}

/** Kết quả parse JSON do AI trả về. */
export type AiLayoutParseResult =
  | { ok: true; layout: DiagramLayout }
  | { ok: false; error: string };

/**
 * Parse JSON layout do AI trả về: bỏ markdown fence nếu có, kiểm tra cấu trúc
 * tối thiểu (version 1, nodes là map {x,y} số). Trả về layout đã chuẩn hóa.
 */
export function parseAiLayoutJson(raw: string): AiLayoutParseResult {
  const cleaned = raw
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/```\s*$/, "")
    .trim();
  let parsed: unknown;
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    return { ok: false, error: "Nội dung dán vào không phải JSON hợp lệ (đã tự bỏ ``` nếu có)." };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: "JSON phải là một object." };
  }
  const obj = parsed as Record<string, unknown>;
  if (obj.version !== undefined && obj.version !== 1) {
    return { ok: false, error: `"version" phải là 1 (nhận được: ${String(obj.version)}).` };
  }
  if (!obj.nodes || typeof obj.nodes !== "object" || Array.isArray(obj.nodes)) {
    return { ok: false, error: 'Thiếu "nodes" (map nodeId → {x, y}).' };
  }
  const nodes: Record<string, { x: number; y: number }> = {};
  for (const [id, pos] of Object.entries(obj.nodes as Record<string, unknown>)) {
    if (!pos || typeof pos !== "object" || Array.isArray(pos)) {
      return { ok: false, error: `Node "${id}" thiếu tọa độ {x, y}.` };
    }
    const x = Number((pos as Record<string, unknown>).x);
    const y = Number((pos as Record<string, unknown>).y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return { ok: false, error: `Tọa độ của node "${id}" phải là số.` };
    }
    nodes[id] = { x, y };
  }
  const edges: DiagramLayoutEdge[] = [];
  if (obj.edges !== undefined) {
    if (!Array.isArray(obj.edges)) return { ok: false, error: '"edges" phải là mảng.' };
    for (const e of obj.edges) {
      if (!e || typeof e !== "object") return { ok: false, error: "Phần tử edges phải là object {source, target}." };
      const eo = e as Record<string, unknown>;
      if (typeof eo.source !== "string" || typeof eo.target !== "string") {
        return { ok: false, error: 'Mỗi edge cần "source" và "target" là string.' };
      }
      edges.push({
        source: eo.source,
        target: eo.target,
        label: typeof eo.label === "string" && eo.label.trim() ? eo.label.trim() : undefined,
      });
    }
  }
  const customNodes: DiagramLayoutCustomNode[] = [];
  if (obj.customNodes !== undefined) {
    if (!Array.isArray(obj.customNodes)) return { ok: false, error: '"customNodes" phải là mảng.' };
    for (const c of obj.customNodes) {
      if (!c || typeof c !== "object") return { ok: false, error: "Phần tử customNodes phải là object." };
      const co = c as Record<string, unknown>;
      if (typeof co.id !== "string" || typeof co.name !== "string") {
        return { ok: false, error: 'Mỗi customNode cần "id" và "name" là string.' };
      }
      customNodes.push({
        id: co.id,
        name: co.name,
        deviceType: typeof co.deviceType === "string" && co.deviceType ? co.deviceType : "custom",
      });
    }
  }
  const notes: Record<string, string> = {};
  if (obj.notes !== undefined) {
    if (!obj.notes || typeof obj.notes !== "object" || Array.isArray(obj.notes)) {
      return { ok: false, error: '"notes" phải là map nodeId → string.' };
    }
    for (const [id, v] of Object.entries(obj.notes as Record<string, unknown>)) {
      if (typeof v === "string" && v.trim()) notes[id] = v.trim();
    }
  }
  return { ok: true, layout: { version: 1, nodes, edges, customNodes, notes } };
}
