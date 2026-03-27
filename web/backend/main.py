from __future__ import annotations

import json
import re
from typing import Any, Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from aika import db as dbm
from aika.epic_doc import EpicDocError, generate_docx
from aika.indexer import sync_project_md_root
from aika.project_layout import detect_project_layout
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

DEFAULT_FOCUS_POINTS: list[dict[str, str]] = [
    {"id": "req", "name": "需求", "prompt": "重点关注需求完整性、需求边界与缺失项。"},
    {"id": "risk", "name": "风险", "prompt": "识别高/中/低风险，给出证据和影响。"},
    {"id": "integration", "name": "接口与集成", "prompt": "关注系统接口、数据流、上下游依赖与一致性。"},
    {"id": "scope", "name": "范围蔓延", "prompt": "识别超范围需求和变更影响。"},
    {"id": "progress", "name": "进度", "prompt": "关注里程碑、任务时序与延期风险。"},
    {"id": "quality", "name": "质量", "prompt": "关注测试覆盖、缺陷闭环与质量门禁。"},
    {"id": "acceptance", "name": "验收", "prompt": "关注验收标准定义、证据闭环和未决事项。"},
    {"id": "data", "name": "数据一致性", "prompt": "关注关键主数据、口径与跨系统一致性问题。"},
]
DEFAULT_CHUNK_LIMIT = 40
DEFAULT_TEXT_MODEL = "qwen3"
DEFAULT_VL_MODEL = "qwen3-vl-plus"
DEFAULT_TEXT_PROVIDER = "openai_compatible"


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return ok({"ok": True})


def _rules_md_path() -> Path:
    return repository_root() / "rules.md"


def _build_settings_payload(conn: Any) -> dict[str, Any]:
    return {
        "focus_points": _get_focus_points(conn),
        "chunk_limit": _get_chunk_limit(conn),
        "llm_settings": _get_llm_settings(conn),
    }


def _read_settings_from_rules_md() -> tuple[dict[str, Any] | None, str | None]:
    p = _rules_md_path()
    if not p.is_file():
        return None, None
    text = p.read_text(encoding="utf-8", errors="replace")
    return _read_settings_from_rules_text(text)


def _read_settings_from_rules_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    lines = text.splitlines()

    focus_points: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("### focus:"):
            rest = line[len("### focus:") :].strip()
            if "|" in rest:
                pid, name = [x.strip() for x in rest.split("|", 1)]
            else:
                pid = rest
                name = rest
            j = i + 1
            buf: list[str] = []
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip().startswith("### focus:"):
                    break
                buf.append(nxt)
                j += 1
            prompt = "\n".join(buf).strip()
            if pid and name:
                focus_points.append({"id": pid, "name": name, "prompt": prompt})
            i = j
            continue
        i += 1

    if not focus_points:
        return None, "rules.md 格式无效：未找到“关注点块”（格式：### focus:<id> | <name>）"
    out: dict[str, Any] = {"focus_points": focus_points}
    return out, None


def _write_settings_to_rules_md(payload: dict[str, Any]) -> None:
    p = _rules_md_path()
    focus_points = payload.get("focus_points")
    if not isinstance(focus_points, list):
        focus_points = DEFAULT_FOCUS_POINTS

    blocks: list[str] = []
    for item in focus_points:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        prm = str(item.get("prompt") or "").strip()
        if not fid or not name:
            continue
        blocks.append(f"### focus:{fid} | {name}\n{prm}\n")

    md = (
        "# 分析规则配置\n\n"
        "该文件由 AI-KA 自动维护，用于保存关注点及其 Prompt。\n\n"
        "## 关注点块\n\n"
        + "\n".join(blocks)
    )
    p.write_text(md, encoding="utf-8")


def _get_focus_points(conn: Any) -> list[dict[str, str]]:
    v = dbm.get_app_setting_json(conn, "focus_points")
    if isinstance(v, list):
        out: list[dict[str, str]] = []
        for item in v:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "id": str(item.get("id") or name),
                    "name": name,
                    "prompt": str(item.get("prompt") or "").strip(),
                }
            )
        if out:
            return out
    return DEFAULT_FOCUS_POINTS


