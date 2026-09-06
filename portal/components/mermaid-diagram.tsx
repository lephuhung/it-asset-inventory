"use client";

/**
 * Render sơ đồ logic hệ thống từ code Mermaid.
 *
 * Người dùng vẽ sơ đồ ở ngoài (mermaid.live hoặc công cụ tương tự), dán code
 * vào ô chỉnh sửa, hệ thống lưu chuỗi và render lại tại đây. Dùng dynamic
 * import để mermaid (gói nặng) không nằm trong bundle ban đầu.
 */
import { useEffect, useId, useRef, useState } from "react";
import { Button, ErrorBanner, Textarea } from "@/components/ui";

export function MermaidDiagram({
  code,
  editable = false,
  onSave,
  saving = false,
  starterButton,
}: {
  code: string | null;
  editable?: boolean;
  onSave?: (code: string) => Promise<void>;
  saving?: boolean;
  /** Nút gợi ý sinh code từ dữ liệu (vd: danh mục thiết bị) — bấm sẽ mở editor với code gợi ý. */
  starterButton?: { label: string; generate: () => string };
}) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(code ?? "");
  const containerId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const renderedFor = useRef<string | null>(null);

  useEffect(() => {
    if (editing) return;
    const source = (code ?? "").trim();
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
  }, [code, editing, containerId]);

  if (editable && (editing || !code)) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-500">
          Vẽ sơ đồ logic ở công cụ ngoài (vd{" "}
          <a
            href="https://mermaid.live"
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 underline"
          >
            mermaid.live
          </a>
          ), copy code Mermaid rồi dán vào đây để hệ thống lưu và hiển thị.
        </p>
        <Textarea
          className="h-64 font-mono text-xs"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={"flowchart LR\n    Internet[Internet] --> FW[Firewall]\n    FW --> SW[Core Switch]\n    SW --> SRV[Server]"}
        />
        <div className="flex gap-2">
          <Button
            onClick={async () => {
              if (!onSave) return;
              await onSave(draft);
              setEditing(false);
            }}
            disabled={saving}
          >
            {saving ? "Đang lưu…" : "Lưu sơ đồ"}
          </Button>
          {editing && code && (
            <Button variant="secondary" onClick={() => setEditing(false)} disabled={saving}>
              Hủy
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && <ErrorBanner message={`Sơ đồ không render được: ${error}`} />}
      {svg ? (
        <div
          className="mermaid-diagram overflow-x-auto rounded-lg border border-slate-200 bg-white p-4"
          data-testid="mermaid-svg"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        !error && (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
            Chưa có sơ đồ logic.
          </div>
        )
      )}
      {editable && onSave && (
        <div className="flex gap-2">
          {starterButton && (
            <Button
              variant="secondary"
              onClick={() => {
                setDraft(starterButton.generate());
                setEditing(true);
              }}
            >
              {starterButton.label}
            </Button>
          )}
          <Button variant="secondary" onClick={() => { setDraft(code ?? ""); setEditing(true); }}>
            Chỉnh sửa code Mermaid
          </Button>
        </div>
      )}
    </div>
  );
}
