"""
Knowledge Item parser.

Parses LLM output for structured knowledge extraction markers:
  <!-- ki: {"focus": "...", "title": "...", "confidence": "high|medium|low",
             "applicable_when": {...}, "not_applicable_when": {...}} -->
  <!-- clarify: {"strategy": "...", "questions": ["q1", "q2"]} -->
  <!-- satisfaction: 0.85 -->
"""
from __future__ import annotations

import json
import re
from typing import Any

_KI_RE = re.compile(r"<!--\s*ki:\s*(\{.*?\})\s*-->", re.DOTALL | re.IGNORECASE)
_CLARIFY_RE = re.compile(r"<!--\s*clarify:\s*(\{.*?\})\s*-->", re.DOTALL | re.IGNORECASE)
_SATISFACTION_RE = re.compile(r"<!--\s*satisfaction:\s*([0-9.]+)\s*-->", re.IGNORECASE)

VALID_CONFIDENCES = {"high", "medium", "low"}


def extract_ki_items(text: str) -> list[dict[str, Any]]:
    """Extract <!-- ki: {...} --> markers from LLM output."""
    out: list[dict[str, Any]] = []
    for m in _KI_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except (json.JSONDecodeError, Exception):
            continue
        title = str(obj.get("title") or "").strip()
        if not title:
            continue
        confidence = str(obj.get("confidence") or "medium").strip().lower()
        if confidence not in VALID_CONFIDENCES:
            confidence = "medium"
        out.append({
            "focus_id": str(obj.get("focus") or obj.get("focus_id") or "").strip(),
            "title": title,
            "content": str(obj.get("content") or "").strip(),
            "confidence": confidence,
            "applicable_when": obj.get("applicable_when") or {},
            "not_applicable_when": obj.get("not_applicable_when") or {},
            "scope_note": str(obj.get("scope_note") or "").strip(),
            "source_evidence": str(obj.get("evidence") or obj.get("source_evidence") or "").strip(),
            "extraction_strategy": str(obj.get("strategy") or "").strip(),
        })
    return out


def extract_clarify(text: str) -> dict[str, Any] | None:
    """Extract the last <!-- clarify: {...} --> marker."""
    matches = list(_CLARIFY_RE.finditer(text))
    if not matches:
        return None
    try:
        obj = json.loads(matches[-1].group(1))
        return {
            "strategy": str(obj.get("strategy") or ""),
            "questions": [str(q) for q in (obj.get("questions") or [])],
        }
    except Exception:
        return None


def extract_satisfaction(text: str) -> float | None:
    """Extract <!-- satisfaction: 0.85 --> score (last occurrence wins)."""
    matches = list(_SATISFACTION_RE.finditer(text))
    if not matches:
        return None
    try:
        return float(matches[-1].group(1))
    except ValueError:
        return None


KI_INSTRUCTION = """
【知识条目标记（必须遵守）】
当你提炼出一条可复用的知识规则时，在该规则后附加：
<!-- ki: {"focus": "<关注点id>", "title": "<规则标题，15字以内>", "confidence": "high|medium|low",
          "content": "<IF-THEN格式规则正文>",
          "applicable_when": {"project_type": ["contract"], "duration_months_gt": 6},
          "not_applicable_when": {"project_type": ["poc"]},
          "scope_note": "<自然语言说明适用条件>",
          "evidence": "<专家陈述的关键原文片段>"} -->

当你仍需澄清时（满意度 < 0.85），在回复末尾附加：
<!-- clarify: {"strategy": "gap_based|fuzzy_signal|critical_incident|reverse_validation",
               "questions": ["追问问题1", "追问问题2"]} -->

当你评估当前知识条目已足够充分（满意度 ≥ 0.85）时，附加：
<!-- satisfaction: 0.90 -->

规则：
- confidence: high=规则条件与结果清晰且有具体案例支撑，medium=有方向但边界模糊，low=仅为提示
- 每轮最多输出 3 条 ki 标记；先深后广
- 不重复已确认的条目（见已提取列表）
""".strip()
