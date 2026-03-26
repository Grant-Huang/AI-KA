from __future__ import annotations

from pathlib import Path


def repo_tmp_dir(repo_root: Path) -> Path:
    return (repo_root / ".tmp").resolve()


def aika_home_dir(repo_root: Path) -> Path:
    return repo_tmp_dir(repo_root) / "aika"


def db_path(repo_root: Path) -> Path:
    return aika_home_dir(repo_root) / "aika.sqlite3"

