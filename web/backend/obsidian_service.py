from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Vault discovery
# ---------------------------------------------------------------------------

_COMMON_VAULT_SEARCH_ROOTS = [
    "~/Documents",
    "~/Desktop",
    "~/Obsidian",
    "~/vaults",
    "~/notes",
    "~/Vault",
    "/workspace",
    "/data",
]

_MAX_DISCOVER_DEPTH = 4


def find_vaults(search_roots: list[str] | None = None) -> list[dict[str, str]]:
    """Scan filesystem roots for Obsidian vaults (directories containing .obsidian/)."""
    roots = search_roots or _COMMON_VAULT_SEARCH_ROOTS
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    for root_str in roots:
        root = Path(root_str).expanduser()
        if not root.is_dir():
            continue
        _walk_for_vaults(root, depth=0, found=found, seen=seen)

    return found


def _walk_for_vaults(path: Path, depth: int, found: list[dict], seen: set[str]) -> None:
    if depth > _MAX_DISCOVER_DEPTH:
        return
    obsidian_dir = path / ".obsidian"
    if obsidian_dir.is_dir():
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            found.append({"path": resolved, "name": read_vault_name(path)})
        return  # don't recurse into a vault
    try:
        for child in path.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                _walk_for_vaults(child, depth + 1, found, seen)
    except PermissionError:
        pass


def read_vault_name(vault_path: Path) -> str:
    """Read vault display name from .obsidian/app.json, fall back to directory name."""
    app_json = vault_path / ".obsidian" / "app.json"
    if app_json.exists():
        try:
            data = json.loads(app_json.read_text(encoding="utf-8", errors="replace"))
            name = data.get("vaultName") or data.get("name") or ""
            if name:
                return str(name)
        except Exception:
            pass
    return vault_path.name


def is_obsidian_vault(path: Path) -> bool:
    return (path / ".obsidian").is_dir()


# ---------------------------------------------------------------------------
# Frontmatter parsing & filtering
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract YAML-like frontmatter from a markdown string (lightweight, no full YAML dep)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, Any] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        val_str = raw_val.strip()
        if not key:
            continue
        # try list syntax: [a, b] or - item lines
        if val_str.startswith("[") and val_str.endswith("]"):
            inner = val_str[1:-1]
            result[key] = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
        else:
            result[key] = val_str
    return result


def strip_frontmatter(text: str) -> str:
    """Remove the YAML frontmatter block from markdown text."""
    return _FRONTMATTER_RE.sub("", text, count=1)


@dataclass
class FrontmatterFilter:
    """Rules for including/excluding files based on frontmatter fields."""
    include_tags: list[str]       # file must have ALL of these tags (empty = no constraint)
    exclude_tags: list[str]       # file must NOT have ANY of these tags
    require_field: dict[str, str] # field -> value: file must match all pairs (empty = no constraint)
    exclude_types: list[str]      # shortcut: exclude files where `type` matches any value

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FrontmatterFilter":
        return cls(
            include_tags=[str(t) for t in d.get("include_tags", [])],
            exclude_tags=[str(t) for t in d.get("exclude_tags", [])],
            require_field={str(k): str(v) for k, v in d.get("require_field", {}).items()},
            exclude_types=[str(t) for t in d.get("exclude_types", ["template"])],
        )

    def matches(self, fm: dict[str, Any]) -> bool:
        tags = _coerce_tags(fm.get("tags"))
        if self.include_tags:
            for t in self.include_tags:
                if t not in tags:
                    return False
        if self.exclude_tags:
            for t in self.exclude_tags:
                if t in tags:
                    return False
        for field, expected in self.require_field.items():
            if str(fm.get(field, "")) != expected:
                return False
        if self.exclude_types:
            ftype = str(fm.get("type", ""))
            if ftype in self.exclude_types:
                return False
        return True


def _coerce_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


# ---------------------------------------------------------------------------
# Wikilinks resolution
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")


def build_wikilink_index(vault_path: Path) -> dict[str, Path]:
    """Build a case-insensitive map from note name → absolute path."""
    index: dict[str, Path] = {}
    for p in vault_path.rglob("*.md"):
        if ".obsidian" in p.parts or "_aika" in p.parts:
            continue
        stem_lower = p.stem.lower()
        if stem_lower not in index:
            index[stem_lower] = p
    return index


def resolve_wikilinks_in_text(
    text: str,
    vault_path: Path,
    wikilink_index: dict[str, Path] | None = None,
    *,
    max_depth: int = 1,
    _depth: int = 0,
) -> str:
    """Replace [[Note Name]] with the content of the referenced note (inline expansion).

    Only expands one level deep by default (avoids circular references).
    """
    if _depth >= max_depth:
        return _WIKILINK_RE.sub(lambda m: f"[{m.group(1)}]", text)

    if wikilink_index is None:
        wikilink_index = build_wikilink_index(vault_path)

    def _replace(m: re.Match) -> str:
        target = m.group(1).strip()
        target_lower = target.lower()
        found = wikilink_index.get(target_lower)
        if found is None:
            return f"[{target}]"
        try:
            content = found.read_text(encoding="utf-8", errors="replace")
            content = strip_frontmatter(content)
            content = resolve_wikilinks_in_text(
                content, vault_path, wikilink_index,
                max_depth=max_depth, _depth=_depth + 1,
            )
            return f"\n\n<!-- [[{target}]] -->\n{content.strip()}\n"
        except Exception:
            return f"[{target}]"

    return _WIKILINK_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Write-back: create Obsidian review note
# ---------------------------------------------------------------------------

def write_review_note(
    vault_path: Path,
    output_folder: str,
    *,
    project_name: str,
    content_markdown: str,
    focus_point_ids: list[str] | None = None,
    conversation_id: int | None = None,
) -> Path:
    """Write a review result as a markdown note into the knowledge vault.

    Returns the absolute path of the written note.
    """
    out_dir = vault_path / output_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_proj = re.sub(r"[^\w一-鿿\-]", "_", project_name).strip("_") or "project"
    ts = datetime.now().strftime("%H%M%S")
    filename = f"{date_str}_{safe_proj}_{ts}.md"

    tags_list = ["aika-review"]
    if focus_point_ids:
        tags_list.extend(f"focus:{fid}" for fid in focus_point_ids)

    tags_yaml = "[" + ", ".join(tags_list) + "]"
    conv_meta = f"\nconversation_id: {conversation_id}" if conversation_id else ""

    frontmatter = (
        f"---\n"
        f"type: aika-review\n"
        f"project: {project_name}\n"
        f"date: {date_str}\n"
        f"tags: {tags_yaml}{conv_meta}\n"
        f"---\n\n"
    )

    note = frontmatter + content_markdown.strip() + "\n"
    note_path = out_dir / filename
    note_path.write_text(note, encoding="utf-8")
    return note_path
