from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aika.indexer import STAGE_KEYWORDS, detect_stage

# 第一层目录名中常见的「阶段」语义片段（与业务文件夹命名习惯对齐）
STAGE_DIR_NAME_FRAGMENTS: tuple[str, ...] = (
    "调研",
    "蓝图",
    "设计",
    "开发",
    "测试",
    "上线",
    "复盘",
    "业务",
    "方案",
    "二开",
    "验收",
    "用例",
    "交付",
)


def _dir_name_looks_like_stage(name: str) -> bool:
    n = name.lower()
    for frag in STAGE_DIR_NAME_FRAGMENTS:
        if frag in n:
            return True
    for key, _ in STAGE_KEYWORDS:
        if key in n:
            return True
    return False


def _subtree_has_stage_signal(root: Path, *, max_depth: int = 8) -> bool:
    """在子树中是否存在阶段路径或阶段目录名（浅层遍历）。"""
    root = root.resolve()
    if not root.is_dir():
        return False
    for dirpath, dirnames, filenames in os.walk(root):
        p = Path(dirpath).resolve()
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > max_depth:
            dirnames[:] = []
            continue
        for part in rel.parts:
            if _dir_name_looks_like_stage(part):
                return True
        rel_prefix = rel.as_posix() + "/" if rel.as_posix() != "." else ""
        for fn in filenames:
            rel_file = rel_prefix + fn
            if detect_stage(rel_file):
                return True
    return False


def detect_project_layout(root: Path) -> dict[str, Any]:
    """
    判断根目录是「单项目根」还是「多子项目容器」。

    - single：第一层即出现典型阶段目录名 → 分析根为当前 root。
    - multi：第一层无阶段名，但多个子目录子树内出现阶段信号 → 候选为各子目录。
    """
    warnings: list[str] = []
    root = root.resolve()
    if not root.is_dir():
        return {
            "mode": "single",
            "root_label": root.name,
            "candidates": [],
            "warnings": ["路径不是目录"],
        }

    children = sorted(
        [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda x: x.name.lower(),
    )

    if not children:
        warnings.append("根目录下没有子目录，将按单项目根目录处理")
        return {
            "mode": "single",
            "root_label": root.name,
            "candidates": [
                {"id": ".", "name": root.name, "path": root.as_posix()},
            ],
            "warnings": warnings,
        }

    stage_at_first_level = any(_dir_name_looks_like_stage(c.name) for c in children)

    if stage_at_first_level:
        return {
            "mode": "single",
            "root_label": root.name,
            "candidates": [
                {"id": ".", "name": root.name, "path": root.as_posix()},
            ],
            "warnings": warnings,
        }

    scored = [c for c in children if _subtree_has_stage_signal(c)]

    if len(scored) >= 2:
        return {
            "mode": "multi",
            "root_label": root.name,
            "candidates": [
                {"id": p.name, "name": p.name, "path": p.as_posix()} for p in scored
            ],
            "warnings": warnings,
        }

    if len(scored) == 1:
        return {
            "mode": "multi",
            "root_label": root.name,
            "candidates": [
                {"id": scored[0].name, "name": scored[0].name, "path": scored[0].as_posix()},
            ],
            "warnings": warnings,
        }

    warnings.append("未在子目录中识别到典型阶段结构，将按单项目根目录处理；可在创建项目时手动调整路径")
    return {
        "mode": "single",
        "root_label": root.name,
        "candidates": [
            {"id": ".", "name": root.name, "path": root.as_posix()},
        ],
        "warnings": warnings,
    }
