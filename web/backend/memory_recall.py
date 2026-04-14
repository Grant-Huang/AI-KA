from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _tokenize(s: str) -> set[str]:
    return {x for x in re.split(r"[^\w\u4e00-\u9fff]+", (s or "").lower()) if len(x) > 1}


def _score(text: str, query: str) -> int:
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
) -> list[dict[str, Any]]:
    """
    关键词重叠打分 + already_surfaced 去重；query 为空时按路径顺序取前 limit 条。
    """
    files = iter_memory_candidate_files(memory_root, project_id)
    scored: list[tuple[int, Path]] = []
    q = (query or "").strip()
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
        sc = _score(text, q) if q else 1
        scored.append((sc, p))
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    out: list[dict[str, Any]] = []
    for sc, p in scored:
        if sc <= 0 and q:
            continue
        try:
            rel = str(p.relative_to(memory_root)).replace("\\", "/")
        except ValueError:
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
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
