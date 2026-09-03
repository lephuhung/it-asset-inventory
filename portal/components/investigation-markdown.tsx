"use client";

import { memo } from "react";

/**
 * Render markdown tối thiểu cho report / message AI.
 *
 * Memoize theo `content`: khi user gõ vào chat input, parent re-render
 * nhưng `content` không đổi → component này không re-render và không
 * chạy lại parser. Trước đây parser chạy trong report/messages của
 * `InvestigationDetailPage` → mỗi ký tự trong chat cũng parse lại.
 *
 * Logic render/format được giữ nguyên 100% — chỉ di chuyển ra file này.
 */

function renderMarkdown(md: string): React.ReactElement {
  const lines = md.split("\n");
  const out: React.ReactElement[] = [];
  let inCode = false;
  let codeBuf: string[] = [];
  let codeKey = 0;
  let prevBlank = false; // gộp nhiều dòng trắng liên tiếp → chỉ 1 dòng trắng
  lines.forEach((line, idx) => {
    if (line.startsWith("```")) {
      if (inCode) {
        out.push(
          <pre key={`c${codeKey++}`} className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">
            <code>{codeBuf.join("\n")}</code>
          </pre>,
        );
        codeBuf = [];
        inCode = false;
      } else {
        inCode = true;
      }
      prevBlank = false;
      return;
    }
    if (inCode) {
      codeBuf.push(line);
      return;
    }
    if (line.trim() === "") {
      // Nhiều dòng trắng liên tiếp → chỉ render 1 <br> (1 dòng trắng)
      if (!prevBlank) out.push(<br key={idx} />);
      prevBlank = true;
      return;
    }
    prevBlank = false;
    if (line.startsWith("# ")) {
      out.push(<h1 key={idx} className="mb-2 mt-4 text-lg font-bold tracking-tight text-slate-900">{line.slice(2)}</h1>);
    } else if (line.startsWith("## ")) {
      out.push(<h2 key={idx} className="mb-2 mt-4 text-base font-semibold tracking-tight text-slate-900">{line.slice(3)}</h2>);
    } else if (line.startsWith("### ")) {
      out.push(<h3 key={idx} className="mb-1 mt-3 text-sm font-semibold text-slate-900">{line.slice(4)}</h3>);
    } else if (line.startsWith("- ")) {
      out.push(<li key={idx} className="ml-4 list-disc text-sm leading-relaxed text-slate-600">{formatInline(line.slice(2))}</li>);
    } else if (/^\d+\.\s/.test(line)) {
      out.push(<li key={idx} className="ml-4 list-decimal text-sm leading-relaxed text-slate-600">{formatInline(line.replace(/^\d+\.\s/, ""))}</li>);
    } else {
      out.push(<p key={idx} className="my-1 text-sm leading-relaxed text-slate-600">{formatInline(line)}</p>);
    }
  });
  return <div>{out}</div>;
}

function formatInline(text: string): React.ReactNode {
  // **bold**
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    }
    // `code`
    const codeParts = p.split(/(`[^`]+`)/g);
    return codeParts.map((cp, j) => {
      if (cp.startsWith("`") && cp.endsWith("`")) {
        return (
          <code key={`${i}-${j}`} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-700">
            {cp.slice(1, -1)}
          </code>
        );
      }
      return <span key={`${i}-${j}`}>{cp}</span>;
    });
  });
}

export const InvestigationMarkdown = memo(function InvestigationMarkdown({
  content,
}: {
  content: string;
}) {
  return <div>{renderMarkdown(content)}</div>;
});
