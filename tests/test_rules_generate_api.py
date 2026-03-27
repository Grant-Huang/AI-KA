from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeProvider:
    def chat_stream(self, *, system: str, user: str, config: object):  # type: ignore[no-untyped-def]
        del system, user, config
        yield '{"goal":"聚焦风险与需求","dimensions":["风险","需求"],"style":{"prefer":["cards","table"]}}'


def test_generate_rules_from_focus_points(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend.main import app

    monkeypatch.setattr("backend.main.get_provider", lambda _provider: _FakeProvider())
    client = TestClient(app)

    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post(
        "/api/v1/projects",
        json={"name": f"p-rules-{uuid.uuid4().hex[:8]}", "root_path": str(src)},
    )
    assert create.status_code == 200
    project_id = create.json()["data"]["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/rules/generate",
        json={"focus_points": ["接口与集成", "验收"], "focus_note": "关注上线风险"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    rules = body["data"]["rules"]
    assert "goal" in rules
    assert "dimensions" in rules
    assert "接口与集成" in rules["dimensions"]
    assert "验收" in rules["dimensions"]
    assert "关注上线风险" in rules["dimensions"]