def _get_chunk_limit(conn: Any) -> int:
    v = dbm.get_app_setting_json(conn, "chunk_limit")
    if isinstance(v, int) and 1 <= v <= 500:
        return v
    return DEFAULT_CHUNK_LIMIT


def _get_llm_api_key_from_db(conn: Any) -> str | None:
    v = dbm.get_app_setting_json(conn, "llm_api_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _get_llm_api_key_effective(conn: Any) -> str | None:
    v = _get_llm_api_key_from_db(conn)
    if v:
        return v
    return get_settings().llm_api_key


def _get_text_model(conn: Any) -> str:
    v = dbm.get_app_setting_json(conn, "llm_text_model")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return DEFAULT_TEXT_MODEL


def _get_text_provider(conn: Any) -> str:
    v = dbm.get_app_setting_json(conn, "llm_text_provider")
    if isinstance(v, str) and v.strip():
        return v.strip()
    st = get_settings()
    return (st.llm_provider or "").strip() or DEFAULT_TEXT_PROVIDER


def _get_text_base_url(conn: Any) -> str:
    v = dbm.get_app_setting_json(conn, "llm_text_base_url")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return str(get_settings().llm_base_url or "").strip()


def _get_vl_model(conn: Any) -> str:
    v = dbm.get_app_setting_json(conn, "llm_vl_model")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return DEFAULT_VL_MODEL


def _get_llm_settings(conn: Any) -> dict[str, Any]:
    return {
        "text_provider": _get_text_provider(conn),
        "text_base_url": _get_text_base_url(conn),
        "text_model": _get_text_model(conn),
        "vl_model": _get_vl_model(conn),
        "has_api_key": bool(_get_llm_api_key_effective(conn)),
    }


def _build_text_llm_config(conn: Any, timeout_s: float) -> LLMConfig:
    return LLMConfig(
        provider=_get_text_provider(conn),
        model=_get_text_model(conn),
        base_url=_get_text_base_url(conn) or None,
        api_key=_get_llm_api_key_effective(conn),
        timeout_s=timeout_s,
    )


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


@app.post("/api/v1/fs/detect-projects")
def detect_projects(payload: dict[str, Any]) -> JSONResponse:
    root_path = str(payload.get("root_path") or "").strip()
    try:
        validated = validate_project_root(root_path)
    except PathValidationError as e:
        return JSONResponse(err(str(e)), status_code=400)
    layout = detect_project_layout(validated)
    return JSONResponse(ok(layout))


@app.get("/api/v1/settings")
def get_app_settings() -> JSONResponse:
    conn = _conn()
    file_data, parse_error = _read_settings_from_rules_md()
    if isinstance(file_data, dict):
        fp = file_data.get("focus_points")
        cl = file_data.get("chunk_limit")
        if isinstance(fp, list):
            dbm.set_app_setting_json(conn, "focus_points", fp)
        if isinstance(cl, int):
            dbm.set_app_setting_json(conn, "chunk_limit", cl)
    payload = _build_settings_payload(conn)
    payload["rules_md_error"] = parse_error
    return JSONResponse(ok(payload))


@app.post("/api/v1/settings")
def save_app_settings(payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    if "chunk_limit" in payload:
        raw = payload.get("chunk_limit")
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return JSONResponse(err("chunk_limit must be integer"), status_code=400)
        if val < 1 or val > 500:
            return JSONResponse(err("chunk_limit must be between 1 and 500"), status_code=400)
        dbm.set_app_setting_json(conn, "chunk_limit", val)
    if "focus_points" in payload:
        raw_fp = payload.get("focus_points")
        if not isinstance(raw_fp, list):
            return JSONResponse(err("focus_points must be a list"), status_code=400)
        out: list[dict[str, str]] = []
        for item in raw_fp:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "id": str(item.get("id") or name),
                    "name": name,
                    "prompt": str(item.get("prompt") or "").strip(),
                }
            )
        if not out:
            return JSONResponse(err("focus_points cannot be empty"), status_code=400)
        dbm.set_app_setting_json(conn, "focus_points", out)
    if "llm_settings" in payload:
        raw_llm = payload.get("llm_settings")
        if not isinstance(raw_llm, dict):
            return JSONResponse(err("llm_settings must be an object"), status_code=400)
        text_provider = str(raw_llm.get("text_provider") or "").strip() or DEFAULT_TEXT_PROVIDER
        text_base_url = str(raw_llm.get("text_base_url") or "").strip()
        text_model = str(raw_llm.get("text_model") or "").strip() or DEFAULT_TEXT_MODEL
        vl_model = str(raw_llm.get("vl_model") or "").strip() or DEFAULT_VL_MODEL
        dbm.set_app_setting_json(conn, "llm_text_provider", text_provider)
        dbm.set_app_setting_json(conn, "llm_text_base_url", text_base_url or None)
        dbm.set_app_setting_json(conn, "llm_text_model", text_model)
        dbm.set_app_setting_json(conn, "llm_vl_model", vl_model)
    if "llm_api_key" in payload:
        raw_key = payload.get("llm_api_key")
        key = str(raw_key or "").strip()
        if key:
            dbm.set_app_setting_json(conn, "llm_api_key", key)
        else:
            dbm.set_app_setting_json(conn, "llm_api_key", None)
    current = _build_settings_payload(conn)
    _write_settings_to_rules_md(current)
    current["rules_md_error"] = None
    return JSONResponse(ok(current))


