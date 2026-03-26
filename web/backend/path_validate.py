from __future__ import annotations

from pathlib import Path

from backend.config import get_settings


class PathValidationError(ValueError):
    pass


def validate_project_root(path_str: str) -> Path:
    raw = (path_str or "").strip()
    if not raw:
        raise PathValidationError("root_path is empty")
    p = Path(raw).expanduser()
    try:
        resolved = p.resolve()
    except OSError as e:
        raise PathValidationError(f"invalid path: {e}") from e
    if ".." in Path(raw).parts:
        raise PathValidationError("path must not contain '..'")
    if not resolved.exists():
        raise PathValidationError("path does not exist")
    if not resolved.is_dir():
        raise PathValidationError("path is not a directory")

    prefix = get_settings().projects_allow_prefix
    if prefix:
        base = Path(prefix).expanduser().resolve()
        try:
            resolved.relative_to(base)
        except ValueError as e:
            raise PathValidationError(f"path must be under allowed prefix: {base}") from e

    return resolved


def validate_path_under_dir(path: Path, base_dir: Path) -> Path:
    resolved = path.resolve()
    base = base_dir.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as e:
        raise PathValidationError("path escapes base directory") from e
    return resolved
