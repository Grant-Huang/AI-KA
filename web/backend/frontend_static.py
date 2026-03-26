from __future__ import annotations

from pathlib import Path


def packaged_dist_dir() -> Path | None:
    """
    Return the packaged frontend dist directory if present.

    In release builds, CI copies `web/frontend/dist/` into the python package
    `frontend_dist/dist/` so it is included inside the wheel.
    """
    try:
        import importlib.resources as resources
    except Exception:
        return None

    try:
        root = resources.files("frontend_dist")
    except ModuleNotFoundError:
        return None

    dist = root / "dist"
    try:
        dist_path = Path(dist)  # type: ignore[arg-type]
    except TypeError:
        # Some importlib.resources backends don't expose a real filesystem path.
        # This app serves static assets from the filesystem only.
        return None

    return dist_path if dist_path.is_dir() else None


def dev_dist_dir(repo_root: Path) -> Path | None:
    """
    Return the dev dist directory (not in wheel) if present.
    """
    dist = (repo_root / "web" / "frontend" / "dist").resolve()
    return dist if dist.is_dir() else None

