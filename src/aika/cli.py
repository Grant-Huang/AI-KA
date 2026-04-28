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


def _skill_packages_root() -> Path:
    import os
    raw = (os.environ.get("AIKA_REVIEW_SKILL_PACKAGES_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_repo_root() / "review_skill_packages").resolve()


def cmd_skill_evolve(args: argparse.Namespace) -> int:
    import sys
    pkg_root = _skill_packages_root() / str(args.package)
    fp_path = pkg_root / "focus-points" / f"focus-{args.focus_id}.md"
    if not fp_path.is_file():
        print(f"[error] focus point file not found: {fp_path}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))
    from backend.skills.focus_point_io import evolve_focus_point, load_focus_point

    fp = load_focus_point(fp_path)
    if fp is None:
        print(f"[error] could not parse {fp_path}", file=sys.stderr)
        return 2

    if args.prompt_file:
        new_prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        print(f"Enter new prompt for focus:{fp.id} (end with Ctrl-D / EOF):")
        new_prompt = sys.stdin.read()

    new_fp = evolve_focus_point(
        fp,
        new_prompt=new_prompt,
        note=args.note or "",
        package_dir=pkg_root,
        repo_root=_repo_root(),
    )
    print(f"[ok] focus:{new_fp.id} evolved to v{new_fp.version}")
    return 0


def cmd_skill_list(args: argparse.Namespace) -> int:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))
    from backend.skills.focus_point_io import list_focus_points

    pkg_root = _skill_packages_root() / str(args.package)
    fps = list_focus_points(pkg_root)
    if not fps:
        print("(no focus-points/*.md files — package may be v1 format)")
        return 0
    for fp in fps:
        print(f"  focus:{fp.id}\tv{fp.version}\t{fp.name}")
    return 0


def cmd_skill_migrate(args: argparse.Namespace) -> int:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))
    from backend.skills.focus_point_io import migrate_from_review_domain

    pkg_root = _skill_packages_root() / str(args.package)
    domain_f = pkg_root / "review_domain.md"
    if not domain_f.is_file():
        print(f"[error] review_domain.md not found: {domain_f}", file=sys.stderr)
        return 2
    text = domain_f.read_text(encoding="utf-8", errors="replace")
    created = migrate_from_review_domain(text, pkg_root, overwrite=bool(args.overwrite))
    if created:
        print(f"[ok] created {len(created)} focus-point files: {', '.join(created)}")
    else:
        print("[ok] no new files created (all exist; use --overwrite to force)")
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

    skill = sp.add_parser("skill")
    skill_sp = skill.add_subparsers(dest="subcmd", required=True)

    skill_evolve = skill_sp.add_parser("evolve", help="Evolve a focus point by bumping version and writing new prompt")
    skill_evolve.add_argument("focus_id", help="Focus point id (e.g. req)")
    skill_evolve.add_argument("--package", required=False, default="package-general", help="Skill package id")
    skill_evolve.add_argument("--note", required=False, default="", help="Change note")
    skill_evolve.add_argument("--prompt-file", required=False, default=None, help="Read new prompt from file (default: stdin)")
    skill_evolve.set_defaults(func=cmd_skill_evolve)

    skill_list = skill_sp.add_parser("list", help="List focus points in a package")
    skill_list.add_argument("--package", required=False, default="package-general")
    skill_list.set_defaults(func=cmd_skill_list)

    skill_migrate = skill_sp.add_parser("migrate", help="Migrate review_domain.md to focus-points/*.md")
    skill_migrate.add_argument("--package", required=False, default="package-general")
    skill_migrate.add_argument("--overwrite", action="store_true", help="Overwrite existing focus-*.md files")
    skill_migrate.set_defaults(func=cmd_skill_migrate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

