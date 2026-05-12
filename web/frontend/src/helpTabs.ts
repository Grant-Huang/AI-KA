/** 与仓库根目录 helpme.md 中二级标题一致，用于拆分为帮助弹窗的 Tab */
export const HELP_TAB_LABELS = ["功能简介", "项目审查", "知识提取", "审查域说明", "设置指南", "常见问题"] as const;

export type HelpTabLabel = (typeof HELP_TAB_LABELS)[number];

export type HelpTabsOk = { ok: true; tabs: { label: string; content: string }[] };
export type HelpTabsFallback = { ok: false; markdown: string };


/**
 * Split markdown by H2 headings, ignoring H2s that appear inside fenced code blocks.
 * Returns a map of heading label → body content, plus any preamble before the first H2.
 */
function splitByH2(text: string): { preamble: string; map: Map<string, string> } {
  const lines = text.split("\n");
  const map = new Map<string, string>();
  let inFence = false;
  let currentLabel: string | null = null;
  const currentLines: string[] = [];
  const preambleLines: string[] = [];

  for (const line of lines) {
    if (/^```/.test(line)) inFence = !inFence;
    if (!inFence && /^##\s/.test(line)) {
      if (currentLabel !== null) {
        map.set(currentLabel, currentLines.join("\n").trim());
      } else {
        preambleLines.push(...currentLines);
      }
      currentLabel = line.replace(/^##\s+/, "").trim();
      currentLines.length = 0;
    } else {
      currentLines.push(line);
    }
  }
  if (currentLabel !== null) {
    map.set(currentLabel, currentLines.join("\n").trim());
  } else {
    preambleLines.push(...currentLines);
  }

  const preamble = preambleLines.join("\n").replace(/^#\s+[^\n]+\n?/m, "").trim();
  return { preamble, map };
}

/**
 * 将 helpme.md 按 `## 功能简介` … `## 常见问题` 拆成多段。
 * 若缺少预期章节标题，返回 ok:false，由调用方整页渲染 markdown。
 * 代码围栏内的 ## 标题不参与分段。
 */
export function parseHelpmeMarkdown(markdown: string): HelpTabsOk | HelpTabsFallback {
  const trimmed = String(markdown || "").trim();
  if (!trimmed) return { ok: false, markdown: "" };

  const { preamble, map } = splitByH2(trimmed);

  const hasAllHeadings = HELP_TAB_LABELS.every((label) => map.has(label));
  if (!hasAllHeadings) {
    return { ok: false, markdown: trimmed };
  }

  const tabs = HELP_TAB_LABELS.map((label) => {
    let content = map.get(label) || "_本节暂无内容。_";
    if (label === "功能简介" && preamble) {
      content = `${preamble}\n\n${content}`;
    }
    return { label, content };
  });

  return { ok: true, tabs };
}
