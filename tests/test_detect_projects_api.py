from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_detect_projects_single(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "调研记录").mkdir()
    client = TestClient(app)
    r = client.post("/api/v1/fs/detect-projects", json={"root_path": str(root)})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["data"]["mode"] == "single"
