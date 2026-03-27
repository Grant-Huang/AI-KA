from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_patch_project_root(tmp_path: Path) -> None:
    client = TestClient(app)
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    name = f"patch-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/projects", json={"name": name, "root_path": str(a)})
    assert r.status_code == 200
    pid = r.json()["data"]["id"]
    r2 = client.patch(f"/api/v1/projects/{pid}", json={"root_path": str(b)})
    assert r2.status_code == 200
    assert r2.json()["data"]["root_path"] == str(b.resolve())
