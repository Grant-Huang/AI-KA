from __future__ import annotations

from pathlib import Path

import pytest

# Ensure `backend` package resolves (installed editable) and repo root for imports
pytest.importorskip("fastapi")

from backend.epic_mapper import analysis_to_epic_doc_config
from backend.path_validate import PathValidationError, validate_project_root
from backend.prompt_builder import build_system_prompt, build_user_prompt


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
