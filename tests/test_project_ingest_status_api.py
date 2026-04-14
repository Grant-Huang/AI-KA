def test_project_ingest_status_not_found(client):
    r = client.get("/api/v1/projects/999999/ingest-status")
    assert r.status_code == 404
    j = r.json()
    assert j["status"] == "error"


def test_project_ingest_status_has_review_records_field(client, tmp_path):
    proj_root = tmp_path / "proj"
    proj_root.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/v1/projects", json={"name": "p1", "root_path": proj_root.as_posix()})
    assert r.status_code == 200
    pid = int(r.json()["data"]["id"])

    r2 = client.get(f"/api/v1/projects/{pid}/ingest-status")
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["status"] == "success"
    assert "has_review_records" in j2["data"]
    assert j2["data"]["has_review_records"] is False

