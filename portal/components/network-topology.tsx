"use client";

/**
 * Canvas sơ đồ mạng bằng React Flow (@xyflow/react) — thay thế trải nghiệm
 * Mermaid (auto-layout cứng) bằng kéo thả tự do: người dùng kéo node xếp lại
 * bố cục, tự nối đường mạng bằng cách kéo từ handle node này sang node khác,
 * xóa đường bằng cách chọn nó rồi bấm Delete/Backspace. Toàn bộ (vị trí node
 * + danh sách cạnh + node tự do) lưu vào DB (`diagram_layout` /
 * `physical_diagram_layout`).
 *
 * - Node thiết bị phản chiếu danh mục thiết bị (icon lucide theo loại, fallback
 *   emoji từ catalog `/api/device-types`) — không thêm/xóa trực tiếp trên canvas.
 * - Node tự do (vd nhóm "DMZ", "Client Wi-Fi") thêm bằng nút "Thêm node",
 *   xóa bằng cách chọn rồi nhấn Delete/Backspace.
 * - Node/edge tự sinh từ danh mục thiết bị (`buildDevicesTopology`). Nếu layout
 *   đã lưu có danh sách cạnh tường minh thì ưu tiên layout; thiết bị mới thêm
 *   (chưa có trong layout) giữ vị trí auto.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  AppWindow,
  BatteryCharging,
  Bot,
  Camera,
  CircleHelp,
  ClipboardCopy,
  ClipboardPaste,
  Download,
  Globe,
  HardDrive,
  LayoutTemplate,
  Monitor,
  Network,
  Package,
  Phone,
  Printer,
  Redo2,
  RotateCcw,
  Router,
  ScanSearch,
  Scale,
  Server,
  Shield,
  Save,
  Tag,
  Undo2,
  Wifi,
} from "lucide-react";
import { toPng } from "html-to-image";
import { api } from "@/lib/api";
import { Button, Field, Input, Modal, Textarea } from "@/components/ui";
import {
  applyDiagramLayout,
  buildAiDiagramPrompt,
  buildDevicesTopology,
  buildLevelSample,
  buildLevelTemplate,
  DEVICE_TYPE_ICON,
  DEVICE_TYPE_LABEL,
  parseAiLayoutJson,
  type DeviceTypeMeta,
  type DiagramLayout,
  type TopologyNodeData,
} from "@/lib/system-profile-diagram";
import type { SystemProfileDevice } from "@/lib/types";

import "@xyflow/react/dist/style.css";

/** Icon lucide theo loại thiết bị chuẩn — fallback là emoji trong data.icon. */
const DEVICE_LUCIDE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  internet: Globe,
  firewall: Shield,
  router: Router,
  switch: Network,
  server: Server,
  workstation: Monitor,
  storage: HardDrive,
  ups: BatteryCharging,
  other: Package,
  custom: Tag,
  website: AppWindow,
  load_balancer: Scale,
  access_point: Wifi,
  printer: Printer,
  camera: Camera,
  ip_phone: Phone,
};

type FlowNode = Node<TopologyNodeData>;

