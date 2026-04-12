from __future__ import annotations

"""
检查「当前活动规则文件」能否被后端加载，包括：

- 关注点块（`_read_settings_from_rules_md` / `_read_settings_from_rules_text`）
- 「组合使用建议」表格（`_read_focus_combo_tips_from_rules_md`）
- 由组合表推导的 `focus_presets`（`_get_focus_presets`，依赖关注点 id 与表格内 `focus:` 引用对齐）

运行：
  PYTHONPATH=web:src python3 -m pytest tests/test_repo_rules_md_load.py -v

若 rules.md（或 AIKA_RULES_FILENAME 指向的文件）无法解析，失败信息中会包含：
  活动文件名、绝对路径、是否存在、以及 _read_settings_from_rules_md 返回的具体原因。
"""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_active_rules_file_loads_or_reports_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """使用仓库根目录与默认 AIKA_RULES_FILENAME（rules.md）做一次加载检查。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(REPO_ROOT))
    monkeypatch.delenv("AIKA_RULES_FILENAME", raising=False)

    from backend.main import (
        _active_rules_filename,
        _get_focus_presets,
        _read_focus_combo_tips_from_rules_md,
        _read_settings_from_rules_md,
        _rules_md_path,
    )

    path = _rules_md_path()
    fn = _active_rules_filename()
    parsed, err = _read_settings_from_rules_md()

    if err or not parsed:
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        preview = ""
        if exists and size is not None:
            raw = path.read_text(encoding="utf-8", errors="replace")
            head = raw[:400].replace("\r\n", "\n")
            preview = f"\n文件前 400 字符预览（便于对照格式）:\n---\n{head}\n---\n"

        pytest.fail(
            "\n=== 规则文件无法加载（诊断）===\n"
            f"活动文件名: {fn}\n"
            f"完整路径: {path}\n"
            f"文件存在: {exists}\n"
            + (f"文件大小（字节）: {size}\n" if size is not None else "")
            + f"后端返回错误: {err!r}\n"
            + preview
            + "解析要求: 至少包含一行「### focus:<id> | <名称>」形式的关注点块；"
            "整文件按行扫描，即使外层有 Markdown 代码围栏，只要行内格式正确即可匹配。\n"
        )

    fps = parsed.get("focus_points") if isinstance(parsed, dict) else None
    assert isinstance(fps, list) and len(fps) >= 1, "解析成功但 focus_points 为空"

    tips = _read_focus_combo_tips_from_rules_md()
    presets = _get_focus_presets()
    assert len(tips) >= 1, (
        "未从「组合使用建议」解析出任何表格行；请检查是否存在 ## 组合使用建议 标题及 Markdown 表格。"
    )
    assert len(presets) >= 1, (
        "组合表已解析但 focus_presets 为空：多为表格中的 focus:id 与关注点块 id 不一致，或推荐列未解析出 `focus:` 引用。"
    )
    for pr in presets:
        assert isinstance(pr.get("focus_points"), list) and len(pr["focus_points"]) >= 1


@pytest.mark.skipif(
    not (REPO_ROOT / "rules_new2.md").is_file(),
    reason="仓库中无 rules_new2.md，跳过",
)
def test_rules_new2_md_loads_when_configured_as_active_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """若使用 AIKA_RULES_FILENAME=rules_new2.md，应对该文件能同样完成解析（与默认 rules.md 独立）。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("AIKA_RULES_FILENAME", "rules_new2.md")

    from backend.main import (
        _get_focus_presets,
        _read_focus_combo_tips_from_rules_md,
        _read_settings_from_rules_md,
        _rules_md_path,
    )

    path = _rules_md_path()
    assert path.name == "rules_new2.md"
    parsed, err = _read_settings_from_rules_md()
    assert err is None and parsed is not None, (
        f"无法加载 {path}：{err!r}"
    )
    fps = parsed.get("focus_points") if isinstance(parsed, dict) else None
    assert isinstance(fps, list) and len(fps) >= 1

    tips = _read_focus_combo_tips_from_rules_md()
    presets = _get_focus_presets()
    assert len(tips) >= 1, "rules_new2.md：组合使用建议未解析出任何行"
    assert len(presets) >= 1, "rules_new2.md：focus_presets 为空（检查 focus id 与表格引用）"
    for pr in presets:
        assert isinstance(pr.get("focus_points"), list) and len(pr["focus_points"]) >= 1


def test_rules_md_parse_error_message_includes_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """无关注点块时，错误信息应说明「未找到关注点块」类原因，便于对照修复。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("AIKA_RULES_FILENAME", raising=False)
    (tmp_path / "rules.md").write_text(
        "# 仅有标题\n\n正文没有 ### focus: 行。\n",
        encoding="utf-8",
    )
    from backend.main import _read_settings_from_rules_md

    parsed, err = _read_settings_from_rules_md()
    assert parsed is None
    assert err is not None
    assert "解析失败" in err
    assert "关注点块" in err
