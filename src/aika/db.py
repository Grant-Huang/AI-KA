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

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  analysis_type TEXT NOT NULL,
  title TEXT NOT NULL,
  preset_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_project_updated ON conversations(project_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  job_id INTEGER,
  focus_points_json TEXT NOT NULL,
  chunk_limit INTEGER NOT NULL,
  chunk_strategy TEXT NOT NULL,
  used_entries_json TEXT NOT NULL,
  output_markdown_path TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
  FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_conversation_created ON analysis_runs(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS conversation_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  final_filename TEXT NOT NULL,
  milestones_filename TEXT NOT NULL,
  fragments_index_filename TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conv_outputs_conversation_created ON conversation_outputs(conversation_id, created_at);

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

CREATE TABLE IF NOT EXISTS memory_file_embeddings (
  path         TEXT PRIMARY KEY,
  embedding    BLOB NOT NULL,
  content_hash TEXT NOT NULL,
  embed_model  TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  card_index INTEGER NOT NULL,
  card_type TEXT NOT NULL DEFAULT 'rule',
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  applicable_scope TEXT,
  exceptions TEXT,
  confidence TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'pending',
  source_turn INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cards_conversation ON knowledge_cards(conversation_id, card_index);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expert_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  industries_json TEXT NOT NULL DEFAULT '[]',
  production_modes_json TEXT NOT NULL DEFAULT '[]',
  functional_modules_json TEXT NOT NULL DEFAULT '[]',
  focus_areas_json TEXT NOT NULL DEFAULT '[]',
  profile_completed INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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


@dataclass(frozen=True)
class ConversationRow:
    id: int
    project_id: int
    analysis_type: str
    title: str
    created_at: str
    updated_at: str
    preset_id: str | None = None
    mode: str = "reviewing"
    state: str = "idle"


@dataclass(frozen=True)
class ConversationGlobalRow:
    id: int
    project_id: int
    project_name: str
    analysis_type: str
    title: str
    created_at: str
    updated_at: str
    preset_id: str | None = None


@dataclass(frozen=True)
class MessageRow:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str
    metadata_json: str | None = None


@dataclass(frozen=True)
class AnalysisRunRow:
    id: int
    conversation_id: int
    job_id: int | None
    focus_points_json: str
    chunk_limit: int
    chunk_strategy: str
    used_entries_json: str
    output_markdown_path: str
    run_metadata_json: str | None = None


@dataclass(frozen=True)
class ConversationOutputRow:
    id: int
    conversation_id: int
    kind: str
    final_filename: str
    milestones_filename: str
    fragments_index_filename: str | None
    created_at: str


@dataclass(frozen=True)
class KnowledgeCardRow:
    id: int
    conversation_id: int
    card_index: int
    card_type: str
    title: str
    content: str
    applicable_scope: str | None
    exceptions: str | None
    confidence: str
    status: str
    source_turn: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class UserRow:
    id: int
    username: str
    display_name: str
    password_hash: str


@dataclass(frozen=True)
class ExpertProfileRow:
    id: int
    user_id: int
    industries: list[str]
    production_modes: list[str]
    functional_modules: list[str]
    focus_areas: list[str]
    profile_completed: bool


def connect(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    _migrate_projects_web_columns(conn)
    _migrate_conversations_preset_id(conn)
    _migrate_analysis_runs_metadata(conn)
    _migrate_conversations_mode_state(conn)
    _migrate_messages_metadata(conn)
    _migrate_chunks_embedding(conn)
    _migrate_users_tables(conn)
    _migrate_knowledge_cards_table(conn)


def _table_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """PRAGMA table_info：用列名 `name` 取值，避免依赖结果列顺序。"""
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    out: set[str] = set()
    for r in rows:
        try:
            out.add(str(r["name"]))
        except (KeyError, IndexError, TypeError):
            out.add(str(r[1]))
    return out


def _migrate_projects_web_columns(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "projects")
    if "rules_json" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN rules_json TEXT")
        conn.commit()


def _migrate_conversations_preset_id(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "conversations")
    if "preset_id" not in cols:
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN preset_id TEXT")
            conn.commit()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            # 列已存在（检测与库状态不一致时仍可能触发）
            if "duplicate column" not in msg and "already exists" not in msg:
                raise
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_project_preset ON conversations(project_id, preset_id)"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass


def _migrate_analysis_runs_metadata(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "analysis_runs")
    if "run_metadata_json" not in cols:
        conn.execute("ALTER TABLE analysis_runs ADD COLUMN run_metadata_json TEXT")
        conn.commit()


def _migrate_conversations_mode_state(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "conversations")
    if "mode" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'reviewing'")
        conn.commit()
    if "state" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN state TEXT NOT NULL DEFAULT 'idle'")
        conn.commit()


def _migrate_messages_metadata(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "messages")
    if "metadata_json" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT")
        conn.commit()


def _migrate_chunks_embedding(conn: sqlite3.Connection) -> None:
    cols = _table_column_names(conn, "document_chunks")
    if "embedding" not in cols:
        conn.execute("ALTER TABLE document_chunks ADD COLUMN embedding BLOB")
        conn.commit()
    if "embed_model" not in cols:
        conn.execute("ALTER TABLE document_chunks ADD COLUMN embed_model TEXT")
        conn.commit()


def _migrate_users_tables(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "users" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              display_name TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS expert_profiles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL UNIQUE,
              industries_json TEXT NOT NULL DEFAULT '[]',
              production_modes_json TEXT NOT NULL DEFAULT '[]',
              functional_modules_json TEXT NOT NULL DEFAULT '[]',
              focus_areas_json TEXT NOT NULL DEFAULT '[]',
              profile_completed INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              expires_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
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


def delete_project(conn: sqlite3.Connection, *, project_id: int) -> bool:
    """
    Delete project row. Related rows are deleted by FK ON DELETE CASCADE:
    - documents -> document_chunks
    - conversations -> messages / analysis_runs / conversation_outputs
    - analysis_jobs / annotations
    """
    cur = conn.execute("DELETE FROM projects WHERE id=?", (int(project_id),))
    conn.commit()
    return bool(cur.rowcount and cur.rowcount > 0)


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


def count_project_chunks(conn: sqlite3.Connection, *, project_id: int) -> int:
    r = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.project_id=?
        """,
        (int(project_id),),
    ).fetchone()
    if r is None:
        return 0
    try:
        return int(r["n"])
    except Exception:
        return int(r[0] or 0)


def count_project_analysis_runs(conn: sqlite3.Connection, *, project_id: int) -> int:
    """
    Count analysis run records under a project.

    We treat existence of analysis_runs as "审查记录" for deletion protection.
    """
    r = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM analysis_runs ar
        JOIN conversations c ON c.id = ar.conversation_id
        WHERE c.project_id=?
        """,
        (int(project_id),),
    ).fetchone()
    if r is None:
        return 0
    try:
        return int(r["n"])
    except Exception:
        return int(r[0] or 0)


def count_project_completed_outputs(conn: sqlite3.Connection, *, project_id: int) -> int:
    """
    Count completed output records under a project.

    We treat existence of conversation_outputs as \"已完成审查记录\" for deletion protection.
    Aborted runs that did not finish should not create conversation_outputs rows.
    """
    r = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM conversation_outputs co
        JOIN conversations c ON c.id = co.conversation_id
        WHERE c.project_id=?
        """,
        (int(project_id),),
    ).fetchone()
    if r is None:
        return 0
    try:
        return int(r["n"])
    except Exception:
        return int(r[0] or 0)


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


def create_conversation(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    analysis_type: str,
    title: str,
    preset_id: str | None = None,
    mode: str = "reviewing",
) -> ConversationRow:
    pid = str(preset_id).strip() if preset_id is not None else None
    cur = conn.execute(
        """
        INSERT INTO conversations(project_id, analysis_type, title, preset_id, mode, state)
        VALUES (?, ?, ?, ?, ?, 'idle')
        """,
        (project_id, str(analysis_type), str(title), pid, str(mode)),
    )
    conn.commit()
    cid = int(cur.lastrowid)
    r = conn.execute(
        "SELECT id, project_id, analysis_type, title, created_at, updated_at, preset_id, mode, state FROM conversations WHERE id=?",
        (cid,),
    ).fetchone()
    assert r is not None
    return _row_to_conversation(r)


def update_conversation_state(
    conn: sqlite3.Connection,
    *,
    conversation_id: int,
    state: str,
    mode: str | None = None,
) -> None:
    if mode is not None:
        conn.execute(
            "UPDATE conversations SET state=?, mode=?, updated_at=datetime('now') WHERE id=?",
            (str(state), str(mode), int(conversation_id)),
        )
    else:
        conn.execute(
            "UPDATE conversations SET state=?, updated_at=datetime('now') WHERE id=?",
            (str(state), int(conversation_id)),
        )
    conn.commit()


def _row_to_conversation(r: sqlite3.Row) -> ConversationRow:
    keys = r.keys()
    pj = r["preset_id"] if "preset_id" in keys else None
    preset_out: str | None = None
    if pj is not None and str(pj).strip():
        preset_out = str(pj).strip()
    mode_val = str(r["mode"]) if "mode" in keys and r["mode"] is not None else "reviewing"
    state_val = str(r["state"]) if "state" in keys and r["state"] is not None else "idle"
    return ConversationRow(
        id=int(r["id"]),
        project_id=int(r["project_id"]),
        analysis_type=str(r["analysis_type"]),
        title=str(r["title"]),
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
        preset_id=preset_out,
        mode=mode_val,
        state=state_val,
    )


def list_conversations(conn: sqlite3.Connection, *, project_id: int, limit: int = 50) -> list[ConversationRow]:
    rows = conn.execute(
        """
        SELECT id, project_id, analysis_type, title, created_at, updated_at, preset_id
        FROM conversations
        WHERE project_id=?
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, int(limit)),
    ).fetchall()
    return [_row_to_conversation(r) for r in rows]


def list_conversations_global(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> list[ConversationGlobalRow]:
    lim = max(1, min(200, int(limit)))
    off = max(0, int(offset))
    query = (q or "").strip().lower()
    sql = """
    SELECT c.id, c.project_id, c.analysis_type, c.title, c.created_at, c.updated_at, c.preset_id,
           p.name AS project_name
    FROM conversations c
    JOIN projects p ON p.id = c.project_id
    """
    params: list[object] = []
    if query:
        sql += " WHERE lower(c.title) LIKE ? OR lower(p.name) LIKE ? "
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ? "
    params.extend([lim, off])
    rows = conn.execute(sql, params).fetchall()
    out: list[ConversationGlobalRow] = []
    for r in rows:
        pj = r["preset_id"] if "preset_id" in r.keys() else None
        preset_out: str | None = None
        if pj is not None and str(pj).strip():
            preset_out = str(pj).strip()
        out.append(
            ConversationGlobalRow(
                id=int(r["id"]),
                project_id=int(r["project_id"]),
                project_name=str(r["project_name"]),
                analysis_type=str(r["analysis_type"]),
                title=str(r["title"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                preset_id=preset_out,
            )
        )
    return out


def list_conversations_by_pair(
    conn: sqlite3.Connection, *, project_id: int, preset_id: str
) -> list[ConversationRow]:
    pid = str(preset_id).strip()
    if not pid:
        return []
    rows = conn.execute(
        """
        SELECT id, project_id, analysis_type, title, created_at, updated_at, preset_id
        FROM conversations
        WHERE project_id=? AND preset_id=?
        ORDER BY updated_at DESC, id DESC
        """,
        (int(project_id), pid),
    ).fetchall()
    return [_row_to_conversation(r) for r in rows]


def get_conversation(conn: sqlite3.Connection, conversation_id: int) -> ConversationRow | None:
    r = conn.execute(
        """
        SELECT id, project_id, analysis_type, title, created_at, updated_at, preset_id
        FROM conversations
        WHERE id=?
        """,
        (conversation_id,),
    ).fetchone()
    if r is None:
        return None
    return _row_to_conversation(r)


def delete_conversation(conn: sqlite3.Connection, *, conversation_id: int) -> bool:
    """
    Delete a conversation by id.

    Note: related rows (messages/analysis_runs/conversation_outputs) are deleted by FK ON DELETE CASCADE.
    Output files on disk are not removed here.
    """
    cur = conn.execute("DELETE FROM conversations WHERE id=?", (int(conversation_id),))
    conn.commit()
    return bool(cur.rowcount and int(cur.rowcount) > 0)


def find_latest_conversation_with_analysis_for_preset(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    preset_id: str,
) -> ConversationRow | None:
    """同项目且 preset_id 一致、且至少有一条 analysis_runs 的会话中，按 updated_at 最近的一条。"""
    pid = str(preset_id).strip()
    if not pid:
        return None
    r = conn.execute(
        """
        SELECT c.id, c.project_id, c.analysis_type, c.title, c.created_at, c.updated_at, c.preset_id
        FROM conversations c
        WHERE c.project_id = ? AND c.preset_id = ?
        AND EXISTS (SELECT 1 FROM analysis_runs ar WHERE ar.conversation_id = c.id)
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT 1
        """,
        (int(project_id), pid),
    ).fetchone()
    if r is None:
        return None
    return _row_to_conversation(r)


def insert_message(
    conn: sqlite3.Connection,
    *,
    conversation_id: int,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> MessageRow:
    meta_s = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
    cur = conn.execute(
        """
        INSERT INTO messages(conversation_id, role, content, metadata_json)
        VALUES (?, ?, ?, ?)
        """,
        (conversation_id, str(role), str(content), meta_s),
    )
    conn.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?", (conversation_id,))
    conn.commit()
    mid = int(cur.lastrowid)
    r = conn.execute(
        "SELECT id, conversation_id, role, content, created_at, metadata_json FROM messages WHERE id=?",
        (mid,),
    ).fetchone()
    if r is None:
        return MessageRow(
            id=mid,
            conversation_id=conversation_id,
            role=str(role),
            content=str(content),
            created_at="",
            metadata_json=meta_s,
        )
    return _row_to_message(r)


def update_message_metadata(
    conn: sqlite3.Connection,
    *,
    message_id: int,
    metadata: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE messages SET metadata_json=? WHERE id=?",
        (json.dumps(metadata, ensure_ascii=False), int(message_id)),
    )
    conn.commit()


def _row_to_message(r: sqlite3.Row) -> MessageRow:
    keys = r.keys()
    meta = r["metadata_json"] if "metadata_json" in keys else None
    return MessageRow(
        id=int(r["id"]),
        conversation_id=int(r["conversation_id"]),
        role=str(r["role"]),
        content=str(r["content"]),
        created_at=str(r["created_at"]),
        metadata_json=(str(meta) if meta is not None else None),
    )


def list_messages(conn: sqlite3.Connection, *, conversation_id: int, limit: int = 200) -> list[MessageRow]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, role, content, created_at, metadata_json
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (conversation_id, int(limit)),
    ).fetchall()
    return [_row_to_message(r) for r in rows]


def list_recent_messages(
    conn: sqlite3.Connection, *, conversation_id: int, limit: int = 24
) -> list[MessageRow]:
    """最近 N 条 user/assistant 消息（按 id 时间正序）。用于多轮对话上下文。"""
    lim = max(1, int(limit))
    rows = conn.execute(
        """
        SELECT id, conversation_id, role, content, created_at, metadata_json
        FROM messages
        WHERE conversation_id=? AND role IN ('user', 'assistant')
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, lim),
    ).fetchall()
    ordered = list(reversed(rows))
    return [_row_to_message(r) for r in ordered]


def insert_analysis_run(
    conn: sqlite3.Connection,
    *,
    conversation_id: int,
    job_id: int | None,
    focus_points: list[str],
    chunk_limit: int,
    chunk_strategy: str,
    used_entries: list[dict[str, Any]],
    output_markdown_path: str,
    run_metadata: dict[str, Any] | None = None,
) -> AnalysisRunRow:
    meta_s: str | None
    if run_metadata is None:
        meta_s = None
    else:
        meta_s = json.dumps(run_metadata, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO analysis_runs(
          conversation_id, job_id, focus_points_json, chunk_limit, chunk_strategy,
          used_entries_json, output_markdown_path, run_metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            (int(job_id) if job_id is not None else None),
            json.dumps(list(focus_points), ensure_ascii=False),
            int(chunk_limit),
            str(chunk_strategy),
            json.dumps(list(used_entries), ensure_ascii=False),
            str(output_markdown_path),
            meta_s,
        ),
    )
    conn.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?", (conversation_id,))
    conn.commit()
    rid = int(cur.lastrowid)
    return AnalysisRunRow(
        id=rid,
        conversation_id=conversation_id,
        job_id=job_id,
        focus_points_json=json.dumps(list(focus_points), ensure_ascii=False),
        chunk_limit=int(chunk_limit),
        chunk_strategy=str(chunk_strategy),
        used_entries_json=json.dumps(list(used_entries), ensure_ascii=False),
        output_markdown_path=str(output_markdown_path),
        run_metadata_json=meta_s,
    )


def get_latest_analysis_run(conn: sqlite3.Connection, *, conversation_id: int) -> AnalysisRunRow | None:
    r = conn.execute(
        """
        SELECT id, conversation_id, job_id, focus_points_json, chunk_limit, chunk_strategy,
               used_entries_json, output_markdown_path, run_metadata_json
        FROM analysis_runs
        WHERE conversation_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    if r is None:
        return None
    rm = r["run_metadata_json"] if "run_metadata_json" in r.keys() else None
    return AnalysisRunRow(
        id=int(r["id"]),
        conversation_id=int(r["conversation_id"]),
        job_id=(int(r["job_id"]) if r["job_id"] is not None else None),
        focus_points_json=str(r["focus_points_json"]),
        chunk_limit=int(r["chunk_limit"]),
        chunk_strategy=str(r["chunk_strategy"]),
        used_entries_json=str(r["used_entries_json"]),
        output_markdown_path=str(r["output_markdown_path"]),
        run_metadata_json=(str(rm) if rm is not None else None),
    )


def insert_conversation_output(
    conn: sqlite3.Connection,
    *,
    conversation_id: int,
    kind: str,
    final_filename: str,
    milestones_filename: str,
    fragments_index_filename: str | None = None,
) -> ConversationOutputRow:
    cur = conn.execute(
        """
        INSERT INTO conversation_outputs(
          conversation_id, kind, final_filename, milestones_filename, fragments_index_filename
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(conversation_id),
            str(kind),
            str(final_filename),
            str(milestones_filename),
            (str(fragments_index_filename) if fragments_index_filename is not None else None),
        ),
    )
    conn.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?", (conversation_id,))
    conn.commit()
    rid = int(cur.lastrowid)
    r = conn.execute(
        """
        SELECT id, conversation_id, kind, final_filename, milestones_filename, fragments_index_filename, created_at
        FROM conversation_outputs
        WHERE id=?
        """,
        (rid,),
    ).fetchone()
    assert r is not None
    return ConversationOutputRow(
        id=int(r["id"]),
        conversation_id=int(r["conversation_id"]),
        kind=str(r["kind"]),
        final_filename=str(r["final_filename"]),
        milestones_filename=str(r["milestones_filename"]),
        fragments_index_filename=(
            str(r["fragments_index_filename"]) if r["fragments_index_filename"] is not None else None
        ),
        created_at=str(r["created_at"]),
    )


def list_conversation_outputs(
    conn: sqlite3.Connection, *, conversation_id: int, limit: int = 50
) -> list[ConversationOutputRow]:
    lim = max(1, min(200, int(limit)))
    rows = conn.execute(
        """
        SELECT id, conversation_id, kind, final_filename, milestones_filename, fragments_index_filename, created_at
        FROM conversation_outputs
        WHERE conversation_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(conversation_id), lim),
    ).fetchall()
    return [
        ConversationOutputRow(
            id=int(r["id"]),
            conversation_id=int(r["conversation_id"]),
            kind=str(r["kind"]),
            final_filename=str(r["final_filename"]),
            milestones_filename=str(r["milestones_filename"]),
            fragments_index_filename=(
                str(r["fragments_index_filename"]) if r["fragments_index_filename"] is not None else None
            ),
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


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


def upsert_memory_embedding(
    conn: sqlite3.Connection,
    *,
    path: str,
    embedding_bytes: bytes,
    content_hash: str,
    embed_model: str,
) -> None:
    from datetime import datetime as _dt
    conn.execute(
        """
        INSERT INTO memory_file_embeddings(path, embedding, content_hash, embed_model, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          embedding=excluded.embedding,
          content_hash=excluded.content_hash,
          embed_model=excluded.embed_model,
          updated_at=excluded.updated_at
        """,
        (str(path), embedding_bytes, str(content_hash), str(embed_model), _dt.utcnow().isoformat()),
    )
    conn.commit()


def get_memory_embedding(
    conn: sqlite3.Connection,
    *,
    path: str,
    content_hash: str,
) -> bytes | None:
    """Returns embedding bytes if stored hash matches, else None (stale or missing)."""
    r = conn.execute(
        "SELECT embedding, content_hash FROM memory_file_embeddings WHERE path=?",
        (str(path),),
    ).fetchone()
    if r is None:
        return None
    if str(r["content_hash"]) != str(content_hash):
        return None
    return bytes(r["embedding"])


def list_all_memory_embeddings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT path, embedding, content_hash, embed_model FROM memory_file_embeddings"
    ).fetchall()
    return [
        {
            "path": str(r["path"]),
            "embedding": bytes(r["embedding"]),
            "content_hash": str(r["content_hash"]),
            "embed_model": str(r["embed_model"]),
        }
        for r in rows
    ]


def update_chunk_embedding(
    conn: sqlite3.Connection,
    *,
    chunk_id: int,
    embedding_bytes: bytes,
    embed_model: str,
) -> None:
    conn.execute(
        "UPDATE document_chunks SET embedding=?, embed_model=? WHERE id=?",
        (embedding_bytes, str(embed_model), int(chunk_id)),
    )


def get_chunk_embeddings_for_project(
    conn: sqlite3.Connection,
    *,
    project_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id AS chunk_id, c.embedding AS embedding, c.embed_model AS embed_model,
               c.text AS text, d.path AS doc_path, c.chunk_index AS chunk_index,
               c.locator_json AS locator_json
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.project_id=? AND c.embedding IS NOT NULL
        ORDER BY d.path, c.chunk_index
        """,
        (int(project_id),),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            loc = json.loads(str(r["locator_json"])) if r["locator_json"] else {}
        except json.JSONDecodeError:
            loc = {}
        out.append(
            {
                "chunk_id": int(r["chunk_id"]),
                "embedding": bytes(r["embedding"]),
                "embed_model": str(r["embed_model"]) if r["embed_model"] else "",
                "text": str(r["text"]),
                "doc_path": str(r["doc_path"]),
                "chunk_index": int(r["chunk_index"]),
                "locator": loc,
            }
        )
    return out


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


def open_db(db_file: Path) -> sqlite3.Connection:
    return connect(db_file)


# ── User & Auth ──────────────────────────────────────────────

def create_user(conn, *, username: str, display_name: str, password_hash: str) -> UserRow:
    cur = conn.execute(
        "INSERT INTO users(username, display_name, password_hash) VALUES (?,?,?)",
        (username, display_name, password_hash),
    )
    conn.commit()
    return get_user_by_id(conn, int(cur.lastrowid))

def get_user_by_id(conn, user_id: int) -> UserRow | None:
    r = conn.execute("SELECT id,username,display_name,password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    if r is None: return None
    return UserRow(id=int(r["id"]), username=str(r["username"]), display_name=str(r["display_name"]), password_hash=str(r["password_hash"]))

def get_user_by_username(conn, username: str) -> UserRow | None:
    r = conn.execute("SELECT id,username,display_name,password_hash FROM users WHERE username=?", (username,)).fetchone()
    if r is None: return None
    return UserRow(id=int(r["id"]), username=str(r["username"]), display_name=str(r["display_name"]), password_hash=str(r["password_hash"]))

def create_auth_session(conn, *, user_id: int, token: str, expires_at: str) -> None:
    conn.execute("INSERT INTO auth_sessions(token,user_id,expires_at) VALUES (?,?,?)", (token, user_id, expires_at))
    conn.commit()

def get_session_user_id(conn, token: str) -> int | None:
    r = conn.execute(
        "SELECT user_id FROM auth_sessions WHERE token=? AND expires_at > datetime('now')",
        (token,)
    ).fetchone()
    return int(r["user_id"]) if r else None

def delete_auth_session(conn, token: str) -> None:
    conn.execute("DELETE FROM auth_sessions WHERE token=?", (token,))
    conn.commit()


# ── Expert Profile ────────────────────────────────────────────

def get_expert_profile(conn, user_id: int) -> ExpertProfileRow | None:
    r = conn.execute("SELECT * FROM expert_profiles WHERE user_id=?", (user_id,)).fetchone()
    if r is None: return None
    return ExpertProfileRow(
        id=int(r["id"]), user_id=int(r["user_id"]),
        industries=json.loads(r["industries_json"] or "[]"),
        production_modes=json.loads(r["production_modes_json"] or "[]"),
        functional_modules=json.loads(r["functional_modules_json"] or "[]"),
        focus_areas=json.loads(r["focus_areas_json"] or "[]"),
        profile_completed=bool(r["profile_completed"]),
    )

def upsert_expert_profile(conn, *, user_id: int, industries: list, production_modes: list, functional_modules: list, focus_areas: list, profile_completed: bool = True) -> ExpertProfileRow:
    from datetime import datetime as _dt
    conn.execute("""
        INSERT INTO expert_profiles(user_id,industries_json,production_modes_json,functional_modules_json,focus_areas_json,profile_completed,updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
          industries_json=excluded.industries_json,
          production_modes_json=excluded.production_modes_json,
          functional_modules_json=excluded.functional_modules_json,
          focus_areas_json=excluded.focus_areas_json,
          profile_completed=excluded.profile_completed,
          updated_at=excluded.updated_at
    """, (user_id, json.dumps(industries, ensure_ascii=False), json.dumps(production_modes, ensure_ascii=False),
          json.dumps(functional_modules, ensure_ascii=False), json.dumps(focus_areas, ensure_ascii=False),
          int(profile_completed), _dt.utcnow().isoformat()))
    conn.commit()
    return get_expert_profile(conn, user_id)


# ── Knowledge Cards ───────────────────────────────────────────

def _migrate_knowledge_cards_table(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "knowledge_cards" not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_cards (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id INTEGER NOT NULL,
              card_index INTEGER NOT NULL,
              card_type TEXT NOT NULL DEFAULT 'rule',
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              applicable_scope TEXT,
              exceptions TEXT,
              confidence TEXT NOT NULL DEFAULT 'medium',
              status TEXT NOT NULL DEFAULT 'pending',
              source_turn INTEGER,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_cards_conversation ON knowledge_cards(conversation_id, card_index);
        """)
        conn.commit()


def _row_to_knowledge_card(r: sqlite3.Row) -> KnowledgeCardRow:
    return KnowledgeCardRow(
        id=int(r["id"]),
        conversation_id=int(r["conversation_id"]),
        card_index=int(r["card_index"]),
        card_type=str(r["card_type"]),
        title=str(r["title"]),
        content=str(r["content"]),
        applicable_scope=r["applicable_scope"],
        exceptions=r["exceptions"],
        confidence=str(r["confidence"]),
        status=str(r["status"]),
        source_turn=int(r["source_turn"]) if r["source_turn"] is not None else None,
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
    )


def insert_knowledge_card(
    conn: sqlite3.Connection,
    *,
    conversation_id: int,
    card_index: int,
    card_type: str,
    title: str,
    content: str,
    applicable_scope: str | None = None,
    exceptions: str | None = None,
    confidence: str = "medium",
    status: str = "pending",
    source_turn: int | None = None,
) -> KnowledgeCardRow:
    cur = conn.execute(
        """
        INSERT INTO knowledge_cards
          (conversation_id, card_index, card_type, title, content,
           applicable_scope, exceptions, confidence, status, source_turn)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (conversation_id, card_index, card_type, title, content,
         applicable_scope, exceptions, confidence, status, source_turn),
    )
    conn.commit()
    r = conn.execute("SELECT * FROM knowledge_cards WHERE id=?", (int(cur.lastrowid),)).fetchone()
    return _row_to_knowledge_card(r)


def list_knowledge_cards(conn: sqlite3.Connection, conversation_id: int) -> list[KnowledgeCardRow]:
    rows = conn.execute(
        "SELECT * FROM knowledge_cards WHERE conversation_id=? ORDER BY card_index",
        (conversation_id,),
    ).fetchall()
    return [_row_to_knowledge_card(r) for r in rows]


def get_knowledge_card(conn: sqlite3.Connection, card_id: int) -> KnowledgeCardRow | None:
    r = conn.execute("SELECT * FROM knowledge_cards WHERE id=?", (card_id,)).fetchone()
    return _row_to_knowledge_card(r) if r else None


def update_knowledge_card_status(conn: sqlite3.Connection, card_id: int, status: str) -> KnowledgeCardRow | None:
    conn.execute(
        "UPDATE knowledge_cards SET status=?, updated_at=datetime('now') WHERE id=?",
        (status, card_id),
    )
    conn.commit()
    return get_knowledge_card(conn, card_id)


def update_knowledge_card_content(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    card_type: str | None = None,
    title: str | None = None,
    content: str | None = None,
    applicable_scope: str | None = None,
    exceptions: str | None = None,
    confidence: str | None = None,
    status: str | None = None,
) -> KnowledgeCardRow | None:
    card = get_knowledge_card(conn, card_id)
    if card is None:
        return None
    conn.execute(
        """
        UPDATE knowledge_cards SET
          card_type=?, title=?, content=?,
          applicable_scope=?, exceptions=?, confidence=?, status=?,
          updated_at=datetime('now')
        WHERE id=?
        """,
        (
            card_type if card_type is not None else card.card_type,
            title if title is not None else card.title,
            content if content is not None else card.content,
            applicable_scope if applicable_scope is not None else card.applicable_scope,
            exceptions if exceptions is not None else card.exceptions,
            confidence if confidence is not None else card.confidence,
            status if status is not None else card.status,
            card_id,
        ),
    )
    conn.commit()
    return get_knowledge_card(conn, card_id)

