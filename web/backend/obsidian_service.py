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


# ---------------------------------------------------------------------------
# Vault project directory convention
# ---------------------------------------------------------------------------

PROJECTS_SUBDIR = "Projects"
AIKA_SUBDIR = "_aika"

# Regex patterns for auto-detecting project number and name from folder names
# Matches: PRJ-2024-001_名称, P2024001-名称, P001_名称, etc.
_PROJECT_ID_RE = re.compile(
    r"^([A-Za-z]{1,6}[-_]?[\d]{2,8}(?:[-_][\d]{2,6})?)"  # project number prefix
    r"[_\-\s]+"                                              # separator
    r"(.+)$"                                                 # project name
)
# Matches: 20240115_名称 (date prefix)
_DATE_PREFIX_RE = re.compile(r"^(\d{6,8})[_\-](.+)$")


def parse_project_name_from_folder(folder_name: str) -> dict[str, str]:
    """
    Extract project_number and project_name from a folder name.
    Returns dict with keys: folder_name, project_number (may be ""), project_name.
    """
    name = folder_name.strip()

    m = _PROJECT_ID_RE.match(name)
    if m:
        return {
            "folder_name": folder_name,
            "project_number": m.group(1),
            "project_name": m.group(2).strip(),
        }

    m = _DATE_PREFIX_RE.match(name)
    if m:
        return {
            "folder_name": folder_name,
            "project_number": "",
            "project_name": m.group(2).strip(),
        }

    return {
        "folder_name": folder_name,
        "project_number": "",
        "project_name": name,
    }


def list_vault_projects(vault_path: Path, *, registered_roots: set[str] | None = None) -> list[dict]:
    """
    Scan vault_path/Projects/ for first-level subdirectories.
    Each entry represents a potential AI-KA project.

    Returns list of dicts:
      folder_name, project_number, project_name,
      abs_path, vault_subfolder,
      already_registered (bool), has_aika_marker (bool)
    """
    projects_dir = vault_path / PROJECTS_SUBDIR
    if not projects_dir.is_dir():
        return []

    reg = registered_roots or set()
    results: list[dict] = []

    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue

        parsed = parse_project_name_from_folder(child.name)
        abs_path = str(child.resolve())
        vault_subfolder = f"{PROJECTS_SUBDIR}/{child.name}"

        results.append({
            **parsed,
            "abs_path": abs_path,
            "vault_subfolder": vault_subfolder,
            "already_registered": abs_path in reg,
            "has_aika_marker": (child / ".aika-project").exists(),
        })

    return results


def find_vault_for_path(path: Path, vaults: list) -> tuple | None:
    """
    Given a filesystem path, find the first vault whose path is a parent of it.
    vaults is a list of ObsidianVaultRow (or any object with .path attribute).
    Returns (vault, vault_subfolder_str) or None.
    """
    resolved = path.resolve()
    for vault in vaults:
        vault_root = Path(vault.path).resolve()
        try:
            rel = resolved.relative_to(vault_root)
            return (vault, rel.as_posix())
        except ValueError:
            continue
    return None


def ensure_vault_structure(vault_path: Path) -> None:
    """Create the standard _aika/ subdirectory structure inside a vault."""
    for subdir in ("reviews", "knowledge", "meta"):
        (vault_path / AIKA_SUBDIR / subdir).mkdir(parents=True, exist_ok=True)
