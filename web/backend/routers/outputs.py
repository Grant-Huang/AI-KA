from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from aika import db as dbm
from backend.path_validate import PathValidationError, validate_path_under_dir
from backend.repo_paths import project_export_dir
from backend.response import err, ok
from backend.deps import get_conn
from backend.services.outputs_index_service import list_outputs_index


router = APIRouter()


@router.get("/api/v1/projects/{project_id}/conversations/{conversation_id}/outputs-index")
def get_conversation_outputs_index(project_id: int, conversation_id: int, limit: int = 50) -> JSONResponse:
    conn = get_conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)
    items = list_outputs_index(
        conn, project_id=project_id, conversation_id=conversation_id, limit=int(limit)
    )
    return JSONResponse(ok({"items": [it.to_dict() for it in items]}))


@router.get("/api/v1/files/{project_id}/{filename:path}")
def download_file(project_id: int, filename: str) -> FileResponse:
    base = project_export_dir(project_id)
    target = (base / filename).resolve()
    try:
        validate_path_under_dir(target, base)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    ext = target.suffix.lower()
    if ext == ".docx":
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext in {".md", ".txt", ".json"}:
        media = "text/plain; charset=utf-8"
    else:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path=str(target), filename=target.name, media_type=media)

