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
    assert "chunk_limit" in body["data"]
    assert "rules_md_error" in body["data"]

    payload = {
        "chunk_limit": 55,
        "focus_points": [
            {"id": "fp1", "name": "关注A", "prompt": "请重点分析A"},
            {"id": "fp2", "name": "关注B", "prompt": "请重点分析B"},
        ],
    }
    s = client.post("/api/v1/settings", json=payload)
    assert s.status_code == 200
    b2 = s.json()["data"]
    assert b2["chunk_limit"] == 55
    assert len(b2["focus_points"]) == 2
    assert b2["rules_md_error"] is None
    rules_md = tmp_path / "rules.md"
    assert rules_md.is_file()
    txt = rules_md.read_text(encoding="utf-8")
    assert "| id | name |" in txt
    assert "### prompt:fp1" in txt
    assert "- chunk_limit: 55" in txt
    assert "关注A" in txt


def test_settings_reports_rules_md_parse_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text("# broken rules\n\nno table here\n", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()["data"]
    assert isinstance(body.get("rules_md_error"), str)
    assert "关注点列表" in body["rules_md_error"]
