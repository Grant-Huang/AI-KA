"""
Review Knowledge Structure API.
Reads structured review knowledge (L0/L1/L2) directly from skill package files.
DB tables (review_phases, review_focus_points_ext, etc.) are no longer the
source of truth; the import endpoint is kept for backward compatibility but
all GET endpoints now parse from review_domain.md on every request.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.response import ok, err
from backend.repo_paths import repository_root
from backend.skills import list_skill_packages, skill_packages_root
from backend.skills.packages import package_dir as get_package_dir
from backend.skills.review_domain_parser import parse_review_domain_structs, import_review_domain_to_db

router = APIRouter()


def _active_package_dir() -> tuple[str, Path] | None:
    rr = repository_root()
    pkgs = list_skill_packages(rr)
    if not pkgs:
        return None
    pkg = pkgs[0]
    return pkg["id"], get_package_dir(rr, pkg["id"])


def _load_structs() -> dict:
    """Parse active skill package files and return all structured data."""
    result = _active_package_dir()
    if result is None:
        return {"phases": [], "focus_points": [], "categories": [], "presets": [], "package_id": ""}
    pkg_id, pkg_dir = result
    return parse_review_domain_structs(pkg_dir, package_id=pkg_id)


@router.post("/api/v1/review-knowledge/import")
def import_review_knowledge() -> JSONResponse:
    """
    Parse active skill package's review_domain.md.
    Now also writes to DB for backward compatibility with older clients,
    but GET endpoints no longer depend on DB state.
    """
    result = _active_package_dir()
    if result is None:
        return JSONResponse(err("No skill packages found"), status_code=404)
    pkg_id, pkg_dir = result

    structs = parse_review_domain_structs(pkg_dir, package_id=pkg_id)
    if "error" in structs:
        return JSONResponse(err(structs["error"]), status_code=400)

    # Back-compat: also import to DB (no-op if already current)
    try:
        from backend.deps import get_conn
        conn = get_conn()
        import_review_domain_to_db(conn, pkg_dir, package_id=pkg_id)
    except Exception:
        pass

    return JSONResponse(ok({
        "phase_count": len(structs["phases"]),
        "focus_point_count": len(structs["focus_points"]),
        "category_count": len(structs["categories"]),
        "preset_count": len(structs["presets"]),
        "package_id": pkg_id,
    }))


@router.get("/api/v1/review-knowledge/phases")
def get_phases() -> JSONResponse:
    structs = _load_structs()
    return JSONResponse(ok({"phases": structs["phases"]}))


@router.get("/api/v1/review-knowledge/focus-points")
def get_focus_points(phase_id: str | None = None) -> JSONResponse:
    structs = _load_structs()
    fps = structs["focus_points"]
    if phase_id:
        fps = [f for f in fps if f["phase_id"] == phase_id]
    return JSONResponse(ok({"focus_points": fps, "total": len(fps)}))


@router.get("/api/v1/review-knowledge/categories")
def get_categories(focus_id: str | None = None) -> JSONResponse:
    structs = _load_structs()
    cats = structs["categories"]
    if focus_id:
        cats = [c for c in cats if c["focus_id"] == focus_id]
    return JSONResponse(ok({"categories": cats, "total": len(cats)}))


@router.get("/api/v1/review-knowledge/presets")
def get_presets() -> JSONResponse:
    structs = _load_structs()
    presets = structs["presets"]
    return JSONResponse(ok({"presets": presets, "total": len(presets)}))
