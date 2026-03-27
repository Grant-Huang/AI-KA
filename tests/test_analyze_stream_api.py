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


class _FakeAnalyzeProvider:
    def chat_stream(self, *, system: str, user: str, config: object):  # type: ignore[no-untyped-def]
        assert "关注点审查清单" in system
        assert "需求" in system
        assert "片段" in user or "hello" in user
        del config
        yield '{"title":"T","blocks":[]}'


def test_analyze_stream_post_rejects_unknown_focus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import app

    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post(
        "/api/v1/projects",
        json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)},
    )
    assert create.status_code == 200
    project_id = create.json()["data"]["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/analyze/stream",
        json={"chunk_limit": 40, "focus_points": ["不存在的关注点名称"]},
    )
    assert resp.status_code == 400


def test_analyze_stream_post_streams_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_provider", lambda _p: _FakeAnalyzeProvider())
    monkeypatch.setattr(main_mod.dbm, "list_chunk_texts", lambda *a, **k: ["hello chunk"])

    from backend.main import app

    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post(
        "/api/v1/projects",
        json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)},
    )
    assert create.status_code == 200
    project_id = create.json()["data"]["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/analyze/stream",
        json={"chunk_limit": 40, "focus_points": ["需求"]},
    )
    assert resp.status_code == 200
    assert b"final" in resp.content
    assert b'"type"' in resp.content
