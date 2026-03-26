from __future__ import annotations

import json
from typing import Any


DEFAULT_RULES: dict[str, Any] = {
    "goal": "对项目文档进行结构化分析，输出可在前端渲染的 blocks。",
    "dimensions": ["需求", "风险", "接口与集成", "待确认事项"],
    "style": {"prefer": ["cards", "table", "tabs"]},
}


BLOCK_SCHEMA_HINT = """
你必须只输出一个 JSON 对象（不要 Markdown 围栏），结构如下：
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
"""


def merge_rules(user_rules: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_RULES)
    if user_rules:
        base.update(user_rules)
    return base


def build_system_prompt(rules: dict[str, Any]) -> str:
    r = merge_rules(rules)
    return (
        "你是资深 IT 实施与项目评审顾问。基于用户提供的文档片段进行分析。\n"
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
    return "以下是项目 Markdown 片段（可能经 docs2md 转换）：\n\n" + "\n".join(parts)
