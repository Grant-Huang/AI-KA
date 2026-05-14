from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from . import db as dbm

if TYPE_CHECKING:
    from backend.obsidian_service import FrontmatterFilter

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


_SKIP_DIR_PREFIXES = (".tmp", "tmp", "sample-docs", ".obsidian", "_aika", ".git")


def scan_project_root(root: Path, *, exts: Iterable[str] = (".md", ".html", ".txt")) -> list[ScanFile]:
    root = root.resolve()
    results: list[ScanFile] = []
    allow = {e.lower() for e in exts}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).resolve().relative_to(root)
        rel_dir_posix = rel_dir.as_posix()
        skip = False
        for prefix in _SKIP_DIR_PREFIXES:
            if rel_dir_posix == prefix or rel_dir_posix.startswith(prefix + "/"):
                skip = True
                break
        if skip:
            dirnames[:] = []
            continue
        # Also prune subdirs that match skip prefixes so os.walk doesn't descend
        dirnames[:] = [d for d in dirnames if not any(d == p or d.startswith(p) for p in _SKIP_DIR_PREFIXES)]

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


def _index_one_scanfile(
    conn,
    *,
    project: dbm.ProjectRow,
    sf: ScanFile,
    strat: str,
    resolve_wikilinks: bool = False,
    vault_path: Path | None = None,
    wikilink_index: dict | None = None,
) -> None:
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

    if resolve_wikilinks and vault_path is not None and sf.ext == ".md":
        chunks = _build_chunks_with_wikilinks(sf.abs_path, strat, vault_path=vault_path, wikilink_index=wikilink_index)
    else:
        chunks = build_chunks_for_file(sf.abs_path, sf.ext, strat)
    for i, ch in enumerate(chunks):
        ch["chunk_index"] = i
    dbm.insert_chunks(conn, doc_id, chunks)
    conn.execute(
        "UPDATE documents SET status=? WHERE id=?",
        ("chunked", doc_id),
    )


def _build_chunks_with_wikilinks(
    abs_path: Path,
    strat: str,
    *,
    vault_path: Path,
    wikilink_index: dict | None,
    max_chars: int = 2000,
) -> list[dict]:
    """Read the file, expand wikilinks, write to a temp buffer, then chunk."""
    try:
        from backend.obsidian_service import (
            build_wikilink_index,
            resolve_wikilinks_in_text,
            strip_frontmatter,
        )
    except ImportError:
        return build_chunks_for_file(abs_path, ".md", strat)

    text = abs_path.read_text(encoding="utf-8", errors="replace")
    text = strip_frontmatter(text)
    idx = wikilink_index if wikilink_index is not None else build_wikilink_index(vault_path)
    expanded = resolve_wikilinks_in_text(text, vault_path, idx)

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as tmp:
        tmp.write(expanded)
        tmp_path = Path(tmp.name)
    try:
        return build_chunks_for_file(tmp_path, ".md", strat, max_chars=max_chars)
    finally:
        tmp_path.unlink(missing_ok=True)


def _sync_scanned_into_project(
    conn,
    *,
    project: dbm.ProjectRow,
    scanned: list[ScanFile],
    chunk_strategy: str,
    resolve_wikilinks: bool = False,
    vault_path: Path | None = None,
    wikilink_index: dict | None = None,
) -> int:
    updated = 0
    strat = chunk_strategy if chunk_strategy in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED) else CHUNK_STRATEGY_BLANK
    for sf in scanned:
        _index_one_scanfile(
            conn, project=project, sf=sf, strat=strat,
            resolve_wikilinks=resolve_wikilinks,
            vault_path=vault_path,
            wikilink_index=wikilink_index,
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
    full_resync: bool = False,
    resolve_wikilinks: bool = False,
    vault_path: Path | None = None,
    frontmatter_filter: "FrontmatterFilter | None" = None,
) -> int:
    """
    Index markdown under md_root (e.g. docs2md output or an Obsidian vault).

    - full_resync=True: 清空本项目已有文档索引后，对目录内全部文件重新分块入库。
    - full_resync=False: 增量模式——仅对新增或内容变化（sha256 变）的文件建索引；磁盘上已删除的文件从索引移除；
      未变化的文件跳过以节省时间。
    chunk_strategy: blank | structured; None => env AIKA_CHUNK_STRATEGY (CLI) or caller must pass (Web).
    resolve_wikilinks: expand [[WikiLinks]] inline before chunking (requires vault_path).
    vault_path: root of the Obsidian vault for wikilink resolution (may differ from md_root).
    frontmatter_filter: if given, files whose frontmatter doesn't match are skipped.
    """
    root = md_root.resolve()
    if not root.is_dir():
        dbm.now_touch_project(conn, project.id)
        dbm.commit(conn)
        return 0
    scanned = scan_project_root(root)
    strat = chunk_strategy if chunk_strategy is not None else resolve_chunk_strategy_from_env()
    strat = strat if strat in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED) else CHUNK_STRATEGY_BLANK

    if frontmatter_filter is not None:
        scanned = _apply_frontmatter_filter(scanned, frontmatter_filter)

    wikilink_index: dict | None = None
    if resolve_wikilinks and vault_path is not None:
        try:
            from backend.obsidian_service import build_wikilink_index
            wikilink_index = build_wikilink_index(vault_path)
        except ImportError:
            pass

    _shared = dict(
        resolve_wikilinks=resolve_wikilinks,
        vault_path=vault_path,
        wikilink_index=wikilink_index,
    )

    if full_resync:
        dbm.delete_project_documents(conn, project.id)
        return _sync_scanned_into_project(
            conn, project=project, scanned=scanned, chunk_strategy=strat, **_shared
        )

    paths_on_disk = {sf.rel_path for sf in scanned}
    existing = dbm.list_documents(conn, project.id)
    for doc in existing:
        if doc.path not in paths_on_disk:
            conn.execute("DELETE FROM documents WHERE id=?", (doc.id,))

    ex_by_path = {d.path: d for d in dbm.list_documents(conn, project.id)}
    updated = 0
    for sf in scanned:
        prev = ex_by_path.get(sf.rel_path)
        if prev is not None and (prev.sha256 or "") == sf.sha256:
            continue
        _index_one_scanfile(
            conn, project=project, sf=sf, strat=strat,
            resolve_wikilinks=resolve_wikilinks,
            vault_path=vault_path,
            wikilink_index=wikilink_index,
        )
        updated += 1

    dbm.now_touch_project(conn, project.id)
    dbm.commit(conn)
    return updated


def _apply_frontmatter_filter(
    scanned: list[ScanFile],
    fm_filter: "FrontmatterFilter",
) -> list[ScanFile]:
    """Return only ScanFiles whose frontmatter matches the filter."""
    kept: list[ScanFile] = []
    for sf in scanned:
        if sf.ext != ".md":
            kept.append(sf)
            continue
        try:
            text = sf.abs_path.read_text(encoding="utf-8", errors="replace")
            from backend.obsidian_service import parse_frontmatter
            fm = parse_frontmatter(text)
        except Exception:
            kept.append(sf)
            continue
        if fm_filter.matches(fm):
            kept.append(sf)
    return kept
