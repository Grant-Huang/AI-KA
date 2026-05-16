import React, { useEffect, useRef, useState, useMemo } from "react";

type Props = { markdown: string };

// ---------------------------------------------------------------------------
// Animated thinking dots
// ---------------------------------------------------------------------------
export function ThinkingDots() {
  return (
    <span className="think-dots" aria-label="思考中">
      <span /><span /><span />
    </span>
  );
}

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
// Fenced code block with copy button
// ---------------------------------------------------------------------------
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore */ }
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        {lang && <span className="code-block-lang">{lang}</span>}
        <button className="code-block-copy" onClick={handleCopy}>
          {copied ? "✓ 已复制" : "复制"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
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
 * - While thinkComplete=false (streaming): think section is expanded with animated dots.
 * - When thinkComplete=true: auto-collapses; user can re-open.
 * - showCursor: appends a blinking typing cursor at the end (used during streaming).
 */
export function ThinkableMarkdown({ markdown, showCursor }: { markdown: string; showCursor?: boolean }) {
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
    return (
      <div className="simple-markdown">
        <SimpleMarkdown markdown={markdown} />
        {showCursor && <span className="typing-cursor" />}
      </div>
    );
  }

  return (
    <div className="simple-markdown">
      {before.trim() ? <SimpleMarkdown markdown={before} /> : null}
      <details
        open={isOpen}
        onToggle={(e) => setIsOpen(e.currentTarget.open)}
        className="think-block"
      >
        <summary className="think-block__summary">
          {!thinkComplete ? (
            <>
              <ThinkingDots />
              <span>思考中…</span>
            </>
          ) : (
            <span>{isOpen ? "思考过程（点击收起）" : "思考完毕（点击展开）"}</span>
          )}
        </summary>
        <div className="think-block__body">
          {think}
        </div>
      </details>
      {after.trim() ? <SimpleMarkdown markdown={after} /> : null}
      {showCursor && <span className="typing-cursor" />}
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
    // Fenced code block
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1; // skip closing ```
      nodes.push(<CodeBlock key={`code-${i}`} lang={lang} code={codeLines.join("\n")} />);
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
