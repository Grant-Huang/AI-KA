from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_settings_get_and_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    g = client.get("/api/v1/settings")
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "success"
    assert "focus_points" in body["data"]
    assert "focus_combo_tips" in body["data"]
    assert "chunk_limit" in body["data"]
    assert body["data"].get("chunk_strategy") == "blank"
    assert "disable_image_parse" in body["data"]
    assert "rules_md_error" in body["data"]
    assert body["data"]["llm_settings"]["text_model"] == "qwen3"
    assert body["data"]["llm_settings"]["vl_model"] == "qwen3-vl-plus"
    assert body["data"]["llm_settings"]["vl_base_url"] == ""
    assert body["data"]["llm_settings"]["text_provider"] == "openai_compatible"
    assert body["data"]["llm_settings"]["text_base_url"] == ""
    assert body["data"]["llm_settings"]["has_text_api_key"] is False
    assert body["data"]["llm_settings"]["has_vl_api_key"] is False
    assert body["data"]["focus_combo_tips"] == []
    assert body["data"]["disable_image_parse"] is True

    payload = {
        "chunk_limit": 55,
        "focus_points": [
            {"id": "fp1", "name": "关注A", "prompt": "请重点分析A"},
            {"id": "fp2", "name": "关注B", "prompt": "请重点分析B"},
        ],
        "llm_settings": {
            "text_provider": "openai_compatible",
            "text_base_url": "https://api.minimax.chat",
            "text_model": "MiniMax-M2.5",
            "vl_model": "qwen3-vl-plus",
            "vl_base_url": "https://vl.example.com/v1",
        },
        "disable_image_parse": True,
        "chunk_strategy": "structured",
        "llm_text_api_key": "sk-text-123",
        "llm_vl_api_key": "sk-vl-123",
    }
    s = client.post("/api/v1/settings", json=payload)
    assert s.status_code == 200
    b2 = s.json()["data"]
    assert b2["chunk_limit"] == 55
    assert len(b2["focus_points"]) == 2
    assert b2["rules_md_error"] is None
    assert b2["llm_settings"]["text_provider"] == "openai_compatible"
    assert b2["llm_settings"]["text_base_url"] == "https://api.minimax.chat"
    assert b2["llm_settings"]["text_model"] == "MiniMax-M2.5"
    assert b2["llm_settings"]["vl_model"] == "qwen3-vl-plus"
    assert b2["llm_settings"]["vl_base_url"] == "https://vl.example.com/v1"
    assert b2["llm_settings"]["has_text_api_key"] is True
    assert b2["llm_settings"]["has_vl_api_key"] is True
    assert b2["disable_image_parse"] is True
    assert b2.get("chunk_strategy") == "structured"
    app_md = tmp_path / "app_settings.md"
    assert app_md.is_file()
    assert '"chunk_strategy"' in app_md.read_text(encoding="utf-8")
    rules_md = tmp_path / "rules.md"
    assert rules_md.is_file()
    txt = rules_md.read_text(encoding="utf-8")
    assert "## 关注点块" in txt
    assert "### focus:fp1 | 关注A" in txt
    assert "chunk_limit" not in txt
    assert "关注A" in txt


def test_settings_rejects_invalid_chunk_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    r = client.post(
        "/api/v1/settings",
        json={
            "chunk_strategy": "nope",
            "focus_points": [{"id": "a", "name": "A", "prompt": "p"}],
        },
    )
    assert r.status_code == 400


