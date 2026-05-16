"""
Project Init / File Append via Upload.

POST /api/v1/projects/init-from-upload
  mode=init  (default): create/register a new project
    - params: files[], paths (JSON), project_name, vault_id (optional)
    - writes to vault/Projects/{name}/ or .tmp/uploads/{name}/

  mode=append: add files to an existing project
    - params: files[], paths (JSON), project_id (required)
    - writes to the project's existing root_path
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aika import db as dbm
from backend.deps import get_conn
from backend.obsidian_service import ensure_vault_structure
from backend.response import ok

router = APIRouter(prefix="/api/v1/projects", tags=["project-init"])

PASSTHROUGH_EXTS = {".md", ".txt", ".markdown"}
CONVERTIBLE_EXTS = {".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".html", ".htm"}


def _convert_to_markdown(src: Path) -> str:
    from markitdown import MarkItDown
    result = MarkItDown().convert(str(src))
    return result.text_content or ""


def _safe_rel_path(rel: str) -> Path:
    """Strip leading slashes/dots; block path traversal."""
    parts = [p for p in Path(rel).parts if p not in ("", ".", "..")]
    return Path(*parts) if parts else Path("upload")


async def _write_files(files: list[UploadFile], rel_paths: list[str], dest_root: Path):
    """Convert and write uploaded files into dest_root. Returns (results, errors)."""
    results: list[dict] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for upload_file, rel_str in zip(files, rel_paths):
            rel = _safe_rel_path(rel_str)
            suffix = rel.suffix.lower()

            content = await upload_file.read()
            if not content:
                errors.append(f"{rel_str}: empty file, skipped")
                continue

            tmp_src = Path(tmpdir) / rel.name
            tmp_src.write_bytes(content)

            if suffix in PASSTHROUGH_EXTS:
                out_rel = rel
                md_text = content.decode("utf-8", errors="replace")
            elif suffix in CONVERTIBLE_EXTS:
                out_rel = rel.with_suffix(".md")
                try:
                    md_text = _convert_to_markdown(tmp_src)
                except Exception as exc:
                    errors.append(f"{rel_str}: conversion failed — {exc}")
                    continue
            else:
                out_rel = rel.with_suffix(".md")
                try:
                    md_text = _convert_to_markdown(tmp_src)
                except Exception:
                    md_text = content.decode("utf-8", errors="replace")

            out_path = dest_root / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md_text, encoding="utf-8")
            results.append({"source": rel_str, "written": str(out_rel)})
    return results, errors


@router.post("/init-from-upload")
async def init_project_from_upload(
    files: Annotated[list[UploadFile], File(...)],
    paths: Annotated[str, Form()] = "[]",
    mode: Annotated[str, Form()] = "init",
    project_name: Annotated[str, Form()] = "",
    vault_id: Annotated[int | None, Form()] = None,
    project_id: Annotated[int | None, Form()] = None,
):
    """
    Upload files to initialize a new project (mode=init) or append to an
    existing one (mode=append).
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    try:
        rel_paths: list[str] = json.loads(paths)
    except Exception:
        rel_paths = []
    while len(rel_paths) < len(files):
        rel_paths.append(files[len(rel_paths)].filename or "upload.md")

    # ── append mode ──────────────────────────────────────────────────────────
    if mode == "append":
        if project_id is None:
            raise HTTPException(status_code=400, detail="project_id is required for append mode")
        with get_conn() as conn:
            project = dbm.get_project_by_id(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project #{project_id} not found")
        dest_root = Path(project.root_path)
        if not dest_root.exists():
            dest_root.mkdir(parents=True, exist_ok=True)

        results, errors = await _write_files(files, rel_paths, dest_root)
        if not results:
            raise HTTPException(status_code=422, detail=f"No files were written. Errors: {errors}")

        return ok({
            "id": project.id,
            "name": project.name,
            "root_path": project.root_path,
            "vault_id": project.vault_id,
            "created": False,
            "files_written": len(results),
            "files": results,
            "errors": errors,
        })

    # ── init mode (default) ──────────────────────────────────────────────────
    name = project_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="project_name is required")

    vault_path: Path | None = None
    if vault_id is not None:
        with get_conn() as conn:
            vault_row = dbm.get_obsidian_vault_by_id(conn, vault_id)
        if vault_row is None:
            raise HTTPException(status_code=404, detail=f"Vault #{vault_id} not found")
        vault_path = Path(vault_row["path"])
        if not vault_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Vault path not accessible: {vault_path}")
        ensure_vault_structure(vault_path)
        dest_root = vault_path / "Projects" / name
    else:
        from backend.repo_paths import repository_root
        dest_root = repository_root() / ".tmp" / "uploads" / name

    dest_root.mkdir(parents=True, exist_ok=True)

    results, errors = await _write_files(files, rel_paths, dest_root)
    if not results:
        raise HTTPException(status_code=422, detail=f"No files were written. Errors: {errors}")

    vault_subfolder = f"Projects/{name}" if vault_id is not None else None
    with get_conn() as conn:
        project = dbm.get_project_by_root_path(conn, str(dest_root))
        if project is None:
            project = dbm.create_project(conn, name=name, root_path=str(dest_root),
                                         vault_id=vault_id, vault_subfolder=vault_subfolder)
            created = True
        else:
            created = False
            if vault_id is not None and project.vault_id is None:
                dbm.update_project_vault(conn, project.id, vault_id=vault_id,
                                         vault_subfolder=vault_subfolder)
                project = dbm.get_project_by_root_path(conn, str(dest_root))

    return ok({
        "id": project.id,
        "name": project.name,
        "root_path": project.root_path,
        "vault_id": project.vault_id,
        "created": created,
        "files_written": len(results),
        "files": results,
        "errors": errors,
    })
