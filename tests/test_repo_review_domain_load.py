from __future__ import annotations

"""
检查当前活动审查技能包 review_domain.md 能否被后端加载。

运行：
  PYTHONPATH=web:src python3 -m pytest tests/test_repo_review_domain_load.py -v
"""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_active_review_domain_loads_or_reports_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(REPO_ROOT))

    from backend.main import (
        _active_review_domain_path,
        _get_focus_presets,
        _read_focus_combo_tips_from_review_domain,
        _read_settings_from_review_domain,
    )

    path = _active_review_domain_path()
    parsed, err = _read_settings_from_review_domain()

    if err or not parsed:
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        preview = ""
        if exists and size is not None:
            raw = path.read_text(encoding="utf-8", errors="replace")
            head = raw[:400].replace("\r\n", "\n")
            preview = f"\n文件前 400 字符预览（便于对照格式）:\n---\n{head}\n---\n"

        pytest.fail(
            "\n=== review_domain.md 无法加载（诊断）===\n"
            f"完整路径: {path}\n"
            f"文件存在: {exists}\n"
            + (f"文件大小（字节）: {size}\n" if size is not None else "")
            + f"后端返回错误: {err!r}\n"
            + preview
        )

    fps = parsed.get("focus_points") if isinstance(parsed, dict) else None
    assert isinstance(fps, list) and len(fps) >= 1, "解析成功但 focus_points 为空"

    tips = _read_focus_combo_tips_from_review_domain()
    presets = _get_focus_presets()
    assert len(tips) >= 1, (
        "未从「组合使用建议」解析出任何表格行；请检查 review_domain.md 中 ## 组合使用建议 及表格。"
    )
    assert len(presets) >= 1, (
        "组合表已解析但 focus_presets 为空：多为表格中的 focus:id 与关注点块 id 不一致。"
    )
    for pr in presets:
        assert isinstance(pr.get("focus_points"), list) and len(pr["focus_points"]) >= 1


def test_review_domain_parse_error_message_includes_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    pkg = tmp_path / "review_skill_packages" / "package-general"
    pkg.mkdir(parents=True)
    (pkg / "review_domain.md").write_text(
        "# 仅有标题\n\n正文没有 ### focus: 行。\n",
        encoding="utf-8",
    )
    from backend.main import _read_settings_from_review_domain

    parsed, err = _read_settings_from_review_domain()
    assert parsed is None
    assert err is not None
    assert "解析失败" in err
    assert "关注点块" in err
