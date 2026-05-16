from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aika import db as dbm
from backend.deps import get_conn
from backend.response import err, ok
from backend.obsidian_service import (
    find_vaults, is_obsidian_vault, read_vault_name,
    list_vault_projects, ensure_vault_structure,
)

router = APIRouter()


def _vault_to_dict(v: dbm.ObsidianVaultRow) -> dict[str, Any]:
    fm_filter = None
    if v.frontmatter_filter_json:
        try:
            fm_filter = json.loads(v.frontmatter_filter_json)
        except Exception:
            pass
    return {
        "id": v.id,
        "path": v.path,
        "name": v.name,
        "role": v.role,
        "frontmatter_filter": fm_filter,
        "output_folder": v.output_folder,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
    }


@router.get("/api/v1/vaults")
def list_vaults() -> JSONResponse:
    conn = get_conn()
    vaults = dbm.list_obsidian_vaults(conn)
    return JSONResponse(ok({"vaults": [_vault_to_dict(v) for v in vaults]}))


@router.post("/api/v1/vaults")
def register_vault(payload: dict[str, Any]) -> JSONResponse:
    path_str = str(payload.get("path") or "").strip()
    if not path_str:
        return JSONResponse(err("path is required"), status_code=400)

    vault_path = Path(path_str).expanduser().resolve()
    if not vault_path.is_dir():
        return JSONResponse(err("directory does not exist"), status_code=400)
    if not is_obsidian_vault(vault_path):
        return JSONResponse(err("not an Obsidian vault (no .obsidian/ directory found)"), status_code=400)

    name = str(payload.get("name") or "").strip() or read_vault_name(vault_path)
    role = str(payload.get("role") or "project").strip()
    if role not in ("project", "knowledge", "both"):
        return JSONResponse(err("role must be project | knowledge | both"), status_code=400)

    fm_filter = payload.get("frontmatter_filter")
    fm_filter_json = json.dumps(fm_filter) if fm_filter else None
    output_folder = str(payload.get("output_folder") or "_aika/reviews").strip()

    conn = get_conn()
    existing = dbm.get_obsidian_vault_by_path(conn, str(vault_path))
    if existing:
        return JSONResponse(
            err("vault already registered"), status_code=409,
        )
    vault = dbm.create_obsidian_vault(
        conn,
        path=str(vault_path),
        name=name,
        role=role,
        frontmatter_filter_json=fm_filter_json,
        output_folder=output_folder,
    )
    return JSONResponse(ok(_vault_to_dict(vault)), status_code=201)


@router.get("/api/v1/vaults/discover")
def discover_vaults() -> JSONResponse:
    results = find_vaults()
    conn = get_conn()
    registered_paths = {v.path for v in dbm.list_obsidian_vaults(conn)}
    for r in results:
        r["already_registered"] = r["path"] in registered_paths
    return JSONResponse(ok({"vaults": results}))


@router.get("/api/v1/vaults/{vault_id}")
def get_vault(vault_id: int) -> JSONResponse:
    conn = get_conn()
    vault = dbm.get_obsidian_vault_by_id(conn, vault_id)
    if vault is None:
        return JSONResponse(err("vault not found"), status_code=404)
    return JSONResponse(ok(_vault_to_dict(vault)))


@router.patch("/api/v1/vaults/{vault_id}")
def update_vault(vault_id: int, payload: dict[str, Any]) -> JSONResponse:
    conn = get_conn()
    vault = dbm.get_obsidian_vault_by_id(conn, vault_id)
    if vault is None:
        return JSONResponse(err("vault not found"), status_code=404)

    name = str(payload["name"]).strip() if "name" in payload else None
    role_raw = str(payload["role"]).strip() if "role" in payload else None
    if role_raw is not None and role_raw not in ("project", "knowledge", "both"):
        return JSONResponse(err("role must be project | knowledge | both"), status_code=400)

    fm_filter = payload.get("frontmatter_filter")
    fm_json: str | None = None
    if "frontmatter_filter" in payload:
        fm_json = json.dumps(fm_filter) if fm_filter else "null"

    output_folder = str(payload["output_folder"]).strip() if "output_folder" in payload else None

    dbm.update_obsidian_vault(
        conn, vault_id,
        name=name,
        role=role_raw,
        frontmatter_filter_json=fm_json,
        output_folder=output_folder,
    )
    updated = dbm.get_obsidian_vault_by_id(conn, vault_id)
    return JSONResponse(ok(_vault_to_dict(updated)))  # type: ignore[arg-type]


@router.get("/api/v1/vaults/{vault_id}/projects")
def list_vault_project_dirs(vault_id: int) -> JSONResponse:
    """
    Scan vault_path/Projects/ and return first-level subdirectories as potential
    AI-KA projects, with auto-detected project number/name and registration status.
    """
    conn = get_conn()
    vault = dbm.get_obsidian_vault_by_id(conn, vault_id)
    if vault is None:
        return JSONResponse(err("vault not found"), status_code=404)

    registered = {p.root_path for p in dbm.get_projects_by_vault_id(conn, vault_id)}
    projects = list_vault_projects(Path(vault.path), registered_roots=registered)
    return JSONResponse(ok({"vault_id": vault_id, "projects": projects}))


@router.post("/api/v1/vaults/{vault_id}/init-structure")
def init_vault_structure(vault_id: int) -> JSONResponse:
    """Create the standard _aika/ subdirectory structure inside the vault."""
    conn = get_conn()
    vault = dbm.get_obsidian_vault_by_id(conn, vault_id)
    if vault is None:
        return JSONResponse(err("vault not found"), status_code=404)
    try:
        ensure_vault_structure(Path(vault.path))
    except OSError as e:
        return JSONResponse(err(f"failed to create vault structure: {e}"), status_code=500)
    return JSONResponse(ok({"initialized": True, "vault_path": vault.path}))


@router.delete("/api/v1/vaults/{vault_id}")
def delete_vault(vault_id: int) -> JSONResponse:
    conn = get_conn()
    removed = dbm.delete_obsidian_vault(conn, vault_id)
    if not removed:
        return JSONResponse(err("vault not found"), status_code=404)
    return JSONResponse(ok({"deleted": True}))
