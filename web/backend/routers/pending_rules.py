"""
Pending Rules API.

Endpoints:
  GET  /api/v1/pending-rules           — list pending knowledge items
  GET  /api/v1/pending-rules/{kid}     — get single pending item (with conflict info)
  POST /api/v1/pending-rules/{kid}/approve  — approve: write to review_domain.md
  POST /api/v1/pending-rules/{kid}/reject   — reject with reason
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aika import db as dbm
from backend.deps import get_conn
from backend.response import err, ok
from backend.rule_conflict_detector import detect_conflicts

router = APIRouter()


class RejectBody(BaseModel):
    reason: str = ""


class ApproveBody(BaseModel):
    reviewed_by: str = "senior_expert"
    note: str = ""


@router.get("/api/v1/pending-rules")
def list_pending_rules() -> JSONResponse:
    conn = get_conn()
    items = dbm.list_knowledge_items(conn, status="pending", limit=200)
    enriched = _enrich_with_conflicts(items)
    return ok({"items": enriched, "total": len(enriched)})


@router.get("/api/v1/pending-rules/{kid}")
def get_pending_rule(kid: str) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    enriched = _enrich_with_conflicts([item])
    return ok(enriched[0] if enriched else item)


@router.post("/api/v1/pending-rules/{kid}/reject")
def reject_pending_rule(kid: str, body: RejectBody) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    dbm.update_knowledge_item_status(conn, kid, status="rejected")
    return ok({"rejected": kid, "reason": body.reason})


@router.post("/api/v1/pending-rules/{kid}/approve")
def approve_pending_rule(kid: str, body: ApproveBody) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    if item["status"] not in ("pending", "approved"):
        return err(f"Item status is '{item['status']}', cannot approve")

    # Write to active skill package review_domain.md
    write_result = _write_rule_to_skill_package(item, note=body.note)
    if not write_result["ok"]:
        return err(write_result.get("error", "Failed to write rule to skill package"))

    dbm.update_knowledge_item_status(conn, kid, status="active")
    return ok({
        "approved": kid,
        "written_to": write_result.get("path"),
        "focus_id": item["extraction_focus_id"],
    })


def _enrich_with_conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add conflict_with field by checking against existing focus points."""
    try:
        existing_fps = _get_existing_focus_points()
    except Exception:
        existing_fps = []

    out = []
    for item in items:
        conflicts = detect_conflicts(item, existing_fps)
        enriched = dict(item)
        enriched["conflict_with"] = conflicts
        enriched["has_conflicts"] = len(conflicts) > 0
        out.append(enriched)
    return out


def _get_existing_focus_points() -> list[dict[str, Any]]:
    """Get current active focus points as dicts."""
    try:
        from backend.skills import skill_packages_root, list_skill_packages
        from backend.skills.focus_point_io import list_focus_points
        from backend.skills.packages import package_dir

        root = skill_packages_root()
        packages = list_skill_packages(root)
        if not packages:
            return []
        pkg = packages[0]
        pkg_d = package_dir(root, pkg["id"])
        fps = list_focus_points(pkg_d)
        return [
            {"id": fp.id, "name": fp.name, "prompt": fp.prompt}
            for fp in fps
        ]
    except Exception:
        return []


def _write_rule_to_skill_package(item: dict[str, Any], note: str = "") -> dict[str, Any]:
    """Append the approved KnowledgeItem as a new focus point or evolve an existing one."""
    try:
        from backend.skills import skill_packages_root, list_skill_packages
        from backend.skills.focus_point_io import (
            FocusPoint, evolve_focus_point, list_focus_points, save_focus_point
        )
        from backend.skills.packages import package_dir
        from backend.repo_paths import repository_root

        root = skill_packages_root()
        packages = list_skill_packages(root)
        if not packages:
            return {"ok": False, "error": "No skill packages found"}

        pkg = packages[0]
        pkg_d = package_dir(root, pkg["id"])
        existing = list_focus_points(pkg_d)
        existing_ids = {fp.id for fp in existing}
        target_id = item["extraction_focus_id"]
        now = datetime.utcnow().isoformat()

        # Build rule text block to append/create
        rule_content = item["content"]
        scope_block = ""
        if item.get("scope_note"):
            scope_block = f"\n**适用范围**：{item['scope_note']}"
        if item.get("applicable_when"):
            aw = item["applicable_when"]
            scope_block += f"\n**适用条件**：{aw}"
        if item.get("not_applicable_when"):
            naw = item["not_applicable_when"]
            scope_block += f"\n**排除条件**：{naw}"

        rule_block = f"\n\n---\n*新增规则（{now[:10]}）*：{rule_content}{scope_block}"

        if target_id in existing_ids:
            # Evolve existing focus point
            fp = next(f for f in existing if f.id == target_id)
            note_text = note or f"新增规则：{item['title']}"
            new_fp = evolve_focus_point(
                fp,
                new_prompt=fp.prompt + rule_block,
                note=note_text,
                package_dir=pkg_d,
                repo_root=repository_root(),
            )
            dest = pkg_d / "focus-points" / f"focus-{new_fp.id}.md"
        else:
            # Create new focus point
            new_fp = FocusPoint(
                id=target_id,
                name=item.get("title", target_id),
                prompt=rule_content + scope_block,
                version=1,
                created_at=now,
                updated_at=now,
                history=[{"version": 1, "updated_at": now, "note": note or "from knowledge extraction"}],
            )
            dest = save_focus_point(new_fp, pkg_d)

        return {"ok": True, "path": str(dest)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
