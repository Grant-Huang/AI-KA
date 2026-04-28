"""
Personal memory layer: ~/.aika/
- ~/.aika/memory/  — personal notes, user preferences, cross-project knowledge
- ~/.aika/focus-overrides/  — personal focus point prompt overrides
- ~/.aika/embeddings.db  — personal embedding cache (SQLite)
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
from pathlib import Path
from typing import Any


def personal_aika_dir() -> Path:
    raw = os.environ.get("AIKA_PERSONAL_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path("~/.aika").expanduser().resolve()


def personal_memory_dir() -> Path:
    return personal_aika_dir() / "memory"


def personal_focus_overrides_dir() -> Path:
    return personal_aika_dir() / "focus-overrides"


def personal_embeddings_db_path() -> Path:
    return personal_aika_dir() / "embeddings.db"


def ensure_personal_dirs() -> Path:
    """Initialize ~/.aika/ directory structure on first run. Returns base dir."""
    base = personal_aika_dir()
    for sub in ("memory", "focus-overrides"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    readme = base / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# AI-KA Personal Memory\n\n"
            "This directory stores your personal AI-KA data:\n\n"
            "- `memory/` — personal notes and cross-project knowledge\n"
            "- `focus-overrides/` — personal overrides for focus point prompts (focus-<id>.md)\n"
            "- `embeddings.db` — local embedding cache\n",
            encoding="utf-8",
        )
    return base


def _open_personal_emb_db() -> sqlite3.Connection:
    db_path = personal_embeddings_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS personal_embeddings (
            path TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            content_hash TEXT NOT NULL,
            embed_model TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def upsert_personal_embedding(path: str, embedding_bytes: bytes, content_hash: str, embed_model: str) -> None:
    from datetime import datetime as _dt
    conn = _open_personal_emb_db()
    conn.execute(
        """
        INSERT INTO personal_embeddings(path, embedding, content_hash, embed_model, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          embedding=excluded.embedding,
          content_hash=excluded.content_hash,
          embed_model=excluded.embed_model,
          updated_at=excluded.updated_at
        """,
        (str(path), embedding_bytes, str(content_hash), str(embed_model), _dt.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_personal_embedding(path: str, content_hash: str) -> bytes | None:
    db_path = personal_embeddings_db_path()
    if not db_path.is_file():
        return None
    conn = _open_personal_emb_db()
    r = conn.execute(
        "SELECT embedding, content_hash FROM personal_embeddings WHERE path=?", (str(path),)
    ).fetchone()
    conn.close()
    if r is None or str(r["content_hash"]) != content_hash:
        return None
    return bytes(r["embedding"])


def list_personal_memory_files() -> list[Path]:
    mem_dir = personal_memory_dir()
    if not mem_dir.is_dir():
        return []
    return sorted(mem_dir.rglob("*.md"))


def load_personal_focus_override(focus_id: str) -> str | None:
    """Return prompt override text for focus_id, or None if no override exists."""
    p = personal_focus_overrides_dir() / f"focus-{focus_id}.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        return text or None
    except OSError:
        return None


def list_personal_focus_overrides() -> list[dict[str, str]]:
    d = personal_focus_overrides_dir()
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("focus-*.md")):
        fid = f.stem[len("focus-"):]
        out.append({"id": fid, "path": str(f)})
    return out


def recall_personal_memory(
    query: str,
    *,
    already_surfaced: set[str],
    limit: int = 3,
    embed_query_vec: list[float] | None = None,
) -> list[dict[str, Any]]:
    """
    Recall snippets from ~/.aika/memory/.
    Uses hybrid scoring when embed_query_vec is provided.
    """
    mem_dir = personal_memory_dir()
    if not mem_dir.is_dir():
        return []

    files = list(mem_dir.rglob("*.md"))
    if not files:
        return []

    import re
    from backend.embedding_service import bytes_to_vec, content_hash as emb_hash, cosine_similarity, hybrid_score, is_configured

    def _tokenize(s: str) -> set[str]:
        return {x for x in re.split(r"[^\w一-鿿]+", (s or "").lower()) if len(x) > 1}

    q_tokens = _tokenize(query)
    scored: list[tuple[float, Path, str]] = []

    for p in files:
        rel = str(p.relative_to(mem_dir)).replace("\\", "/")
        if f"personal:{rel}" in already_surfaced:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        kw_raw = len(q_tokens & _tokenize(text)) if q_tokens else 1

        if embed_query_vec is not None and is_configured():
            h = emb_hash(text)
            emb_bytes = get_personal_embedding(rel, h)
            if emb_bytes:
                sem = cosine_similarity(embed_query_vec, bytes_to_vec(emb_bytes))
            else:
                sem = 0.0
            if sem < 0.3 and kw_raw == 0:
                continue
            score = hybrid_score(min(kw_raw / 10.0, 1.0), sem)
        else:
            if not kw_raw and query:
                continue
            score = float(kw_raw)

        scored.append((score, p, text))

    scored.sort(key=lambda x: (-x[0], str(x[1])))
    out: list[dict[str, Any]] = []
    for sc, p, body in scored[:limit]:
        rel = str(p.relative_to(mem_dir)).replace("\\", "/")
        if len(body) > 4000:
            body = body[:4000] + "\n（已截断）\n"
        out.append({
            "id": f"personal:{rel}",
            "title": p.stem,
            "body": body,
            "score": sc,
            "source": "personal",
        })
    return out


# ---------------------------------------------------------------------------
# Memory suggestion queue
# ---------------------------------------------------------------------------
_SUGGESTION_FILENAME = "memory-suggestions.json"


def _suggestions_path() -> Path:
    return personal_aika_dir() / _SUGGESTION_FILENAME


def add_memory_suggestion(suggestion: dict[str, Any]) -> None:
    """Append a pending memory suggestion. Never auto-writes to memory/."""
    import json
    from datetime import datetime as _dt
    path = _suggestions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    suggestion.setdefault("created_at", _dt.utcnow().isoformat())
    suggestion.setdefault("status", "pending")
    existing.append(suggestion)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def list_memory_suggestions() -> list[dict[str, Any]]:
    import json
    path = _suggestions_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def approve_memory_suggestion(index: int) -> dict[str, Any] | None:
    """Write approved suggestion to memory/ and mark it approved in queue."""
    import json
    path = _suggestions_path()
    suggestions = list_memory_suggestions()
    if index < 0 or index >= len(suggestions):
        return None
    s = suggestions[index]
    title = str(s.get("title") or "memory").strip()
    content = str(s.get("content") or "").strip()
    if not content:
        return None
    mem_dir = personal_memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)
    dest = mem_dir / f"{title}.md"
    dest.write_text(content, encoding="utf-8")
    suggestions[index]["status"] = "approved"
    path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    return suggestions[index]


def dismiss_memory_suggestion(index: int) -> bool:
    import json
    path = _suggestions_path()
    suggestions = list_memory_suggestions()
    if index < 0 or index >= len(suggestions):
        return False
    suggestions[index]["status"] = "dismissed"
    path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
