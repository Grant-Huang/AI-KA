from __future__ import annotations

from pathlib import Path

import pytest

from aika import db as dbm
from aika.analyze import AnalyzeScope, run_extract_annotations
from aika.epic_doc import build_generate_command
from aika.indexer import compute_sha256, sync_project
from aika.llm import LLMConfig


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


def test_compute_sha256_is_stable(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    write_text(f, "hello\nworld\n")
    a = compute_sha256(f)
    b = compute_sha256(f)
    assert a == b


def test_sync_creates_documents_and_chunks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_file = repo_root / ".tmp" / "aika" / "aika.sqlite3"

    proj_root = tmp_path / "proj"
    write_text(proj_root / "01_调研" / "a.md", "# t\n\np1\n\np2\n")
    write_text(proj_root / "02_蓝图" / "b.txt", "x\n\ny\n")

    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "demo", proj_root.as_posix())

    updated = sync_project(conn, project=prj)
    assert updated == 2

    docs = dbm.list_documents(conn, prj.id)
    assert len(docs) == 2
    assert {d.stage for d in docs} == {"调研", "蓝图"}
    assert all(d.status == "chunked" for d in docs)

    chunk_count = conn.execute("SELECT COUNT(1) AS c FROM document_chunks").fetchone()["c"]
    assert int(chunk_count) >= 2


def test_sync_is_idempotent_for_same_content(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_file = repo_root / ".tmp" / "aika" / "aika.sqlite3"

    proj_root = tmp_path / "proj"
    write_text(proj_root / "docs" / "a.md", "p1\n\np2\n")

    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "demo", proj_root.as_posix())

    sync_project(conn, project=prj)
    chunks1 = conn.execute("SELECT COUNT(1) AS c FROM document_chunks").fetchone()["c"]

    sync_project(conn, project=prj)
    chunks2 = conn.execute("SELECT COUNT(1) AS c FROM document_chunks").fetchone()["c"]

    assert int(chunks1) == int(chunks2)


def test_search_chunks_returns_locator_and_doc_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_file = repo_root / ".tmp" / "aika" / "aika.sqlite3"

    proj_root = tmp_path / "proj"
    write_text(proj_root / "01_调研" / "a.md", "alpha\n\nbravo target\n\ncharlie\n")

    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "demo", proj_root.as_posix())
    sync_project(conn, project=prj)

    rows = dbm.search_chunks(conn, project_id=prj.id, query="TARGET")
    assert len(rows) >= 1
    r0 = rows[0]
    assert "a.md" in str(r0["doc_path"])
    assert int(r0["chunk_index"]) >= 0
    assert "locator_json" in r0.keys()


def test_epic_doc_command_builder(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.json"
    out = tmp_path / "out.docx"
    cmd = build_generate_command(config_path=cfg, output_path=out)
    assert cmd[:2] == ["epic-doc", "generate"]
    assert str(cfg) in cmd
    assert str(out) in cmd


def test_analyze_run_extract_annotations_with_mock_provider(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_file = repo_root / ".tmp" / "aika" / "aika.sqlite3"

    proj_root = tmp_path / "proj"
    # 让 mock provider 产出 requirement/risk
    write_text(proj_root / "01_调研" / "a.md", "这里有需求\n\n这里也有风险\n")

    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "demo", proj_root.as_posix())
    sync_project(conn, project=prj)

    inserted = run_extract_annotations(
        conn,
        project=prj,
        scope=AnalyzeScope(stage="调研", limit_chunks=10),
        llm_cfg=LLMConfig(provider="mock"),
    )
    assert inserted >= 1

    anns = dbm.list_annotations(conn, prj.id)
    assert len(anns) == inserted
    assert {a.type for a in anns}.issubset({"requirement", "risk"})


def test_list_annotations_with_evidence_returns_doc_and_locator(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_file = repo_root / ".tmp" / "aika" / "aika.sqlite3"

    proj_root = tmp_path / "proj"
    write_text(proj_root / "01_调研" / "a.md", "这里有需求\n")

    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "demo", proj_root.as_posix())
    sync_project(conn, project=prj)

    run_extract_annotations(
        conn,
        project=prj,
        scope=AnalyzeScope(stage="调研", limit_chunks=10),
        llm_cfg=LLMConfig(provider="mock"),
    )

    rows = dbm.list_annotations_with_evidence(conn, project_id=prj.id, limit=50)
    assert len(rows) >= 1
    r0 = rows[0]
    assert "doc_path" in r0.keys()
    assert "locator_json" in r0.keys()

