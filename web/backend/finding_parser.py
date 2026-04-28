from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .conversation_models import Finding, FindingSeverity, next_finding_id

# LLM 在输出中嵌入的结构化发现标记
# 格式: <!-- finding: {"focus_id": "req", "title": "...", "severity": "high", "evidence": "..."} -->
_FINDING_MARKER_RE = re.compile(
    r"<!--\s*finding:\s*(\{.*?\})\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# evolve-hint 标记（Sprint 7 用）
_EVOLVE_HINT_RE = re.compile(
    r"<!--\s*evolve-hint:\s*([a-z_\-]+)\s*\|\s*(.*?)\s*-->",
    re.IGNORECASE,
)

VALID_SEVERITIES = {FindingSeverity.HIGH, FindingSeverity.MEDIUM, FindingSeverity.LOW,
                   "high", "medium", "low"}


def extract_findings_from_markdown(
    text: str,
    existing_findings: list[Finding],
    focus_ids_used: list[str],
) -> list[Finding]:
    """
    从 LLM Markdown 输出中提取结构化发现标记，
    分配 ID（接续已有发现编号），去重后返回新发现列表。
    """
    raw_findings: list[Finding] = []
    for m in _FINDING_MARKER_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except (json.JSONDecodeError, Exception):
            continue
        focus_id = str(obj.get("focus_id") or "").strip()
        title = str(obj.get("title") or "").strip()
        severity = str(obj.get("severity") or "low").strip().lower()
        evidence = str(obj.get("evidence") or "").strip()
        if not title:
            continue
        if severity not in VALID_SEVERITIES:
            severity = "low"
        # focus_id fallback: 若 LLM 未提供，取本次用的第一个
        if not focus_id and focus_ids_used:
            focus_id = focus_ids_used[0]
        raw_findings.append(Finding(
            id="",  # assigned below
            focus_id=focus_id,
            title=title,
            severity=severity,
            evidence=evidence,
        ))

    # 去重并分配 ID
    all_so_far: list[Finding] = list(existing_findings)
    new_findings: list[Finding] = []
    for f in raw_findings:
        if _is_duplicate(f, all_so_far):
            continue
        fid = next_finding_id(all_so_far + new_findings)
        f.id = fid
        new_findings.append(f)
        all_so_far.append(f)
    return new_findings


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """
    跨轮次发现去重：同 focus_id + 标题相似度 > 0.72 视为重复，保留第一条。
    """
    out: list[Finding] = []
    for f in findings:
        if not _is_duplicate(f, out):
            out.append(f)
    return out


def _is_duplicate(candidate: Finding, existing: list[Finding]) -> bool:
    for e in existing:
        if e.focus_id != candidate.focus_id:
            continue
        ratio = SequenceMatcher(None, e.title, candidate.title).ratio()
        if ratio > 0.72:
            return True
    return False


def extract_evolve_hints(text: str) -> list[dict[str, str]]:
    """提取 LLM 输出中的演化建议标记（Sprint 7 使用）。"""
    out: list[dict[str, str]] = []
    for m in _EVOLVE_HINT_RE.finditer(text):
        focus_id = m.group(1).strip()
        suggestion = m.group(2).strip()
        if focus_id and suggestion:
            out.append({"focus_id": focus_id, "suggestion": suggestion})
    return out


FINDING_INSTRUCTION = """
【结构化发现标记（必须遵守）】
在每个具体发现后，立即附加一个 HTML 注释标记（不影响渲染，但机器需要读取）：
<!-- finding: {"focus_id": "<关注点id>", "title": "<发现标题，15字以内>", "severity": "high|medium|low", "evidence": "<来源片段或行号，简短>"} -->

规则：
- 每个值得记录的发现（问题、风险、缺失项）都必须有此标记
- severity: high=可能影响项目成败, medium=需要关注, low=建议改进
- focus_id 使用本次审查的关注点 id（见上方审查清单）
- 无发现时不输出此注释
""".strip()
