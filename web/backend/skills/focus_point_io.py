"""
Focus point file I/O — new per-file format with YAML frontmatter.

Format (focus-points/<id>.md):
---
schema: aika-focus/1
id: req
name: 需求完整性
version: 1
created_at: 2024-01-01T00:00:00
updated_at: 2024-01-01T00:00:00
history:
  - version: 1
    updated_at: 2024-01-01T00:00:00
    note: initial
---
<prompt body>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


FOCUS_POINTS_DIR = "focus-points"
FOCUS_HISTORY_DIR = ".aika/focus-history"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


@dataclass
class FocusPoint:
    id: str
    name: str
    prompt: str
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_md(self) -> str:
        now = self.updated_at or datetime.utcnow().isoformat()
        fm_lines = [
            "---",
            "schema: aika-focus/1",
            f"id: {self.id}",
            f"name: {self.name}",
            f"version: {self.version}",
            f"created_at: {self.created_at or now}",
            f"updated_at: {now}",
        ]
        if self.history:
            fm_lines.append("history:")
            for h in self.history:
                fm_lines.append(f"  - version: {h.get('version', 1)}")
                fm_lines.append(f"    updated_at: {h.get('updated_at', now)}")
                note = h.get("note", "")
                if note:
                    fm_lines.append(f"    note: {note}")
        fm_lines.append("---")
        return "\n".join(fm_lines) + "\n" + self.prompt.strip() + "\n"


def _parse_frontmatter_simple(text: str) -> dict[str, Any] | None:
    """Minimal YAML-like frontmatter parser (no external dep required)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm_text = m.group(1)
    if _HAS_YAML:
        try:
            return yaml.safe_load(fm_text) or {}
        except Exception:
            pass
    result: dict[str, Any] = {}
    for line in fm_text.splitlines():
        if ":" not in line or line.strip().startswith("-"):
            continue
        key, _, val = line.partition(":")
        result[key.strip()] = val.strip()
    return result


def load_focus_point(path: Path) -> FocusPoint | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = _parse_frontmatter_simple(text)
    if not isinstance(fm, dict):
        return None
    fid = str(fm.get("id") or path.stem).strip()
    name = str(fm.get("name") or fid).strip()
    version = int(fm.get("version") or 1)
    created_at = str(fm.get("created_at") or "")
    updated_at = str(fm.get("updated_at") or "")
    history = fm.get("history") or []
    if not isinstance(history, list):
        history = []
    prompt = text[m.end():].strip()
    return FocusPoint(
        id=fid,
        name=name,
        prompt=prompt,
        version=version,
        created_at=created_at,
        updated_at=updated_at,
        history=history,
    )


def save_focus_point(fp: FocusPoint, package_dir: Path) -> Path:
    dest_dir = package_dir / FOCUS_POINTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"focus-{fp.id}.md"
    dest.write_text(fp.to_md(), encoding="utf-8")
    return dest


def list_focus_points(package_dir: Path) -> list[FocusPoint]:
    d = package_dir / FOCUS_POINTS_DIR
    if not d.is_dir():
        return []
    out: list[FocusPoint] = []
    for f in sorted(d.glob("focus-*.md")):
        fp = load_focus_point(f)
        if fp:
            out.append(fp)
    return out


def migrate_from_review_domain(
    review_domain_text: str,
    package_dir: Path,
    *,
    overwrite: bool = False,
) -> list[str]:
    """
    Split review_domain.md focus blocks into individual focus-*.md files.
    Returns list of created file ids.
    """
    from backend.skills.review_domain_io import _DOMAIN_FOCUS_HEADING_LINE_RE

    dest_dir = package_dir / FOCUS_POINTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    lines = review_domain_text.splitlines()
    current_id: str | None = None
    current_name: str | None = None
    current_lines: list[str] = []
    created: list[str] = []
    now = datetime.utcnow().isoformat()

    def _flush() -> None:
        if current_id is None:
            return
        dest = dest_dir / f"focus-{current_id}.md"
        if dest.is_file() and not overwrite:
            return
        prompt = "\n".join(current_lines).strip()
        fp = FocusPoint(
            id=current_id,
            name=current_name or current_id,
            prompt=prompt,
            version=1,
            created_at=now,
            updated_at=now,
            history=[{"version": 1, "updated_at": now, "note": "migrated from review_domain.md"}],
        )
        dest.write_text(fp.to_md(), encoding="utf-8")
        created.append(current_id)

    in_focus_block = False
    for line in lines:
        m = _DOMAIN_FOCUS_HEADING_LINE_RE.match(line.strip())
        if m:
            _flush()
            current_id = m.group(1).strip()
            current_name = m.group(2).strip()
            current_lines = []
            in_focus_block = True
            continue
        if in_focus_block:
            if line.strip() == "---" and not current_lines:
                continue
            current_lines.append(line)

    _flush()
    return created


def evolve_focus_point(
    fp: FocusPoint,
    *,
    new_prompt: str,
    note: str = "",
    package_dir: Path,
    repo_root: Path | None = None,
) -> FocusPoint:
    """
    Bump version, archive old content to focus-history, write new file.
    """
    now = datetime.utcnow().isoformat()
    old_entry: dict[str, Any] = {
        "version": fp.version,
        "updated_at": fp.updated_at or now,
    }
    if note:
        old_entry["note"] = note

    if repo_root:
        history_dir = repo_root / FOCUS_HISTORY_DIR
        history_dir.mkdir(parents=True, exist_ok=True)
        archive_path = history_dir / f"focus-{fp.id}-v{fp.version}.md"
        archive_path.write_text(fp.to_md(), encoding="utf-8")

    new_fp = FocusPoint(
        id=fp.id,
        name=fp.name,
        prompt=new_prompt.strip(),
        version=fp.version + 1,
        created_at=fp.created_at or now,
        updated_at=now,
        history=[*fp.history, old_entry],
    )
    save_focus_point(new_fp, package_dir)
    return new_fp
