"use client";

/**
 * Chip dấu vết tool.
 *
 * CHỈ hiển thị field an toàn: tool, ok, row_count, byte_count, duration_ms,
 * client_id, flow_id, error_category. Tuyệt đối không render payload thô,
 * `params_digest`/`args_digest` hay `summary` (contract D4) — dữ liệu đó có thể
 * chứa thông tin ngoài phạm vi được phép hiển thị.
 */

import { CheckCircle2, CircleDashed, CircleX, Wrench } from "lucide-react";
import type { ChatToolCall } from "@/lib/types";

function ms(value: number | null): string {
  if (value === null) return "";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function ToolChip({ tool }: { tool: ChatToolCall }) {
  const running = tool.ok === null;
  const Icon = running ? CircleDashed : tool.ok ? CheckCircle2 : CircleX;
  const tone = running ? "text-slate-400" : tool.ok ? "text-emerald-600" : "text-red-600";

  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs">
      <span className={`inline-flex items-center gap-1 ${tone}`} aria-hidden="true">
        <Icon size={13} />
      </span>
      <span className="font-medium text-slate-700">{tool.tool || "công cụ"}</span>

      {running ? (
        <span className="text-slate-500">đang chạy…</span>
      ) : tool.ok ? (
        <span className="text-slate-500">
          {tool.row_count !== null ? `${tool.row_count} dòng` : "xong"}
          {tool.byte_count !== null ? ` · ${tool.byte_count} B` : ""}
        </span>
      ) : (
        <span className="text-red-600">{tool.error_category ?? "thất bại"}</span>
      )}

      {tool.duration_ms !== null && <span className="text-slate-400">{ms(tool.duration_ms)}</span>}
      {tool.client_id && <span className="font-mono text-slate-500">{tool.client_id}</span>}
      {tool.flow_id && <span className="font-mono text-slate-500">{tool.flow_id}</span>}
    </li>
  );
}

export function ChatToolTrace({ tools }: { tools: ChatToolCall[] }) {
  if (!tools || tools.length === 0) return null;

  return (
    <div className="mb-2">
      <div className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        <Wrench size={12} aria-hidden="true" />
        <span>Công cụ đã dùng</span>
      </div>
      <ul className="flex flex-col gap-1">
        {tools.map((t) => (
          <ToolChip key={t.tool_call_id} tool={t} />
        ))}
      </ul>
    </div>
  );
}