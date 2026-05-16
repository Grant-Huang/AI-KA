"""
Phase 0 gate tests: Vault directory convention + projects.vault_id linkage.

Gates:
- DB migration adds vault_id / vault_subfolder columns without breaking existing rows
- ensure_project auto-detects vault when path is inside a registered vault
- ensure_project works as before when path is NOT inside any vault
- GET /api/v1/vaults/{id}/projects returns correct subfolder list
- parse_project_name_from_folder extracts number and name correctly
- POST /api/v1/vaults/{id}/init-structure creates _aika/ subdirs
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from backend.main import app
from backend.obsidian_service import parse_project_name_from_folder, list_vault_projects

client = TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests: project name parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder,exp_num,exp_name", [
    ("PRJ-2024-001_电商平台重构",   "PRJ-2024-001", "电商平台重构"),
    ("P2024001-客户管理系统",        "P2024001",     "客户管理系统"),
    ("P001_支付系统升级v2",          "P001",         "支付系统升级v2"),
    ("20240115_数据治理项目",        "",             "数据治理项目"),
    ("电商平台重构",                  "",             "电商平台重构"),
    ("simple-project",              "",             "simple-project"),
])
def test_parse_project_name(folder, exp_num, exp_name):
    result = parse_project_name_from_folder(folder)
    assert result["folder_name"] == folder
    assert result["project_number"] == exp_num
    assert result["project_name"] == exp_name


# ---------------------------------------------------------------------------
# Integration: vault project directory scanning
# ---------------------------------------------------------------------------

def test_list_vault_projects_empty_when_no_projects_dir(tmp_path):
    """Vault with no Projects/ folder returns empty list."""
    (tmp_path / ".obsidian").mkdir()
    result = list_vault_projects(tmp_path)
    assert result == []


def test_list_vault_projects_returns_subfolders(tmp_path):
    """Projects/ subfolders appear with parsed names."""
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "Projects" / "PRJ-001_测试项目").mkdir(parents=True)
    (tmp_path / "Projects" / "简单项目").mkdir()

    results = list_vault_projects(tmp_path)
    assert len(results) == 2
    names = {r["folder_name"] for r in results}
    assert "PRJ-001_测试项目" in names
    assert "简单项目" in names

    numbered = next(r for r in results if r["folder_name"] == "PRJ-001_测试项目")
    assert numbered["project_number"] == "PRJ-001"
    assert numbered["project_name"] == "测试项目"
    assert numbered["vault_subfolder"] == "Projects/PRJ-001_测试项目"


def test_list_vault_projects_marks_registered(tmp_path):
    """already_registered flag is set when abs_path is in the registered set."""
    (tmp_path / ".obsidian").mkdir()
    proj_dir = tmp_path / "Projects" / "项目A"
    proj_dir.mkdir(parents=True)

    registered = {str(proj_dir.resolve())}
    results = list_vault_projects(tmp_path, registered_roots=registered)
    assert len(results) == 1
    assert results[0]["already_registered"] is True


# ---------------------------------------------------------------------------
# API: vault project listing endpoint
# ---------------------------------------------------------------------------

def test_vault_projects_endpoint_404_unknown_vault():
    r = client.get("/api/v1/vaults/99999/projects")
    assert r.status_code == 404


def test_vault_projects_endpoint_returns_list(tmp_path):
    """Register a vault, create Projects/ subfolders, verify endpoint lists them."""
    vault_dir = tmp_path / "MyVault"
    vault_dir.mkdir()
    (vault_dir / ".obsidian").mkdir()
    (vault_dir / "Projects" / "PRJ-001_Alpha项目").mkdir(parents=True)
    (vault_dir / "Projects" / "Beta项目").mkdir()

    reg = client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    assert reg.status_code == 201
    vault_id = reg.json()["data"]["id"]

    r = client.get(f"/api/v1/vaults/{vault_id}/projects")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["vault_id"] == vault_id
    projects = data["projects"]
    assert len(projects) == 2
    folder_names = {p["folder_name"] for p in projects}
    assert "PRJ-001_Alpha项目" in folder_names
    assert "Beta项目" in folder_names


# ---------------------------------------------------------------------------
# API: init-structure endpoint
# ---------------------------------------------------------------------------

def test_init_vault_structure(tmp_path):
    vault_dir = tmp_path / "Vault"
    vault_dir.mkdir()
    (vault_dir / ".obsidian").mkdir()

    reg = client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    vault_id = reg.json()["data"]["id"]

    r = client.post(f"/api/v1/vaults/{vault_id}/init-structure")
    assert r.status_code == 200
    assert r.json()["data"]["initialized"] is True

    assert (vault_dir / "_aika" / "reviews").is_dir()
    assert (vault_dir / "_aika" / "knowledge").is_dir()
    assert (vault_dir / "_aika" / "meta").is_dir()


# ---------------------------------------------------------------------------
# API: ensure_project auto-detects vault linkage
# ---------------------------------------------------------------------------

def test_ensure_project_auto_links_vault(tmp_path):
    """ensure_project sets vault_id when path is inside a registered vault."""
    vault_dir = tmp_path / "Vault"
    (vault_dir / ".obsidian").mkdir(parents=True)
    proj_dir = vault_dir / "Projects" / "项目A"
    proj_dir.mkdir(parents=True)

    reg = client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    vault_id = reg.json()["data"]["id"]

    r = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["created"] is True
    assert data["vault_id"] == vault_id
    assert data["vault_subfolder"] == "Projects/项目A"


def test_ensure_project_no_vault_link_when_outside(tmp_path):
    """ensure_project leaves vault_id as None when path is not inside any vault."""
    proj_dir = tmp_path / "standalone_project"
    proj_dir.mkdir()

    r = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["vault_id"] is None
    assert data["vault_subfolder"] is None


def test_ensure_project_existing_gets_vault_backfilled(tmp_path):
    """Re-calling ensure_project on an existing project back-fills missing vault_id."""
    vault_dir = tmp_path / "Vault"
    (vault_dir / ".obsidian").mkdir(parents=True)
    proj_dir = vault_dir / "Projects" / "项目B"
    proj_dir.mkdir(parents=True)

    # Create project BEFORE registering vault
    r1 = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    assert r1.json()["data"]["vault_id"] is None

    # Now register vault
    reg = client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    vault_id = reg.json()["data"]["id"]

    # Re-ensure: should back-fill
    r2 = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    assert r2.status_code == 200
    assert r2.json()["data"]["created"] is False
    assert r2.json()["data"]["vault_id"] == vault_id


# ---------------------------------------------------------------------------
# Regression: existing ensure_project behaviour unchanged
# ---------------------------------------------------------------------------

def test_ensure_project_idempotent(tmp_path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    r1 = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir), "name": "MyProj"})
    pid = r1.json()["data"]["id"]
    r2 = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    assert r2.json()["data"]["id"] == pid
    assert r2.json()["data"]["created"] is False


def test_get_project_returns_vault_fields(tmp_path):
    """GET /api/v1/projects/{id} now includes vault_id and vault_subfolder."""
    vault_dir = tmp_path / "Vault"
    (vault_dir / ".obsidian").mkdir(parents=True)
    proj_dir = vault_dir / "Projects" / "项目C"
    proj_dir.mkdir(parents=True)

    client.post("/api/v1/vaults", json={"path": str(vault_dir), "role": "project"})
    r = client.post("/api/v1/projects/ensure", json={"root_path": str(proj_dir)})
    pid = r.json()["data"]["id"]

    detail = client.get(f"/api/v1/projects/{pid}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert "vault_id" in data
    assert "vault_subfolder" in data
    assert data["vault_subfolder"] == "Projects/项目C"
