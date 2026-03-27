from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_ensure_project_create_then_reuse(tmp_path: Path) -> None:
    client = TestClient(app)
    root = tmp_path / "proj-root"
    root.mkdir()

    r1 = client.post("/api/v1/projects/ensure", json={"root_path": str(root), "name": "项目A"})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["status"] == "success"
    assert b1["data"]["created"] is True
    pid = b1["data"]["id"]

    r2 = client.post("/api/v1/projects/ensure", json={"root_path": str(root), "name": "项目A"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["status"] == "success"
    assert b2["data"]["created"] is False
    assert b2["data"]["id"] == pid
