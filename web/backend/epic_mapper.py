from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def analysis_to_epic_doc_config(*, theme: str, title: str, analysis: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    if analysis.get("title"):
        blocks.append({"type": "heading", "text": str(analysis["title"]), "level": 1})
    for b in analysis.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        epic_blocks = _map_block(b)
        blocks.extend(epic_blocks)

    return {
        "theme": theme,
        "meta": {
            "title": title,
            "author": "AI-KA",
            "subject": "Project analysis",
        },
        "header": {"text": title[:80], "align": "right"},
        "footer": {"text": "AI-KA", "page_number": True, "align": "center"},
        "blocks": blocks,
    }


def _map_block(b: dict[str, Any]) -> list[dict[str, Any]]:
    t = str(b.get("type") or "").lower()
    out: list[dict[str, Any]] = []

    if t == "heading":
        level = int(b.get("level") or 2)
        level = max(1, min(4, level))
        out.append({"type": "heading", "text": str(b.get("text") or ""), "level": level})
    elif t == "paragraph":
        out.append({"type": "paragraph", "text": str(b.get("text") or "")})
    elif t == "tags":
        items = b.get("items") or []
        if isinstance(items, list) and items:
            lines = "\n".join(f"- {x}" for x in items if str(x).strip())
            out.append({"type": "paragraph", "text": "标签：\n" + lines})
    elif t == "table":
        headers = b.get("headers") or []
        rows = b.get("rows") or []
        if not isinstance(headers, list):
            headers = []
        if not isinstance(rows, list):
            rows = []
        data: list[list[Any]] = [list(headers)]
        for row in rows:
            if isinstance(row, list):
                data.append(list(row))
        if len(data) > 1 or (data and any(str(c).strip() for c in data[0])):
            out.append(
                {
                    "type": "table",
                    "data": data,
                    "headers": True,
                    "style": "striped",
                }
            )
    elif t == "cards":
        for it in b.get("items") or []:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "")
            body = str(it.get("body") or "")
            tags = it.get("tags") or []
            tag_s = ""
            if isinstance(tags, list) and tags:
                tag_s = " [" + ", ".join(str(x) for x in tags) + "]"
            out.append({"type": "heading", "text": title + tag_s, "level": 3})
            out.append({"type": "paragraph", "text": body})
    elif t == "tabs":
        out.append({"type": "heading", "text": str(b.get("title") or "分栏"), "level": 2})
        for item in b.get("items") or []:
            if not isinstance(item, dict):
                continue
            tab = str(item.get("tab") or "Tab")
            out.append({"type": "heading", "text": tab, "level": 3})
            for inner in item.get("blocks") or []:
                if isinstance(inner, dict):
                    out.extend(_map_block(inner))
    elif t == "callout":
        out.append(
            {
                "type": "callout",
                "style": str(b.get("style") or "info"),
                "title": str(b.get("title") or ""),
                "text": str(b.get("text") or ""),
            }
        )
    return out


def dump_epic_config_json(config: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