@app.post("/api/v1/settings/rules-md/validate")
def validate_rules_md_payload(payload: dict[str, Any]) -> JSONResponse:
    text = str(payload.get("text") or "")
    parsed, parse_error = _read_settings_from_rules_text(text)
    if parse_error:
        return JSONResponse(err(parse_error), status_code=400)
    fps = (parsed or {}).get("focus_points", [])
    return JSONResponse(ok({"focus_points": fps, "count": len(fps)}))


@app.post("/api/v1/settings/rules-md/import")
def import_rules_md_payload(payload: dict[str, Any]) -> JSONResponse:
    text = str(payload.get("text") or "")
    parsed, parse_error = _read_settings_from_rules_text(text)
    if parse_error:
        return JSONResponse(err(parse_error), status_code=400)
    focus_points = (parsed or {}).get("focus_points")
    if not isinstance(focus_points, list) or not focus_points:
        return JSONResponse(err("rules.md 中未解析到有效关注点"), status_code=400)

    conn = _conn()
    dbm.set_app_setting_json(conn, "focus_points", focus_points)
    _rules_md_path().write_text(text, encoding="utf-8")
    current = _build_settings_payload(conn)
    current["rules_md_error"] = None
    return JSONResponse(ok(current))


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


@app.post("/api/v1/projects/ensure")
def ensure_project(payload: dict[str, Any]) -> JSONResponse:
    root_path = str(payload.get("root_path") or "").strip()
    req_name = str(payload.get("name") or "").strip()
    if not root_path:
        return JSONResponse(err("root_path is required"), status_code=400)
    try:
        validated = validate_project_root(root_path)
    except PathValidationError as e:
        return JSONResponse(err(str(e)), status_code=400)

    conn = _conn()
    existed = dbm.get_project_by_root_path(conn, validated.as_posix())
    if existed is not None:
        return JSONResponse(ok({"id": existed.id, "name": existed.name, "root_path": existed.root_path, "created": False}))

    base = req_name or Path(validated).name or "project"
    name = base
    suffix = 2
    while dbm.get_project_by_name(conn, name) is not None:
        name = f"{base}-{suffix}"
        suffix += 1
    prj = dbm.create_project(conn, name, validated.as_posix())
    return JSONResponse(ok({"id": prj.id, "name": prj.name, "root_path": prj.root_path, "created": True}))


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


