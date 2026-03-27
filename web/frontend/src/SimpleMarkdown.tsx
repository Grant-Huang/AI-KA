import React from "react";

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

