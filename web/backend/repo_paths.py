from __future__ import annotations

import os
from pathlib import Path


def repository_root() -> Path:
    env = os.environ.get("AIKA_REPO_ROOT")
    if env:
        return Path(env).resolve()
    # web/backend/*.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def relative_posix(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def project_md_out_dir(project_id: int) -> Path:
    return repository_root() / ".tmp" / "aika" / "projects" / str(project_id) / "md_out"


def project_export_dir(project_id: int) -> Path:
    return repository_root() / ".tmp" / "aika" / "projects" / str(project_id) / "exports"
