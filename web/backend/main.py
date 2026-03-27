from __future__ import annotations

import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from aika import db as dbm
from aika.epic_doc import EpicDocError, generate_docx
from aika.indexer import sync_project_md_root
from aika.llm import LLMConfig, LLMError, get_provider
from aika.paths import db_path

from backend.config import get_settings
from backend.docs2md_runner import Docs2MdError, run_convert_directory
from backend.folder_picker import FolderPickerError, pick_folder_native
from backend.epic_mapper import analysis_to_epic_doc_config, dump_epic_config_json
from backend.frontend_static import dev_dist_dir, packaged_dist_dir
from backend.path_validate import PathValidationError, validate_path_under_dir, validate_project_root
from backend.prompt_builder import build_system_prompt, build_user_prompt, merge_rules
from backend.repo_paths import project_export_dir, project_md_out_dir, repository_root
from backend.response import err, ok


def _conn():
    root = repository_root()
    conn = dbm.connect(db_path(root))
    dbm.ensure_schema(conn)
    return conn


app = FastAPI(title="AI-KA Web", version="0.1.0")
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_repo_root = repository_root()


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return ok({"ok": True})


def _client_is_localhost(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    ff = (request.headers.get("x-forwarded-for") or "").strip()
    if ff:
        first = ff.split(",")[0].strip()
        if first in ("127.0.0.1", "::1"):
            return True
    return False


@app.get("/api/v1/fs/capabilities")
def fs_capabilities(request: Request) -> JSONResponse:
    st = get_settings()
    local = _client_is_localhost(request)
    enabled = st.enable_native_folder_picker and (not st.fs_picker_localhost_only or local)
    return JSONResponse(
        ok(
            {
                "native_folder_picker": enabled,
                "localhost_only": st.fs_picker_localhost_only,
            }
        )
    )


@app.post("/api/v1/fs/pick-directory")
def pick_directory(request: Request) -> JSONResponse:
    st = get_settings()
    if not st.enable_native_folder_picker:
        return JSONResponse(err("native folder picker is disabled"), status_code=403)
    if st.fs_picker_localhost_only and not _client_is_localhost(request):
        return JSONResponse(
            err("folder picker is only available when accessing the API from localhost"),
            status_code=403,
        )
    try:
        chosen = pick_folder_native()
    except FolderPickerError as e:
        return JSONResponse(err(str(e)), status_code=503)
    if chosen is None:
        return JSONResponse(err("directory selection cancelled"), status_code=400)
    try:
        validated = validate_project_root(chosen)
    except PathValidationError as e:
        return JSONResponse(err(str(e)), status_code=400)
    return JSONResponse(ok({"path": validated.as_posix()}))


@app.post("/api/v1/projects")
def create_project(payload: dict[str, Any]) -> JSONResponse:
    name = str(payload.get("name") or "").strip()
    root_path = str(payload.get("root_path") or "").strip()
    if not name:
        return JSONResponse(err("name is required"), status_code=400)
    try:
        validated = validate_project_root(root_path)
    except PathValidationError as e:
        return JSONResponse(err(str(e)), status_code=400)
    conn = _conn()
    existing = dbm.get_project_by_name(conn, name)
    if existing:
        return JSONResponse(err("project name already exists"), status_code=409)
    try:
        prj = dbm.create_project(conn, name, validated.as_posix())
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return JSONResponse(err("project name already exists"), status_code=409)
        raise
    return JSONResponse(ok({"id": prj.id, "name": prj.name, "root_path": prj.root_path}))


@app.get("/api/v1/projects")
def list_projects() -> JSONResponse:
    conn = _conn()
    items = dbm.list_projects(conn)
    return JSONResponse(
        ok(
            {
                "projects": [
                    {"id": p.id, "name": p.name, "root_path": p.root_path} for p in items
                ]
            }
        )
    )


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    rules = None
    if prj.rules_json:
        try:
            rules = json.loads(prj.rules_json)
        except json.JSONDecodeError:
            rules = None
    return JSONResponse(
        ok(
            {
                "id": prj.id,
                "name": prj.name,
                "root_path": prj.root_path,
                "rules": rules,
                "md_out": str(project_md_out_dir(prj.id)),
            }
        )
    )


@app.get("/api/v1/projects/{project_id}/rules")
def get_rules(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    rules = merge_rules(json.loads(prj.rules_json)) if prj.rules_json else merge_rules(None)
    return JSONResponse(ok({"rules": rules}))


@app.post("/api/v1/projects/{project_id}/rules")
def save_rules(project_id: int, payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        return JSONResponse(err("rules must be an object"), status_code=400)
    dbm.update_project_rules(conn, project_id, json.dumps(rules, ensure_ascii=False))
    return JSONResponse(ok({"saved": True}))


def _sse_line(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _clean_json_text(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _coerce_rules_obj(obj: Any, focus_points: list[str], focus_note: str) -> dict[str, Any]:
    merged_focus = [x for x in focus_points if x]
    if focus_note:
        merged_focus.append(focus_note)
    if not isinstance(obj, dict):
        return merge_rules({"dimensions": merged_focus})
    goal = str(obj.get("goal") or "").strip() or "基于转换后的 Markdown 做项目风险与需求梳理"
    dimensions = obj.get("dimensions")
    if not isinstance(dimensions, list):
        dimensions = []
    dimensions_clean = [str(x).strip() for x in dimensions if str(x).strip()]
    for item in merged_focus:
        if item not in dimensions_clean:
            dimensions_clean.append(item)
    if not dimensions_clean:
        dimensions_clean = ["需求", "风险", "接口与集成"]
    style = obj.get("style")
    if not isinstance(style, dict):
        style = {"prefer": ["cards", "table", "tabs"]}
    return {"goal": goal, "dimensions": dimensions_clean, "style": style}


@app.post("/api/v1/projects/{project_id}/rules/generate")
def generate_rules(project_id: int, payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)

    points_raw = payload.get("focus_points")
    focus_points = [str(x).strip() for x in (points_raw if isinstance(points_raw, list) else []) if str(x).strip()]
    focus_note = str(payload.get("focus_note") or "").strip()
    if not focus_points and not focus_note:
        return JSONResponse(err("focus_points or focus_note is required"), status_code=400)

    st = get_settings()
    cfg = LLMConfig(
        provider=st.llm_provider,
        model=st.llm_model,
        base_url=st.llm_base_url,
        api_key=st.llm_api_key,
        timeout_s=180.0,
    )
    provider = get_provider(cfg.provider)
    system = (
        "你是资深 IT 实施顾问。请基于用户给出的分析关注点，输出 analysis rules JSON。"
        "只输出 JSON 对象，不要 Markdown。"
        '格式：{"goal":"...","dimensions":["..."],"style":{"prefer":["cards","table","tabs"]}}'
    )
    user = (
        f"项目名：{prj.name}\n"
        f"用户选择关注点：{json.dumps(focus_points, ensure_ascii=False)}\n"
        f"用户补充说明：{focus_note}\n"
        "要求：\n"
        "1) dimensions 必须覆盖所有关注点；\n"
        "2) goal 一句话且可执行；\n"
        "3) 输出必须是合法 JSON。"
    )
    try:
        chunks: list[str] = []
        for piece in provider.chat_stream(system=system, user=user, config=cfg):
            chunks.append(piece)
        raw = "".join(chunks)
        parsed = json.loads(_clean_json_text(raw))
    except (LLMError, json.JSONDecodeError):
        parsed = {}

    rules = _coerce_rules_obj(parsed, focus_points=focus_points, focus_note=focus_note)
    dbm.update_project_rules(conn, project_id, json.dumps(rules, ensure_ascii=False))
    return JSONResponse(ok({"rules": rules, "saved": True}))


def _normalize_analysis_for_ui(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {"title": "分析", "blocks": [{"type": "paragraph", "text": str(obj)}]}
    if obj.get("blocks"):
        return obj
    anns = obj.get("annotations")
    if isinstance(anns, list) and anns:
        items: list[dict[str, Any]] = []
        for a in anns:
            if not isinstance(a, dict):
                continue
            items.append(
                {
                    "title": str(a.get("type") or "item"),
                    "body": str(a.get("content") or ""),
                    "tags": [str(a.get("confidence") or "")] if a.get("confidence") else [],
                }
            )
        return {"title": str(obj.get("title") or "分析"), "blocks": [{"type": "cards", "items": items}]}
    return {"title": str(obj.get("title") or "分析"), "blocks": [{"type": "paragraph", "text": json.dumps(obj, ensure_ascii=False)}]}


@app.get("/api/v1/projects/{project_id}/convert-md/stream")
def convert_md_stream(project_id: int) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        src = validate_project_root(prj.root_path)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    out_dir = project_md_out_dir(project_id)

    def gen():
        try:
            for line in run_convert_directory(input_dir=src, output_dir=out_dir, format_="md"):
                yield _sse_line({"type": "log", "text": line.rstrip("\n")})
            yield _sse_line({"type": "complete", "md_out": str(out_dir)})
        except Docs2MdError as e:
            yield _sse_line({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/v1/projects/{project_id}/index-md")
def index_md(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    md_root = project_md_out_dir(project_id)
    if not md_root.is_dir():
        return JSONResponse(err("md_out does not exist; run convert-md first"), status_code=400)
    n = sync_project_md_root(conn, project=prj, md_root=md_root)
    return JSONResponse(ok({"indexed_documents": n}))


@app.get("/api/v1/projects/{project_id}/analyze/stream")
def analyze_stream(
    project_id: int,
    chunk_limit: int = Query(default=40, ge=1, le=500),
) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    rules_dict: dict[str, Any] | None = None
    if prj.rules_json:
        try:
            rules_dict = json.loads(prj.rules_json)
        except json.JSONDecodeError:
            rules_dict = None
    texts = dbm.list_chunk_texts(conn, project_id=project_id, limit=chunk_limit)
    if not texts:
        raise HTTPException(status_code=400, detail="no chunks; run index-md after convert-md")

    st = get_settings()
    cfg = LLMConfig(
        provider=st.llm_provider,
        model=st.llm_model,
        base_url=st.llm_base_url,
        api_key=st.llm_api_key,
        timeout_s=300.0,
    )
    system = build_system_prompt(rules_dict or {})
    user = build_user_prompt(chunk_texts=texts)

    def gen():
        provider = get_provider(cfg.provider)
        acc: list[str] = []
        try:
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            full = "".join(acc)
            cleaned = full.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            try:
                analysis = json.loads(cleaned)
            except json.JSONDecodeError:
                yield _sse_line({"type": "final", "analysis": None, "raw": full})
            else:
                analysis = _normalize_analysis_for_ui(analysis)
                yield _sse_line({"type": "final", "analysis": analysis, "raw": None})
        except LLMError as e:
            yield _sse_line({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/v1/projects/{project_id}/export/docx")
def export_docx(project_id: int, payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        return JSONResponse(err("analysis object required"), status_code=400)
    theme = str(payload.get("theme") or "tech")
    title = str(payload.get("title") or f"项目分析-{prj.name}")
    exp_dir = project_export_dir(project_id)
    exp_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = exp_dir / "epic_export.json"
    docx_path = exp_dir / "analysis_export.docx"
    epic_cfg = analysis_to_epic_doc_config(theme=theme, title=title, analysis=analysis)
    dump_epic_config_json(epic_cfg, cfg_path)
    try:
        generate_docx(config_path=cfg_path, output_path=docx_path, dry_run=False)
    except EpicDocError as e:
        return JSONResponse(err(str(e)), status_code=500)
    rel = f"{project_id}/analysis_export.docx"
    return JSONResponse(
        ok(
            {
                "download_path": f"/api/v1/files/{rel}",
                "docx": str(docx_path),
            }
        )
    )


@app.get("/api/v1/files/{project_id}/{filename:path}")
def download_file(project_id: int, filename: str) -> FileResponse:
    if filename != "analysis_export.docx":
        raise HTTPException(status_code=404, detail="not found")
    base = project_export_dir(project_id)
    target = (base / filename).resolve()
    try:
        validate_path_under_dir(target, base)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=str(target), filename="analysis_export.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


_dist = packaged_dist_dir() or dev_dist_dir(_repo_root)
if _dist is not None:
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
