"""Review Queue CRUD API.

Endpoints:
  GET    /api/v1/review-queue          — list items (sorted by priority)
  GET    /api/v1/review-queue/{id}     — get single item
  PATCH  /api/v1/review-queue/{id}     — update status / reject
  DELETE /api/v1/review-queue/{id}     — delete item
  POST   /api/v1/review-queue          — manually add item (senior expert only)
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aika import db as dbm
from backend.deps import get_conn
from backend.response import err, ok

router = APIRouter()


class ReviewQueuePatch(BaseModel):
    status: str | None = None
    reviewed_by: str | None = None
    reject_reason: str | None = None


class ReviewQueueCreate(BaseModel):
    focus_id: str
    suggestion: str
    source_role: str = "senior_expert"
    source_type: str = "extraction"
    project_id: str | None = None


_VALID_STATUSES = {"pending_review", "in_review", "approved", "rejected", "archived"}


@router.get("/api/v1/review-queue")
def list_review_queue(
    status: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> JSONResponse:
    conn = get_conn()
    items = dbm.list_review_queue(conn, status=status, project_id=project_id, limit=limit)
    return ok({"items": items, "total": len(items)})


@router.get("/api/v1/review-queue/{item_id}")
def get_review_queue_item(item_id: str) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_review_queue_item(conn, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review queue item not found")
    return ok(item)


@router.patch("/api/v1/review-queue/{item_id}")
def patch_review_queue_item(item_id: str, body: ReviewQueuePatch) -> JSONResponse:
    conn = get_conn()
    if body.status and body.status not in _VALID_STATUSES:
        return err(f"Invalid status: {body.status}. Valid: {sorted(_VALID_STATUSES)}")
    item = dbm.get_review_queue_item(conn, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review queue item not found")
    updated = dbm.update_review_queue_status(
        conn,
        item_id,
        status=body.status or item["status"],
        reviewed_by=body.reviewed_by,
        reject_reason=body.reject_reason,
    )
    if not updated:
        return err("Update failed")
    return ok(dbm.get_review_queue_item(conn, item_id))


@router.delete("/api/v1/review-queue/{item_id}")
def delete_review_queue_item(item_id: str) -> JSONResponse:
    conn = get_conn()
    deleted = dbm.delete_review_queue_item(conn, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Review queue item not found")
    return ok({"deleted": item_id})


@router.post("/api/v1/review-queue")
def create_review_queue_item(body: ReviewQueueCreate) -> JSONResponse:
    conn = get_conn()
    item_id = f"rq-{uuid.uuid4().hex[:12]}"
    dbm.upsert_review_queue_item(
        conn,
        id=item_id,
        focus_id=body.focus_id,
        suggestion=body.suggestion,
        source_role=body.source_role,
        source_type=body.source_type,
        project_id=body.project_id,
    )
    item = dbm.get_review_queue_item(conn, item_id)
    return ok(item)
