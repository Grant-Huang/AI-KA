"""
Evolution queue for focus point improvement hints.
Hints are written to: <repo>/.aika/evolution-queue/<focus_id>.jsonl
Each line is a JSON object with full provenance fields.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def evolution_queue_dir(repo_root: Path) -> Path:
    return repo_root / ".aika" / "evolution-queue"


def _current_user_role() -> str:
    """Read AIKA_USER_ROLE env var; default to 'consultant'."""
    return os.environ.get("AIKA_USER_ROLE", "consultant").strip()


def append_evolve_hint(
    repo_root: Path,
    *,
    focus_id: str,
    suggestion: str,
    source_role: str | None = None,
    source_type: str = "evolve_hint",
    project_id: str | int | None = None,
    conversation_id: int | None = None,
    turn: int = 0,
) -> None:
    """Append a single evolve hint to the queue file for focus_id.

    source_role: 'senior_expert' | 'consultant' | 'ai_self'. Defaults to AIKA_USER_ROLE env var.
    source_type: 'evolve_hint' | 'post_review' | 'extraction'.
    """
    d = evolution_queue_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    queue_file = d / f"{focus_id}.jsonl"
    entry: dict[str, Any] = {
        "focus_id": focus_id,
        "suggestion": suggestion,
        "source_role": source_role or _current_user_role(),
        "source_type": source_type,
        "status": "pending_review",
        "project_id": str(project_id) if project_id is not None else None,
        "conversation_id": conversation_id,
        "turn": turn,
        "created_at": datetime.utcnow().isoformat(),
    }
    with queue_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_hints_for_focus(repo_root: Path, focus_id: str) -> list[dict[str, Any]]:
    """Read all queued hints for a focus point."""
    queue_file = evolution_queue_dir(repo_root) / f"{focus_id}.jsonl"
    if not queue_file.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in queue_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def list_all_hint_focus_ids(repo_root: Path) -> list[str]:
    """Return focus IDs that have queued hints."""
    d = evolution_queue_dir(repo_root)
    if not d.is_dir():
        return []
    return [f.stem for f in sorted(d.glob("*.jsonl")) if f.stat().st_size > 0]


def clear_hints_for_focus(repo_root: Path, focus_id: str) -> int:
    """Delete the queue file for focus_id. Returns number of hints cleared."""
    queue_file = evolution_queue_dir(repo_root) / f"{focus_id}.jsonl"
    if not queue_file.is_file():
        return 0
    hints = list_hints_for_focus(repo_root, focus_id)
    queue_file.unlink()
    return len(hints)
