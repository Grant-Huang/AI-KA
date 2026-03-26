from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db as dbm
from . import analyze
from . import epic_doc
from . import indexer
from .paths import db_path
from .llm import LLMConfig


def _repo_root() -> Path:
    return Path.cwd().resolve()


def cmd_project_init(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)

    root = Path(args.root).resolve()
    prj = dbm.create_project(conn, args.name, root.as_posix())
    print(f"[ok] project created: name={prj.name} root={prj.root_path}")
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    items = dbm.list_projects(conn)
    if not items:
        print("(no projects)")
        return 0
    for p in items:
        print(f"- {p.name}\t{p.root_path}")
    return 0


def cmd_project_sync(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    prj = dbm.get_project_by_name(conn, args.project)
    if prj is None:
        print(f"[error] project not found: {args.project}", file=sys.stderr)
        return 2
    updated = indexer.sync_project(conn, project=prj)
    print(f"[ok] synced: {updated} documents")
    return 0


def cmd_doc_list(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    prj = dbm.get_project_by_name(conn, args.project)
    if prj is None:
        print(f"[error] project not found: {args.project}", file=sys.stderr)
        return 2
    docs = dbm.list_documents(conn, prj.id, stage=args.stage)
    if not docs:
        print("(no documents)")
        return 0
    for d in docs:
        stage = d.stage or "-"
        print(f"- {d.path}\t{stage}\t{d.status}\t{d.sha256 or '-'}")
    return 0


def cmd_doc_search(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    prj = dbm.get_project_by_name(conn, args.project)
    if prj is None:
        print(f"[error] project not found: {args.project}", file=sys.stderr)
        return 2

    rows = dbm.search_chunks(
        conn,
        project_id=prj.id,
        query=args.query,
        stage=args.stage,
        limit=int(args.limit),
    )
    if not rows:
        print("(no matches)")
        return 0

    for r in rows:
        loc = json.loads(r["locator_json"])
        snippet = str(r["text"]).replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        stage = r["doc_stage"] or "-"
        print(
            f"- {r['doc_path']}\t{stage}\tchunk#{int(r['chunk_index'])}"
            f"\tL{int(loc.get('start_line', 0))}-L{int(loc.get('end_line', 0))}\t{snippet}"
        )
    return 0


def cmd_report_render(args: argparse.Namespace) -> int:
    cfg = Path(args.config).resolve()
    out = Path(args.out).resolve()
    try:
        res = epic_doc.generate_docx(
            config_path=cfg,
            output_path=out,
            dry_run=bool(args.dry_run),
        )
    except epic_doc.EpicDocError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(" ".join(res.command))
        return 0

    print(f"[ok] saved: {res.output_path}")
    return 0


def cmd_analyze_run(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    prj = dbm.get_project_by_name(conn, args.project)
    if prj is None:
        print(f"[error] project not found: {args.project}", file=sys.stderr)
        return 2

    llm_cfg = LLMConfig(
        provider=str(args.provider),
        model=(str(args.model) if args.model else None),
        base_url=(str(args.base_url) if args.base_url else None),
        api_key=(str(args.api_key) if args.api_key else None),
        timeout_s=float(args.timeout_s),
    )
    scope = analyze.AnalyzeScope(
        stage=(str(args.stage) if args.stage else None),
        limit_chunks=(int(args.limit_chunks) if args.limit_chunks else None),
    )

    try:
        inserted = analyze.run_extract_annotations(conn, project=prj, scope=scope, llm_cfg=llm_cfg)
    except Exception as e:
        print(f"[error] analyze failed: {e}", file=sys.stderr)
        return 2

    print(f"[ok] inserted annotations: {inserted}")
    return 0


def cmd_annotation_list(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    conn = dbm.connect(db_path(repo_root))
    dbm.ensure_schema(conn)
    prj = dbm.get_project_by_name(conn, args.project)
    if prj is None:
        print(f"[error] project not found: {args.project}", file=sys.stderr)
        return 2

    rows = dbm.list_annotations_with_evidence(
        conn,
        project_id=prj.id,
        type_=args.type,
        limit=int(args.limit),
    )
    if not rows:
        print("(no annotations)")
        return 0
    for r in rows:
        loc = json.loads(r["locator_json"])
        conf = r["confidence"] or "-"
        v = "verified" if bool(int(r["is_verified"])) else "unverified"
        stage = r["doc_stage"] or "-"
        print(
            f"- #{int(r['annotation_id'])}\t{r['annotation_type']}\t{conf}\t{v}"
            f"\t{r['doc_path']}\t{stage}\tchunk#{int(r['chunk_index'])}"
            f"\tL{int(loc.get('start_line', 0))}-L{int(loc.get('end_line', 0))}\t{r['content']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aika")
    sp = p.add_subparsers(dest="cmd", required=True)

    prj = sp.add_parser("project")
    prj_sp = prj.add_subparsers(dest="subcmd", required=True)

    prj_init = prj_sp.add_parser("init")
    prj_init.add_argument("--name", required=True)
    prj_init.add_argument("--root", required=True)
    prj_init.set_defaults(func=cmd_project_init)

    prj_list = prj_sp.add_parser("list")
    prj_list.set_defaults(func=cmd_project_list)

    prj_sync = prj_sp.add_parser("sync")
    prj_sync.add_argument("--project", required=True)
    prj_sync.set_defaults(func=cmd_project_sync)

    doc = sp.add_parser("doc")
    doc_sp = doc.add_subparsers(dest="subcmd", required=True)

    doc_list = doc_sp.add_parser("list")
    doc_list.add_argument("--project", required=True)
    doc_list.add_argument("--stage", required=False, default=None)
    doc_list.set_defaults(func=cmd_doc_list)

    doc_search = doc_sp.add_parser("search")
    doc_search.add_argument("--project", required=True)
    doc_search.add_argument("--query", required=True)
    doc_search.add_argument("--stage", required=False, default=None)
    doc_search.add_argument("--limit", required=False, default=20)
    doc_search.set_defaults(func=cmd_doc_search)

    rpt = sp.add_parser("report")
    rpt_sp = rpt.add_subparsers(dest="subcmd", required=True)

    rpt_render = rpt_sp.add_parser("render")
    rpt_render.add_argument("--config", required=True, help="epic-doc config JSON path")
    rpt_render.add_argument("--out", required=True, help="output .docx path")
    rpt_render.add_argument("--dry-run", action="store_true", help="print command only")
    rpt_render.set_defaults(func=cmd_report_render)

    az = sp.add_parser("analyze")
    az_sp = az.add_subparsers(dest="subcmd", required=True)

    az_run = az_sp.add_parser("run")
    az_run.add_argument("--project", required=True)
    az_run.add_argument("--provider", required=True, help="mock | openai_compatible")
    az_run.add_argument("--model", required=False, default=None)
    az_run.add_argument("--base-url", required=False, default=None)
    az_run.add_argument("--api-key", required=False, default=None)
    az_run.add_argument("--timeout-s", required=False, default=60.0)
    az_run.add_argument("--stage", required=False, default=None)
    az_run.add_argument("--limit-chunks", required=False, default=None)
    az_run.set_defaults(func=cmd_analyze_run)

    ann = sp.add_parser("annotation")
    ann_sp = ann.add_subparsers(dest="subcmd", required=True)

    ann_list = ann_sp.add_parser("list")
    ann_list.add_argument("--project", required=True)
    ann_list.add_argument("--type", required=False, default=None)
    ann_list.add_argument("--limit", required=False, default=200)
    ann_list.set_defaults(func=cmd_annotation_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

