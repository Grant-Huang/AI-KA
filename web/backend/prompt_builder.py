from __future__ import annotations

import json
from typing import Any


DEFAULT_RULES: dict[str, Any] = {
    "goal": "对项目文档进行结构化分析，输出可在前端渲染的 blocks。",
    "dimensions": ["需求", "风险", "接口与集成", "待确认事项"],
    "style": {"prefer": ["cards", "table", "tabs"]},
}


BLOCK_SCHEMA_HINT = """
【强制输出格式】只能输出一个合法 JSON 对象，不得包含任何前缀文字、后缀说明、注释或 Markdown 围栏（```json ... ```）。
输出必须能被 json.loads() 直接解析，结构如下：
{
  "title": "可选标题",
  "blocks": [
    {"type": "heading", "level": 2, "text": "章节"},
    {"type": "paragraph", "text": "段落"},
    {"type": "tags", "items": ["标签1", "标签2"]},
    {"type": "table", "headers": ["列A","列B"], "rows": [["a","b"]]},
    {"type": "cards", "items": [{"title":"卡片标题","body":"内容","tags":["t1"]}]},
    {"type": "tabs", "title": "可选", "items": [{"tab":"页签名","blocks":[ ... 内嵌同结构 ... ]}]},
    {"type": "callout", "style": "info|warning|danger|success", "title": "可选", "text": "提示内容"}
  ]
}
第一个字符必须是 {，最后一个字符必须是 }，JSON 之外不能有任何其他内容。
"""


def merge_rules(user_rules: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_RULES)
    if user_rules:
        base.update(user_rules)
    return base


def build_system_prompt(
    rules: dict[str, Any] | None = None,
    *,
    focus_definitions: list[dict[str, str]] | None = None,
) -> str:
    """
    主流程：传入 focus_definitions（来自 rules.md/设置中的 name+prompt，并按本次勾选子集过滤），
    驱动文档审查；不再依赖 LLM 预生成的 goal/dimensions JSON。
    兼容：未传关注点定义时，仍使用 merge_rules(rules) 的旧维度字段。
    """
    if focus_definitions:
        lines: list[str] = [
            "你是资深 IT 实施与项目评审顾问。基于用户提供的文档片段，按「关注点审查清单」逐项审查并输出结构化结论。\n",
            "输出语言要求：除专有名词、英文缩写、代码/协议字段外，其余文本必须使用简体中文。\n",
            "审查要求：\n",
            "- 对下列每个关注点分别给出：发现、结论、建议（如适用）；\n",
            "- 结论需引用片段证据（片段编号或原文要点摘录）；\n",
            "- 若某关注点无证据，明确说明未在片段中发现相关内容。\n",
            "\n关注点审查清单（名称与审查要点来自 rules.md / 应用设置）：\n",
        ]
        for i, fd in enumerate(focus_definitions, 1):
            name = str(fd.get("name") or "").strip()
            pid = str(fd.get("id") or name).strip()
            prm = str(fd.get("prompt") or "").strip()
            lines.append(f"{i}. 【{name}】（id={pid}）\n   审查要点：{prm}\n")
        lines.append(
            "\n输出风格偏好："
            + json.dumps(DEFAULT_RULES.get("style", {}), ensure_ascii=False)
            + "\n"
        )
        return "".join(lines) + BLOCK_SCHEMA_HINT

    r = merge_rules(rules)
    return (
        "你是资深 IT 实施与项目评审顾问。基于用户提供的文档片段进行分析。\n"
        "输出语言要求：除专有名词、英文缩写、代码/协议字段外，其余文本必须使用简体中文。\n"
        f"分析目标：{r.get('goal', '')}\n"
        f"关注维度：{json.dumps(r.get('dimensions', []), ensure_ascii=False)}\n"
        f"输出风格偏好：{json.dumps(r.get('style', {}), ensure_ascii=False)}\n"
        + BLOCK_SCHEMA_HINT
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
    return "以下是项目 Markdown 片段（可能经 docs2md 转换）。请按系统要求输出中文 JSON：\n\n" + "\n".join(parts)
