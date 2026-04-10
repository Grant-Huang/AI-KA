from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  root_path TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  stage TEXT,
  path TEXT NOT NULL,
  ext TEXT NOT NULL,
  sha256 TEXT,
  mtime REAL,
  status TEXT NOT NULL,
  parse_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, path),
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_project_stage ON documents(project_id, stage);
CREATE INDEX IF NOT EXISTS idx_documents_project_status ON documents(project_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_project_sha ON documents(project_id, sha256);

CREATE TABLE IF NOT EXISTS document_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER,
  locator_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(document_id, chunk_index),
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id, chunk_index);

CREATE TABLE IF NOT EXISTS analysis_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  job_type TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  llm_config_json TEXT,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL,
  error_code TEXT,
  error_message TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_project_status ON analysis_jobs(project_id, status);

CREATE TABLE IF NOT EXISTS annotations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  chunk_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT,
  status TEXT,
  module TEXT,
  tags_json TEXT,
  is_verified INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY(chunk_id) REFERENCES document_chunks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_annotations_project_type ON annotations(project_id, type);
CREATE INDEX IF NOT EXISTS idx_annotations_project_verified ON annotations(project_id, is_verified);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class ProjectRow:
    id: int
    name: str
    root_path: str
    rules_json: str | None = None


@dataclass(frozen=True)
class DocumentRow:
    id: int
    project_id: int
    stage: str | None
    path: str
    ext: str
    sha256: str | None
    mtime: float | None
    status: str
    parse_error: str | None


@dataclass(frozen=True)
class AnalysisJobRow:
    id: int
    project_id: int
    job_type: str
    status: str
    progress: int
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True)
class AnnotationRow:
    id: int
    project_id: int
    chunk_id: int
    type: str
    content: str
    source: str
    confidence: str | None
    is_verified: bool


