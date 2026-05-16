"""
Project Init via File Upload.

POST /api/v1/projects/init-from-upload
  - Accept multipart: files[] + paths (JSON array of relative paths) + project_name + vault_id
  - Convert non-markdown files via markitdown
  - Write converted files to vault/Projects/{project_name}/
  - Register project in DB via ensure_project logic
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
from backend.response import err, ok

router = APIRouter(prefix="/api/v1/projects", tags=["project-init"])

PASSTHROUGH_EXTS = {".md", ".txt", ".markdown"}
CONVERTIBLE_EXTS = {".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".html", ".htm"}


def _convert_to_markdown(src: Path) -> str:
    from markitdown import MarkItDown
    md = MarkItDown()
    result = md.convert(str(src))
    return result.text_content or ""


def _safe_rel_path(rel: str) -> Path:
    """Strip leading slashes/dots and ensure no path traversal."""
    parts = [p for p in Path(rel).parts if p not in ("", ".", "..")]
    return Path(*parts) if parts else Path("upload")


@router.post("/init-from-upload")
async def init_project_from_upload(
    files: Annotated[list[UploadFile], File(...)],
    paths: Annotated[str, Form()] = "[]",
    project_name: Annotated[str, Form()] = "",
    vault_id: Annotated[int | None, Form()] = None,
):
    """
    Upload files (or a directory) to initialize a project in an Obsidian Vault.
    Files are converted to Markdown via markitdown and written to
    vault/Projects/{project_name}/.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # Parse relative paths (same length as files, if provided)
    try:
        rel_paths: list[str] = json.loads(paths)
    except Exception:
        rel_paths = []

    # Pad or default relative paths
    while len(rel_paths) < len(files):
        rel_paths.append(files[len(rel_paths)].filename or "upload.md")

    # Resolve vault path
    vault_path: Path | None = None
    if vault_id is not None:
        with get_conn() as conn:
            vault_row = dbm.get_obsidian_vault_by_id(conn, vault_id)
        if vault_row is None:
            raise HTTPException(status_code=404, detail=f"Vault #{vault_id} not found")
        vault_path = Path(vault_row["path"])
        if not vault_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Vault path not accessible: {vault_path}")

    # Determine project_name
    name = project_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="project_name is required")

    # Decide destination
    if vault_path is not None:
        ensure_vault_structure(vault_path)
        dest_root = vault_path / "Projects" / name
    else:
        # No vault: write to a temporary staging area under .tmp/uploads/
        from backend.repo_paths import repository_root
        dest_root = repository_root() / ".tmp" / "uploads" / name

    dest_root.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    errors: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for upload_file, rel_str in zip(files, rel_paths):
            rel = _safe_rel_path(rel_str)
            suffix = rel.suffix.lower()
            original_name = rel.name

            # Read uploaded bytes
            content = await upload_file.read()
            if not content:
                errors.append(f"{rel_str}: empty file, skipped")
                continue

            # Write to temp file for conversion
            tmp_src = Path(tmpdir) / original_name
            tmp_src.write_bytes(content)

            # Determine output path (always .md)
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
                # Unknown extension: try conversion, fall back to plain text
                out_rel = rel.with_suffix(".md")
                try:
                    md_text = _convert_to_markdown(tmp_src)
                except Exception:
                    md_text = content.decode("utf-8", errors="replace")

            # Write output
            out_path = dest_root / out_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md_text, encoding="utf-8")
            results.append({"source": rel_str, "written": str(out_rel)})

    if not results:
        raise HTTPException(status_code=422, detail=f"No files were written. Errors: {errors}")

    # Register project in DB
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