@app.patch("/api/v1/projects/{project_id}")
def patch_project(project_id: int, payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    new_root = payload.get("root_path")
    new_name = payload.get("name")
    if new_root is not None:
        try:
            validated = validate_project_root(str(new_root).strip())
        except PathValidationError as e:
            return JSONResponse(err(str(e)), status_code=400)
        dbm.clear_project_index_state(conn, project_id)
        dbm.update_project_root(conn, project_id, validated.as_posix())
    if new_name is not None:
        name = str(new_name).strip()
        if not name:
            return JSONResponse(err("name is empty"), status_code=400)
        existing = dbm.get_project_by_name(conn, name)
        if existing and existing.id != project_id:
            return JSONResponse(err("project name already exists"), status_code=409)
        dbm.update_project_name(conn, project_id, name)
    prj2 = dbm.get_project_by_id(conn, project_id)
    if prj2 is None:
        return JSONResponse(err("project not found"), status_code=404)
    return JSONResponse(ok({"id": prj2.id, "name": prj2.name, "root_path": prj2.root_path}))


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


def _rules_generate_prompts(
    conn: Any, prj: Any, focus_points: list[str], focus_note: str
) -> tuple[str, str, LLMConfig, Any]:
    cfg = _build_text_llm_config(conn, timeout_s=180.0)
    provider = get_provider(cfg.provider)
    fp_defs = _get_focus_points(conn)
    prompt_by_name = {x["name"]: x.get("prompt", "") for x in fp_defs}
    selected_focus = [
        {"name": n, "prompt": prompt_by_name.get(n, "")}
        for n in focus_points
    ]
    system = (
        "你是资深 IT 实施顾问。请基于用户给出的分析关注点，输出 analysis rules JSON。"
        "只输出 JSON 对象，不要 Markdown。"
        '格式：{"goal":"...","dimensions":["..."],"style":{"prefer":["cards","table","tabs"]}}'
    )
    user = (
        f"项目名：{prj.name}\n"
        f"用户选择关注点：{json.dumps(selected_focus, ensure_ascii=False)}\n"
        f"用户补充说明：{focus_note}\n"
        "要求：\n"
        "1) dimensions 必须覆盖所有关注点；\n"
        "2) goal 一句话且可执行；\n"
        "3) 输出必须是合法 JSON。"
    )
    return system, user, cfg, provider


def _rules_from_llm_raw(raw: str, focus_points: list[str], focus_note: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_clean_json_text(raw))
    except json.JSONDecodeError:
        parsed = {}
    return _coerce_rules_obj(parsed, focus_points=focus_points, focus_note=focus_note)


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

    system, user, cfg, provider = _rules_generate_prompts(conn, prj, focus_points, focus_note)
    try:
        chunks: list[str] = []
        for piece in provider.chat_stream(system=system, user=user, config=cfg):
            chunks.append(piece)
        raw = "".join(chunks)
    except LLMError as e:
        return JSONResponse(err(str(e)), status_code=502)

    rules = _rules_from_llm_raw(raw, focus_points=focus_points, focus_note=focus_note)
    dbm.update_project_rules(conn, project_id, json.dumps(rules, ensure_ascii=False))
    return JSONResponse(ok({"rules": rules, "saved": True}))


@app.post("/api/v1/projects/{project_id}/rules/generate/stream")
def generate_rules_stream(project_id: int, payload: dict[str, Any]) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")

    points_raw = payload.get("focus_points")
    focus_points = [str(x).strip() for x in (points_raw if isinstance(points_raw, list) else []) if str(x).strip()]
    focus_note = str(payload.get("focus_note") or "").strip()
    if not focus_points and not focus_note:
        raise HTTPException(status_code=400, detail="focus_points or focus_note is required")

    system, user, cfg, provider = _rules_generate_prompts(conn, prj, focus_points, focus_note)

    def gen() -> Iterator[str]:
        try:
            acc: list[str] = []
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            raw = "".join(acc)
            rules = _rules_from_llm_raw(raw, focus_points=focus_points, focus_note=focus_note)
            dbm.update_project_rules(conn, project_id, json.dumps(rules, ensure_ascii=False))
            yield _sse_line({"type": "final", "rules": rules, "saved": True})
        except LLMError as e:
            yield _sse_line({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


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
            for line in run_convert_directory(
                input_dir=src,
                output_dir=out_dir,
                format_="md",
                vl_api_key=_get_llm_api_key_effective(conn),
                vl_model=_get_vl_model(conn),
            ):
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

    cfg = _build_text_llm_config(conn, timeout_s=300.0)
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