def connect(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    _migrate_projects_web_columns(conn)


def _migrate_projects_web_columns(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "rules_json" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN rules_json TEXT")
        conn.commit()


def now_touch_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute(
        "UPDATE projects SET updated_at=datetime('now') WHERE id=?",
        (project_id,),
    )


def create_project(conn: sqlite3.Connection, name: str, root_path: str) -> ProjectRow:
    cur = conn.execute(
        "INSERT INTO projects(name, root_path) VALUES (?, ?)",
        (name, root_path),
    )
    conn.commit()
    project_id = int(cur.lastrowid)
    return ProjectRow(id=project_id, name=name, root_path=root_path, rules_json=None)


def get_project_by_name(conn: sqlite3.Connection, name: str) -> ProjectRow | None:
    row = conn.execute(
        "SELECT id, name, root_path, rules_json FROM projects WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_project(row)


def get_project_by_id(conn: sqlite3.Connection, project_id: int) -> ProjectRow | None:
    row = conn.execute(
        "SELECT id, name, root_path, rules_json FROM projects WHERE id=?",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_project(row)


def get_project_by_root_path(conn: sqlite3.Connection, root_path: str) -> ProjectRow | None:
    row = conn.execute(
        "SELECT id, name, root_path, rules_json FROM projects WHERE root_path=? ORDER BY id LIMIT 1",
        (root_path,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_project(row)


def _row_to_project(row: sqlite3.Row) -> ProjectRow:
    rj = row["rules_json"] if "rules_json" in row.keys() else None
    return ProjectRow(
        id=int(row["id"]),
        name=str(row["name"]),
        root_path=str(row["root_path"]),
        rules_json=(str(rj) if rj is not None else None),
    )


def update_project_rules(conn: sqlite3.Connection, project_id: int, rules_json: str | None) -> None:
    conn.execute(
        "UPDATE projects SET rules_json=?, updated_at=datetime('now') WHERE id=?",
        (rules_json, project_id),
    )
    conn.commit()


def clear_project_index_state(conn: sqlite3.Connection, project_id: int) -> None:
    """Remove annotations, documents and chunks for a project (e.g. after root_path change)."""
    conn.execute("DELETE FROM annotations WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM documents WHERE project_id=?", (project_id,))
    conn.commit()


def update_project_root(conn: sqlite3.Connection, project_id: int, root_path: str) -> None:
    conn.execute(
        "UPDATE projects SET root_path=?, updated_at=datetime('now') WHERE id=?",
        (root_path, project_id),
    )
    conn.commit()


def update_project_name(conn: sqlite3.Connection, project_id: int, name: str) -> None:
    conn.execute(
        "UPDATE projects SET name=?, updated_at=datetime('now') WHERE id=?",
        (name, project_id),
    )
    conn.commit()


def delete_project_documents(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE project_id=?", (project_id,))
    conn.commit()


def list_projects(conn: sqlite3.Connection) -> list[ProjectRow]:
    rows = conn.execute("SELECT id, name, root_path, rules_json FROM projects ORDER BY id").fetchall()
    return [_row_to_project(r) for r in rows]


def upsert_document(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    stage: str | None,
    rel_path: str,
    ext: str,
    sha256: str,
    mtime: float,
    status: str,
    parse_error: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO documents(project_id, stage, path, ext, sha256, mtime, status, parse_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, path) DO UPDATE SET
          stage=excluded.stage,
          ext=excluded.ext,
          sha256=excluded.sha256,
          mtime=excluded.mtime,
          status=excluded.status,
          parse_error=excluded.parse_error,
          updated_at=datetime('now')
        """,
        (project_id, stage, rel_path, ext, sha256, mtime, status, parse_error),
    )
    row = conn.execute(
        "SELECT id FROM documents WHERE project_id=? AND path=?",
        (project_id, rel_path),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def list_documents(conn: sqlite3.Connection, project_id: int, stage: str | None = None) -> list[DocumentRow]:
    if stage is None:
        rows = conn.execute(
            """
            SELECT id, project_id, stage, path, ext, sha256, mtime, status, parse_error
            FROM documents
            WHERE project_id=?
            ORDER BY path
            """,
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, project_id, stage, path, ext, sha256, mtime, status, parse_error
            FROM documents
            WHERE project_id=? AND stage=?
            ORDER BY path
            """,
            (project_id, stage),
        ).fetchall()
    return [
        DocumentRow(
            id=int(r["id"]),
            project_id=int(r["project_id"]),
            stage=(str(r["stage"]) if r["stage"] is not None else None),
            path=str(r["path"]),
            ext=str(r["ext"]),
            sha256=(str(r["sha256"]) if r["sha256"] is not None else None),
            mtime=(float(r["mtime"]) if r["mtime"] is not None else None),
            status=str(r["status"]),
            parse_error=(str(r["parse_error"]) if r["parse_error"] is not None else None),
        )
        for r in rows
    ]


def clear_chunks_for_document(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))


def insert_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    chunks: Iterable[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
    for c in chunks:
        conn.execute(
            """
            INSERT INTO document_chunks(document_id, chunk_index, text, token_count, locator_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                document_id,
                int(c["chunk_index"]),
                str(c["text"]),
                int(c.get("token_count") or 0),
                json.dumps(c["locator"], ensure_ascii=False),
            ),
        )


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def list_chunk_entries(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sql = """
    SELECT d.path AS doc_path, c.chunk_index AS chunk_index, c.text AS text, c.locator_json AS locator_json
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.project_id=?
    ORDER BY d.path, c.chunk_index
    """
    params: list[object] = [project_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_loc = r["locator_json"]
        try:
            loc = json.loads(str(raw_loc)) if raw_loc else {}
        except json.JSONDecodeError:
            loc = {}
        if not isinstance(loc, dict):
            loc = {}
        out.append(
            {
                "doc_path": str(r["doc_path"]),
                "chunk_index": int(r["chunk_index"]),
                "text": str(r["text"]),
                "locator": loc,
            }
        )
    return out


def list_chunk_texts(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    limit: int | None = None,
) -> list[str]:
    return [e["text"] for e in list_chunk_entries(conn, project_id=project_id, limit=limit)]


def search_chunks(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    query: str,
    stage: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    q = query.strip()
    if not q:
        return []

    params: list[object] = [project_id, q.lower(), limit]
    stage_sql = ""
    if stage is not None:
        stage_sql = "AND d.stage=?"
        params = [project_id, stage, q.lower(), limit]

    sql = f"""
    SELECT
      d.path AS doc_path,
      d.stage AS doc_stage,
      c.chunk_index AS chunk_index,
      c.locator_json AS locator_json,
      c.text AS text
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.project_id = ?
      {stage_sql}
      AND instr(lower(c.text), ?) > 0
    ORDER BY d.path, c.chunk_index
    LIMIT ?
    """
    return list(conn.execute(sql, params).fetchall())


def create_analysis_job(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    job_type: str,
    scope_json: str,
    llm_config_json: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO analysis_jobs(project_id, job_type, scope_json, llm_config_json, status, progress)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, job_type, scope_json, llm_config_json, "queued", 0),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_analysis_job_status(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    status: str,
    progress: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    sets: list[str] = ["status=?", "updated_at=datetime('now')"]
    params: list[object] = [status]
    if progress is not None:
        sets.append("progress=?")
        params.append(int(progress))
    if error_code is not None:
        sets.append("error_code=?")
        params.append(error_code)
    if error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    if started:
        sets.append("started_at=datetime('now')")
    if finished:
        sets.append("finished_at=datetime('now')")
    params.append(job_id)
    conn.execute(f"UPDATE analysis_jobs SET {', '.join(sets)} WHERE id=?", params)


def get_analysis_job(conn: sqlite3.Connection, job_id: int) -> AnalysisJobRow | None:
    r = conn.execute(
        """
        SELECT id, project_id, job_type, status, progress, error_code, error_message
        FROM analysis_jobs
        WHERE id=?
        """,
        (job_id,),
    ).fetchone()
    if r is None:
        return None
    return AnalysisJobRow(
        id=int(r["id"]),
        project_id=int(r["project_id"]),
        job_type=str(r["job_type"]),
        status=str(r["status"]),
        progress=int(r["progress"]),
        error_code=(str(r["error_code"]) if r["error_code"] is not None else None),
        error_message=(str(r["error_message"]) if r["error_message"] is not None else None),
    )


def list_annotations(conn: sqlite3.Connection, project_id: int, type_: str | None = None) -> list[AnnotationRow]:
    if type_ is None:
        rows = conn.execute(
            """
            SELECT id, project_id, chunk_id, type, content, source, confidence, is_verified
            FROM annotations
            WHERE project_id=?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, project_id, chunk_id, type, content, source, confidence, is_verified
            FROM annotations
            WHERE project_id=? AND type=?
            ORDER BY id
            """,
            (project_id, type_),
        ).fetchall()
    return [
        AnnotationRow(
            id=int(r["id"]),
            project_id=int(r["project_id"]),
            chunk_id=int(r["chunk_id"]),
            type=str(r["type"]),
            content=str(r["content"]),
            source=str(r["source"]),
            confidence=(str(r["confidence"]) if r["confidence"] is not None else None),
            is_verified=bool(int(r["is_verified"])),
        )
        for r in rows
    ]


def insert_annotation(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    chunk_id: int,
    type_: str,
    content: str,
    source: str,
    confidence: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO annotations(project_id, chunk_id, type, content, source, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, chunk_id, type_, content, source, confidence),
    )
    return int(cur.lastrowid)


def list_annotations_with_evidence(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    type_: str | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    if type_ is None:
        rows = conn.execute(
            """
            SELECT
              a.id AS annotation_id,
              a.type AS annotation_type,
              a.content AS content,
              a.confidence AS confidence,
              a.is_verified AS is_verified,
              a.chunk_id AS chunk_id,
              d.path AS doc_path,
              d.stage AS doc_stage,
              c.chunk_index AS chunk_index,
              c.locator_json AS locator_json
            FROM annotations a
            JOIN document_chunks c ON c.id = a.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE a.project_id=?
            ORDER BY a.id
            LIMIT ?
            """,
            (project_id, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
              a.id AS annotation_id,
              a.type AS annotation_type,
              a.content AS content,
              a.confidence AS confidence,
              a.is_verified AS is_verified,
              a.chunk_id AS chunk_id,
              d.path AS doc_path,
              d.stage AS doc_stage,
              c.chunk_index AS chunk_index,
              c.locator_json AS locator_json
            FROM annotations a
            JOIN document_chunks c ON c.id = a.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE a.project_id=? AND a.type=?
            ORDER BY a.id
            LIMIT ?
            """,
            (project_id, type_, int(limit)),
        ).fetchall()
    return list(rows)


def get_app_setting_json(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(str(row["value_json"]))
    except json.JSONDecodeError:
        return None


def set_app_setting_json(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO app_settings(key, value_json, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
          value_json=excluded.value_json,
          updated_at=datetime('now')
        """,
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()

