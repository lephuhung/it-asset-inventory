"use client";

/**
 * Chip ngữ cảnh máy — **mềm** (soft).
 *
 * Mở `/machines/<id>` chỉ gợi ý máy đó cho lượt kế tiếp; nó KHÔNG tự ghi vào
 * hội thoại. Muốn lưu vĩnh viễn thì người dùng bấm "Ghim" → `onPin` gọi
 * `PATCH /chat/conversations/{id}` với `machine_id`. Bấm "Gỡ" chỉ bỏ ghi đè
 * lượt, quay về `machine_id` đã lưu sẵn của hội thoại (nếu có).
 */

import { useState } from "react";
import { HardDrive, Pin, X } from "lucide-react";
import { shortUuid } from "@/lib/format";

export interface ChatContextChipProps {
  machineId: string | null;
  hostname?: string | null;
  /** Đã lưu vào hội thoại chưa. */
  pinned?: boolean;
  onClear(): void;
  onPin(machineId: string): void;
}

export function ChatContextChip({
  machineId,
  hostname = null,
  pinned = false,
  onClear,
  onPin,
}: ChatContextChipProps) {
  const [pinning, setPinning] = useState(false);
  if (!machineId) return null;

  const label = hostname || `máy ${shortUuid(machineId)}`;

  return (
    <div className="shrink-0 px-3 pb-2">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs">
        <HardDrive size={13} className="shrink-0 text-slate-400" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-slate-600" title={label}>
          Đang hỏi về: <span className="font-medium text-slate-800">{label}</span>
        </span>

        {pinned ? (
          <span className="shrink-0 text-slate-400">Đã ghim</span>
        ) : (
          <button
            type="button"
            disabled={pinning}
            onClick={() => {
              setPinning(true);
              onPin(machineId);
            }}
            aria-label={`Ghim ngữ cảnh ${label} vào hội thoại`}
            className="flex shrink-0 cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-slate-500 hover:bg-white hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Pin size={12} aria-hidden="true" />
            <span>Ghim</span>
          </button>
        )}

        <button
          type="button"
          onClick={onClear}
          aria-label={`Gỡ ngữ cảnh ${label} khỏi lượt này`}
          className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-slate-400 hover:bg-white hover:text-slate-700"
        >
          <X size={13} aria-hidden="true" />
        </button>
      </div>
      <p className="mt-1 px-1 text-[11px] text-slate-400">
        Ngữ cảnh này chỉ áp dụng cho lượt tiếp theo — hội thoại không tự đổi.
      </p>
    </div>
  );
}