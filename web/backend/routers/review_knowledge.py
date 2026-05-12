"""
Review Knowledge Structure API.
Endpoints for importing and querying the structured review knowledge (L0/L1/L2).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aika import db as dbm
from backend.deps import get_conn
from backend.response import ok, err
from backend.repo_paths import repository_root
from backend.skills import list_skill_packages, skill_packages_root
from backend.skills.packages import package_dir as get_package_dir

router = APIRouter()


def _active_package_dir() -> tuple[str, Path] | None:
    rr = repository_root()
    root = skill_packages_root(rr)
    pkgs = list_skill_packages(rr)
    if not pkgs:
        return None
    pkg = pkgs[0]
    return pkg["id"], get_package_dir(rr, pkg["id"])


@router.post("/api/v1/review-knowledge/import")
def import_review_knowledge() -> JSONResponse:
    """Parse the active skill package's review_domain.md and import into DB."""
    result = _active_package_dir()
    if result is None:
        return err("No skill packages found")
    pkg_id, pkg_dir = result

    conn = get_conn()
    from backend.skills.review_domain_parser import import_review_domain_to_db
    summary = import_review_domain_to_db(conn, pkg_dir, package_id=pkg_id)
    if "error" in summary:
        return err(summary["error"])
    return ok(summary)


@router.get("/api/v1/review-knowledge/phases")
def get_phases() -> JSONResponse:
    conn = get_conn()
    phases = dbm.list_review_phases(conn)
    return ok({"phases": phases})


@router.get("/api/v1/review-knowledge/focus-points")
def get_focus_points(phase_id: str | None = None) -> JSONResponse:
    conn = get_conn()
    fps = dbm.list_review_focus_points_ext(conn, phase_id=phase_id)
    return ok({"focus_points": fps, "total": len(fps)})


@router.get("/api/v1/review-knowledge/categories")
def get_categories(focus_id: str | None = None) -> JSONResponse:
    conn = get_conn()
    cats = dbm.list_review_categories(conn, focus_id=focus_id)
    return ok({"categories": cats, "total": len(cats)})


@router.get("/api/v1/review-knowledge/presets")
def get_presets() -> JSONResponse:
    conn = get_conn()
    result = _active_package_dir()
    pkg_id = result[0] if result else None
    presets = dbm.list_review_presets_ext(conn, package_id=pkg_id)
    # Enrich with focus members
    enriched = []
    for p in presets:
        members = dbm.list_preset_focus_members(conn, p["id"])
        enriched.append({**p, "focus_members": members})
    return ok({"presets": enriched, "total": len(enriched)})
