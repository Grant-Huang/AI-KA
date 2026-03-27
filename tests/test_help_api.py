from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_helpme_endpoint_reads_markdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "helpme.md").write_text("# 帮助\n\n内容", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/v1/helpme")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "markdown" in data
    assert "# 帮助" in data["markdown"]

