from __future__ import annotations

from aika import db as dbm
from aika.paths import db_path

from backend.repo_paths import repository_root


def get_conn():
    root = repository_root()
    conn = dbm.connect(db_path(root))
    dbm.ensure_schema(conn)
    return conn

