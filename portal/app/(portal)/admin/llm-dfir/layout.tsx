import { Brain } from "lucide-react";
import { ReactNode } from "react";

/** Layout cho khu vực LLM-DFIR — chỉ có 1 trang (Cấu hình LLM),
 *  nên không cần subnav. Trang "Cuộc điều tra" đã chuyển sang
 *  /llm-dfir/investigations và có mục riêng trong sidebar.
 *  Theo Design.md: title heavy + tracking âm, icon sticker tile (màu trang trí). */
export default function LlmDfirLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
          <Brain className="size-6" />
        </span>
        <div className="min-w-0">
          <h1 className="text-[22px] font-bold tracking-tight text-slate-900">
            AI Điều tra (LLM-DFIR)
          </h1>
          <p className="mt-0.5 text-sm leading-snug text-slate-500">
            Tích hợp Model LLM (Ollama / OpenAI / Qwen) để phân tích log Velociraptor tự động
          </p>
        </div>
      </div>

      {children}
    </div>
  );
}
