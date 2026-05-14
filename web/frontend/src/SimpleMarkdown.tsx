import React, { useEffect, useRef, useState, useMemo } from "react";

type Props = { markdown: string };

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(`[^`]+`)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("`") && p.endsWith("`")) {
          return <code key={i}>{p.slice(1, -1)}</code>;
        }
        return <React.Fragment key={i}>{p}</React.Fragment>;
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Think-block splitter & ThinkableMarkdown
// ---------------------------------------------------------------------------

const _THINK_OPEN_RE = /<(think|thinking|redacted_thinking)>/i;
const _THINK_CLOSE_RE = /<\/(think|thinking|redacted_thinking)>/i;

function splitThinkBlock(md: string): {
  before: string;
  think: string;
  after: string;
  thinkComplete: boolean;
} {
  const t = String(md || "");
  const openM = t.match(_THINK_OPEN_RE);
  if (!openM || openM.index === undefined) {
    return { before: t, think: "", after: "", thinkComplete: true };
  }
  const afterOpen = t.slice(openM.index + openM[0].length);
  const closeM = afterOpen.match(_THINK_CLOSE_RE);
  if (!closeM || closeM.index === undefined) {
    return { before: t.slice(0, openM.index), think: afterOpen, after: "", thinkComplete: false };
  }
  return {
    before: t.slice(0, openM.index),
    think: afterOpen.slice(0, closeM.index),
    after: afterOpen.slice(closeM.index + closeM[0].length),
    thinkComplete: true,
  };
}

/**
 * Renders markdown that may contain a <think> block.
 * - While thinkComplete=false (streaming): think section is expanded.
 * - When thinkComplete=true (body started): auto-collapses; user can re-open.
 */
export function ThinkableMarkdown({ markdown }: { markdown: string }) {
  const { before, think, after, thinkComplete } = useMemo(
    () => splitThinkBlock(markdown),
    [markdown],
  );

  const [isOpen, setIsOpen] = useState(true);
  const prevCompleteRef = useRef(false);

  useEffect(() => {
    if (thinkComplete && !prevCompleteRef.current) {
      setIsOpen(false);
    }
    prevCompleteRef.current = thinkComplete;
  }, [thinkComplete]);

  if (!think) {
    return <SimpleMarkdown markdown={markdown} />;
  }

  return (
    <div className="simple-markdown">
      {before.trim() ? <SimpleMarkdown markdown={before} /> : null}
      <details
        open={isOpen}
        onToggle={(e) => setIsOpen(e.currentTarget.open)}
        className="think-block"
        style={{ margin: "6px 0", borderRadius: 6, border: "1px solid #e5e7eb", background: "#fafaf8" }}
      >
        <summary
          style={{
            cursor: "pointer",
            padding: "4px 10px",
            fontSize: 12,
            color: "#6b7280",
            userSelect: "none",
            listStyle: "none",
          }}
        >
          💭 思考过程{!thinkComplete ? "（进行中…）" : "（已完成，点击展开）"}
        </summary>
        <div
          style={{
            padding: "8px 12px",
            fontSize: 12,
            color: "#6b7280",
            whiteSpace: "pre-wrap",
            lineHeight: 1.6,
            maxHeight: 400,
            overflowY: "auto",
            borderTop: "1px solid #e5e7eb",
          }}
        >
          {think}
        </div>
      </details>
      {after.trim() ? <SimpleMarkdown markdown={after} /> : null}
    </div>
  );
}

export default function SimpleMarkdown({ markdown }: Props) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (line.startsWith("### ")) {
      nodes.push(<h3 key={`h3-${i}`}>{line.slice(4)}</h3>);
      i += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      nodes.push(<h2 key={`h2-${i}`}>{line.slice(3)}</h2>);
      i += 1;
      continue;
    }
    if (line.startsWith("# ")) {
      nodes.push(<h1 key={`h1-${i}`}>{line.slice(2)}</h1>);
      i += 1;
      continue;
    }
    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("- ")) {
        items.push(lines[i].trim().slice(2));
        i += 1;
      }
      nodes.push(
        <ul key={`ul-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      nodes.push(
        <ol key={`ol-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ol>,
      );
      continue;
    }
    if (line.startsWith("|") && line.endsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length) {
        const t = lines[i].trim();
        if (!(t.startsWith("|") && t.endsWith("|"))) break;
        tableLines.push(t);
        i += 1;
      }
      const rows = tableLines
        .map((t) => t.slice(1, -1).split("|").map((c) => c.trim()))
        .filter((r) => r.length >= 2);
      const hasHeader = rows.length >= 2 && rows[1].every((c) => /^-+$/.test(c.replace(/:/g, "")));
      const header = hasHeader ? rows[0] : null;
      const body = hasHeader ? rows.slice(2) : rows;
      nodes.push(
        <table key={`tbl-${i}`}>
          {header ? (
            <thead>
              <tr>
                {header.map((h, idx) => (
                  <th key={idx}>{renderInline(h)}</th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody>
            {body.map((r, ridx) => (
              <tr key={ridx}>
                {r.map((c, cidx) => (
                  <td key={cidx}>{renderInline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (line === "---") {
      nodes.push(<hr key={`hr-${i}`} />);
      i += 1;
      continue;
    }
    nodes.push(<p key={`p-${i}`}>{renderInline(line)}</p>);
    i += 1;
  }
  return <div className="simple-markdown">{nodes}</div>;
}

