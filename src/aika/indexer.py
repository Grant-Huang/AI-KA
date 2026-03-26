from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import db as dbm


STAGE_KEYWORDS: list[tuple[str, str]] = [
    ("调研", "调研"),
    ("蓝图", "蓝图"),
    ("设计", "设计"),
    ("开发", "开发"),
    ("测试", "测试"),
    ("上线", "上线"),
    ("复盘", "复盘"),
]


@dataclass(frozen=True)
class ScanFile:
    rel_path: str
    abs_path: Path
    ext: str
    mtime: float
    sha256: str
    stage: str | None


def _normalize_rel_path(p: Path) -> str:
    return p.as_posix()


def detect_stage(rel_path: str) -> str | None:
    lower = rel_path.lower()
    parts = [p for p in lower.split("/") if p]
    for folder in parts:
        for key, stage in STAGE_KEYWORDS:
            if key in folder:
                return stage
    return None


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan_project_root(root: Path, *, exts: Iterable[str] = (".md", ".txt")) -> list[ScanFile]:
    root = root.resolve()
    results: list[ScanFile] = []
    allow = {e.lower() for e in exts}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).resolve().relative_to(root)
        rel_dir_posix = rel_dir.as_posix()
        if rel_dir_posix.startswith(".tmp") or rel_dir_posix.startswith("tmp"):
            dirnames[:] = []
            continue
        if rel_dir_posix.startswith("sample-docs"):
            dirnames[:] = []
            continue

        for fn in filenames:
            p = Path(dirpath) / fn
            ext = p.suffix.lower()
            if ext not in allow:
                continue
            rel_path = _normalize_rel_path(p.resolve().relative_to(root))
            st = p.stat()
            sha = compute_sha256(p)
            results.append(
                ScanFile(
                    rel_path=rel_path,
                    abs_path=p.resolve(),
                    ext=ext,
                    mtime=float(st.st_mtime),
                    sha256=sha,
                    stage=detect_stage(rel_path),
                )
            )
    results.sort(key=lambda x: x.rel_path)
    return results


def parse_md_or_txt(file_path: Path) -> list[dict]:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    paragraphs: list[dict] = []

    buf: list[str] = []
    start_line: int | None = None

    def flush(end_line: int) -> None:
        nonlocal buf, start_line
        if start_line is None:
            return
        para_text = "\n".join(buf).strip()
        if para_text:
            paragraphs.append(
                {
                    "text": para_text,
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
        buf = []
        start_line = None

    for i, line in enumerate(lines, start=1):
        if line.strip() == "":
            flush(i - 1)
            continue
        if start_line is None:
            start_line = i
        buf.append(line)

    flush(len(lines))
    return paragraphs


def chunk_paragraphs(paragraphs: list[dict], *, max_chars: int = 2000) -> list[dict]:
    chunks: list[dict] = []
    cur: list[dict] = []
    cur_chars = 0

    def emit() -> None:
        nonlocal cur, cur_chars
        if not cur:
            return
        text = "\n\n".join(p["text"] for p in cur).strip()
        locator = {
            "paragraph_count": len(cur),
            "start_line": int(cur[0]["start_line"]),
            "end_line": int(cur[-1]["end_line"]),
        }
        chunks.append(
            {
                "chunk_index": len(chunks),
                "text": text,
                "token_count": max(1, len(text) // 4),
                "locator": locator,
            }
        )
        cur = []
        cur_chars = 0

    for p in paragraphs:
        t = str(p["text"])
        if cur and cur_chars + len(t) > max_chars:
            emit()
        cur.append(p)
        cur_chars += len(t)

    emit()
    return chunks


def _sync_scanned_into_project(conn, *, project: dbm.ProjectRow, scanned: list[ScanFile]) -> int:
    updated = 0
    for sf in scanned:
        doc_id = dbm.upsert_document(
            conn,
            project_id=project.id,
            stage=sf.stage,
            rel_path=sf.rel_path,
            ext=sf.ext,
            sha256=sf.sha256,
            mtime=sf.mtime,
            status="indexed",
            parse_error=None,
        )

        paragraphs = parse_md_or_txt(sf.abs_path)
        chunks = chunk_paragraphs(paragraphs)
        dbm.insert_chunks(conn, doc_id, chunks)
        conn.execute(
            "UPDATE documents SET status=? WHERE id=?",
            ("chunked", doc_id),
        )
        updated += 1

    dbm.now_touch_project(conn, project.id)
    dbm.commit(conn)
    return updated


def sync_project(conn, *, project: dbm.ProjectRow) -> int:
    root = Path(project.root_path)
    scanned = scan_project_root(root)
    return _sync_scanned_into_project(conn, project=project, scanned=scanned)


def sync_project_md_root(conn, *, project: dbm.ProjectRow, md_root: Path) -> int:
    """
    Replace indexed documents/chunks for project with scan of md_root (e.g. docs2md output).
    """
    dbm.delete_project_documents(conn, project.id)
    root = md_root.resolve()
    if not root.is_dir():
        dbm.now_touch_project(conn, project.id)
        dbm.commit(conn)
        return 0
    scanned = scan_project_root(root)
    return _sync_scanned_into_project(conn, project=project, scanned=scanned)

