from __future__ import annotations

from pathlib import Path

import pytest

# Ensure `backend` package resolves (installed editable) and repo root for imports
pytest.importorskip("fastapi")

from backend.epic_mapper import analysis_to_epic_doc_config
from backend.path_validate import PathValidationError, validate_project_root
from backend.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    build_user_prompt_from_entries,
    format_chunk_index_markdown,
)


def test_validate_project_root_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError):
        validate_project_root(str(tmp_path / ".." / "etc"))


def test_validate_project_root_accepts_existing_dir(tmp_path: Path) -> None:
    d = tmp_path / "proj"
    d.mkdir()
    p = validate_project_root(str(d))
    assert p.is_dir()


def test_prompt_builder_includes_dimensions() -> None:
    s = build_system_prompt({"goal": "x", "dimensions": ["a", "b"]})
    assert "a" in s and "b" in s
    u = build_user_prompt(chunk_texts=["hello"])
    assert "hello" in u


def test_prompt_from_entries_includes_file_and_section() -> None:
    entries = [
        {
            "doc_path": "x.md",
            "chunk_index": 0,
            "text": "body",
            "locator": {"start_line": 1, "end_line": 3, "heading_path": ["A", "B"]},
        }
    ]
    u, used = build_user_prompt_from_entries(entries)
    assert "文件" in u and "片段" in u and "章节" in u and "body" in u
    assert len(used) == 1
    idx = format_chunk_index_markdown(used)
    assert "片段与来源索引" in idx and "x.md" in idx


def test_prompt_builder_focus_definitions() -> None:
    s = build_system_prompt(
        None,
        focus_definitions=[{"id": "req", "name": "需求", "prompt": "检查需求完整性"}],
    )
    assert "关注点审查清单" in s
    assert "需求" in s
    assert "检查需求完整性" in s


def test_analysis_to_epic_has_blocks() -> None:
    analysis = {
        "title": "T",
        "blocks": [
            {"type": "paragraph", "text": "p"},
            {"type": "tags", "items": ["x"]},
        ],
    }
    cfg = analysis_to_epic_doc_config(theme="minimal", title="Doc", analysis=analysis)
    assert cfg["theme"] == "minimal"
    assert any(b.get("type") == "paragraph" for b in cfg["blocks"])
