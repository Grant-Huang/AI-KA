from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aika import db as dbm


def _tokenize(s: str) -> set[str]:
    return {x for x in re.split(r"[^\w一-鿿]+", (s or "").lower()) if len(x) > 1}


def _keyword_score(text: str, query: str) -> int:
    q = _tokenize(query)
    t = _tokenize(text)
    if not q:
        return 0
    return len(q & t)


def memory_root_under_repo(repo_root: Path) -> Path:
    return repo_root / ".aika" / "memory"


def iter_memory_candidate_files(memory_root: Path, project_id: int) -> list[Path]:
    out: list[Path] = []
    for sub in ("user", "feedback"):
        d = memory_root / sub
        if d.is_dir():
            out.extend(sorted(d.glob("*.md")))
    for sub in (f"project/{project_id}", f"reference/{project_id}"):
        d = memory_root / sub
        if d.is_dir():
            out.extend(sorted(d.glob("*.md")))
    return sorted(out, key=lambda p: str(p))


def recall_memory_snippets(
    *,
    memory_root: Path,
    project_id: int,
    query: str,
    already_surfaced: set[str],
    limit: int = 5,
    max_body_chars: int = 6000,
    db_conn: Any = None,
    embed_query_vec: list[float] | None = None,
    semantic_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    """
    Hybrid recall: keyword overlap (35%) + cosine similarity (65%) when embeddings available.
    Falls back to keyword-only when embed_query_vec is None or db_conn is None.
    Files scoring below semantic_threshold (on semantic dimension) are filtered out when
    semantic scoring is active; when no embeddings are available keyword>0 threshold applies.
    """
    from backend.embedding_service import bytes_to_vec, content_hash, cosine_similarity, hybrid_score

    files = iter_memory_candidate_files(memory_root, project_id)
    scored: list[tuple[float, Path, str]] = []  # (score, path, body)
    q = (query or "").strip()

    use_semantic = embed_query_vec is not None and db_conn is not None

    # Preload embeddings from db keyed by rel path
    db_embeddings: dict[str, bytes] = {}
    if use_semantic and db_conn is not None:
        try:
            rows = dbm.list_all_memory_embeddings(db_conn)
            db_embeddings = {r["path"]: r["embedding"] for r in rows}
        except Exception:
            use_semantic = False

    for p in files:
        try:
            rel = str(p.relative_to(memory_root)).replace("\\", "/")
        except ValueError:
            continue
        if rel in already_surfaced:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        kw_raw = _keyword_score(text, q) if q else 1

        if use_semantic:
            assert embed_query_vec is not None
            emb_bytes = db_embeddings.get(rel)
            if emb_bytes:
                doc_vec = bytes_to_vec(emb_bytes)
                sem = cosine_similarity(embed_query_vec, doc_vec)
            else:
                sem = 0.0

            if sem < semantic_threshold and kw_raw == 0:
                continue

            # Normalise keyword score to [0,1] — cap at 10 matches
            kw_norm = min(kw_raw / 10.0, 1.0)
            score = hybrid_score(kw_norm, sem)
        else:
            if q and kw_raw <= 0:
                continue
            score = float(kw_raw)

        scored.append((score, p, text))

    scored.sort(key=lambda x: (-x[0], str(x[1])))

    out: list[dict[str, Any]] = []
    for sc, p, body in scored:
        try:
            rel = str(p.relative_to(memory_root)).replace("\\", "/")
        except ValueError:
            continue
        if len(body) > max_body_chars:
            body = body[:max_body_chars] + "\n\n（已截断）\n"
        out.append(
            {
                "id": rel,
                "title": p.stem,
                "body": body,
                "score": sc,
            }
        )
        if len(out) >= limit:
            break
    return out
