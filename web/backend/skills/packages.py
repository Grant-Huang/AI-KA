"""
审查技能包：支持 v1（review_domain.md）和 v2（focus-points/*.md + manifest.json）格式。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DOMAIN_FILENAME = "review_domain.md"
MANIFEST_FILENAME = "manifest.json"
DEFAULT_PACKAGE_ID = "package-general"
FOCUS_POINTS_SUBDIR = "focus-points"


def skill_packages_root(repo_root: Path) -> Path:
    raw = (os.environ.get("AIKA_REVIEW_SKILL_PACKAGES_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (repo_root / "review_skill_packages").resolve()


def package_dir(repo_root: Path, package_id: str) -> Path:
    return skill_packages_root(repo_root) / str(package_id).strip()


def domain_path(repo_root: Path, package_id: str) -> Path:
    return package_dir(repo_root, package_id) / DOMAIN_FILENAME


def manifest_path(repo_root: Path, package_id: str) -> Path:
    return package_dir(repo_root, package_id) / MANIFEST_FILENAME


def focus_points_dir(repo_root: Path, package_id: str) -> Path:
    return package_dir(repo_root, package_id) / FOCUS_POINTS_SUBDIR


def is_v2_package(repo_root: Path, package_id: str) -> bool:
    """A package is v2 if it has a focus-points/ directory with at least one focus-*.md."""
    d = focus_points_dir(repo_root, package_id)
    if not d.is_dir():
        return False
    return any(d.glob("focus-*.md"))


def read_manifest(repo_root: Path, package_id: str) -> dict[str, Any] | None:
    p = manifest_path(repo_root, package_id)
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def list_skill_packages(repo_root: Path) -> list[dict[str, Any]]:
    root = skill_packages_root(repo_root)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        pid = child.name
        has_domain = (child / DOMAIN_FILENAME).is_file()
        has_focus_points = is_v2_package(repo_root, pid)
        if not has_domain and not has_focus_points:
            continue
        m = read_manifest(repo_root, pid) or {}
        schema_ver = str(m.get("schema_version") or "1")
        out.append(
            {
                "id": pid,
                "name": str(m.get("name") or pid),
                "version": str(m.get("version") or ""),
                "description": str(m.get("description") or ""),
                "schema_version": schema_ver,
                "path": str(domain_path(repo_root, pid)),
            }
        )
    return out


def _minimal_domain_placeholder() -> str:
    return (
        "# 分析规则配置\n\n"
        "该文件由 AI-KA 自动维护。\n\n"
        "## 关注点块\n\n"
        "### focus:req | 需求\n"
        "请根据片段审查需求完整性。\n"
        "---\n\n"
        "## 组合使用建议\n\n"
        "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 默认 | `focus:req` |  |  | |\n"
    )


def ensure_default_skill_package(repo_root: Path) -> None:
    """
    若默认包目录下无 review_domain.md，则从 default_skills.md 或占位内容创建，并写入 manifest.json。
    """
    root = skill_packages_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    pkg_dir = root / DEFAULT_PACKAGE_ID
    domain_f = pkg_dir / DOMAIN_FILENAME
    if domain_f.is_file():
        return
    pkg_dir.mkdir(parents=True, exist_ok=True)
    default_src = repo_root / "default_skills.md"
    text = ""
    if default_src.is_file():
        text = default_src.read_text(encoding="utf-8", errors="replace")
    else:
        text = _minimal_domain_placeholder()
    domain_f.write_text(text, encoding="utf-8")
    man = pkg_dir / MANIFEST_FILENAME
    if not man.is_file():
        man.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "id": DEFAULT_PACKAGE_ID,
                    "name": "通用审查（默认）",
                    "version": "1.0.0",
                    "description": "由 default_skills.md 或占位初始化",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def package_version_for_hash(repo_root: Path, package_id: str) -> str:
    m = read_manifest(repo_root, package_id) or {}
    v = str(m.get("version") or "").strip()
    return v or "0"
