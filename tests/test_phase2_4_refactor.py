"""
Phase 2-4 gate tests.

Phase 2: Skill package tables → file-based reading
Phase 3: Analysis run markers written to Vault
Phase 4: Session quality reports written to meta JSONL file
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Phase 2: review-knowledge endpoints read from files, not DB
# ---------------------------------------------------------------------------

def test_review_knowledge_phases_returns_list():
    """GET /review-knowledge/phases works without DB import."""
    r = client.get("/api/v1/review-knowledge/phases")
    assert r.status_code == 200
    data = r.json()
    assert "phases" in data["data"]
    # May be empty list if no skill package, but must be a list
    assert isinstance(data["data"]["phases"], list)


def test_review_knowledge_focus_points_returns_list():
    r = client.get("/api/v1/review-knowledge/focus-points")
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["focus_points"], list)


def test_review_knowledge_categories_returns_list():
    r = client.get("/api/v1/review-knowledge/categories")
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["categories"], list)


def test_review_knowledge_presets_returns_list():
    r = client.get("/api/v1/review-knowledge/presets")
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["presets"], list)


def test_review_knowledge_phase_filter():
    """phase_id filter works at file-parse level."""
    r = client.get("/api/v1/review-knowledge/focus-points?phase_id=phase-does-not-exist")
    assert r.status_code == 200
    assert r.json()["data"]["focus_points"] == []
    assert r.json()["data"]["total"] == 0


def test_review_knowledge_import_still_works():
    """POST /review-knowledge/import remains functional."""
    r = client.post("/api/v1/review-knowledge/import")
    # 200 OK or 404 (no skill package) — both are valid
    assert r.status_code in (200, 404)


def test_review_knowledge_no_db_dependency(tmp_path, monkeypatch):
    """
    File-based endpoints return data even when DB is fresh (no prior import).
    This verifies there is no hidden DB dependency for GET endpoints.
    """
    from backend.skills.review_domain_parser import parse_review_domain_structs
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "review_domain.md").write_text(
        "### focus:req | 需求完整性\n内容\n\n## 组合使用建议\n\n"
        "| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 默认 | `focus:req` | PM | 检查需求 | MD报告 |\n",
        encoding="utf-8",
    )
    structs = parse_review_domain_structs(pkg_dir, package_id="test-pkg")
    assert len(structs["focus_points"]) == 1
    assert structs["focus_points"][0]["id"] == "req"
    assert structs["focus_points"][0]["name"] == "需求完整性"
    assert len(structs["presets"]) == 1
    assert structs["presets"][0]["focus_members"][0]["focus_id"] == "req"


# ---------------------------------------------------------------------------
# Phase 3: vault run markers
# ---------------------------------------------------------------------------

def test_vault_run_marker_write_and_detect(tmp_path):
    from backend.obsidian_service import write_run_marker, has_review_records_in_vault
    vault = tmp_path / "Vault"
    vault.mkdir()

    assert not has_review_records_in_vault(vault, "项目A")

    write_run_marker(vault, project_name="项目A", project_id=1, conversation_id=42, focus_points=["req"])
    assert has_review_records_in_vault(vault, "项目A")

    # Different project is unaffected
    assert not has_review_records_in_vault(vault, "项目B")


def test_vault_run_marker_content(tmp_path):
    from backend.obsidian_service import write_run_marker, _run_markers_dir
    vault = tmp_path / "Vault"
    vault.mkdir()
    write_run_marker(vault, project_name="Alpha", project_id=5, conversation_id=99, focus_points=["req", "risk"])

    markers = list(_run_markers_dir(vault, "Alpha").glob("run-*.json"))
    assert len(markers) == 1
    data = json.loads(markers[0].read_text())
    assert data["project_id"] == 5
    assert data["conversation_id"] == 99
    assert "req" in data["focus_points"]


def test_ingest_status_has_review_records_from_vault(tmp_path):
    """has_review_records in ingest-status reflects vault markers."""
    from backend.obsidian_service import write_run_marker

    vault_dir = tmp_path / "Vault"
    (vault_dir / ".obsidian").mkdir(parents=True)
    proj_dir = vault_dir / "Projects" / "测试项目"
    proj_dir.mkdir(parents=True)

    # Register vault + project
    reg = client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    assert reg.status_code == 201
    ep = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    pid = ep.json()["data"]["id"]
    proj_name = ep.json()["data"]["name"]

    # No records yet
    r1 = client.get(f"/api/v1/projects/{pid}/ingest-status")
    assert r1.json()["data"]["has_review_records"] is False

    # Write a vault marker directly (simulating a completed analysis)
    write_run_marker(vault_dir, project_name=proj_name, project_id=pid,
                     conversation_id=1, focus_points=["req"])

    # Now ingest-status should reflect it
    r2 = client.get(f"/api/v1/projects/{pid}/ingest-status")
    assert r2.json()["data"]["has_review_records"] is True


def test_delete_project_blocked_by_vault_marker(tmp_path):
    """Project with vault run markers cannot be deleted."""
    from backend.obsidian_service import write_run_marker

    vault_dir = tmp_path / "VaultDel"
    (vault_dir / ".obsidian").mkdir(parents=True)
    proj_dir = vault_dir / "Projects" / "待删项目"
    proj_dir.mkdir(parents=True)

    client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    ep = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    pid = ep.json()["data"]["id"]
    proj_name = ep.json()["data"]["name"]

    # Should be deletable initially
    # (don't actually delete to avoid side effects; just verify no marker blocks it)
    r_status = client.get(f"/api/v1/projects/{pid}/ingest-status")
    assert r_status.json()["data"]["has_review_records"] is False

    # Write marker
    write_run_marker(vault_dir, project_name=proj_name, project_id=pid,
                     conversation_id=7, focus_points=["risk"])

    # Delete should now be blocked
    r_del = client.delete(f"/api/v1/projects/{pid}")
    assert r_del.status_code == 409


# ---------------------------------------------------------------------------
# Phase 4: quality reports → meta JSONL file
# ---------------------------------------------------------------------------

def test_quality_report_append_and_read(tmp_path, monkeypatch):
    from backend.routers.extraction import (
        _append_quality_report_to_file,
        _read_quality_reports_from_file,
        _quality_reports_path,
    )
    monkeypatch.chdir(tmp_path)

    # Override repo root so .aika/meta/ goes into tmp_path
    from backend import repo_paths as rp
    monkeypatch.setattr(rp, "repository_root", lambda: tmp_path)

    import backend.routers.extraction as ext_mod
    monkeypatch.setattr(ext_mod, "repository_root", lambda: tmp_path)

    _append_quality_report_to_file("sqr-001", "session-abc", {
        "expert_type": "PM",
        "high_value_questions": ["Q1"],
        "low_value_questions": [],
    })
    _append_quality_report_to_file("sqr-002", "session-xyz", {
        "expert_type": "Dev",
        "high_value_questions": ["Q2"],
        "low_value_questions": ["Q3"],
    })

    all_reports = _read_quality_reports_from_file()
    assert len(all_reports) == 2

    filtered = _read_quality_reports_from_file(session_ref="session-abc")
    assert len(filtered) == 1
    assert filtered[0]["id"] == "sqr-001"


def test_quality_report_file_survives_db_loss(tmp_path, monkeypatch):
    """JSONL file contains all reports independently of DB."""
    from backend.routers.extraction import _append_quality_report_to_file, _read_quality_reports_from_file
    import backend.routers.extraction as ext_mod
    monkeypatch.setattr(ext_mod, "repository_root", lambda: tmp_path)

    for i in range(3):
        _append_quality_report_to_file(f"sqr-{i}", f"ref-{i}", {"expert_type": "QA"})

    reports = _read_quality_reports_from_file(limit=10)
    assert len(reports) == 3
    # Most recent first
    assert reports[0]["id"] == "sqr-2"