def test_settings_reports_rules_md_parse_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text("# broken rules\n\nno table here\n", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()["data"]
    assert isinstance(body.get("rules_md_error"), str)
    assert "关注点块" in body["rules_md_error"]


def test_trim_accidental_combo_section_in_prompt_unit() -> None:
    from backend.main import _trim_accidental_combo_section_in_prompt

    p = "正文\n\n## 组合使用建议\n\n| 评审节点 | x |\n|---|---|"
    assert "组合使用建议" not in _trim_accidental_combo_section_in_prompt(p)
    assert _trim_accidental_combo_section_in_prompt(p).strip() == "正文"


def test_trim_accidental_combo_section_h3_heading_unit() -> None:
    from backend.main import _trim_accidental_combo_section_in_prompt

    p = "正文\n\n### 组合使用建议\n\n| 评审节点 | x |\n|---|---|"
    assert "组合使用建议" not in _trim_accidental_combo_section_in_prompt(p)
    assert _trim_accidental_combo_section_in_prompt(p).strip() == "正文"


def test_focus_prompt_stops_before_combo_section_heading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """最后一个 ### focus: 之后若接 ## 组合使用建议 等二级标题，prompt 不得吞入表格。"""
    text = (
        "# x\n\n"
        "## 关注点块\n\n"
        "### focus:a | A\n"
        "line for a\n\n"
        "### focus:b | B\n"
        "line for b\n\n"
        "## 组合使用建议\n\n"
        "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 阶段1 | `focus:a` | | | |\n"
    )
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(text, encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    fps = r.json()["data"]["focus_points"]
    assert len(fps) == 2
    assert "组合使用建议" not in fps[1]["prompt"]
    assert "评审节点" not in fps[1]["prompt"]
    tips = r.json()["data"]["focus_combo_tips"]
    assert len(tips) == 1
    assert tips[0]["stage"] == "阶段1"


def test_rules_md_rejects_h3_combo_suggestions_heading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """「组合使用建议」须用 ##；禁止 ### 组合使用建议（强校验仅允许 ### focus:）。"""
    text = (
        "# x\n\n"
        "## 关注点块\n\n"
        "### focus:a | A\n"
        "line for a\n\n"
        "### focus:b | B\n"
        "line for b\n\n"
        "### 组合使用建议\n\n"
        "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 阶段1 | `focus:a` | | | |\n"
    )
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(text, encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    err = r.json()["data"]["rules_md_error"]
    assert isinstance(err, str)
    assert "focus:" in err
    assert "###" in err or "三级" in err
    assert r.json()["data"]["focus_combo_tips"] == []
    assert len(r.json()["data"]["focus_points"]) == 0


def test_validate_and_import_reject_h3_combo_suggestions_heading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    text = (
        "# x\n\n## 关注点块\n\n### focus:a | A\np\n\n### 组合使用建议\n\n"
        "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| n | `focus:a` | | | |\n"
    )
    v = client.post("/api/v1/settings/rules-md/validate", json={"text": text})
    assert v.status_code == 400
    assert "focus:" in v.json()["message"]

    i = client.post("/api/v1/settings/rules-md/import", json={"text": text})
    assert i.status_code == 400
    assert "focus:" in i.json()["message"]


def test_settings_clear_llm_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    s1 = client.post(
        "/api/v1/settings",
        json={
            "llm_settings": {
                "text_provider": "openai_compatible",
                "text_base_url": "",
                "text_model": "qwen3",
                "vl_model": "qwen3-vl-plus",
                "vl_base_url": "",
            },
            "llm_text_api_key": "sk-text-abc",
            "llm_vl_api_key": "sk-vl-abc",
        },
    )
    assert s1.status_code == 200
    assert s1.json()["data"]["llm_settings"]["has_text_api_key"] is True
    assert s1.json()["data"]["llm_settings"]["has_vl_api_key"] is True

    s2 = client.post("/api/v1/settings", json={"llm_text_api_key": "", "llm_vl_api_key": ""})
    assert s2.status_code == 200
    assert s2.json()["data"]["llm_settings"]["has_text_api_key"] is False
    assert s2.json()["data"]["llm_settings"]["has_vl_api_key"] is False


def test_import_rules_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    text = (
        "# custom\n\n"
        "## 关注点块\n\n"
        "### focus:reqx | 需求扩展\n"
        "这是扩展需求关注点。\n\n"
        "### focus:riskx | 风险扩展\n"
        "这是扩展风险关注点。\n"
    )
    v = client.post("/api/v1/settings/rules-md/validate", json={"text": text})
    assert v.status_code == 200
    assert v.json()["data"]["count"] == 2

    i = client.post("/api/v1/settings/rules-md/import", json={"text": text})
    assert i.status_code == 200
    data = i.json()["data"]
    assert len(data["focus_points"]) == 2
    assert data["focus_points"][0]["id"] == "reqx"
    saved = (tmp_path / "rules.md").read_text(encoding="utf-8")
    assert "focus:reqx" in saved


def test_settings_reads_focus_combo_tips_alt_heading_and_fullwidth_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        (
            "# r\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "p\n\n"
            "## 组合使用建议\n\n"
            "｜ 评审节点 ｜ 推荐组合的关注点 ｜ 审查角色 ｜ 审查目标与原则 ｜ 输出要求 ｜\n"
            "｜---｜---｜---｜---｜---｜\n"
            "｜ 蓝图评审 ｜ `focus:req` ｜ ｜ ｜ ｜\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    tips = r.json()["data"]["focus_combo_tips"]
    assert len(tips) == 1
    assert tips[0]["stage"] == "蓝图评审"
    presets = r.json()["data"]["focus_presets"]
    assert len(presets) == 1
    assert presets[0]["name"] == "蓝图评审"
    assert "需求" in presets[0]["focus_points"]


def test_focus_presets_parse_chinese_ids_five_column_combo_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """中文 focus id + 五列表（说明类内容放在审查目标与原则列）。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        (
            "# r\n\n"
            "## 关注点块\n\n"
            "### focus:一审-文档结构 | 方案一审·文档结构\n"
            "p1\n\n"
            "### focus:一审-调研现状 | 方案一审·调研现状说明\n"
            "p2\n\n"
            "## 组合使用建议\n\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| **方案一审** | `focus:一审-文档结构` + `focus:一审-调研现状` | | 说明文字 | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    presets = r.json()["data"]["focus_presets"]
    assert len(presets) == 1
    assert "**方案一审**" in presets[0]["name"] or "方案一审" in presets[0]["name"]
    assert presets[0].get("review_goals_principles") == "说明文字"
    names = presets[0]["focus_points"]
    assert "方案一审·文档结构" in names
    assert "方案一审·调研现状说明" in names
    assert names.index("方案一审·文档结构") < names.index("方案一审·调研现状说明")


def test_settings_post_returns_focus_combo_tips_and_presets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    payload = {
        "focus_points": [
            {"id": "fp1", "name": "关注A", "prompt": "请重点分析A"},
            {"id": "fp2", "name": "关注B", "prompt": "请重点分析B"},
        ],
        "focus_presets": [
            {"id": "preset_x", "name": "双关注方案", "focus_points": ["关注A", "关注B"]},
        ],
        "llm_settings": {
            "text_provider": "openai_compatible",
            "text_base_url": "",
            "text_model": "qwen3",
            "vl_model": "qwen3-vl-plus",
            "vl_base_url": "",
        },
    }
    s = client.post("/api/v1/settings", json=payload)
    assert s.status_code == 200
    data = s.json()["data"]
    assert "focus_combo_tips" in data
    assert len(data["focus_combo_tips"]) == 1
    assert data["focus_combo_tips"][0]["stage"] == "双关注方案"
    assert len(data.get("focus_presets", [])) == 1
    assert data["focus_presets"][0]["name"] == "双关注方案"
    assert set(data["focus_presets"][0]["focus_points"]) == {"关注A", "关注B"}


def test_settings_reads_focus_combo_tips_from_rules_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        (
            "# r\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "需求提示\n\n"
            "## 组合使用建议\n\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 蓝图评审 | `focus:req` + `focus:integration` | | | |\n"
            "| 验收评审 | `focus:acceptance` + `focus:data` | | | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    tips = r.json()["data"]["focus_combo_tips"]
    assert len(tips) == 2
    assert tips[0]["stage"] == "蓝图评审"
    assert "focus:req" in tips[0]["recommended"]


def test_no_auto_fallback_to_default_rules_when_rules_md_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """损坏的 rules.md 不会触发读取 default_rules.md；应报错且关注点/组合表为空。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        "# broken\n\n## 组合使用建议\n| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n| --- | --- | --- | --- | --- |\n| 假行 | `focus:ghost` | | | |\n",
        encoding="utf-8",
    )
    (tmp_path / "default_rules.md").write_text(
        (
            "# d\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "p\n\n"
            "## 组合使用建议\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 蓝图 | `focus:req` | | | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data.get("rules_md_error"), str) and data["rules_md_error"]
    assert "解析失败" in data["rules_md_error"]
    assert data["focus_points"] == []
    assert data["focus_combo_tips"] == []
    assert data["focus_presets"] == []


def test_restore_default_rules_template_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "default_rules.md").write_text(
        (
            "# d\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "p\n\n"
            "## 组合使用建议\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 蓝图 | `focus:req` | | | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.post("/api/v1/settings/rules-md/restore-default-template")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data.get("rules_md_error") in (None, "")
    assert len(data["focus_points"]) >= 1
    assert (tmp_path / "rules.md").is_file()


def test_combo_tips_respects_ai_ka_rules_filename_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """AIKA_RULES_FILENAME=rules_new2.md 时只读该文件，不合并其它规则文件。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("AIKA_RULES_FILENAME", "rules_new2.md")
    (tmp_path / "rules.md").write_text(
        "# r\n\n### focus:x | X\n旧表\n## 组合使用建议\n| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n| --- | --- | --- | --- | --- |\n| 错 | `focus:x` | | | |\n",
        encoding="utf-8",
    )
    (tmp_path / "rules_new2.md").write_text(
        (
            "# r\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "p\n\n"
            "## 组合使用建议\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 节点A | `focus:req` | | | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data.get("rules_filename") == "rules_new2.md"
    tips = data["focus_combo_tips"]
    assert len(tips) == 1
    assert tips[0]["stage"] == "节点A"


def test_combo_tips_uses_last_combo_heading_when_two_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """两处「组合*建议」标题时取最后一处（避免正文误匹配抢先）。"""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        (
            "# r\n\n"
            "## 关注点块\n\n"
            "### focus:req | 需求\n"
            "## 组合使用建议（导读）\n"
            "正文无表格\n\n"
            "## 组合使用建议\n"
            "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 末段评审 | `focus:req` | | | |\n"
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    tips = r.json()["data"]["focus_combo_tips"]
    assert len(tips) == 1
    assert tips[0]["stage"] == "末段评审"
