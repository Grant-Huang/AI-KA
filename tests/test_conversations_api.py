from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from backend.main import app


def test_create_and_list_conversations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    # project root must exist for ensure
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    client = TestClient(app)

    pr = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_root), "name": "p"})
    assert pr.status_code == 200
    pid = int(pr.json()["data"]["id"])

    r0 = client.get(f"/api/v1/projects/{pid}/conversations")
    assert r0.status_code == 200
    assert r0.json()["data"]["conversations"] == []

    c1 = client.post(f"/api/v1/projects/{pid}/conversations", json={"analysis_type": "KA", "title": "T1"})
    assert c1.status_code == 200
    cid = int(c1.json()["data"]["id"])
    assert c1.json()["data"]["analysis_type"] == "KA"

    r1 = client.get(f"/api/v1/projects/{pid}/conversations")
    assert r1.status_code == 200
    items = r1.json()["data"]["conversations"]
    assert len(items) == 1
    assert int(items[0]["id"]) == cid
    assert items[0]["title"] == "T1"


def test_followup_requires_prior_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    client = TestClient(app)
    pr = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_root), "name": "p"})
    pid = int(pr.json()["data"]["id"])
    c1 = client.post(f"/api/v1/projects/{pid}/conversations", json={"analysis_type": "KA", "title": "T1"})
    cid = int(c1.json()["data"]["id"])

    fu = client.post(f"/api/v1/projects/{pid}/conversations/{cid}/followup/stream", json={"question": "x"})
    # no prior analysis run
    assert fu.status_code == 400

