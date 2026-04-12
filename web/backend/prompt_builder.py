from __future__ import annotations

import json
from typing import Any


DEFAULT_RULES: dict[str, Any] = {
    "goal": "对项目文档进行结构化分析，输出适合阅读与导出的 Markdown。",
    "dimensions": ["需求", "风险", "接口与集成", "待确认事项"],
    "style": {"prefer": ["cards", "table", "tabs"]},
}


MARKDOWN_OUTPUT_HINT = """
【强制输出格式】只输出一份可渲染的 Markdown 正文（UTF-8），不要输出 JSON，不要输出任何代码围栏（```）。
要求：
- 必须使用简体中文（专有名词/缩写除外）；
- 必须分章节输出（使用 `##` / `###`）；
- 必须给出“结论”与“建议”（如无证据需说明“未在片段中发现”）；
- 如引用证据，请标注片段编号（例如：片段 12），并与各片段块头中的「文件 / 章节」一致。
禁止：
- 不要输出 `<think>` / `</think>`；
- 不要输出任何“我将如何分析/Let me analyze...”之类的过程性文字。
"""

DEFAULT_REVIEW_ROLE = (
    "你是资深 IT 实施与项目评审顾问。基于用户提供的文档片段，按「关注点审查清单」逐项审查并输出结构化结论。"
)

DEFAULT_REVIEW_GOALS_AND_PRINCIPLES = """输出语言要求：除专有名词、英文缩写、代码/协议字段外，其余文本必须使用简体中文。
审查要求：
- 对下列每个关注点分别给出：发现、结论、建议（如适用）；
- 结论需引用片段证据（片段编号或原文要点摘录）；
- 若某关注点无证据，明确说明未在片段中发现相关内容。"""


def merge_rules(user_rules: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_RULES)
    if user_rules:
        base.update(user_rules)
    return base


def build_system_prompt(
    rules: dict[str, Any] | None = None,
    *,
    focus_definitions: list[dict[str, str]] | None = None,
    review_role: str | None = None,
    review_goals_principles: str | None = None,
    output_requirements: str | None = None,
) -> str:
    """
    主流程：传入 focus_definitions（来自 rules.md/设置中的 name+prompt，并按本次勾选子集过滤），
    驱动文档审查。

    review_role / review_goals_principles / output_requirements 来自「预设组合」；
    任一项非空则替换下方对应的默认段落，实现完整替代写死的角色、原则与输出格式说明。
    关注点清单始终来自 focus_definitions，不由预设整段替换。
    """
    if focus_definitions:
        role = (review_role or "").strip() or DEFAULT_REVIEW_ROLE
        goals = (review_goals_principles or "").strip() or DEFAULT_REVIEW_GOALS_AND_PRINCIPLES
        output = (output_requirements or "").strip() or MARKDOWN_OUTPUT_HINT
        lines: list[str] = [
            "【审查角色】\n",
            role + "\n\n",
            "【审查目标与原则】\n",
            goals + "\n\n",
            "关注点审查清单（名称与审查要点来自 rules.md / 应用设置）：\n",
        ]
        for i, fd in enumerate(focus_definitions, 1):
            name = str(fd.get("name") or "").strip()
            pid = str(fd.get("id") or name).strip()
            prm = str(fd.get("prompt") or "").strip()
            lines.append(f"{i}. 【{name}】（id={pid}）\n   审查要点：{prm}\n")
        lines.append("\n【输出要求】\n")
        lines.append(output)
        return "".join(lines)

    r = merge_rules(rules)
    return (
        "你是资深 IT 实施与项目评审顾问。基于用户提供的文档片段进行分析。\n"
        "输出语言要求：除专有名词、英文缩写、代码/协议字段外，其余文本必须使用简体中文。\n"
        f"分析目标：{r.get('goal', '')}\n"
        f"关注维度：{json.dumps(r.get('dimensions', []), ensure_ascii=False)}\n"
        f"输出风格偏好：{json.dumps(r.get('style', {}), ensure_ascii=False)}\n"
        + MARKDOWN_OUTPUT_HINT
    )


def build_user_prompt(*, chunk_texts: list[str], max_chars: int = 120_000) -> str:
    parts: list[str] = []
    total = 0
    for i, t in enumerate(chunk_texts):
        block = f"--- 片段 {i + 1} ---\n{t}\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "以下是项目 Markdown 片段（可能经 docs2md 转换）。请按系统要求输出中文 Markdown：\n\n" + "\n".join(parts)


