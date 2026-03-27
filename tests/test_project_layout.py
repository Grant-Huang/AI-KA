from __future__ import annotations

from pathlib import Path

from aika.project_layout import detect_project_layout


def test_single_mode_when_stage_dirs_at_first_level(tmp_path: Path) -> None:
    root = tmp_path / "客户A项目"
    root.mkdir()
    (root / "业务调研").mkdir()
    (root / "蓝图方案").mkdir()
    out = detect_project_layout(root)
    assert out["mode"] == "single"
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["path"] == str(root.resolve())


def test_multi_mode_when_projects_under_root(tmp_path: Path) -> None:
    root = tmp_path / "交付根"
    root.mkdir()
    p1 = root / "项目甲"
    p2 = root / "项目乙"
    p1.mkdir()
    p2.mkdir()
    (p1 / "01_调研").mkdir()
    (p2 / "测试用例").mkdir()
    out = detect_project_layout(root)
    assert out["mode"] == "multi"
    names = {c["name"] for c in out["candidates"]}
    assert names == {"项目甲", "项目乙"}
