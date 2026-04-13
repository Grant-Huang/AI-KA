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
    def chat_stream(self, *, system: str, user: str, config: object, prior_messages=None):  # type: ignore[no-untyped-def]
        assert "关注点审查清单" in system
        assert "需求" in system
        assert "片段" in user and ("hello" in user or "文件" in user)
        del config
        assert prior_messages is None
        yield "## T\n\nOK\n"


def test_analyze_stream_post_rejects_unknown_focus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import app

    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post("/api/v1/projects/ensure", json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)})
    assert create.status_code == 200
    project_id = int(create.json()["data"]["id"])
    conv = client.post(f"/api/v1/projects/{project_id}/conversations", json={"analysis_type": "KA", "title": "T1"})
    assert conv.status_code == 200
    conversation_id = int(conv.json()["data"]["id"])

    resp = client.post(
        f"/api/v1/projects/{project_id}/conversations/{conversation_id}/analyze/stream",
        json={"chunk_limit": 40, "focus_points": ["不存在的关注点名称"]},
    )
    assert resp.status_code == 400


def test_analyze_stream_post_streams_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "rules.md").write_text(
        "# r\n\n## 关注点块\n\n### focus:req | 需求\n关注点提示\n",
        encoding="utf-8",
    )
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_provider", lambda _p: _FakeAnalyzeProvider())
    monkeypatch.setattr(
        main_mod.dbm,
        "list_chunk_entries",
        lambda *a, **k: [
            {
                "doc_path": "a.md",
                "chunk_index": 0,
                "text": "hello chunk",
                "locator": {"start_line": 1, "end_line": 1, "heading_path": []},
            }
        ],
    )

    from backend.main import app

    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post("/api/v1/projects/ensure", json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)})
    assert create.status_code == 200
    project_id = int(create.json()["data"]["id"])
    conv = client.post(f"/api/v1/projects/{project_id}/conversations", json={"analysis_type": "KA", "title": "T1"})
    assert conv.status_code == 200
    conversation_id = int(conv.json()["data"]["id"])

    resp = client.post(
        f"/api/v1/projects/{project_id}/conversations/{conversation_id}/analyze/stream",
        json={"chunk_limit": 40, "focus_points": ["需求"]},
    )
    assert resp.status_code == 200
    assert b"final" in resp.content
    assert b'"type"' in resp.content
    assert "片段与来源索引".encode("utf-8") in resp.content
