"use client";

/**
 * Render sơ đồ từ code Mermaid, kèm chế độ chỉnh sửa.
 *
 * Mặc định chỉ hiện **hình render**: nếu `code` trống mà có `fallbackCode`
 * (tự sinh từ danh sách thiết bị) thì render ảnh tự sinh — người dùng không
 * thấy code. Bấm "Chỉnh sửa sơ đồ" mới mở ô code + hướng dẫn; khi lưu, chạy
 * `validate` (nếu có): nếu có cảnh báo lệch thiết bị thì phải tick xác nhận
 * "Tôi hiểu sự khác biệt" mới lưu được.
 *
 * Dùng dynamic import để mermaid (gói nặng) không nằm trong bundle ban đầu.
 */
import { useEffect, useId, useRef, useState } from "react";
import { Button, ErrorBanner, Textarea } from "@/components/ui";

export function MermaidDiagram({
  code,
  fallbackCode,
  autoLabel,
  editable = false,
  onSave,
  saving = false,
  validate,
}: {
  code: string | null;
  /** Code tự sinh (vd từ danh mục thiết bị) — dùng khi `code` trống. */
  fallbackCode?: string;
  /** Ghi chú khi đang hiển thị sơ đồ tự sinh (vd: "Sơ đồ tự sinh từ danh mục thiết bị"). */
  autoLabel?: string;
  editable?: boolean;
  onSave?: (code: string) => Promise<void>;
  saving?: boolean;
  /** Trả về danh sách cảnh báo lệch giữa sơ đồ và dữ liệu đã khai (rỗng = khớp). */
  validate?: (code: string) => string[];
}) {
  const effective = (code ?? "").trim() || (fallbackCode ?? "").trim() || null;
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(code ?? "");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const containerId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const renderedFor = useRef<string | null>(null);

  useEffect(() => {
    if (editing) return;
    const source = effective;
    if (!source) {
      setSvg(null);
      setError(null);
      return;
    }
    if (renderedFor.current === source) return;
    renderedFor.current = source;
    let cancelled = false;
    void (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        const { svg: out } = await mermaid.render(`mmd-${containerId}-${Date.now()}`, source);
        if (!cancelled) {
          setSvg(out);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          renderedFor.current = null;
          setSvg(null);
          setError(e instanceof Error ? e.message : "Code Mermaid không hợp lệ");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [effective, editing, containerId]);

  const openEditor = () => {
    setDraft((code ?? fallbackCode ?? "").trim());
    setWarnings([]);
    setAcknowledged(false);
    setEditing(true);
  };

  const checkDraft = (value: string) => {
    setDraft(value);
    setWarnings(validate ? validate(value) : []);
    setAcknowledged(false);
  };

  const canSave = warnings.length === 0 || acknowledged;

  if (editable && editing) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
          <p className="mb-1 font-medium">Hướng dẫn viết code Mermaid (flowchart):</p>
          <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px]">{`flowchart LR
    Internet(("🌐 Internet")) --> FW["🛡️ Firewall"]
    FW --> SW["🔀 Core Switch"]
    SW --> SRV["🖥️ Máy chủ ứng dụng"]
    SRV --> DB["💾 Hệ thống lưu trữ"]`}</pre>
          <p className="mt-1">
            Mỗi node là <code className="font-mono">ID["Icon Tên thiết bị"]</code>, nối bằng
            <code className="font-mono"> --&gt; </code>. Có thể vẽ thử ở{" "}
            <a href="https://mermaid.live" target="_blank" rel="noopener noreferrer" className="text-brand-600 underline">mermaid.live</a>{" "}
            rồi dán code vào đây. Hệ thống sẽ kiểm tra sơ đồ có khớp với thiết bị đã khai báo.
          </p>
        </div>
        <Textarea
          className="h-64 font-mono text-xs"
          value={draft}
          onChange={(e) => checkDraft(e.target.value)}
          placeholder={"flowchart LR\n    Internet((\"🌐 Internet\")) --> FW[\"🛡️ Firewall\"]"}
        />
        {warnings.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            <p className="mb-1 font-semibold">Sơ đồ chưa khớp với thiết bị đã khai báo:</p>
            <ul className="list-disc pl-4">
              {warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
            <label className="mt-2 flex items-center gap-2 font-medium">
              <input
                type="checkbox"
                className="size-4 cursor-pointer accent-brand-600"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              Tôi hiểu sự khác biệt và vẫn muốn lưu sơ đồ này
            </label>
          </div>
        )}
        <div className="flex gap-2">
          <Button
            onClick={async () => {
              if (!onSave) return;
              await onSave(draft.trim());
              setEditing(false);
            }}
            disabled={saving || !canSave}
          >
            {saving ? "Đang lưu…" : "Lưu sơ đồ"}
          </Button>
          <Button variant="secondary" onClick={() => setEditing(false)} disabled={saving}>
            Hủy
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && <ErrorBanner message={`Sơ đồ không render được: ${error}`} />}
      {svg ? (
        <>
          {!code?.trim() && fallbackCode && autoLabel && (
            <p className="text-xs text-slate-400">{autoLabel}</p>
          )}
          <div
            className="mermaid-diagram overflow-x-auto rounded-lg border border-slate-200 bg-white p-4"
            data-testid="mermaid-svg"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </>
      ) : (
        !error && (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
            Chưa có sơ đồ.
          </div>
        )
      )}
      {editable && onSave && (
        <Button variant="secondary" onClick={openEditor}>
          Chỉnh sửa sơ đồ
        </Button>
      )}
    </div>
  );
}
