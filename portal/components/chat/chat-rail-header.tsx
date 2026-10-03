"use client";

/**
 * Header hồ sơ của rail: avatar, tên, trạng thái kết nối — bám theo thiết kế.
 * Trạng thái phản ánh đúng việc rail đang làm, không phải trang mở chung:
 * `idle` = sẵn sàng, `streaming` = đang trả lời, `canceled` = đã dừng.
 */

import { MessageSquare, PanelRightClose, ShieldCheck, X } from "lucide-react";

export type RailStatus = "idle" | "streaming" | "canceled";

const STATUS_META: Record<RailStatus, { label: string; dot: string }> = {
  idle: { label: "Đã kết nối", dot: "bg-emerald-500" },
  streaming: { label: "Đang trả lời", dot: "animate-pulse bg-amber-500" },
  canceled: { label: "Đã dừng", dot: "bg-slate-400" },
};

export function ChatRailHeader({
  status,
  onClose,
  closeButtonRef,
  docked,
}: {
  status: RailStatus;
  onClose(): void;
  closeButtonRef?: React.Ref<HTMLButtonElement>;
  /** true = cột cạnh nội dung (desktop), false = drawer phủ màn hình. */
  docked?: boolean;
}) {
  const meta = STATUS_META[status];

  return (
    <header className="relative shrink-0 border-b border-slate-200 px-4 pb-4 pt-5">
      <button
        type="button"
        onClick={onClose}
        ref={closeButtonRef}
        aria-label={docked ? "Thu gọn trợ lý tra cứu" : "Đóng trợ lý tra cứu"}
        className="absolute right-3 top-3 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
      >
        {docked ? (
          <PanelRightClose size={18} aria-hidden="true" />
        ) : (
          <X size={18} aria-hidden="true" />
        )}
      </button>

      <div className="flex flex-col items-center text-center">
        <span
          aria-hidden="true"
          className="flex h-16 w-16 items-center justify-center rounded-full border border-slate-200 bg-gradient-to-br from-slate-50 to-slate-100 text-slate-500"
        >
          <MessageSquare size={26} />
        </span>

        <h2 className="mt-3 text-base font-semibold text-slate-900">Trợ lý tra cứu</h2>

        <p className="mt-0.5 flex items-center gap-1.5 text-sm text-slate-500">
          <span className={`h-2 w-2 rounded-full ${meta.dot}`} aria-hidden="true" />
          <span>{meta.label}</span>
        </p>

        {/* Chỉ SuperAdmin mới thấy rail; hiện lại để nhắc ranh giới tin cậy. */}
        <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
          <ShieldCheck size={11} aria-hidden="true" />
          Chỉ SuperAdmin
        </p>
      </div>
    </header>
  );
}

/** Tab icon-only: tab đang chọn nằm trên nền trắng dạng pill, như thiết kế. */
export function ChatRailTabs({
  active,
  onChange,
  historyCount,
}: {
  active: "history" | "chat";
  onChange(tab: "history" | "chat"): void;
  /** Hiện badge số lượng trên tab lịch sử. */
  historyCount?: number;
}) {
  const tabs = [
    { id: "history" as const, label: "Lịch sử trò chuyện", icon: MessageSquare, badge: historyCount },
    { id: "chat" as const, label: "Trò chuyện", icon: MessageSquare, badge: undefined },
  ];

  return (
    <div
      role="tablist"
      aria-label="Chế độ xem trợ lý tra cứu"
      className="mx-4 mb-1 mt-3 flex shrink-0 items-center gap-1 rounded-full bg-slate-100 p-1"
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`chat-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`chat-panel-${tab.id}`}
            onClick={() => onChange(tab.id)}
            title={tab.label}
            className={`flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-full py-2 text-xs font-medium transition-all ${
              selected
                ? "bg-white text-slate-800 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            <tab.icon size={15} aria-hidden="true" />
            <span className="hidden sm:inline">{tab.id === "history" ? "Lịch sử" : "Chat"}</span>
            {tab.badge !== undefined && tab.badge > 0 && (
              <span className="rounded-full bg-slate-200 px-1.5 text-[10px] text-slate-600">
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}