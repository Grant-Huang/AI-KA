"""
Knowledge extraction data models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KnowledgeItem:
    id: str
    extraction_focus_id: str
    title: str
    content: str
    source_evidence: str = ""
    confidence: str = "medium"          # high | medium | low
    status: str = "pending"             # pending | approved | rejected | active
    tags: list[str] = field(default_factory=list)
    applicable_when: dict[str, Any] = field(default_factory=dict)
    not_applicable_when: dict[str, Any] = field(default_factory=dict)
    scope_note: str = ""
    source_role: str = "senior_expert"  # senior_expert | consultant | ai_self
    source_type: str = "extraction"     # extraction | post_review | evolve_hint
    backtest_result: dict[str, Any] | None = None
    conflict_with: list[str] = field(default_factory=list)
    extraction_strategy: str = ""       # fuzzy_signal | gap_based | critical_incident | reverse_validation
    project_id: int | None = None
    conversation_id: int | None = None
    review_queue_item_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "extraction_focus_id": self.extraction_focus_id,
            "title": self.title,
            "content": self.content,
            "source_evidence": self.source_evidence,
            "confidence": self.confidence,
            "status": self.status,
            "tags": self.tags,
            "applicable_when": self.applicable_when,
            "not_applicable_when": self.not_applicable_when,
            "scope_note": self.scope_note,
            "source_role": self.source_role,
            "source_type": self.source_type,
            "backtest_result": self.backtest_result,
            "conflict_with": self.conflict_with,
            "extraction_strategy": self.extraction_strategy,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "review_queue_item_id": self.review_queue_item_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ReviewQueueItem:
    id: str
    focus_id: str
    suggestion: str
    source_role: str = "ai_self"        # senior_expert | consultant | ai_self
    source_type: str = "evolve_hint"    # evolve_hint | post_review | extraction
    status: str = "pending_review"      # pending_review | in_review | approved | rejected | archived
    occurrences: int = 1
    project_ids: list[str] = field(default_factory=list)
    conversation_id: int | None = None
    created_at: str = ""
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "focus_id": self.focus_id,
            "suggestion": self.suggestion,
            "source_role": self.source_role,
            "source_type": self.source_type,
            "status": self.status,
            "occurrences": self.occurrences,
            "project_ids": self.project_ids,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "reject_reason": self.reject_reason,
        }


@dataclass
class ExpertProfile:
    domains: list[str] = field(default_factory=list)
    background: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domains": self.domains,
            "background": self.background,
            "updated_at": self.updated_at,
        }


def next_ki_id(existing: list[KnowledgeItem | dict[str, Any]]) -> str:
    """Generate the next ki-NNN id based on existing items."""
    max_n = 0
    for item in existing:
        kid = item["id"] if isinstance(item, dict) else item.id
        if kid.startswith("ki-"):
            try:
                n = int(kid[3:])
                max_n = max(max_n, n)
            except ValueError:
                pass
    return f"ki-{max_n + 1:03d}"
