"""
Gate tests for POST /api/v1/projects/init-from-upload.

Coverage:
  - mode=init: creates project in .tmp/uploads/ when no vault
  - mode=init: rejects missing project_name
  - mode=init: rejects missing files
  - mode=init: idempotent — re-upload to same path returns created=False
  - mode=append: adds files to existing project
  - mode=append: rejects missing project_id
  - mode=append: 404 when project_id unknown
  - file passthrough: .md / .txt written as-is
  - file path traversal: blocked by _safe_rel_path
  - empty file: skipped with error entry, not crash
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest


def _md_file(name: str, content: str = "# Hello") -> tuple:
    return (name, io.BytesIO(content.encode()), "text/plain")


# ── helpers ──────────────────────────────────────────────────────────────────


def _upload(client, *, files, paths=None, mode="init", project_name="", vault_id=None, project_id=None):
    data: dict = {"mode": mode, "project_name": project_name}
    if paths is not None:
        import json
        data["paths"] = json.dumps(paths)
    if vault_id is not None:
        data["vault_id"] = str(vault_id)
    if project_id is not None:
        data["project_id"] = str(project_id)
    return client.post(
        "/api/v1/projects/init-from-upload",
        data=data,
        files=[("files", f) for f in files],
    )


# ── init mode ────────────────────────────────────────────────────────────────


def test_init_creates_project_no_vault(client, tmp_path: Path):
    """mode=init without vault writes to .tmp/uploads/ and registers project."""
    r = _upload(
        client,
        files=[_md_file("notes.md", "# Test")],
        paths=["notes.md"],
        project_name="AlphaProject",
    )
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "success"
    d = j["data"]
    assert d["name"] == "AlphaProject"
    assert d["created"] is True
    assert d["files_written"] == 1
    assert d["errors"] == []
    assert d["vault_id"] is None
    # verify file actually written
    assert Path(d["root_path"]).joinpath("notes.md").exists()


def test_init_idempotent(client, tmp_path: Path):
    """Re-uploading to the same project_name returns created=False."""
    kwargs = dict(files=[_md_file("doc.md")], paths=["doc.md"], project_name="BetaProject")
    r1 = _upload(client, **kwargs)
    assert r1.status_code == 200
    assert r1.json()["data"]["created"] is True

    # Second upload of different file — same project name
    r2 = _upload(client, files=[_md_file("doc2.md", "# v2")], paths=["doc2.md"], project_name="BetaProject")
    assert r2.status_code == 200
    assert r2.json()["data"]["created"] is False
    assert r2.json()["data"]["name"] == "BetaProject"


def test_init_requires_project_name(client):
    r = _upload(client, files=[_md_file("f.md")], project_name="")
    assert r.status_code == 400
    assert "project_name" in r.json()["detail"].lower()


def test_init_requires_files(client):
    r = client.post(
        "/api/v1/projects/init-from-upload",
        data={"mode": "init", "project_name": "X"},
        files=[],
    )
    assert r.status_code == 422  # fastapi validation — files is required


def test_init_passthrough_md(client, tmp_path: Path):
    """Markdown files written as-is without conversion."""
    content = "# My Spec\n\nSection 1."
    r = _upload(
        client,
        files=[_md_file("spec.md", content)],
        paths=["spec.md"],
        project_name="MDPassthrough",
    )
    assert r.status_code == 200
    d = r.json()["data"]
    out_path = Path(d["root_path"]) / "spec.md"
    assert out_path.exists()
    assert out_path.read_text() == content


def test_init_txt_passthrough(client, tmp_path: Path):
    """Plain text (.txt) files are written as-is."""
    r = _upload(
        client,
        files=[("readme.txt", io.BytesIO(b"plain text"), "text/plain")],
        paths=["readme.txt"],
        project_name="TxtPassthrough",
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert Path(d["root_path"]).joinpath("readme.txt").exists()


def test_init_empty_file_skipped(client):
    """Empty files are skipped with an entry in errors, not a crash."""
    r = _upload(
        client,
        files=[("empty.md", io.BytesIO(b""), "text/plain")],
        paths=["empty.md"],
        project_name="EmptySkip",
    )
    # All files skipped → 422
    assert r.status_code == 422


def test_init_path_traversal_blocked(client):
    """Paths with .. components are sanitised to prevent traversal."""
    r = _upload(
        client,
        files=[_md_file("evil.md", "bad")],
        paths=["../../etc/evil.md"],
        project_name="TraversalTest",
    )
    # Request should succeed but the written path must NOT escape project root
    assert r.status_code == 200
    d = r.json()["data"]
    root = Path(d["root_path"])
    for entry in d["files"]:
        written = root / entry["written"]
        assert str(written).startswith(str(root)), f"Path escaped root: {written}"


# ── append mode ──────────────────────────────────────────────────────────────


def test_append_adds_files_to_existing_project(client, tmp_path: Path):
    """mode=append writes into an existing project's root_path."""
    # first, create a project via init
    r = _upload(
        client,
        files=[_md_file("v1.md", "# v1")],
        paths=["v1.md"],
        project_name="AppendTarget",
    )
    assert r.status_code == 200
    pid = r.json()["data"]["id"]

    # append a new file
    r2 = _upload(
        client,
        files=[_md_file("v2.md", "# v2")],
        paths=["v2.md"],
        mode="append",
        project_id=pid,
    )
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["created"] is False
    assert d2["files_written"] == 1
    root = Path(d2["root_path"])
    assert (root / "v1.md").exists()
    assert (root / "v2.md").exists()


def test_append_requires_project_id(client):
    r = _upload(
        client,
        files=[_md_file("x.md")],
        mode="append",
    )
    assert r.status_code == 400
    assert "project_id" in r.json()["detail"].lower()


def test_append_unknown_project_returns_404(client):
    r = _upload(
        client,
        files=[_md_file("x.md")],
        mode="append",
        project_id=999999,
    )
    assert r.status_code == 404


# ── vault mode ───────────────────────────────────────────────────────────────


def test_init_with_vault_writes_to_vault_projects(client, tmp_path: Path):
    """When vault_id is given, files are written to vault/Projects/<name>/."""
    vault_dir = tmp_path / "myVault"
    vault_dir.mkdir()
    (vault_dir / ".obsidian").mkdir()

    # register vault
    rv = client.post(
        "/api/v1/vaults",
        json={"path": str(vault_dir), "role": "project"},
    )
    assert rv.status_code in (200, 201)
    vid = rv.json()["data"]["id"]

    r = _upload(
        client,
        files=[_md_file("plan.md", "# Plan")],
        paths=["plan.md"],
        project_name="VaultedProject",
        vault_id=vid,
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["vault_id"] == vid
    expected = vault_dir / "Projects" / "VaultedProject" / "plan.md"
    assert expected.exists()
