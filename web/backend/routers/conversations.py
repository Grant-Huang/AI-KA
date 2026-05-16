from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aika import db as dbm
from backend.path_validate import PathValidationError, validate_project_root
from backend.response import err, ok
from backend.deps import get_conn, get_project_or_404


router = APIRouter()


@router.get("/api/v1/conversations")
def list_conversations_global(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = None,
) -> JSONResponse:
    conn = get_conn()
    items = dbm.list_conversations_global(conn, limit=int(limit), offset=int(offset), q=q)
    out = []
    for c in items:
        prj = dbm.get_project_by_id(conn, c.project_id)
        project_exists = prj is not None
        project_available = False
        if prj is not None:
            try:
                validate_project_root(prj.root_path)
                project_available = True
            except PathValidationError:
                project_available = False
        out.append(
            {
                "id": c.id,
                "project_id": c.project_id,
                "project_name": c.project_name,
                "analysis_type": c.analysis_type,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "preset_id": c.preset_id,
                "project_exists": project_exists,
                "project_available": project_available,
            }
        )
    return JSONResponse(ok({"conversations": out}))


@router.get("/api/v1/conversations/by-pair")
def list_conversations_by_pair(
    project_id: int = Query(..., ge=1),
    preset_id: str = Query(..., min_length=1),
) -> JSONResponse:
    conn = get_conn()
    get_project_or_404(conn, project_id)
    rows = dbm.list_conversations_by_pair(conn, project_id=int(project_id), preset_id=str(preset_id))
    items = [
        {
            "id": r.id,
            "project_id": r.project_id,
            "analysis_type": r.analysis_type,
            "title": r.title,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "preset_id": r.preset_id,
        }
        for r in rows
    ]
    return JSONResponse(ok({"count": len(items), "conversations": items}))


class _PatchConversationBody(BaseModel):
    title: str | None = None
    starred: bool | None = None


@router.patch("/api/v1/conversations/{cid}")
def patch_conversation_api(cid: int, body: _PatchConversationBody) -> JSONResponse:
    conn = get_conn()
    updated = dbm.update_conversation(conn, cid, title=body.title, starred=body.starred)
    if not updated:
        return JSONResponse(err("conversation not found or no changes"), status_code=404)
    return JSONResponse(ok({"ok": True}))

