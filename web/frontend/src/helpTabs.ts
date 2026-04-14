/** 与仓库根目录 helpme.md 中二级标题一致，用于拆分为帮助弹窗的 Tab */
export const HELP_TAB_LABELS = ["功能简介", "操作流程", "审查域说明", "设置指南", "常见问题"] as const;

export type HelpTabLabel = (typeof HELP_TAB_LABELS)[number];

export type HelpTabsOk = { ok: true; tabs: { label: string; content: string }[] };
export type HelpTabsFallback = { ok: false; markdown: string };

function escapeReg(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * 将 helpme.md 按 `## 功能简介` … `## 常见问题` 拆成多段。
 * 若缺少预期章节标题，返回 ok:false，由调用方整页渲染 markdown。
 */
export function parseHelpmeMarkdown(markdown: string): HelpTabsOk | HelpTabsFallback {
  const trimmed = String(markdown || "").trim();
  if (!trimmed) return { ok: false, markdown: "" };

  const hasAllHeadings = HELP_TAB_LABELS.every((label) =>
    new RegExp(`^##\\s+${escapeReg(label)}\\s*$`, "m").test(trimmed),
  );
  if (!hasAllHeadings) {
    return { ok: false, markdown: trimmed };
  }

  const blocks = trimmed.split(/(?=^##\s+)/m);
  const map = new Map<string, string>();
  for (let i = 1; i < blocks.length; i++) {
    const m = blocks[i].match(/^##\s+(.+?)\s*\n([\s\S]*)$/);
    if (m) map.set(m[1].trim(), m[2].trim());
  }

  /** 去掉单独的一级标题行，其余前言并入「功能简介」 */
  const preamble = blocks[0]
    ? blocks[0]
        .replace(/^#\s+[^\n]+\s*\n?/m, "")
        .trim()
    : "";

  const tabs = HELP_TAB_LABELS.map((label) => {
    let content = map.get(label) || "_本节暂无内容。_";
    if (label === "功能简介" && preamble) {
      content = `${preamble}\n\n${content}`;
    }
    return { label, content };
  });

  return { ok: true, tabs };
}
