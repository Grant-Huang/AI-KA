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
    rules_md = tmp_path / "rules.md"
    assert rules_md.is_file()
    txt = rules_md.read_text(encoding="utf-8")
    assert "## 关注点块" in txt
    assert "### focus:fp1 | 关注A" in txt
    assert "chunk_limit" not in txt
    assert "关注A" in txt


def test_settings_reports_rules_md_parse_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text("# broken rules\n\nno table here\n", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()["data"]
    assert isinstance(body.get("rules_md_error"), str)
    assert "关注点块" in body["rules_md_error"]


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


def test_settings_reads_focus_combo_tips_from_rules_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        (
            "# r\n\n"
            "### focus:req | 需求\n"
            "需求提示\n\n"
            "## 组合使用建议\n\n"
            "| 评审节点 | 推荐组合的关注点 |\n"
            "|---|---|\n"
            "| 蓝图评审 | `focus:req` + `focus:integration` |\n"
            "| 验收评审 | `focus:acceptance` + `focus:data` |\n"
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
