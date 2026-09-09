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

/** Block types: heading (h1/h2/h3), paragraph, list (ul/ol), code fence, blank. */
type Block =
  | { kind: "h1"; text: string }
  | { kind: "h2"; text: string }
  | { kind: "h3"; text: string }
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "code"; text: string };

/** Parse markdown thành danh sách block — gộp dòng liên tiếp cùng loại
 *  (CommonMark-style): nhiều dòng text liên tiếp → 1 paragraph,
 *  nhiều `- ` liên tiếp → 1 <ul>, nhiều `1. ` liên tiếp → 1 <ol>. */
function parseBlocks(md: string): Block[] {
  // Bỏ YAML frontmatter ở đầu: dòng đầu là `---`, tiếp theo là nội dung,
  // đóng bằng `---` — phổ biến trong report schema.
  const stripped = md.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const lines = stripped.split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      blocks.push({ kind: "code", text: buf.join("\n") });
      continue;
    }
    if (line.trim() === "") {
      i++;
      continue;
    }
    // Horizontal rule `---` đứng một mình — bỏ qua
    if (/^---\s*$/.test(line)) {
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push({ kind: "h1", text: line.slice(2) });
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push({ kind: "h2", text: line.slice(3) });
      i++;
      continue;
    }
    if (line.startsWith("### ")) {
      blocks.push({ kind: "h3", text: line.slice(4) });
      i++;
      continue;
    }
    if (line.startsWith("- ")) {
      const items: string[] = [line.slice(2)];
      i++;
      while (i < lines.length && lines[i].startsWith("- ")) {
        items.push(lines[i].slice(2));
        i++;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [line.replace(/^\d+\.\s/, "")];
      i++;
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ""));
        i++;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }
    // Paragraph: gộp các dòng text liên tiếp (kể cả dòng rỗng đơn) thành 1 block
    const para: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !isBlockStart(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "p", lines: para });
  }
  return blocks;
}

function isBlockStart(line: string): boolean {
  return (
    line.startsWith("# ") ||
    line.startsWith("## ") ||
    line.startsWith("### ") ||
    line.startsWith("- ") ||
    line.startsWith("```") ||
    /^\d+\.\s/.test(line)
  );
}

function renderMarkdown(md: string): React.ReactElement {
  const blocks = parseBlocks(md);
  return (
    <div className="space-y-3 text-sm leading-relaxed text-slate-700">
      {blocks.map((b, idx) => {
        switch (b.kind) {
          case "h1":
            return (
              <h1 key={idx} className="text-lg font-bold tracking-tight text-slate-900">
                {formatInline(b.text)}
              </h1>
            );
          case "h2":
            return (
              <h2 key={idx} className="text-base font-semibold tracking-tight text-slate-900">
                {formatInline(b.text)}
              </h2>
            );
          case "h3":
            return (
              <h3 key={idx} className="text-sm font-semibold text-slate-900">
                {formatInline(b.text)}
              </h3>
            );
          case "p":
            return (
              <p key={idx} className="text-slate-700">
                {b.lines.map((ln, j) => (
                  <span key={j}>
                    {j > 0 && " "}
                    {formatInline(ln)}
                  </span>
                ))}
              </p>
            );
          case "ul":
            return (
              <ul key={idx} className="list-disc space-y-1 pl-5">
                {b.items.map((it, j) => (
                  <li key={j}>{formatInline(it)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={idx} className="list-decimal space-y-1 pl-5">
                {b.items.map((it, j) => (
                  <li key={j}>{formatInline(it)}</li>
                ))}
              </ol>
            );
          case "code":
            return (
              <pre
                key={idx}
                className="overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100"
              >
                <code>{b.text}</code>
              </pre>
            );
        }
      })}
    </div>
  );
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
