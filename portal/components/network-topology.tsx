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
  Camera,
  CircleHelp,
  Globe,
  HardDrive,
  Monitor,
  Network,
  Package,
  Phone,
  Printer,
  RotateCcw,
  Router,
  Scale,
  Server,
  Shield,
  Save,
  Tag,
  Wifi,
} from "lucide-react";
import { Button, Field, Input, Modal } from "@/components/ui";
import {
  applyDiagramLayout,
  buildDevicesTopology,
  DEVICE_TYPE_ICON,
  DEVICE_TYPE_LABEL,
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

/** Gắn type custom node; node thiết bị khóa xóa (phản chiếu danh mục thiết bị). */
function toFlowNodes(
  topo: { id: string; position: { x: number; y: number }; data: TopologyNodeData }[],
  notes?: Record<string, string>,
): FlowNode[] {
  return topo.map((n) => ({
    ...n,
    type: "device" as const,
    deletable: false,
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
}: {
  devices: SystemProfileDevice[];
  meta?: DeviceTypeMeta;
  layout: DiagramLayout | null;
  canEdit?: boolean;
  saving?: boolean;
  onSave?: (layout: DiagramLayout) => Promise<void>;
}) {
  const topology = useMemo(() => buildDevicesTopology(devices, meta), [devices, meta]);
  const initialNodes = useMemo(
    () => [
      ...toFlowNodes(applyDiagramLayout(topology.nodes, layout), layout?.notes),
      ...customNodesFromLayout(layout),
    ],
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
    savedEdgesToFlow(layout?.edges, validIds, autoEdges),
  );
  const [savedLayout, setSavedLayout] = useState<DiagramLayout | null>(layout ?? null);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [noteEditor, setNoteEditor] = useState<{ nodeId: string; nodeName: string; value: string } | null>(null);
  const [renameEditor, setRenameEditor] = useState<{ nodeId: string; value: string } | null>(null);
  const [edgeLabelEditor, setEdgeLabelEditor] = useState<{ edgeId: string; title: string; value: string } | null>(null);
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

  // Danh mục thiết bị thay đổi (thêm/xóa/sửa sau khi load) → sinh lại node thiết
  // bị, giữ node tự do; cạnh: ưu tiên cạnh đã lưu (bỏ cạnh trỏ node đã xóa)
  const topologyKey = stableStringify([topology.edges, topology.nodes.map((n) => n.id)]);
  useEffect(() => {
    setNodes((current) => {
      const customs = current.filter((n) => n.id.startsWith("custom-"));
      return [...toFlowNodes(applyDiagramLayout(topology.nodes, savedLayout), savedLayout?.notes), ...customs];
    });
    setEdges(savedEdgesToFlow(savedLayout?.edges, validIds, autoEdges));
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
        .filter((n) => n.id.startsWith("custom-"))
        .map((n) => ({ id: n.id, name: n.data.name, deviceType: n.data.deviceType })),
      notes: Object.fromEntries(
        nodes.filter((n) => n.data.note?.trim()).map((n) => [n.id, n.data.note!.trim()]),
      ),
    }),
    [nodes, edges],
  );
  const dirty = stableStringify(currentLayout) !== stableStringify(savedLayout);

  const onConnect = useCallback(
    (c: Connection) => {
      if (c.source === c.target) return;
      setError(null);
      setEdges((es) => {
        if (es.some((e) => e.source === c.source && e.target === c.target)) return es;
        return addEdge({ id: `e-${c.source}-${c.target}-${es.length}-${Date.now()}`, ...c }, es);
      });
    },
    [setEdges],
  );

  /** Thêm node tự do (đã chọn loại) vào giữa khung nhìn đang nhìn. */
  const addCustomNode = useCallback(
    (deviceType: string, name: string) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const position = rect
        ? screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
        : { x: 0, y: 0 };
      const id = `custom-${Date.now()}`;
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
    [screenToFlowPosition, setNodes],
  );

  /** Sắp xếp lại: thiết bị về vị trí auto theo tầng; giữ nguyên node tự do + đường nối. */
  const rearrange = useCallback(() => {
    setNodes((current) => [
      ...toFlowNodes(topology.nodes, savedLayout?.notes),
      ...current.filter((n) => n.id.startsWith("custom-")),
    ]);
  }, [topology.nodes, savedLayout?.notes, setNodes]);

  /** Chuột phải vào node → mở modal đặt/sửa ghi chú (IP, dải IP, vlan…). */
  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: FlowNode) => {
    event.preventDefault();
    setNoteEditor({ nodeId: node.id, nodeName: node.data.name, value: node.data.note ?? "" });
  }, []);

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
          Hồ sơ chưa khai thiết bị — thêm thiết bị ở tab <b>Thiết bị</b> để vẽ sơ đồ đầy đủ. Hiện chỉ có node
          Internet và Máy trạm mặc định.
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
          <li>Lăn chuột thu phóng, chuột phải di chuyển. Nhớ bấm <b>Lưu bố cục</b>.</li>
        </ul>
      </details>
      <div ref={canvasRef} className="h-[480px] overflow-hidden rounded-lg border border-slate-200 bg-slate-50" data-testid="topology-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeContextMenu={onNodeContextMenu}
          onNodeDoubleClick={onNodeDoubleClick}
          onEdgeDoubleClick={onEdgeDoubleClick}
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
          <Button variant="secondary" onClick={rearrange}>
            <RotateCcw className="size-4" /> Sắp xếp lại
          </Button>
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
                  const label = edgeLabelEditor.value.trim() || undefined;
                  setEdges((es) => es.map((x) => (x.id === edgeLabelEditor.edgeId ? { ...x, label } : x)));
                  setEdgeLabelEditor(null);
                }
              }}
            />
          </Field>
        )}
      </Modal>
    </div>
  );
}
