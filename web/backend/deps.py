from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from aika import db as dbm
from aika.paths import db_path

from backend.repo_paths import repository_root


def get_conn():
    root = repository_root()
    conn = dbm.connect(db_path(root))
    dbm.ensure_schema(conn)
    return conn


def get_project_or_404(conn: Any, project_id: int) -> Any:
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    return prj


def get_conversation_or_404(conn: Any, conversation_id: int, *, project_id: int | None = None) -> Any:
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or (project_id is not None and conv.project_id != project_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv
