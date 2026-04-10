from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import db as dbm

CHUNK_STRATEGY_BLANK = "blank"
CHUNK_STRATEGY_STRUCTURED = "structured"

# 遇到 <= 此级别的 ATX 标题时，将当前累积段落先分块再开始新节（仅 structured / .md）
MD_HEADING_SPLIT_LEVEL = 2

_STRICT_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


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


def resolve_chunk_strategy_from_env() -> str:
    v = (os.environ.get("AIKA_CHUNK_STRATEGY") or "").strip().lower()
    if v in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED):
        return v
    return CHUNK_STRATEGY_BLANK


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


def _parse_atx_heading(line: str) -> tuple[int, str] | None:
    m = _STRICT_ATX.match(line.rstrip())
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def chunk_md_structured(file_path: Path, *, max_chars: int = 2000) -> list[dict]:
    """
    标题/围栏感知：在 #/## 边界处分节并分块；代码围栏整体为一段；节内仍为空行分段 + chunk_paragraphs。
    """
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    n = len(lines)

    chunks_coll: list[dict] = []
    pending: list[dict] = []
    stack: list[tuple[int, str]] = []

    in_fence = False
    fence_body: list[str] = []
    fence_start_line: int | None = None

    para_lines: list[str] = []
    para_start: int | None = None

    def flush_para(end_line: int) -> None:
        nonlocal para_lines, para_start
        if para_start is None:
            return
        para_text = "\n".join(para_lines).strip()
        if para_text:
            pending.append(
                {
                    "text": para_text,
                    "start_line": para_start,
                    "end_line": end_line,
                }
            )
        para_lines = []
        para_start = None

    def section_heading_meta() -> tuple[str | None, int | None]:
        sec_title: str | None = None
        sec_level: int | None = None
        for lev, tit in stack:
            if lev <= MD_HEADING_SPLIT_LEVEL:
                sec_title = tit
                sec_level = lev
        return sec_title, sec_level

    def flush_section_chunks() -> None:
        nonlocal pending
        if not pending:
            return
        hp = [t for _, t in stack]
        sec_title, sec_level = section_heading_meta()
        for ch in chunk_paragraphs(pending, max_chars=max_chars):
            loc = dict(ch["locator"])
            loc["kind"] = "md_structured"
            loc["heading_path"] = list(hp)
            loc["section_title"] = sec_title
            loc["section_level"] = sec_level
            chunks_coll.append(
                {
                    "chunk_index": len(chunks_coll),
                    "text": ch["text"],
                    "token_count": ch["token_count"],
                    "locator": loc,
                }
            )
        pending.clear()

    i = 0
    while i < n:
        line = lines[i]
        line_no = i + 1

        if in_fence:
            if line.strip().startswith("```"):
                inner = "\n".join(fence_body)
                if inner.strip() and fence_start_line is not None:
                    pending.append(
                        {
                            "text": "```\n" + inner + "\n```",
                            "start_line": fence_start_line,
                            "end_line": line_no - 1,
                        }
                    )
                fence_body = []
                fence_start_line = None
                in_fence = False
            else:
                fence_body.append(line)
            i += 1
            continue

        if line.strip().startswith("```"):
            flush_para(line_no - 1)
            in_fence = True
            fence_start_line = line_no + 1
            fence_body = []
            i += 1
            continue

        hd = _parse_atx_heading(line)
        if hd is not None:
            level, _title = hd
            flush_para(line_no - 1)
            if level <= MD_HEADING_SPLIT_LEVEL:
                flush_section_chunks()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, _title))
            i += 1
            continue

        if line.strip() == "":
            flush_para(line_no - 1)
        else:
            if para_start is None:
                para_start = line_no
            para_lines.append(line)
        i += 1

    flush_para(n)
    flush_section_chunks()

    for j, ch in enumerate(chunks_coll):
        ch["chunk_index"] = j
    return chunks_coll


def build_chunks_for_file(abs_path: Path, ext: str, chunk_strategy: str, *, max_chars: int = 2000) -> list[dict]:
    ext_l = ext.lower()
    strat = chunk_strategy if chunk_strategy in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED) else CHUNK_STRATEGY_BLANK

    if ext_l == ".md" and strat == CHUNK_STRATEGY_STRUCTURED:
        return chunk_md_structured(abs_path, max_chars=max_chars)

    paragraphs = parse_md_or_txt(abs_path)
    chunks = chunk_paragraphs(paragraphs, max_chars=max_chars)
    kind = "txt_plain" if ext_l == ".txt" else "blank"
    for ch in chunks:
        loc = dict(ch["locator"])
        loc["kind"] = kind
        if kind == "blank":
            loc["heading_path"] = []
            loc["section_title"] = None
            loc["section_level"] = None
        ch["locator"] = loc
    return chunks


def _sync_scanned_into_project(
    conn,
    *,
    project: dbm.ProjectRow,
    scanned: list[ScanFile],
    chunk_strategy: str,
) -> int:
    updated = 0
    strat = chunk_strategy if chunk_strategy in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED) else CHUNK_STRATEGY_BLANK
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

        chunks = build_chunks_for_file(sf.abs_path, sf.ext, strat)
        for i, ch in enumerate(chunks):
            ch["chunk_index"] = i
        dbm.insert_chunks(conn, doc_id, chunks)
        conn.execute(
            "UPDATE documents SET status=? WHERE id=?",
            ("chunked", doc_id),
        )
        updated += 1

    dbm.now_touch_project(conn, project.id)
    dbm.commit(conn)
    return updated


def sync_project(
    conn,
    *,
    project: dbm.ProjectRow,
    chunk_strategy: str | None = None,
) -> int:
    root = Path(project.root_path)
    scanned = scan_project_root(root)
    strat = chunk_strategy if chunk_strategy is not None else resolve_chunk_strategy_from_env()
    return _sync_scanned_into_project(conn, project=project, scanned=scanned, chunk_strategy=strat)


def sync_project_md_root(
    conn,
    *,
    project: dbm.ProjectRow,
    md_root: Path,
    chunk_strategy: str | None = None,
) -> int:
    """
    Replace indexed documents/chunks for project with scan of md_root (e.g. docs2md output).
    chunk_strategy: blank | structured; None => env AIKA_CHUNK_STRATEGY (CLI) or caller must pass (Web).
    """
    dbm.delete_project_documents(conn, project.id)
    root = md_root.resolve()
    if not root.is_dir():
        dbm.now_touch_project(conn, project.id)
        dbm.commit(conn)
        return 0
    scanned = scan_project_root(root)
    strat = chunk_strategy if chunk_strategy is not None else resolve_chunk_strategy_from_env()
    return _sync_scanned_into_project(conn, project=project, scanned=scanned, chunk_strategy=strat)