function DeviceNode({ data, selected }: NodeProps<FlowNode>) {
  const Icon = DEVICE_LUCIDE_ICON[data.deviceType];
  /** Các dòng thông tin khai báo — chỉ hiện dòng có dữ liệu, tự wrap theo dòng. */
  const infoRows: [string, string][] = (
    [
      ["Loại", data.typeLabel ?? (data.deviceType === "custom" ? "Node tự do" : data.deviceType)],
      ["Mã", data.deviceCode ?? ""],
      ["IP", data.ip ?? ""],
      ["Model", data.model ?? ""],
      ["Vị trí", data.location ?? ""],
      ["Mục đích", data.purpose ?? ""],
      ["Ghi chú", data.note ?? ""],
    ] as [string, string][]
  ).filter(([, v]) => v?.trim());
  return (
    <div
      className={`group relative flex min-w-32 flex-col items-center gap-1 rounded-lg border bg-white px-3 py-2 shadow-sm transition-shadow hover:shadow-md hover:z-50 ${
        selected ? "border-brand-500 ring-2 ring-brand-500/30" : "border-slate-200"
      }`}
    >
      {Icon ? (
        <Icon className={`size-6 ${data.deviceType === "custom" ? "text-slate-500" : "text-brand-600"}`} />
      ) : (
        <span className="text-2xl leading-none">{data.icon}</span>
      )}
      <span className="max-w-40 text-center text-sm font-medium leading-tight text-slate-800">{data.name}</span>
      {data.deviceCode && (
        <span className="font-mono text-[11px] text-slate-400">{data.deviceCode}</span>
      )}
      {data.note && (
        <span className="max-w-40 truncate rounded bg-slate-100 px-1.5 py-0.5 text-center font-mono text-[10px] text-slate-500">
          {data.note}
        </span>
      )}
      {/* Tooltip thông tin khai báo — nhiều dòng, wrap nội dung dài */}
      {infoRows.length > 0 && (
        <div className="pointer-events-none invisible absolute left-1/2 top-full z-50 mt-2 w-64 -translate-x-1/2 rounded-lg border border-slate-200 bg-white p-2.5 text-left opacity-0 shadow-xl transition-opacity group-hover:visible group-hover:opacity-100">
          <p className="mb-1.5 border-b border-slate-100 pb-1 text-xs font-semibold text-slate-700">{data.name}</p>
          <dl className="space-y-1">
            {infoRows.map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[11px] leading-snug">
                <dt className="w-14 shrink-0 font-medium text-slate-400">{k}</dt>
                <dd className="min-w-0 flex-1 whitespace-normal break-words text-slate-600">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {/* Điểm nối: đầu vào ở đỉnh, đầu ra ở đáy — nối được bao nhiêu đường tùy ý */}
      <Handle type="target" position={Position.Top} className="!size-2.5 !bg-slate-400" />
      <Handle type="source" position={Position.Bottom} className="!size-2.5 !bg-brand-500" />
    </div>
  );
}

const nodeTypes = { device: DeviceNode };

/** Node không thuộc danh mục thiết bị (node tự do `custom-*` / node mẫu `sample-*`). */
const isVirtualNode = (id: string) => id.startsWith("custom-") || id.startsWith("sample-");

/** Gắn type custom node; node thiết bị khóa xóa (phản chiếu danh mục thiết bị). */
function toFlowNodes(
  topo: { id: string; position: { x: number; y: number }; data: TopologyNodeData }[],
  notes?: Record<string, string>,
): FlowNode[] {
  return topo.map((n) => ({
    ...n,
    type: "device" as const,
    deletable: !!n.data.virtual,
    data: { ...n.data, note: notes?.[n.id] ?? n.data.note },
  }));
}

/** Node tự do từ layout đã lưu — vị trí nằm trong `nodes` map. */
function customNodesFromLayout(layout: DiagramLayout | null | undefined): FlowNode[] {
  return (layout?.customNodes ?? []).map((c) => ({
    id: c.id,
    type: "device" as const,
    deletable: true,
    position: layout?.nodes[c.id] ?? { x: 0, y: 0 },
    data: {
      name: c.name,
      deviceCode: null,
      deviceType: c.deviceType || "custom",
      icon: "🏷️",
      note: layout?.notes?.[c.id],
    },
  }));
}

/** JSON ổn định thứ tự key để so sánh dirty. */
function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_k, v: unknown) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      return Object.fromEntries(
        Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)),
      );
    }
    return v;
  });
}

