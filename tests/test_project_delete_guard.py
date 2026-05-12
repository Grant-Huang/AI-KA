from __future__ import annotations

from pathlib import Path

import pytest


def test_delete_project_blocked_when_has_analysis_runs(client, tmp_path: Path):
    proj_root = tmp_path / "proj"
    proj_root.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/v1/projects", json={"name": "p1", "root_path": proj_root.as_posix()})
    assert r.status_code == 200
    pid = int(r.json()["data"]["id"])

    r2 = client.post(
        f"/api/v1/projects/{pid}/conversations",
        json={"analysis_type": "KA", "title": "t1", "preset_id": "default"},
    )
    assert r2.status_code == 200
    cid = int(r2.json()["data"]["id"])

    # Insert a conversation_output to simulate a completed review (the guard checks this table)
    from backend.main import _conn
    from src.aika import db as dbm

    conn = _conn()
    dbm.insert_conversation_output(
        conn,
        conversation_id=cid,
        kind="analysis",
        final_filename="out.md",
        milestones_filename="milestones.json",
    )

    r3 = client.delete(f"/api/v1/projects/{pid}")
    assert r3.status_code == 409
    j3 = r3.json()
    assert j3["status"] == "error"

    # project should still exist
    r4 = client.get(f"/api/v1/projects/{pid}")
    assert r4.status_code == 200


def test_delete_project_allowed_when_no_analysis_runs(client, tmp_path: Path):
    proj_root = tmp_path / "proj2"
    proj_root.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/v1/projects", json={"name": "p2", "root_path": proj_root.as_posix()})
    assert r.status_code == 200
    pid = int(r.json()["data"]["id"])

    r2 = client.delete(f"/api/v1/projects/{pid}")
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["status"] == "success"
    assert j2["data"]["deleted"] is True

    r3 = client.get(f"/api/v1/projects/{pid}")
    assert r3.status_code == 404

