from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConversationMode(str, Enum):
    REVIEWING  = "reviewing"   # 审查模式：读文档，产出发现
    CLARIFYING = "clarifying"  # 追问模式：不重读文档，就已有发现问答
    REFINING   = "refining"    # 精炼模式：带约束重新审查
    GENERATING = "generating"  # 生成模式：聚合发现→文档


class ConversationState(str, Enum):
    IDLE            = "idle"
    IN_PROGRESS     = "in_progress"
    AWAITING_INPUT  = "awaiting_input"
    DONE            = "done"


class UserIntent(str, Enum):
    ANALYZE_NEW   = "analyze_new"   # 审查/分析/检查 + 章节/文档
    CLARIFY       = "clarify"       # 追问、解释、展开
    REFINE        = "refine"        # 深化、重新审、加强
    UPDATE_FINDING = "update_finding"  # 更新某条发现的状态
    GENERATE_DOC  = "generate_doc"  # 生成/导出报告
    CHAT          = "chat"          # 普通问答，不触发分析管道


class FindingStatus(str, Enum):
    OPEN         = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED     = "resolved"


class FindingSeverity(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


@dataclass
class Finding:
    id: str                          # e.g. "f-001"
    focus_id: str                    # e.g. "req"
    title: str
    severity: str                    # FindingSeverity value
    evidence: str = ""
    chunk_ids: list[int] = field(default_factory=list)
    status: str = FindingStatus.OPEN  # FindingStatus value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "focus_id": self.focus_id,
            "title": self.title,
            "severity": self.severity,
            "evidence": self.evidence,
            "chunk_ids": self.chunk_ids,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        return cls(
            id=str(d.get("id", "")),
            focus_id=str(d.get("focus_id", "")),
            title=str(d.get("title", "")),
            severity=str(d.get("severity", FindingSeverity.LOW)),
            evidence=str(d.get("evidence", "")),
            chunk_ids=list(d.get("chunk_ids", [])),
            status=str(d.get("status", FindingStatus.OPEN)),
        )


@dataclass
class MessageMetadata:
    mode: str = ConversationMode.REVIEWING
    focus_points_used: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    refinement_round: int = 0
    self_critique_summary: str | None = None
    deep_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "focus_points_used": self.focus_points_used,
            "findings": [f.to_dict() for f in self.findings],
            "refinement_round": self.refinement_round,
            "self_critique_summary": self.self_critique_summary,
            "deep_mode": self.deep_mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MessageMetadata":
        findings = [Finding.from_dict(f) for f in d.get("findings", [])]
        return cls(
            mode=str(d.get("mode", ConversationMode.REVIEWING)),
            focus_points_used=list(d.get("focus_points_used", [])),
            findings=findings,
            refinement_round=int(d.get("refinement_round", 0)),
            self_critique_summary=d.get("self_critique_summary"),
            deep_mode=bool(d.get("deep_mode", False)),
        )

    @classmethod
    def from_json(cls, s: str | None) -> "MessageMetadata":
        if not s:
            return cls()
        try:
            return cls.from_dict(json.loads(s))
        except (json.JSONDecodeError, Exception):
            return cls()


def collect_findings_from_conversation(
    messages: list[Any],  # list[MessageRow]
    status_filter: set[str] | None = None,
) -> list[Finding]:
    """从会话的所有 assistant 消息中聚合结构化发现。"""
    seen_ids: set[str] = set()
    out: list[Finding] = []
    for msg in messages:
        if getattr(msg, "role", None) != "assistant":
            continue
        meta = MessageMetadata.from_json(getattr(msg, "metadata_json", None))
        for f in meta.findings:
            if f.id in seen_ids:
                continue
            if status_filter is not None and f.status not in status_filter:
                continue
            seen_ids.add(f.id)
            out.append(f)
    return out


def next_finding_id(existing: list[Finding]) -> str:
    """生成下一个发现 ID，格式 f-001、f-002 …"""
    if not existing:
        return "f-001"
    nums = []
    for f in existing:
        try:
            nums.append(int(f.id.split("-")[1]))
        except (IndexError, ValueError):
            pass
    nxt = max(nums, default=0) + 1
    return f"f-{nxt:03d}"