export function NetworkTopologyCanvas(props: {
  devices: SystemProfileDevice[];
  meta?: DeviceTypeMeta;
  layout: DiagramLayout | null;
  canEdit?: boolean;
  saving?: boolean;
  onSave?: (layout: DiagramLayout) => Promise<void>;
  /** Tên hồ sơ + nhãn sơ đồ — dùng trong prompt AI. */
  profileName?: string;
  profileId?: string;
  profileLevel?: 1 | 2 | 3;
  variant?: string;
}) {
  return (
    <ReactFlowProvider>
      <TopologyCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function TopologyCanvasInner({
  devices,
  meta,
  layout,
  canEdit = false,
  saving = false,
  onSave,
  profileName,
  profileId,
  profileLevel,
  variant = "mạng",
}: {
  devices: SystemProfileDevice[];
  meta?: DeviceTypeMeta;
  layout: DiagramLayout | null;
  canEdit?: boolean;
  saving?: boolean;
  onSave?: (layout: DiagramLayout) => Promise<void>;
  profileName?: string;
  profileId?: string;
  profileLevel?: 1 | 2 | 3;
  variant?: string;
}) {
  const topology = useMemo(() => buildDevicesTopology(devices, meta), [devices, meta]);
  // Sơ đồ mẫu theo cấp độ — hiển thị khi hồ sơ chưa lưu bố cục nào
  const levelSample = useMemo(
    () => buildLevelSample(devices, profileLevel ?? 2, meta),
    [devices, profileLevel, meta],
  );
  const initialNodes = useMemo<FlowNode[]>(
    () => {
      if (layout) {
        return [
          ...toFlowNodes(applyDiagramLayout(topology.nodes, layout), layout.notes),
          ...customNodesFromLayout(layout),
        ];
      }
      // Chưa lưu bố cục → hiển thị sơ đồ mẫu theo cấp độ
      return toFlowNodes(levelSample.nodes);
    },
    // Chỉ tính lúc mount — các cập nhật sau xử lý trong effect theo topologyKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const validIds = useMemo(() => new Set(topology.nodes.map((n) => n.id)), [topology.nodes]);
  const autoEdges = useMemo<Edge[]>(
    () => topology.edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
    [topology.edges],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    savedEdgesToFlow(
      layout?.edges ?? levelSample.layout.edges,
      new Set([...validIds, ...levelSample.nodes.map((n) => n.id)]),
      autoEdges,
    ),
  );
  const [savedLayout, setSavedLayout] = useState<DiagramLayout | null>(layout ?? null);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [noteEditor, setNoteEditor] = useState<{ nodeId: string; nodeName: string; value: string } | null>(null);
  const [renameEditor, setRenameEditor] = useState<{ nodeId: string; value: string } | null>(null);
  const [edgeLabelEditor, setEdgeLabelEditor] = useState<{ edgeId: string; title: string; value: string } | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiPaste, setAiPaste] = useState("");
  const [aiPasteError, setAiPasteError] = useState<string | null>(null);
  const [aiCopied, setAiCopied] = useState(false);
  const [aiCalling, setAiCalling] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewFindings, setReviewFindings] = useState<{ severity: string; title: string; detail: string }[]>([]);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewModel, setReviewModel] = useState<string | null>(null);
  /* Undo/redo: snapshot = JSON {nodes, edges} rút gọn */
  const [past, setPast] = useState<string[]>([]);
  const [future, setFuture] = useState<string[]>([]);
  const canvasRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  /** Merge một phần data của node (giữ nguyên các field còn lại). */
  const patchNodeData = useCallback(
    (nodeId: string, patch: Partial<TopologyNodeData>) => {
      setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)));
    },
    [setNodes],
  );

  /** Danh sách loại node có thể thêm: catalog động nếu có, fallback map chuẩn. */
  const nodeTypeOptions = useMemo(() => {
    const codes = new Set([
      ...(meta?.labels ? Object.keys(meta.labels) : []),
      ...Object.keys(DEVICE_TYPE_LABEL),
    ]);
    return [...codes].map((code) => ({
      code,
      label: meta?.labels?.[code] ?? DEVICE_TYPE_LABEL[code] ?? code,
      icon: meta?.icons?.[code] ?? DEVICE_TYPE_ICON[code] ?? "📦",
    }));
  }, [meta]);

  /** Chuyển danh sách cạnh đã lưu thành edge React Flow, bỏ cạnh trỏ node không còn. */
  function savedEdgesToFlow(
    saved: { source: string; target: string; label?: string }[] | undefined,
    ids: Set<string>,
    auto: Edge[],
  ): Edge[] {
    if (!saved || saved.length === 0) return auto;
    const seen = new Set<string>();
    const result: Edge[] = [];
    for (const [i, e] of saved.entries()) {
      if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue;
      const key = `${e.source}->${e.target}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({
        id: `e-saved-${i}-${key}`,
        source: e.source,
        target: e.target,
        label: e.label,
        labelBgStyle: { fill: "#ffffff" },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
        labelShowBg: true,
        style: { strokeWidth: 1.5 },
      });
    }
    return result;
  }

  // Danh mục thiết bị thay đổi (thêm/xóa/sửa sau khi load) → sinh lại node:
  // đã lưu bố cục thì theo layout; chưa lưu thì về sơ đồ mẫu theo cấp độ
  const topologyKey = stableStringify([
    topology.edges,
    levelSample.nodes.map((n) => n.id),
    levelSample.layout.edges,
  ]);
  useEffect(() => {
    if (savedLayout) {
      setNodes((current) => {
        const virtuals = current.filter((n) => isVirtualNode(n.id));
        return [...toFlowNodes(applyDiagramLayout(topology.nodes, savedLayout), savedLayout?.notes), ...virtuals];
      });
      setEdges(savedEdgesToFlow(savedLayout.edges, validIds, autoEdges));
    } else {
      setNodes(toFlowNodes(levelSample.nodes));
      setEdges(
        savedEdgesToFlow(levelSample.layout.edges, new Set(levelSample.nodes.map((n) => n.id)), autoEdges),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topologyKey]);

  const currentLayout = useMemo<DiagramLayout>(
    () => ({
      version: 1,
      nodes: Object.fromEntries(nodes.map((n) => [n.id, n.position])),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        label: typeof e.label === "string" ? e.label : undefined,
      })),
      customNodes: nodes
        .filter((n) => isVirtualNode(n.id))
        .map((n) => ({ id: n.id, name: n.data.name, deviceType: n.data.deviceType })),
      notes: Object.fromEntries(
        nodes.filter((n) => n.data.note?.trim()).map((n) => [n.id, n.data.note!.trim()]),
      ),
    }),
    [nodes, edges],
  );
  const dirty = stableStringify(currentLayout) !== stableStringify(savedLayout);

  /* ── Undo / Redo ── (định nghĩa trước các mutation để deps không TDZ) */
  const snapshot = useCallback(
    () =>
      JSON.stringify({
        nodes: nodes.map((n) => ({ id: n.id, position: n.position, data: n.data, deletable: n.deletable })),
        edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, label: e.label })),
      }),
    [nodes, edges],
  );
  const pushHistory = useCallback(
    (pre?: string) => {
      setPast((p) => [...p.slice(-49), pre ?? snapshot()]);
      setFuture([]);
    },
    [snapshot],
  );
  const restore = useCallback(
    (snap: string) => {
      const parsed = JSON.parse(snap) as { nodes: FlowNode[]; edges: Edge[] };
      setNodes(parsed.nodes);
      setEdges(parsed.edges);
    },
    [setNodes, setEdges],
  );
  const undo = useCallback(() => {
    if (past.length === 0) return;
    const prev = past[past.length - 1];
    setPast(past.slice(0, -1));
    setFuture([snapshot(), ...future].slice(0, 50));
    restore(prev);
  }, [past, future, snapshot, restore]);
  const redo = useCallback(() => {
    if (future.length === 0) return;
    const next = future[0];
    setPast([...past.slice(-49), snapshot()]);
    setFuture(future.slice(1));
    restore(next);
  }, [past, future, snapshot, restore]);
  const dragSnapshot = useRef<string | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
  /** Bọc onNodesChange/onEdgesChange: có xóa phần tử thì ghi lịch sử trước. */
  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      if (changes.some((c) => c.type === "remove")) pushHistory();
      onNodesChange(changes);
    },
    [onNodesChange, pushHistory],
  );
  const handleEdgesChange = useCallback(
    (changes: Parameters<typeof onEdgesChange>[0]) => {
      if (changes.some((c) => c.type === "remove")) pushHistory();
      onEdgesChange(changes);
    },
    [onEdgesChange, pushHistory],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (c.source === c.target) return;
      setError(null);
      pushHistory();
      setEdges((es) => {
        if (es.some((e) => e.source === c.source && e.target === c.target)) return es;
        return addEdge({ id: `e-${c.source}-${c.target}-${es.length}-${Date.now()}`, ...c }, es);
      });
    },
    [setEdges, pushHistory],
  );

  /** Thêm node tự do (đã chọn loại) vào giữa khung nhìn đang nhìn. */
  const addCustomNode = useCallback(
    (deviceType: string, name: string) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const position = rect
        ? screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
        : { x: 0, y: 0 };
      const id = `custom-${Date.now()}`;
      pushHistory();
      setNodes((ns) => [
        ...ns,
        {
          id,
          type: "device",
          deletable: true,
          position: { x: position.x - 64, y: position.y - 32 },
          data: { name, deviceCode: null, deviceType, icon: "🏷️" },
        },
      ]);
    },
    [screenToFlowPosition, setNodes, pushHistory],
  );

  /** Sắp xếp lại: thiết bị về vị trí auto theo tầng; giữ nguyên node tự do + đường nối. */
  const rearrange = useCallback(() => {
    pushHistory();
    setNodes((current) => [
      ...toFlowNodes(topology.nodes, savedLayout?.notes),
      ...current.filter((n) => isVirtualNode(n.id)),
    ]);
  }, [topology.nodes, savedLayout?.notes, setNodes, pushHistory]);

  /** Chuột phải vào node → mở modal đặt/sửa ghi chú (IP, dải IP, vlan…). */
  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: FlowNode) => {
    event.preventDefault();
    setNoteEditor({ nodeId: node.id, nodeName: node.data.name, value: node.data.note ?? "" });
  }, []);

  /* ── Vẽ bằng AI ── */

  const openAiModal = useCallback(() => {
    setAiPrompt(
      buildAiDiagramPrompt({
        profileTitle: profileName ?? "hồ sơ",
        variant,
        devices,
        meta,
        layout: currentLayout,
      }),
    );
    setAiPaste("");
    setAiPasteError(null);
    setAiCopied(false);
    setAiOpen(true);
  }, [profileName, variant, devices, meta, currentLayout]);

  const copyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(aiPrompt);
      setAiCopied(true);
    } catch {
      // Clipboard API bị chặn (iframe/webview) — fallback select + execCommand
      const ta = document.getElementById("ai-prompt-text") as HTMLTextAreaElement | null;
      if (ta) {
        ta.focus();
        ta.select();
        document.execCommand("copy");
        setAiCopied(true);
      }
    }
    setTimeout(() => setAiCopied(false), 2000);
  }, [aiPrompt]);

  /**
   * Dán JSON do AI trả về → validate → GỘP vào sơ đồ hiện tại (không phá hủy):
   * node/đường không được nhắc tới được giữ nguyên; edges chỉ thay thế khi JSON
   * có danh sách edges mới không rỗng.
   */
  const applyAiJson = useCallback(() => {
    setAiPasteError(null);
    const res = parseAiLayoutJson(aiPaste);
    if (!res.ok) {
      setAiPasteError(res.error);
      return;
    }
    const parsed = res.layout;
    const known = new Set(levelSample.nodes.map((n) => n.id));
    const customSet = new Set((parsed.customNodes ?? []).map((c) => c.id));
    const unknown = Object.keys(parsed.nodes).filter((id) => !known.has(id) && !customSet.has(id));
    if (unknown.length > 0) {
      setAiPasteError(
        `JSON chứa node không thuộc hồ sơ: ${unknown.slice(0, 5).join(", ")}${unknown.length > 5 ? "…" : ""}. ` +
          "Chỉ dùng id thiết bị đã khai, __internet__, __workstation__ hoặc id khai trong customNodes.",
      );
      return;
    }
    pushHistory();
    const allIds = new Set([...known, ...customSet]);

    // Gộp vị trí/ghi chú: node không được nhắc tới giữ nguyên như đang có.
    // Node ảo (custom-*/sample-*) xử lý riêng ở existingCustoms/newCustoms —
    // lọc ra khỏi đây để không bị nhân đôi id trên canvas.
    const mergedNodes: FlowNode[] = nodes.filter((n) => !isVirtualNode(n.id)).map((n) => {
      const pos = parsed.nodes[n.id];
      const note = parsed.notes?.[n.id];
      return {
        ...n,
        position: pos ?? n.position,
        data: note !== undefined ? { ...n.data, note: note || undefined } : n.data,
      };
    });
    // customNodes: giữ custom cũ, thêm custom mới (cập nhật tên/loại/vị trí nếu JSON khai trùng id)
    const customMeta = new Map((parsed.customNodes ?? []).map((c) => [c.id, c]));
    const existingCustoms = nodes
      .filter((n) => isVirtualNode(n.id))
      .map((n) => {
        const meta = customMeta.get(n.id);
        return meta
          ? {
              ...n,
              position: parsed.nodes[n.id] ?? n.position,
              data: { ...n.data, name: meta.name, deviceType: meta.deviceType, note: parsed.notes?.[n.id] },
            }
          : n;
      });
    const newCustoms: FlowNode[] = (parsed.customNodes ?? [])
      .filter((c) => !existingCustoms.some((e) => e.id === c.id))
      .map((c, i) => ({
        id: c.id,
        type: "device" as const,
        deletable: true,
        position: parsed.nodes[c.id] ?? { x: 200 + i * 40, y: 220 },
        data: {
          name: c.name,
          deviceCode: null,
          deviceType: c.deviceType,
          icon: "🏷️",
          note: parsed.notes?.[c.id],
        },
      }));
    setNodes([...mergedNodes, ...existingCustoms, ...newCustoms]);

    // edges: chỉ thay thế khi JSON có danh sách edges mới; ngoài ra giữ nguyên
    setEdges(
      parsed.edges && parsed.edges.length > 0
        ? savedEdgesToFlow(parsed.edges, allIds, [])
        : edges,
    );
    setAiOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiPaste, levelSample.nodes, nodes, edges, setNodes, setEdges, pushHistory]);

  /* ── Gọi AI phía server (dùng chung cấu hình LLM-DFIR) ── */

  const apiVariant = variant === "vật lý" ? "physical" : "logic";

  const callAiGenerate = useCallback(async () => {
    if (!profileId || devices.length === 0) return;
    setAiCalling(true);
    setAiPasteError(null);
    try {
      const res = await api.post<{ layout: Record<string, unknown>; model: string }>(
        `/system-profiles/${profileId}/diagram/ai-generate`,
        // Gửi layout đang hiển thị trên canvas (kể cả node chưa lưu) — nếu chỉ
        // gửi layout đã lưu DB, AI sẽ không thấy node mới và có thể trả về sơ
        // đồ chỉ gồm 2 node mặc định.
        { variant: apiVariant, layout: currentLayout },
      );
      setAiPaste(JSON.stringify(res.layout, null, 2));
    } catch (e) {
      setAiPasteError(e instanceof Error ? e.message : "Lỗi khi gọi AI vẽ sơ đồ");
    } finally {
      setAiCalling(false);
    }
  }, [profileId, apiVariant, currentLayout, devices.length]);

  const runAiReview = useCallback(async () => {
    if (!profileId || devices.length === 0) return;
    setReviewOpen(true);
    setReviewLoading(true);
    setReviewError(null);
    setReviewFindings([]);
    setReviewModel(null);
    try {
      const res = await api.post<{
        findings: { severity: string; title: string; detail: string }[];
        model: string;
      }>(`/system-profiles/${profileId}/diagram/ai-review`, {
        variant: apiVariant,
        layout: currentLayout,
      });
      setReviewFindings(res.findings);
      setReviewModel(res.model);
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : "Lỗi khi gọi AI rà soát");
    } finally {
      setReviewLoading(false);
    }
  }, [profileId, apiVariant, currentLayout, devices.length]);

  /* ── Template mẫu theo cấp độ ── */

  const applyLevelTemplate = useCallback(() => {
    if (!profileLevel) return;
    pushHistory();
    const tpl = buildLevelTemplate(devices, profileLevel, meta);
    const allIds = new Set(topology.nodes.map((n) => n.id));
    setNodes(toFlowNodes(applyDiagramLayout(topology.nodes, tpl), savedLayout?.notes));
    setEdges(savedEdgesToFlow(tpl.edges, allIds, []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileLevel, devices, meta, topology.nodes, savedLayout?.notes, setNodes, setEdges, pushHistory]);

  /* ── Xuất PNG ── */

  const exportPng = useCallback(async () => {
    const el = canvasRef.current;
    if (!el) return;
    setError(null);
    try {
      const dataUrl = await toPng(el, { backgroundColor: "#f8fafc", pixelRatio: 2 });
      const a = document.createElement("a");
      a.download = `so-do-${(profileName ?? "ho-so").replace(/\s+/g, "-").toLowerCase()}-${variant}.png`;
      a.href = dataUrl;
      a.click();
    } catch {
      setError("Không xuất được PNG — thử thu nhỏ sơ đồ rồi xuất lại.");
    }
  }, [profileName, variant]);

  /** Double-click node tự do → mở modal đổi tên (tên thiết bị thuộc danh mục). */
  const onNodeDoubleClick = useCallback(
    (event: React.MouseEvent, node: FlowNode) => {
      if (!node.id.startsWith("custom-")) return;
      event.preventDefault();
      setRenameEditor({ nodeId: node.id, value: node.data.name });
    },
    [],
  );

  /** Double-click vào đường nối → đặt/sửa nhãn (vlan, mô tả link…). */
  const onEdgeDoubleClick = useCallback((event: React.MouseEvent, edge: Edge) => {
    event.preventDefault();
    setEdgeLabelEditor({
      edgeId: edge.id,
      title: edge.label && typeof edge.label === "string" ? edge.label : "đường nối",
      value: edge.label && typeof edge.label === "string" ? edge.label : "",
    });
  }, []);

  const save = useCallback(async () => {
    if (!onSave) return;
    setError(null);
    try {
      await onSave(currentLayout);
      setSavedLayout(currentLayout);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được bố cục");
    }
  }, [onSave, currentLayout]);

  return (
    <div className="space-y-2">
      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{error}</p>
      )}
      {devices.length === 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
          Hồ sơ chưa khai thiết bị — đang hiển thị <b>sơ đồ mẫu cấp độ {profileLevel ?? 2}</b> với các node
          "(mẫu)". Thêm thiết bị ở tab <b>Thiết bị</b> để thay các node mẫu bằng thiết bị thật.
        </p>
      )}
      <details className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5">
        <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-slate-500">
          <CircleHelp className="size-3.5" /> Hướng dẫn chỉnh sửa sơ đồ
        </summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs leading-relaxed text-slate-500">
          <li>Sơ đồ load <b>toàn bộ thiết bị</b> đã khai (chưa có đường sẵn) — <b>nối đường</b>: kéo từ chấm tròn dưới node này lên đỉnh node khác.</li>
          <li><b>Nhãn đường nối</b> (vlan, link…): double-click vào đường; <b>ghi chú node</b> (IP…): chuột phải vào node.</li>
          <li><b>Gỡ đường / xóa node tự do</b>: chọn rồi nhấn <kbd className="rounded border bg-white px-1 font-mono text-[10px]">Delete</kbd>; <b>đổi tên node tự do</b>: double-click.</li>
          <li><b>Vẽ bằng AI</b>: copy prompt (đã có sẵn thông tin hệ thống) gửi cho ChatGPT/Gemini… hoặc bấm "Gọi AI vẽ ngay"; dán JSON trả về để render. <b>AI rà soát</b>: nhờ AI kiểm tra an toàn + ghi chú.</li>
          <li><b>Hoàn tác/làm lại</b>: Ctrl+Z / Ctrl+Shift+Z. Lăn chuột thu phóng, chuột phải di chuyển. Nhớ bấm <b>Lưu bố cục</b>.</li>
        </ul>
      </details>
      <div ref={canvasRef} className="h-[480px] overflow-hidden rounded-lg border border-slate-200 bg-slate-50" data-testid="topology-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          onNodeContextMenu={onNodeContextMenu}
          onNodeDoubleClick={onNodeDoubleClick}
          onEdgeDoubleClick={onEdgeDoubleClick}
          onNodeDragStart={() => {
            dragSnapshot.current = snapshot();
          }}
          onNodeDragStop={() => {
            if (dragSnapshot.current) {
              pushHistory(dragSnapshot.current);
              dragSnapshot.current = null;
            }
          }}
          deleteKeyCode={["Backspace", "Delete"]}
          minZoom={0.2}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {canEdit && onSave && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void save()} loading={saving} disabled={!dirty}>
            <Save className="size-4" /> {dirty ? "Lưu bố cục" : "Đã lưu"}
          </Button>
          {/* Click để mở/đóng menu; menu tự xuống dòng khi nhiều loại */}
          <div className="relative">
            <Button variant="secondary" onClick={() => setPickerOpen((v) => !v)}>
              <Tag className="size-4" /> Thêm node
            </Button>
            {pickerOpen && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setPickerOpen(false)} aria-hidden />
                <div className="absolute left-0 top-full z-30 mt-1 flex w-80 flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-1.5 shadow-lg">
                  {nodeTypeOptions.map((t) => (
                    <button
                      key={t.code}
                      type="button"
                      onClick={() => {
                        addCustomNode(t.code, t.label);
                        setPickerOpen(false);
                      }}
                      className="flex items-center gap-1 rounded-md border border-transparent px-2 py-1 text-xs text-slate-700 hover:border-slate-200 hover:bg-slate-50"
                      title={`Thêm node ${t.label}`}
                    >
                      <span>{t.icon}</span> {t.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <Button
            variant="secondary"
            onClick={openAiModal}
            disabled={devices.length === 0}
            title={devices.length === 0 ? "Khai báo thiết bị ở tab Thiết bị trước khi nhờ AI vẽ sơ đồ" : undefined}
          >
            <Bot className="size-4" /> Vẽ bằng AI
          </Button>
          <Button
            variant="secondary"
            onClick={() => void runAiReview()}
            disabled={devices.length === 0}
            title={devices.length === 0 ? "Khai báo thiết bị ở tab Thiết bị trước khi nhờ AI rà soát sơ đồ" : undefined}
          >
            <ScanSearch className="size-4" /> AI rà soát
          </Button>
          {profileLevel && (
            <Button variant="secondary" onClick={applyLevelTemplate} title={`Dùng bố cục mẫu cho hồ sơ cấp độ ${profileLevel}`}>
              <LayoutTemplate className="size-4" /> Mẫu cấp độ {profileLevel}
            </Button>
          )}
          <Button variant="secondary" onClick={() => void exportPng()}>
            <Download className="size-4" /> Xuất PNG
          </Button>
          <Button variant="secondary" onClick={rearrange}>
            <RotateCcw className="size-4" /> Sắp xếp lại
          </Button>
          <div className="ml-auto flex gap-1">
            <Button variant="secondary" onClick={undo} disabled={past.length === 0} title="Hoàn tác (Ctrl+Z)">
              <Undo2 className="size-4" />
            </Button>
            <Button variant="secondary" onClick={redo} disabled={future.length === 0} title="Làm lại (Ctrl+Shift+Z)">
              <Redo2 className="size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Modal ghi chú node (chuột phải vào node) */}
      <Modal
        open={noteEditor !== null}
        onClose={() => setNoteEditor(null)}
        title={noteEditor ? `Ghi chú — ${noteEditor.nodeName}` : ""}
        footer={
          <>
            <Button variant="secondary" onClick={() => setNoteEditor(null)}>Hủy</Button>
            <Button
              onClick={() => {
                if (!noteEditor) return;
                pushHistory();
                patchNodeData(noteEditor.nodeId, { note: noteEditor.value.trim() || undefined });
                setNoteEditor(null);
              }}
            >
              Lưu ghi chú
            </Button>
          </>
        }
      >
        {noteEditor && (
          <Field label="Ghi chú (IP, dải IP, vlan…)" hint="Để trống để xóa ghi chú.">
            <Input
              autoFocus
              value={noteEditor.value}
              onChange={(e) => setNoteEditor({ ...noteEditor, value: e.target.value })}
              placeholder="10.10.0.1/24"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  pushHistory();
                  patchNodeData(noteEditor.nodeId, { note: noteEditor.value.trim() || undefined });
                  setNoteEditor(null);
                }
              }}
            />
          </Field>
        )}
      </Modal>

      {/* Modal đổi tên node tự do (double-click vào node) */}
      <Modal
        open={renameEditor !== null}
        onClose={() => setRenameEditor(null)}
        title="Đổi tên node"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRenameEditor(null)}>Hủy</Button>
            <Button
              disabled={!renameEditor?.value.trim()}
              onClick={() => {
                if (!renameEditor?.value.trim()) return;
                pushHistory();
                patchNodeData(renameEditor.nodeId, { name: renameEditor.value.trim() });
                setRenameEditor(null);
              }}
            >
              Lưu
            </Button>
          </>
        }
      >
        {renameEditor && (
          <Field label="Tên node">
            <Input
              autoFocus
              value={renameEditor.value}
              onChange={(e) => setRenameEditor({ ...renameEditor, value: e.target.value })}
            />
          </Field>
        )}
      </Modal>

      {/* Modal nhãn đường nối (double-click vào line) */}
      <Modal
        open={edgeLabelEditor !== null}
        onClose={() => setEdgeLabelEditor(null)}
        title="Nhãn đường nối"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEdgeLabelEditor(null)}>Hủy</Button>
            <Button
              onClick={() => {
                if (!edgeLabelEditor) return;
                pushHistory();
                const label = edgeLabelEditor.value.trim() || undefined;
                setEdges((es) => es.map((e) => (e.id === edgeLabelEditor.edgeId ? { ...e, label } : e)));
                setEdgeLabelEditor(null);
              }}
            >
              Lưu nhãn
            </Button>
          </>
        }
      >
        {edgeLabelEditor && (
          <Field label="Nhãn (vlan, mô tả link…)" hint="Để trống để xóa nhãn.">
            <Input
              autoFocus
              value={edgeLabelEditor.value}
              onChange={(e) => setEdgeLabelEditor({ ...edgeLabelEditor, value: e.target.value })}
              placeholder="VLAN 10 — trunk"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  pushHistory();
                  const label = edgeLabelEditor.value.trim() || undefined;
                  setEdges((es) => es.map((x) => (x.id === edgeLabelEditor.edgeId ? { ...x, label } : x)));
                  setEdgeLabelEditor(null);
                }
              }}
            />
          </Field>
        )}
      </Modal>

      {/* Modal vẽ sơ đồ bằng AI: copy prompt → dán JSON trả về để render */}
      <Modal
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        title={`Vẽ sơ đồ ${variant} bằng AI`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setAiOpen(false)}>Đóng</Button>
            <Button onClick={applyAiJson} disabled={!aiPaste.trim()}>
              <ClipboardPaste className="size-4" /> Dán &amp; render JSON
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">Bước 1 — Prompt cho AI</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => void copyPrompt()}>
                  <ClipboardCopy className="size-3.5" /> {aiCopied ? "Đã sao chép!" : "Sao chép"}
                </Button>
              </div>
            </div>
            {profileId && (
              <div className="mb-2 rounded-lg border border-brand-200 bg-brand-50 p-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-slate-600">
                    Hoặc gọi thẳng AI đã cấu hình trong hệ thống (dùng chung LLM-DFIR) — kết quả tự điền vào bước 2.
                  </p>
                  <Button size="sm" onClick={() => void callAiGenerate()} loading={aiCalling}>
                    <Bot className="size-3.5" /> Gọi AI vẽ ngay
                  </Button>
                </div>
              </div>
            )}
            <Textarea
              id="ai-prompt-text"
              className="h-56 font-mono text-[11px]"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              readOnly
            />
            <p className="mt-1 text-xs text-slate-400">
              Prompt đã gồm danh sách thiết bị, id node bắt buộc và quy cách JSON. Dán vào ChatGPT/Gemini/Copilot…
            </p>
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Bước 2 — Dán JSON AI trả về</span>
            <Textarea
              className="h-40 font-mono text-[11px]"
              value={aiPaste}
              onChange={(e) => {
                setAiPaste(e.target.value);
                setAiPasteError(null);
              }}
              placeholder={'{"version": 1, "nodes": {"__internet__": {"x": 0, "y": 0}, ...}, "edges": [...]}'}
            />
            {aiPasteError && (
              <p className="mt-1 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{aiPasteError}</p>
            )}
            <p className="mt-1 text-xs text-slate-400">
              JSON sẽ được <b>gộp</b> vào sơ đồ hiện tại — node/đường cũ không bị xóa; kiểm tra rồi bấm <b>Lưu bố cục</b> để ghi vào hồ sơ.
            </p>
          </div>
        </div>
      </Modal>

      {/* Modal AI rà soát sơ đồ */}
      <Modal
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        title={`AI rà soát sơ đồ ${variant}`}
        footer={
          <Button variant="secondary" onClick={() => setReviewOpen(false)}>Đóng</Button>
        }
      >
        <div className="space-y-2">
          {reviewLoading && <p className="text-sm text-slate-500">Đang gọi AI rà soát… (có thể mất vài chục giây)</p>}
          {reviewError && (
            <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{reviewError}</p>
          )}
          {!reviewLoading && !reviewError && reviewFindings.length === 0 && (
            <p className="text-sm text-slate-500">AI không phát hiện vấn đề nào — sơ đồ hợp lý và ghi chú đầy đủ.</p>
          )}
          {reviewFindings.map((f, i) => {
            const cls =
              f.severity === "high"
                ? "border-red-200 bg-red-50 text-red-800"
                : f.severity === "low"
                  ? "border-sky-200 bg-sky-50 text-sky-800"
                  : "border-amber-200 bg-amber-50 text-amber-800";
            const label = f.severity === "high" ? "Nghiêm trọng" : f.severity === "low" ? "Gợi ý" : "Cần lưu ý";
            return (
              <div key={i} className={`rounded-lg border p-2.5 ${cls}`}>
                <p className="text-xs font-semibold">
                  [{label}] {f.title}
                </p>
                <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed">{f.detail}</p>
              </div>
            );
          })}
          {reviewModel && !reviewLoading && (
            <p className="text-[11px] text-slate-400">Model: {reviewModel}</p>
          )}
        </div>
      </Modal>
    </div>
  );
}
