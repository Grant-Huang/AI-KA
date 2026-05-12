"""
Rule conflict detector.

Checks whether a new KnowledgeItem conflicts with existing FocusPoint rules.
Uses LLM-assisted semantic comparison when available, falls back to keyword overlap.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


def detect_conflicts(
    new_item: dict[str, Any],
    existing_focus_points: list[dict[str, Any]],
) -> list[str]:
    """Return list of focus_point ids that may conflict with new_item.

    existing_focus_points: list of dicts with keys: id, name, prompt (text of the rule).
    """
    conflicts: list[str] = []
    new_text = (new_item.get("title", "") + " " + new_item.get("content", "")).lower()
    new_focus = str(new_item.get("extraction_focus_id") or "").strip()

    for fp in existing_focus_points:
        fp_id = str(fp.get("id") or "").strip()
        fp_text = (str(fp.get("name") or "") + " " + str(fp.get("prompt") or "")).lower()

        # Same focus_id and high text similarity → likely conflict or redundant
        if fp_id == new_focus:
            ratio = SequenceMatcher(None, new_text[:300], fp_text[:300]).ratio()
            if ratio > 0.55:
                conflicts.append(fp_id)
                continue

        # Negation conflict: new says "must X", existing says "do not X"
        if _has_negation_conflict(new_text, fp_text):
            conflicts.append(fp_id)

    return list(dict.fromkeys(conflicts))  # deduplicate, preserve order


def _has_negation_conflict(text_a: str, text_b: str) -> bool:
    """Heuristic: detect if two rules contradict each other via negation keywords."""
    negation_pairs = [
        (r"\b必须\b", r"\b不能\b|不要\b|禁止\b"),
        (r"\b应该\b", r"\b不应该\b|不应\b"),
        (r"\b需要\b", r"\b不需要\b|无需\b"),
        (r"\b建议\b", r"\b不建议\b"),
    ]
    for pos_pat, neg_pat in negation_pairs:
        if re.search(pos_pat, text_a) and re.search(neg_pat, text_b):
            return True
        if re.search(pos_pat, text_b) and re.search(neg_pat, text_a):
            return True
    return False


async def detect_conflicts_with_llm(
    new_item: dict[str, Any],
    existing_focus_points: list[dict[str, Any]],
    provider: Any,
    cfg: Any,
) -> list[str]:
    """LLM-assisted conflict detection. Returns list of conflicting focus_ids."""
    if not existing_focus_points:
        return []

    fps_summary = "\n".join(
        f"- [{fp.get('id','')}] {fp.get('name','')}: {str(fp.get('prompt',''))[:100]}"
        for fp in existing_focus_points[:15]
    )
    new_rule_text = f"标题：{new_item.get('title','')}\n内容：{new_item.get('content','')}"

    prompt = f"""判断以下新规则是否与现有规则存在冲突（语义矛盾或相互否定）。

新规则：
{new_rule_text}

现有规则列表：
{fps_summary}

请输出冲突的规则 id（仅输出方括号中的 id，用逗号分隔，无冲突则输出 none）："""

    try:
        parts: list[str] = []
        for chunk in provider.chat_stream(
            system="你是规则一致性检查专家，请简洁地识别规则冲突。",
            user=prompt,
            config=cfg,
            prior_messages=None,
        ):
            if isinstance(chunk, dict):
                parts.append(chunk.get("content") or chunk.get("text") or "")
            else:
                parts.append(str(chunk))
        response = "".join(parts).strip().lower()
        if response in ("none", "无", "无冲突", ""):
            return []
        ids = [s.strip() for s in re.split(r"[,，\s]+", response) if s.strip() and s.strip() != "none"]
        valid_ids = {fp.get("id", "") for fp in existing_focus_points}
        return [i for i in ids if i in valid_ids]
    except Exception:
        # Fallback to keyword-based detection
        return detect_conflicts(new_item, existing_focus_points)
