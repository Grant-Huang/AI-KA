"""Write confirmed knowledge cards to personal and org storage, and generate session MD files."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from aika.db import KnowledgeCardRow
from backend.personal_memory import personal_aika_dir
from backend.repo_paths import repository_root


# ── Helpers ───────────────────────────────────────────────────

def _safe_filename(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w一-鿿\-]", "_", text)
    return s[:max_len].strip("_") or "card"


def _card_to_md(card: KnowledgeCardRow) -> str:
    type_labels = {
        "risk_signal": "风险信号", "rule": "判断规则",
        "process": "操作流程", "best_practice": "最佳实践",
        "anti_pattern": "反面案例",
    }
    conf_labels = {"high": "高（多次验证）", "medium": "中（个人经验）", "low": "低（推测）"}
    lines = [
        f"# {card.title}",
        "",
        f"**类型**：{type_labels.get(card.card_type, card.card_type)}",
        f"**置信度**：{conf_labels.get(card.confidence, card.confidence)}",
    ]
    if card.applicable_scope:
        lines.append(f"**适用范围**：{card.applicable_scope}")
    if card.exceptions:
        lines.append(f"**例外情况**：{card.exceptions}")
    lines += ["", "## 核心内容", "", card.content, ""]
    return "\n".join(lines)


# ── Personal knowledge write ──────────────────────────────────

def personal_extraction_dir(username: str) -> Path:
    return personal_aika_dir() / "extraction-sessions" / username


def write_personal_card(username: str, card: KnowledgeCardRow) -> Path:
    """Write a confirmed card as a markdown file to ~/.aika/extraction-sessions/<username>/cards/."""
    cards_dir = personal_extraction_dir(username) / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y%m%d")
    fname = f"{date_str}-{card.id}-{_safe_filename(card.title)}.md"
    path = cards_dir / fname
    path.write_text(_card_to_md(card), encoding="utf-8")
    return path


# ── Org pending queue ─────────────────────────────────────────

def org_pending_dir() -> Path:
    return repository_root() / ".aika" / "pending-knowledge"


def write_org_pending(card: KnowledgeCardRow, username: str) -> Path:
    """Append a confirmed card to the org pending queue as a JSON file."""
    pending_dir = org_pending_dir()
    pending_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    fname = f"{ts}-{card.id}-{_safe_filename(card.title)}.json"
    path = pending_dir / fname
    payload: dict[str, Any] = {
        "card_id": card.id,
        "conversation_id": card.conversation_id,
        "submitted_by": username,
        "submitted_at": datetime.utcnow().isoformat(),
        "card_type": card.card_type,
        "title": card.title,
        "content": card.content,
        "applicable_scope": card.applicable_scope,
        "exceptions": card.exceptions,
        "confidence": card.confidence,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ── Session Markdown file ─────────────────────────────────────

def generate_session_md(
    *,
    session_id: int,
    title: str,
    display_name: str,
    username: str,
    focus_label: str,
    messages: list[dict],
    cards: list[KnowledgeCardRow],
) -> tuple[Path, str]:
    """Generate the session markdown file and save it. Returns (path, filename)."""
    date_str = datetime.utcnow().strftime("%Y%m%d")
    safe_name = _safe_filename(display_name, 10)
    safe_focus = _safe_filename(focus_label, 12) if focus_label else "通用"
    filename = f"知识提取_{safe_name}_{safe_focus}_{date_str}.md"

    confirmed_cards = [c for c in cards if c.status in ("confirmed", "edited")]
    rejected_cards = [c for c in cards if c.status == "rejected"]
    pending_cards = [c for c in cards if c.status == "pending"]

    lines = [
        "# 知识提取会话记录",
        "",
        f"- 专家：{display_name}",
        f"- 日期：{datetime.utcnow().strftime('%Y-%m-%d')}",
        f"- 方向：{focus_label or '通用'}",
        f"- 已确认卡片：{len(confirmed_cards)} 张",
        "",
        "---",
        "",
        "## 对话记录",
        "",
    ]
    for msg in messages:
        role_label = "AI" if msg.get("role") == "assistant" else display_name
        created = msg.get("created_at", "")[:16].replace("T", " ")
        lines.append(f"**[{created}] {role_label}**")
        lines.append("")
        lines.append(msg.get("content", ""))
        lines.append("")
        lines.append("---")
        lines.append("")

    if confirmed_cards:
        type_labels = {
            "risk_signal": "风险信号", "rule": "判断规则",
            "process": "操作流程", "best_practice": "最佳实践",
            "anti_pattern": "反面案例",
        }
        lines += ["## 已确认知识卡片", ""]
        for i, card in enumerate(confirmed_cards, 1):
            lines.append(f"### 卡片 #{i} · {type_labels.get(card.card_type, card.card_type)}")
            lines.append("")
            lines.append(f"**{card.title}**")
            lines.append("")
            lines.append(card.content)
            if card.applicable_scope:
                lines.append(f"\n*适用范围：{card.applicable_scope}*")
            if card.exceptions:
                lines.append(f"\n*例外情况：{card.exceptions}*")
            lines += [f"\n*置信度：{card.confidence}*", ""]

    content = "\n".join(lines)

    # Save to personal extraction dir
    session_dir = personal_extraction_dir(username)
    session_dir.mkdir(parents=True, exist_ok=True)
    personal_path = session_dir / filename
    personal_path.write_text(content, encoding="utf-8")

    # Save to org extraction-sessions (desensitized copy goes same place for now)
    org_dir = repository_root() / ".aika" / "extraction-sessions"
    org_dir.mkdir(parents=True, exist_ok=True)
    (org_dir / filename).write_text(content, encoding="utf-8")

    return personal_path, filename