# 送入模型时排除的章节名（docs2md 等常把 Word 页眉页脚落成独立标题）
_HEADER_FOOTER_TITLES_ZH: frozenset[str] = frozenset({"页眉", "页脚", "页眉页脚"})
_HEADER_FOOTER_TITLES_EN: frozenset[str] = frozenset({"header", "footer"})


def _is_header_footer_locator(loc: dict[str, Any]) -> bool:
    """若章节路径或当前节标题为页眉/页脚类节点，则不在分析 prompt 中保留该 chunk。"""
    titles: list[str] = []
    hp = loc.get("heading_path")
    if isinstance(hp, list):
        for x in hp:
            t = str(x).strip()
            if t:
                titles.append(t)
    st = loc.get("section_title")
    if isinstance(st, str):
        t = st.strip()
        if t:
            titles.append(t)
    for t in titles:
        if t in _HEADER_FOOTER_TITLES_ZH:
            return True
        if t.lower() in _HEADER_FOOTER_TITLES_EN:
            return True
    return False


def _format_section_from_locator(loc: dict[str, Any]) -> str:
    hp = loc.get("heading_path")
    if isinstance(hp, list) and hp:
        return " > ".join(str(x) for x in hp if str(x).strip())
    return "—"


def _format_lines_from_locator(loc: dict[str, Any]) -> str:
    sl = loc.get("start_line")
    el = loc.get("end_line")
    if isinstance(sl, int) and isinstance(el, int):
        return f"{sl}-{el}"
    return "—"


def build_user_prompt_from_entries(
    entries: list[dict[str, Any]],
    *,
    max_chars: int = 120_000,
) -> tuple[str, list[dict[str, Any]]]:
    """
    返回 (prompt 文本, 实际纳入 prompt 的 entries 子列表)，用于与文末索引表一致。
    """
    filtered: list[dict[str, Any]] = []
    for e in entries:
        loc = e.get("locator") if isinstance(e.get("locator"), dict) else {}
        if _is_header_footer_locator(loc):
            continue
        filtered.append(e)

    parts: list[str] = []
    total = 0
    used: list[dict[str, Any]] = []
    for i, e in enumerate(filtered):
        loc = e.get("locator") if isinstance(e.get("locator"), dict) else {}
        path = str(e.get("doc_path") or "")
        section = _format_section_from_locator(loc)
        lines_rng = _format_lines_from_locator(loc)
        body = str(e.get("text") or "")
        header = f"--- 片段 {i + 1} | 文件: {path} | 章节: {section} | 行: {lines_rng} ---\n"
        block = header + body + "\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
        used.append(e)
    intro = "以下是项目 Markdown 片段（可能经 docs2md 转换）。请按系统要求输出中文 Markdown：\n\n"
    return intro + "\n".join(parts), used


def format_chunk_index_markdown(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    rows: list[str] = [
        "",
        "## 片段与来源索引",
        "",
        "| 片段 | 文件 | 章节 | 行号 |",
        "| --- | --- | --- | --- |",
    ]
    for i, e in enumerate(entries, start=1):
        loc = e.get("locator") if isinstance(e.get("locator"), dict) else {}
        path = str(e.get("doc_path") or "").replace("|", "\\|")
        section = _format_section_from_locator(loc).replace("|", "\\|")
        lines_rng = _format_lines_from_locator(loc)
        rows.append(f"| {i} | {path} | {section} | {lines_rng} |")
    rows.append("")
    return "\n".join(rows)


def format_chunk_index_lines_markdown(entries: list[dict[str, Any]]) -> str:
    """
    可单独下载的完整「片段与来源索引」Markdown：每个纳入模型的片段占一行（非表格），
    与送入模型的分块集合一致；用于解析完成后下载，不包含在审查结论正文中。
    """
    if not entries:
        return ""
    lines: list[str] = [
        "# 片段与来源索引",
        "",
        "以下为本次分析纳入模型的分块；每行一个片段。",
        "",
    ]
    for i, e in enumerate(entries, start=1):
        loc = e.get("locator") if isinstance(e.get("locator"), dict) else {}
        path = str(e.get("doc_path") or "").replace("|", "\\|")
        section = _format_section_from_locator(loc).replace("|", "\\|")
        lines_rng = _format_lines_from_locator(loc)
        lines.append(f"片段 {i} | 文件: {path} | 章节: {section} | 行: {lines_rng}")
    lines.append("")
    return "\n".join(lines)
