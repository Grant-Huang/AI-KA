from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from aika import db as dbm
from aika.paths import db_path
from backend.main import app
from backend.repo_paths import repository_root


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
    assert "updated_at" in items[0] and "created_at" in items[0]


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


def test_get_conversation_detail_has_analysis_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    client = TestClient(app)
    pr = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_root), "name": "p"})
    pid = int(pr.json()["data"]["id"])
    c1 = client.post(f"/api/v1/projects/{pid}/conversations", json={"analysis_type": "KA", "title": "T1"})
    cid = int(c1.json()["data"]["id"])

    r = client.get(f"/api/v1/projects/{pid}/conversations/{cid}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] == cid
    assert data["title"] == "T1"
    assert data["has_analysis_run"] is False
    assert data.get("last_analysis_focus_points") in (None, [])


def test_create_conversation_with_preset_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    client = TestClient(app)
    pr = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_root), "name": "p"})
    pid = int(pr.json()["data"]["id"])
    c1 = client.post(
        f"/api/v1/projects/{pid}/conversations",
        json={"analysis_type": "KA", "title": "WithPreset", "preset_id": "p_test_xyz"},
    )
    assert c1.status_code == 200
    cid = int(c1.json()["data"]["id"])
    assert c1.json()["data"].get("preset_id") == "p_test_xyz"
    r = client.get(f"/api/v1/projects/{pid}/conversations/{cid}")
    assert r.status_code == 200
    assert r.json()["data"].get("preset_id") == "p_test_xyz"
    listed = client.get(f"/api/v1/projects/{pid}/conversations")
    items = listed.json()["data"]["conversations"]
    assert any(int(x["id"]) == cid and x.get("preset_id") == "p_test_xyz" for x in items)


def test_preset_history_without_and_with_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    client = TestClient(app)
    pr = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_root), "name": "p"})
    pid = int(pr.json()["data"]["id"])
    c1 = client.post(
        f"/api/v1/projects/{pid}/conversations",
        json={"analysis_type": "KA", "title": "H1", "preset_id": "p_hist"},
    )
    cid = int(c1.json()["data"]["id"])

    h0 = client.get(f"/api/v1/projects/{pid}/conversations/preset-history", params={"preset_id": "p_hist"})
    assert h0.status_code == 200
    d0 = h0.json()["data"]
    assert d0["has_reviewed_history"] is False
    assert d0["latest_conversation"] is None

    root = repository_root()
    conn = dbm.connect(db_path(root))
    dbm.insert_analysis_run(
        conn,
        conversation_id=cid,
        job_id=None,
        focus_points=["a"],
        chunk_limit=10,
        chunk_strategy="blank",
        used_entries=[],
        output_markdown_path=str(tmp_path / "analysis_out.md"),
    )

    h1 = client.get(f"/api/v1/projects/{pid}/conversations/preset-history", params={"preset_id": "p_hist"})
    assert h1.status_code == 200
    d1 = h1.json()["data"]
    assert d1["has_reviewed_history"] is True
    latest = d1["latest_conversation"]
    assert latest is not None
    assert int(latest["id"]) == cid
    assert latest.get("title") == "H1"

