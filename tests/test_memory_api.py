from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_memory_upsert_and_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post("/api/v1/projects/ensure", json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)})
    assert create.status_code == 200
    project_id = int(create.json()["data"]["id"])
    rel = f"project/{project_id}/note.md"
    w = client.post(
        f"/api/v1/projects/{project_id}/memory/upsert",
        json={"path": rel, "content": "# T\n\nMES 关键词\n"},
    )
    assert w.status_code == 200
    lst = client.get(f"/api/v1/projects/{project_id}/memory/files")
    assert lst.status_code == 200
    files = lst.json()["data"]["files"]
    assert any(rel in f for f in files)
