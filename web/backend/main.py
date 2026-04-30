from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Iterator
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime

from aika import db as dbm
from aika.epic_doc import EpicDocError, generate_docx
from aika.indexer import CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED, sync_project_md_root
from aika.llm import LLMConfig, LLMError, get_provider
from aika.paths import db_path

from backend.config import get_settings
from backend.docs2md_runner import Docs2MdError, run_convert_directory
from backend.folder_picker import FolderPickerError, pick_folder_native
from backend.epic_mapper import analysis_to_epic_doc_config, dump_epic_config_json
from backend.frontend_static import dev_dist_dir, packaged_dist_dir
from backend.path_validate import PathValidationError, validate_path_under_dir, validate_project_root
from backend.prompt_builder import (
    build_system_prompt,
    build_user_prompt_from_entries,
    format_chunk_index_lines_markdown,
    merge_rules,
)
from backend.repo_paths import project_export_dir, project_md_out_dir, repository_root
from backend.response import err, ok
from backend.routers.conversations import router as conversations_router
from backend.routers.outputs import router as outputs_router
from backend.run_metadata import build_run_metadata, sha256_short
from backend.memory_recall import iter_memory_candidate_files, memory_root_under_repo, recall_memory_snippets
from backend.conversation_models import (
    ConversationMode, MessageMetadata, collect_findings_from_conversation,
    FindingStatus,
)
from backend.intent_classifier import classify_intent
from backend.finding_parser import (
    FINDING_INSTRUCTION, extract_findings_from_markdown, extract_evolve_hints,
    deduplicate_findings,
)
from backend.context_builder import (
    build_rolling_context, format_open_findings_for_prompt,
    collect_open_findings, collect_all_findings,
)
from backend.conversation_fsm import transition as fsm_transition, mark_awaiting
from backend.embedding_service import (
    configure as configure_embeddings,
    content_hash as emb_content_hash,
    embed_text,
    is_configured as embeddings_configured,
    vec_to_bytes,
)
from backend.personal_memory import (
    add_memory_suggestion,
    approve_memory_suggestion,
    dismiss_memory_suggestion,
    ensure_personal_dirs,
    list_memory_suggestions,
    load_personal_focus_override,
    recall_personal_memory,
)
from backend.hooks import register_builtin_hooks, run_after_analyze_hooks, run_before_analyze_hooks
from backend.hooks.registry import list_hook_names
from backend.services.outputs_files_service import (
    append_milestone_event,
    finalize_milestones_file,
    init_milestones_file,
    make_outputs_filenames,
)
from backend.skills import (
    DEFAULT_PACKAGE_ID,
    domain_path,
    ensure_default_skill_package,
    list_skill_packages,
    package_version_for_hash,
    read_manifest,
    skill_packages_root,
)
from backend.skills.packages import focus_points_dir, is_v2_package, package_dir
from backend.skills.focus_point_io import (
    evolve_focus_point,
    list_focus_points,
    load_focus_point,
    migrate_from_review_domain,
)
from backend.skills.review_domain_io import (
    derive_focus_presets_from_combo_tips,
    extract_focus_combo_tips_from_domain_text,
    merge_preset_review_into_derived,
    read_composer_hint_from_domain_text,
    read_settings_from_domain_text,
    read_settings_from_package_dir,
    write_review_domain_file,
)


def _conn():
    root = repository_root()
    conn = dbm.connect(db_path(root))
    dbm.ensure_schema(conn)
    return conn


_MULTITURN_MESSAGE_MAX_CHARS = 8000
_MULTITURN_RECENT_LIMIT = 24


def _truncate_message_for_context(text: str, max_chars: int = _MULTITURN_MESSAGE_MAX_CHARS) -> str:
    t = str(text or "")
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n\n（已截断）\n"


def _message_rows_to_prior_tuples(rows: list[Any]) -> list[tuple[str, str]]:
    return [(str(r.role), _truncate_message_for_context(r.content)) for r in rows]


@asynccontextmanager
async def _lifespan(application: FastAPI):
    try:
        ensure_personal_dirs()
    except Exception:
        pass
    _reload_embedding_config()
    yield


app = FastAPI(title="AI-KA Web", version="0.1.0", lifespan=_lifespan)
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(outputs_router)
app.include_router(conversations_router)

register_builtin_hooks()


@app.middleware("http")
async def _no_cache_spa_entry(request: Request, call_next):
    """避免浏览器长期缓存 index.html，导致仍引用旧哈希的 /assets/*.css、*.js。"""
    response = await call_next(request)
    if request.url.path in ("/", "/index.html") and response.status_code == 200:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


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
DEFAULT_CHUNK_STRATEGY = CHUNK_STRATEGY_BLANK
DEFAULT_TEXT_MODEL = "qwen3"
DEFAULT_VL_MODEL = "qwen3-vl-plus"
DEFAULT_TEXT_PROVIDER = "openai_compatible"


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return ok({"ok": True})


@app.post("/api/v1/tools/invoke")
def tools_invoke(payload: dict[str, Any]) -> JSONResponse:
    """内部 Tool 注册表调用（与 backend.tools.registry 对齐）。"""
    name = str(payload.get("name") or "").strip()
    if not name:
        return JSONResponse(err("name is required"), status_code=400)
    raw_kw = payload.get("kwargs")
    kwargs: dict[str, Any] = raw_kw if isinstance(raw_kw, dict) else {}
    from backend.tools.registry import invoke_tool

    return JSONResponse(ok(invoke_tool(name, **kwargs)))


@app.get("/api/v1/projects/{project_id}/memory/files")
def list_project_memory_files(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    root = memory_root_under_repo(repository_root())
    files = iter_memory_candidate_files(root, project_id)
    rels = [str(f.relative_to(root)).replace("\\", "/") for f in files]
    return JSONResponse(ok({"memory_root": str(root), "files": rels}))


@app.post("/api/v1/projects/{project_id}/memory/upsert")
def upsert_project_memory_file(project_id: int, payload: dict[str, Any]) -> JSONResponse:
    """写入单条记忆文件（相对路径须落在 user|feedback|project/<id>|reference/<id> 下）。"""
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    rel = str(payload.get("path") or "").strip().replace("\\", "/")
    content = str(payload.get("content") or "")
    if not rel.endswith(".md"):
        return JSONResponse(err("path must be a .md file under allowed memory dirs"), status_code=400)
    root = memory_root_under_repo(repository_root())
    allowed_prefixes = (
        "user/",
        "feedback/",
        f"project/{project_id}/",
        f"reference/{project_id}/",
    )
    if not any(rel.startswith(p) for p in allowed_prefixes):
        return JSONResponse(err("path not in allowed memory directories"), status_code=400)
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError:
        return JSONResponse(err("invalid path"), status_code=400)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_text(content, encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(str(e)), status_code=500)

    # Lazily embed the written file if embedding is configured
    embed_status = "skipped"
    if embeddings_configured():
        try:
            from backend.embedding_service import bytes_to_vec  # noqa: F401 (verify import)
            h = emb_content_hash(content)
            existing = dbm.get_memory_embedding(conn, path=rel, content_hash=h)
            if existing is None:
                vec = embed_text(content[:8000])
                dbm.upsert_memory_embedding(
                    conn,
                    path=rel,
                    embedding_bytes=vec_to_bytes(vec),
                    content_hash=h,
                    embed_model=_get_embedding_model(),
                )
            embed_status = "ok"
        except Exception:
            embed_status = "error"

    return JSONResponse(ok({"path": rel, "written": True, "embed": embed_status}))


# ---------------------------------------------------------------------------
# Personal memory endpoints (~/.aika/)
# ---------------------------------------------------------------------------

@app.get("/api/v1/personal/memory/suggestions")
def get_personal_memory_suggestions() -> JSONResponse:
    return JSONResponse(ok(list_memory_suggestions()))


class MemorySuggestionBody(BaseModel):
    title: str = Field(..., description="Memory file title (no extension)")
    content: str = Field(..., description="Markdown content for the memory file")
    reason: str = Field(default="", description="Why this memory is suggested")


@app.post("/api/v1/personal/memory/suggestions")
def create_personal_memory_suggestion(body: MemorySuggestionBody) -> JSONResponse:
    """Add a pending memory suggestion (never auto-writes to memory/)."""
    add_memory_suggestion({"title": body.title, "content": body.content, "reason": body.reason})
    return JSONResponse(ok({"queued": True}))


@app.post("/api/v1/personal/memory/suggestions/{index}/approve")
def approve_personal_memory_suggestion(index: int) -> JSONResponse:
    result = approve_memory_suggestion(index)
    if result is None:
        return JSONResponse(err("suggestion not found or empty"), status_code=404)
    return JSONResponse(ok(result))


@app.post("/api/v1/personal/memory/suggestions/{index}/dismiss")
def dismiss_personal_memory_suggestion(index: int) -> JSONResponse:
    ok_flag = dismiss_memory_suggestion(index)
    return JSONResponse(ok({"dismissed": ok_flag}))


@app.get("/api/v1/personal/focus-overrides")
def list_personal_focus_override_files() -> JSONResponse:
    from backend.personal_memory import list_personal_focus_overrides
    return JSONResponse(ok(list_personal_focus_overrides()))


class PersonalFocusOverrideBody(BaseModel):
    prompt: str = Field(..., description="Override prompt text for this focus point")


@app.put("/api/v1/personal/focus-overrides/{focus_id}")
def upsert_personal_focus_override(focus_id: str, body: PersonalFocusOverrideBody) -> JSONResponse:
    from backend.personal_memory import personal_focus_overrides_dir
    d = personal_focus_overrides_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"focus-{focus_id}.md"
    try:
        dest.write_text(body.prompt, encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(str(e)), status_code=500)
    return JSONResponse(ok({"focus_id": focus_id, "written": True}))


@app.delete("/api/v1/personal/focus-overrides/{focus_id}")
def delete_personal_focus_override(focus_id: str) -> JSONResponse:
    from backend.personal_memory import personal_focus_overrides_dir
    dest = personal_focus_overrides_dir() / f"focus-{focus_id}.md"
    if not dest.is_file():
        return JSONResponse(err("override not found"), status_code=404)
    dest.unlink()
    return JSONResponse(ok({"focus_id": focus_id, "deleted": True}))


def _get_active_skill_package_id() -> str:
    """活动审查技能包 id，存于 app_settings.md JSON。"""
    app_cfg, _ = _read_app_settings_md()
    if isinstance(app_cfg, dict):
        v = app_cfg.get("active_skill_package_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return DEFAULT_PACKAGE_ID


def _active_review_domain_path() -> Path:
    """当前活动包的 review_domain.md（唯一关注点与组合表来源）。"""
    rr = repository_root()
    ensure_default_skill_package(rr)
    return domain_path(rr, _get_active_skill_package_id())


def _review_domain_file_hash_and_name() -> tuple[str, str]:
    rr = repository_root()
    ensure_default_skill_package(rr)
    pid = _get_active_skill_package_id()
    p = domain_path(rr, pid)
    if not p.is_file():
        return "", f"{pid}"
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", f"{pid}"
    ver = package_version_for_hash(rr, pid)
    return sha256_short(txt + "@" + ver), f"{pid}@{ver}"


def _default_skills_template_path() -> Path:
    return repository_root() / "default_skills.md"


def _app_settings_md_path() -> Path:
    return repository_root() / "app_settings.md"


def _default_app_settings_md_path() -> Path:
    return repository_root() / "default_app_settings.md"


def _parse_json_fenced_block(text: str) -> dict[str, Any] | None:
    lines = str(text or "").splitlines()
    start = -1
    for i, raw in enumerate(lines):
        if raw.strip().startswith("```"):
            fence = raw.strip()
            lang = fence.strip("`").strip().lower()
            if lang in {"json", ""}:
                start = i + 1
                break
    if start < 0:
        return None
    buf: list[str] = []
    j = start
    while j < len(lines) and lines[j].strip() != "```":
        buf.append(lines[j])
        j += 1
    raw_json = "\n".join(buf).strip()
    if not raw_json:
        return None
    obj = json.loads(raw_json)
    if isinstance(obj, dict):
        return obj
    return None


def _read_app_settings_md() -> tuple[dict[str, Any], str | None]:
    p = _app_settings_md_path()
    if p.is_file():
        try:
            obj = _parse_json_fenced_block(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(obj, dict):
                return obj, None
            err_msg = "app_settings.md 格式无效：未找到 JSON fenced block"
        except Exception as e:
            err_msg = str(e)
        fb = _default_app_settings_md_path()
        if fb.is_file():
            try:
                obj2 = _parse_json_fenced_block(fb.read_text(encoding="utf-8", errors="replace"))
                if isinstance(obj2, dict):
                    return obj2, f"app_settings.md 解析失败，已回退 default_app_settings.md：{err_msg}"
            except Exception:
                pass
        return {}, err_msg
    fb = _default_app_settings_md_path()
    if fb.is_file():
        try:
            obj2 = _parse_json_fenced_block(fb.read_text(encoding="utf-8", errors="replace"))
            if isinstance(obj2, dict):
                return obj2, "app_settings.md 不存在，已回退 default_app_settings.md"
        except Exception as e:
            return {}, str(e)
    return {}, "app_settings.md 与 default_app_settings.md 均不存在"


def _read_app_settings_md_debug() -> tuple[dict[str, Any], str | None, str]:
    """
    与 _read_app_settings_md 类似，但额外返回本次实际使用的来源文件名：
    - app_settings.md
    - default_app_settings.md
    - none
    """
    p = _app_settings_md_path()
    if p.is_file():
        cfg, err = _read_app_settings_md()
        # _read_app_settings_md 内部可能回退到 default，因此这里再判断 err 文案
        if err and "default_app_settings.md" in err:
            return cfg, err, "default_app_settings.md"
        return cfg, err, "app_settings.md"
    fb = _default_app_settings_md_path()
    if fb.is_file():
        cfg, err = _read_app_settings_md()
        return cfg, err, "default_app_settings.md"
    cfg, err = _read_app_settings_md()
    return cfg, err, "none"


def _normalize_chunk_strategy(raw: Any) -> str:
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED):
            return v
    return DEFAULT_CHUNK_STRATEGY


MD_INDEX_MODE_INCREMENTAL = "incremental"
MD_INDEX_MODE_FULL = "full"


def _normalize_md_index_mode(v: Any) -> str:
    if isinstance(v, str) and v.strip().lower() == MD_INDEX_MODE_FULL:
        return MD_INDEX_MODE_FULL
    return MD_INDEX_MODE_INCREMENTAL


def _write_app_settings_md(payload: dict[str, Any]) -> None:
    """合并写入 app_settings.md，保留 focus_preset_review_overlay、active_skill_package_id 等扩展键。"""
    p = _app_settings_md_path()
    base, _ = _read_app_settings_md()
    merged: dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    merged.update(payload)
    obj: dict[str, Any] = {
        "chunk_limit": int(merged.get("chunk_limit") or DEFAULT_CHUNK_LIMIT),
        "chunk_strategy": _normalize_chunk_strategy(merged.get("chunk_strategy")),
        "disable_image_parse": bool(merged.get("disable_image_parse", True)),
        "md_index_mode": _normalize_md_index_mode(merged.get("md_index_mode")),
        "llm_settings": merged.get("llm_settings") if isinstance(merged.get("llm_settings"), dict) else {},
        "llm_text_api_key": str(merged.get("llm_text_api_key") or ""),
        "llm_vl_api_key": str(merged.get("llm_vl_api_key") or ""),
        "embedding_model": str(merged.get("embedding_model") or ""),
    }
    aid = merged.get("active_skill_package_id")
    if isinstance(aid, str) and aid.strip():
        obj["active_skill_package_id"] = aid.strip()
    else:
        obj["active_skill_package_id"] = DEFAULT_PACKAGE_ID
    ovr = merged.get("focus_preset_review_overlay")
    if isinstance(ovr, list):
        obj["focus_preset_review_overlay"] = ovr
    text = "# 应用设置\n\n```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```\n"
    p.write_text(text, encoding="utf-8")

def _reload_embedding_config() -> None:
    """Re-configure embedding singleton from current app_settings.md. Non-fatal."""
    try:
        em = _get_embed_model_from_llm_settings()
        base = _get_embed_base_url_from_llm_settings()
        if em and base:
            configure_embeddings(base_url=base, model=em)
    except Exception:
        pass


def _helpme_md_path() -> Path:
    root = repository_root()
    direct = root / "helpme.md"
    if direct.is_file():
        return direct
    return root / "docs" / "helpme.md"


def _build_settings_payload(conn: Any) -> dict[str, Any]:
    derived = _get_focus_presets()
    overlay = _read_focus_preset_review_overlay()
    merged_presets = merge_preset_review_into_derived(derived, overlay) if overlay else derived
    rr = repository_root()
    ensure_default_skill_package(rr)
    sp_id = _get_active_skill_package_id()
    sp_list = list_skill_packages(rr)
    return {
        "focus_points": _get_focus_points(),
        "focus_presets": merged_presets,
        "chunk_limit": _get_chunk_limit(),
        "chunk_strategy": _get_chunk_strategy(),
        "disable_image_parse": _get_disable_image_parse(),
        "md_index_mode": _get_md_index_mode(),
        "llm_settings": _get_llm_settings(),
        "repo_root": str(rr),
        "active_skill_package_id": sp_id,
        "skill_packages": sp_list,
        "skill_packages_root": str(skill_packages_root(rr)),
        "review_domain_path": str(domain_path(rr, sp_id)),
        "focus_combo_tips": _read_focus_combo_tips_from_review_domain(),
        "composer_hint": _read_composer_hint_from_review_domain(),
        "embedding_model": _get_embedding_model(),
    }


def _read_settings_from_review_domain() -> tuple[dict[str, Any] | None, str | None]:
    """从当前活动审查技能包读取 focus points（v2 focus-points/*.md 优先，否则 v1 review_domain.md）。"""
    from backend.skills.review_domain_io import read_settings_from_package_dir
    rr = repository_root()
    pid = _get_active_skill_package_id()
    ensure_default_skill_package(rr)
    pkg_d = package_dir(rr, pid)
    parsed, err = read_settings_from_package_dir(pkg_d)
    if parsed and not err:
        return parsed, None
    if err:
        return None, f"review_domain.md（包 {pid}）解析失败：{err}"
    return None, f"review_domain.md（包 {pid}）解析失败：无法读取关注点"


def _domain_text_aligned_with_focus_parse() -> str | None:
    p = _active_review_domain_path()
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    parsed, err = read_settings_from_domain_text(text)
    if parsed and not err:
        return text
    return None


def _read_focus_combo_tips_from_review_domain() -> list[dict[str, str]]:
    raw = _domain_text_aligned_with_focus_parse()
    if not raw:
        return []
    return extract_focus_combo_tips_from_domain_text(raw)


def _read_composer_hint_from_review_domain() -> str | None:
    p = _active_review_domain_path()
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    return read_composer_hint_from_domain_text(text)


def _read_focus_preset_review_overlay() -> list[dict[str, Any]]:
    """从 app_settings.md 读取预设的审查角色/目标/输出要求（组合表可能不含这些列）。"""
    app_cfg, _ = _read_app_settings_md()
    raw = app_cfg.get("focus_preset_review_overlay")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict) and x.get("id")]


def _get_focus_points() -> list[dict[str, str]]:
    parsed, _ = _read_settings_from_review_domain()
    fps = (parsed or {}).get("focus_points") if isinstance(parsed, dict) else None
    if isinstance(fps, list) and fps:
        out: list[dict[str, str]] = []
        for item in fps:
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
    return []


def _get_focus_presets() -> list[dict[str, Any]]:
    tips = _read_focus_combo_tips_from_review_domain()
    focus_defs = _get_focus_points()
    return derive_focus_presets_from_combo_tips(tips, focus_defs)


def _write_settings_to_review_domain(payload: dict[str, Any]) -> None:
    write_review_domain_file(_active_review_domain_path(), payload, DEFAULT_FOCUS_POINTS)


def _get_chunk_limit() -> int:
    app_cfg, _ = _read_app_settings_md()
    v = app_cfg.get("chunk_limit") if isinstance(app_cfg, dict) else None
    if isinstance(v, int) and 1 <= v <= 500:
        return v
    return DEFAULT_CHUNK_LIMIT


def _get_chunk_strategy() -> str:
    app_cfg, _ = _read_app_settings_md()
    v = app_cfg.get("chunk_strategy") if isinstance(app_cfg, dict) else None
    return _normalize_chunk_strategy(v)


def _get_disable_image_parse() -> bool:
    app_cfg, _ = _read_app_settings_md()
    v = app_cfg.get("disable_image_parse") if isinstance(app_cfg, dict) else None
    if isinstance(v, bool):
        return v
    return True


def _get_md_index_mode() -> str:
    app_cfg, _ = _read_app_settings_md()
    v = app_cfg.get("md_index_mode") if isinstance(app_cfg, dict) else None
    return _normalize_md_index_mode(v)


def _get_text_llm_api_key_effective() -> str | None:
    app_cfg, _ = _read_app_settings_md()
    if isinstance(app_cfg, dict):
        v = app_cfg.get("llm_text_api_key") or app_cfg.get("llm_api_key")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return get_settings().llm_api_key


def _get_vl_llm_api_key_effective() -> str | None:
    app_cfg, _ = _read_app_settings_md()
    if isinstance(app_cfg, dict):
        v = app_cfg.get("llm_vl_api_key") or app_cfg.get("llm_api_key")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return get_settings().llm_api_key


def _get_text_model() -> str:
    app_cfg, _ = _read_app_settings_md()
    raw = (app_cfg.get("llm_settings") or {}) if isinstance(app_cfg, dict) else {}
    v = raw.get("text_model") if isinstance(raw, dict) else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    return DEFAULT_TEXT_MODEL


def _get_text_provider() -> str:
    app_cfg, _ = _read_app_settings_md()
    raw = (app_cfg.get("llm_settings") or {}) if isinstance(app_cfg, dict) else {}
    v = raw.get("text_provider") if isinstance(raw, dict) else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    st = get_settings()
    return (st.llm_provider or "").strip() or DEFAULT_TEXT_PROVIDER


def _get_text_base_url() -> str:
    app_cfg, _ = _read_app_settings_md()
    raw = (app_cfg.get("llm_settings") or {}) if isinstance(app_cfg, dict) else {}
    v = raw.get("text_base_url") if isinstance(raw, dict) else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    return str(get_settings().llm_base_url or "").strip()


def _get_vl_model() -> str:
    app_cfg, _ = _read_app_settings_md()
    raw = (app_cfg.get("llm_settings") or {}) if isinstance(app_cfg, dict) else {}
    v = raw.get("vl_model") if isinstance(raw, dict) else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    return DEFAULT_VL_MODEL


def _get_vl_base_url() -> str:
    app_cfg, _ = _read_app_settings_md()
    raw = (app_cfg.get("llm_settings") or {}) if isinstance(app_cfg, dict) else {}
    v = raw.get("vl_base_url") if isinstance(raw, dict) else None
    if isinstance(v, str) and v.strip():
        return v.strip()
    return str(get_settings().llm_base_url or "").strip()


def _get_embedding_model() -> str:
    app_cfg, _ = _read_app_settings_md()
    v = app_cfg.get("embedding_model") if isinstance(app_cfg, dict) else None
    return str(v).strip() if isinstance(v, str) and v.strip() else ""


def _get_embed_model_from_llm_settings() -> str:
    app_cfg, _ = _read_app_settings_md()
    llm = app_cfg.get("llm_settings") if isinstance(app_cfg, dict) else {}
    if isinstance(llm, dict):
        v = llm.get("embed_model")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _get_embed_base_url_from_llm_settings() -> str:
    app_cfg, _ = _read_app_settings_md()
    llm = app_cfg.get("llm_settings") if isinstance(app_cfg, dict) else {}
    if isinstance(llm, dict):
        v = llm.get("embed_base_url")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _get_llm_settings() -> dict[str, Any]:
    return {
        "text_provider": _get_text_provider(),
        "text_base_url": _get_text_base_url(),
        "text_model": _get_text_model(),
        "vl_model": _get_vl_model(),
        "vl_base_url": _get_vl_base_url(),
        "embed_model": _get_embed_model_from_llm_settings(),
        "embed_base_url": _get_embed_base_url_from_llm_settings(),
        "has_text_api_key": bool(_get_text_llm_api_key_effective()),
        "has_vl_api_key": bool(_get_vl_llm_api_key_effective()),
    }


def _build_text_llm_config(conn: Any, timeout_s: float) -> LLMConfig:
    return LLMConfig(
        provider=_get_text_provider(),
        model=_get_text_model(),
        base_url=_get_text_base_url() or None,
        api_key=_get_text_llm_api_key_effective(),
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


@app.get("/api/v1/settings")
def get_app_settings() -> JSONResponse:
    conn = _conn()
    _, parse_error = _read_settings_from_review_domain()
    payload = _build_settings_payload(conn)
    payload["review_domain_error"] = parse_error
    app_cfg, app_err, app_src = _read_app_settings_md_debug()
    payload["app_settings_error"] = app_err
    payload["app_settings_source"] = app_src
    return JSONResponse(ok(payload))


@app.get("/api/v1/helpme")
def get_helpme_markdown() -> JSONResponse:
    p = _helpme_md_path()
    if not p.is_file():
        return JSONResponse(err("helpme.md not found"), status_code=404)
    text = p.read_text(encoding="utf-8", errors="replace")
    return JSONResponse(ok({"markdown": text, "source": p.as_posix()}))


@app.post("/api/v1/settings")
def save_app_settings(payload: dict[str, Any]) -> JSONResponse:
    conn = _conn()
    current = _build_settings_payload(conn)
    app_cfg, _ = _read_app_settings_md()
    presets_style_overlay: list[dict[str, Any]] | None = None
    if "chunk_limit" in payload:
        raw = payload.get("chunk_limit")
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return JSONResponse(err("chunk_limit must be integer"), status_code=400)
        if val < 1 or val > 500:
            return JSONResponse(err("chunk_limit must be between 1 and 500"), status_code=400)
        current["chunk_limit"] = val
        app_cfg["chunk_limit"] = val
    if "chunk_strategy" in payload:
        raw_cs = payload.get("chunk_strategy")
        if not isinstance(raw_cs, str):
            return JSONResponse(err("chunk_strategy must be a string"), status_code=400)
        v = raw_cs.strip().lower()
        if v not in (CHUNK_STRATEGY_BLANK, CHUNK_STRATEGY_STRUCTURED):
            return JSONResponse(err("chunk_strategy must be blank or structured"), status_code=400)
        current["chunk_strategy"] = v
        app_cfg["chunk_strategy"] = v
    if "disable_image_parse" in payload:
        current["disable_image_parse"] = bool(payload.get("disable_image_parse"))
        app_cfg["disable_image_parse"] = current["disable_image_parse"]
    if "md_index_mode" in payload:
        raw_m = payload.get("md_index_mode")
        if raw_m is not None and not isinstance(raw_m, str):
            return JSONResponse(err("md_index_mode must be a string"), status_code=400)
        mode = _normalize_md_index_mode(raw_m if isinstance(raw_m, str) else MD_INDEX_MODE_INCREMENTAL)
        current["md_index_mode"] = mode
        app_cfg["md_index_mode"] = mode
    if "active_skill_package_id" in payload:
        raw_id = payload.get("active_skill_package_id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return JSONResponse(err("active_skill_package_id must be a non-empty string"), status_code=400)
        spid = raw_id.strip()
        rr = repository_root()
        ensure_default_skill_package(rr)
        if not domain_path(rr, spid).is_file():
            return JSONResponse(err(f"审查技能包不存在或未包含 review_domain.md：{spid}"), status_code=400)
        app_cfg["active_skill_package_id"] = spid
        current["active_skill_package_id"] = spid
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
        current["focus_points"] = out
    if "focus_presets" in payload:
        raw_presets = payload.get("focus_presets")
        if raw_presets is None:
            current["focus_presets"] = []
        elif not isinstance(raw_presets, list):
            return JSONResponse(err("focus_presets must be a list"), status_code=400)
        else:
            cleaned: list[dict[str, Any]] = []
            seen: set[str] = set()
            for it in raw_presets:
                if not isinstance(it, dict):
                    continue
                pid = str(it.get("id") or "").strip()
                name = str(it.get("name") or "").strip()
                fps = it.get("focus_points")
                if not pid or not name or not isinstance(fps, list):
                    continue
                if pid in seen:
                    continue
                focus_points = [str(x).strip() for x in fps if str(x).strip()]
                if not focus_points:
                    continue
                row: dict[str, Any] = {"id": pid, "name": name, "focus_points": focus_points}
                for k in ("review_role", "review_goals_principles", "output_requirements"):
                    v = it.get(k)
                    if not isinstance(v, str) or not v.strip():
                        return JSONResponse(
                            err(f"focus_presets[{pid}].{k} must be a non-empty string"),
                            status_code=400,
                        )
                    row[k] = v.strip()
                cleaned.append(row)
                seen.add(pid)
            current["focus_presets"] = cleaned
            presets_style_overlay = cleaned
    if "llm_settings" in payload:
        raw_llm = payload.get("llm_settings")
        if not isinstance(raw_llm, dict):
            return JSONResponse(err("llm_settings must be an object"), status_code=400)
        text_provider = str(raw_llm.get("text_provider") or "").strip() or DEFAULT_TEXT_PROVIDER
        text_base_url = str(raw_llm.get("text_base_url") or "").strip()
        text_model = str(raw_llm.get("text_model") or "").strip() or DEFAULT_TEXT_MODEL
        vl_model = str(raw_llm.get("vl_model") or "").strip() or DEFAULT_VL_MODEL
        vl_base_url = str(raw_llm.get("vl_base_url") or "").strip()
        embed_model = str(raw_llm.get("embed_model") or "").strip()
        embed_base_url = str(raw_llm.get("embed_base_url") or "").strip()
        current["llm_settings"] = {
            "text_provider": text_provider,
            "text_base_url": text_base_url,
            "text_model": text_model,
            "vl_model": vl_model,
            "vl_base_url": vl_base_url,
            "embed_model": embed_model,
            "embed_base_url": embed_base_url,
            # 先占位，后面会根据 payload 覆盖
            "has_text_api_key": bool(_get_text_llm_api_key_effective()),
            "has_vl_api_key": bool(_get_vl_llm_api_key_effective()),
        }
        app_cfg["llm_settings"] = {
            "text_provider": text_provider,
            "text_base_url": text_base_url,
            "text_model": text_model,
            "vl_model": vl_model,
            "vl_base_url": vl_base_url,
            "embed_model": embed_model,
            "embed_base_url": embed_base_url,
        }
        if embed_model and embed_base_url:
            configure_embeddings(base_url=embed_base_url, model=embed_model)

    # API Key: 随 app_settings.md 等持久化（不再写数据库业务表）
    text_key = None
    vl_key = None
    if "llm_api_key" in payload:
        current["llm_api_key"] = str(payload.get("llm_api_key") or "").strip()
    if "llm_text_api_key" in payload:
        text_key = str(payload.get("llm_text_api_key") or "").strip()
        current["llm_text_api_key"] = text_key
        app_cfg["llm_text_api_key"] = text_key
    if "llm_vl_api_key" in payload:
        vl_key = str(payload.get("llm_vl_api_key") or "").strip()
        current["llm_vl_api_key"] = vl_key
        app_cfg["llm_vl_api_key"] = vl_key

    if isinstance(current.get("llm_settings"), dict):
        # 让本次响应立即体现 key 的变化（测试也依赖此行为）
        if text_key is not None:
            current["llm_settings"]["has_text_api_key"] = bool(text_key)
        if vl_key is not None:
            current["llm_settings"]["has_vl_api_key"] = bool(vl_key)

    if presets_style_overlay is not None:
        slim: list[dict[str, Any]] = []
        for x in presets_style_overlay:
            if not isinstance(x, dict):
                continue
            pid = str(x.get("id") or "").strip()
            if not pid:
                continue
            row: dict[str, Any] = {"id": pid}
            for k in ("review_role", "review_goals_principles", "output_requirements"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    row[k] = v.strip()
            if len(row) > 1:
                slim.append(row)
        app_cfg["focus_preset_review_overlay"] = slim

    try:
        _write_settings_to_review_domain(current)
    except ValueError as e:
        return JSONResponse(err(str(e)), status_code=400)
    _write_app_settings_md(app_cfg)
    current = _build_settings_payload(conn)
    current["review_domain_error"] = None
    current["focus_combo_tips"] = _read_focus_combo_tips_from_review_domain()
    derived_presets = _get_focus_presets()
    if presets_style_overlay is not None:
        current["focus_presets"] = merge_preset_review_into_derived(derived_presets, presets_style_overlay)
    else:
        current["focus_presets"] = derived_presets
    return JSONResponse(ok(current))


@app.post("/api/v1/settings/review-domain/validate")
def validate_review_domain_payload(payload: dict[str, Any]) -> JSONResponse:
    text = str(payload.get("text") or "")
    parsed, parse_error = read_settings_from_domain_text(text)
    if parse_error:
        return JSONResponse(err(parse_error), status_code=400)
    fps = (parsed or {}).get("focus_points", [])
    return JSONResponse(ok({"focus_points": fps, "count": len(fps)}))


@app.post("/api/v1/settings/review-domain/import")
def import_review_domain_payload(payload: dict[str, Any]) -> JSONResponse:
    text = str(payload.get("text") or "")
    parsed, parse_error = read_settings_from_domain_text(text)
    if parse_error:
        return JSONResponse(err(parse_error), status_code=400)
    focus_points = (parsed or {}).get("focus_points")
    if not isinstance(focus_points, list) or not focus_points:
        return JSONResponse(err("review_domain.md 中未解析到有效关注点"), status_code=400)

    conn = _conn()
    dest = _active_review_domain_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_text(text, encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(f"写入 review_domain.md 失败：{e}"), status_code=500)
    current = _build_settings_payload(conn)
    current["review_domain_error"] = None
    return JSONResponse(ok(current))


@app.post("/api/v1/skill-packages/migrate-legacy-file")
def migrate_legacy_markdown_file_to_active_package(payload: dict[str, Any]) -> JSONResponse:
    """将仓库根目录下指定的 .md 解析并写入当前活动审查技能包的 review_domain.md（默认 default_skills.md）。"""
    bn = str(payload.get("filename") or "default_skills.md").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.md", bn):
        return JSONResponse(err("filename must be a basename like default_skills.md"), status_code=400)
    src = repository_root() / bn
    if not src.is_file():
        return JSONResponse(err(f"源文件不存在：{src}"), status_code=404)
    text = src.read_text(encoding="utf-8", errors="replace")
    _, parse_error = read_settings_from_domain_text(text)
    if parse_error:
        return JSONResponse(err(parse_error), status_code=400)
    dest = _active_review_domain_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_text(text, encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(f"写入失败：{e}"), status_code=500)
    conn = _conn()
    out = _build_settings_payload(conn)
    out["review_domain_error"] = None
    return JSONResponse(ok(out))


@app.post("/api/v1/skill-packages/{package_id}/focus-points/migrate")
def migrate_focus_points_to_files(package_id: str, payload: dict[str, Any]) -> JSONResponse:
    """将 review_domain.md 中的关注点块拆分为 focus-points/*.md 独立文件。"""
    rr = repository_root()
    ensure_default_skill_package(rr)
    pkg_d = package_dir(rr, package_id)
    domain_f = domain_path(rr, package_id)
    if not domain_f.is_file():
        return JSONResponse(err("review_domain.md not found for this package"), status_code=404)
    overwrite = bool(payload.get("overwrite", False))
    text = domain_f.read_text(encoding="utf-8", errors="replace")
    try:
        created = migrate_from_review_domain(text, pkg_d, overwrite=overwrite)
    except Exception as e:
        return JSONResponse(err(f"migration failed: {e}"), status_code=500)
    if created:
        # Bump manifest to schema_version 2
        mp = rr / "review_skill_packages" / package_id / "manifest.json"
        try:
            m = read_manifest(rr, package_id) or {}
            m["schema_version"] = "2"
            if "focus_refs" not in m:
                m["focus_refs"] = [{"id": fid} for fid in created]
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
    return JSONResponse(ok({"created": created, "count": len(created)}))


@app.get("/api/v1/skill-packages/{package_id}/focus-points")
def list_package_focus_points(package_id: str) -> JSONResponse:
    """列出技能包的所有 focus-points/*.md 文件（v2 格式）。"""
    rr = repository_root()
    ensure_default_skill_package(rr)
    pkg_d = package_dir(rr, package_id)
    fps = list_focus_points(pkg_d)
    return JSONResponse(ok({
        "package_id": package_id,
        "is_v2": is_v2_package(rr, package_id),
        "focus_points": [
            {
                "id": fp.id,
                "name": fp.name,
                "version": fp.version,
                "updated_at": fp.updated_at,
                "prompt": fp.prompt,
            }
            for fp in fps
        ],
    }))


class EvolveFocusPointBody(BaseModel):
    prompt: str = Field(..., description="新的 Prompt 正文")
    note: str = Field(default="", description="本次变更说明")


@app.put("/api/v1/skill-packages/{package_id}/focus-points/{focus_id}")
def evolve_focus_point_endpoint(package_id: str, focus_id: str, body: EvolveFocusPointBody) -> JSONResponse:
    """更新（进化）指定关注点的 Prompt，版本号递增，旧版本归档到 .aika/focus-history/。"""
    rr = repository_root()
    ensure_default_skill_package(rr)
    pkg_d = package_dir(rr, package_id)
    fp_path = focus_points_dir(rr, package_id) / f"focus-{focus_id}.md"
    fp = load_focus_point(fp_path)
    if fp is None:
        return JSONResponse(err(f"focus point {focus_id} not found in package {package_id}"), status_code=404)
    try:
        new_fp = evolve_focus_point(
            fp,
            new_prompt=body.prompt,
            note=body.note,
            package_dir=pkg_d,
            repo_root=rr,
        )
    except Exception as e:
        return JSONResponse(err(str(e)), status_code=500)
    return JSONResponse(ok({
        "id": new_fp.id,
        "name": new_fp.name,
        "version": new_fp.version,
        "updated_at": new_fp.updated_at,
    }))


@app.get("/api/v1/skill-packages/{package_id}/focus-points/{focus_id}/hints")
def list_focus_point_hints(package_id: str, focus_id: str) -> JSONResponse:
    """List queued evolution hints for a focus point (S7-2 backend)."""
    from backend.evolution_queue import list_hints_for_focus
    rr = repository_root()
    hints = list_hints_for_focus(rr, focus_id)
    return JSONResponse(ok({"focus_id": focus_id, "hints": hints, "count": len(hints)}))


@app.delete("/api/v1/skill-packages/{package_id}/focus-points/{focus_id}/hints")
def clear_focus_point_hints(package_id: str, focus_id: str) -> JSONResponse:
    """Clear the evolution hint queue for a focus point."""
    from backend.evolution_queue import clear_hints_for_focus
    rr = repository_root()
    n = clear_hints_for_focus(rr, focus_id)
    return JSONResponse(ok({"focus_id": focus_id, "cleared": n}))


@app.get("/api/v1/evolution-hints")
def list_all_evolution_hints() -> JSONResponse:
    """List all focus IDs with pending evolution hints."""
    from backend.evolution_queue import list_all_hint_focus_ids, list_hints_for_focus
    rr = repository_root()
    focus_ids = list_all_hint_focus_ids(rr)
    return JSONResponse(ok({
        "focus_ids": focus_ids,
        "total_focuses": len(focus_ids),
    }))


class ImprovePromptBody(BaseModel):
    dry_run: bool = Field(default=True, description="If true, return suggested prompt without saving")
    note: str = Field(default="", description="Change note")


@app.post("/api/v1/skill-packages/{package_id}/focus-points/{focus_id}/improve")
def improve_focus_point_with_llm(package_id: str, focus_id: str, body: ImprovePromptBody) -> JSONResponse:
    """
    LLM-assisted focus point rewrite using accumulated evolve-hints (S7-3).
    Reads hints from queue, generates improved prompt, optionally saves.
    """
    from backend.evolution_queue import clear_hints_for_focus, list_hints_for_focus
    rr = repository_root()
    hints = list_hints_for_focus(rr, focus_id)
    if not hints:
        return JSONResponse(err("no evolution hints found for this focus point"), status_code=400)

    ensure_default_skill_package(rr)
    pkg_d = package_dir(rr, package_id)
    fp_path = focus_points_dir(rr, package_id) / f"focus-{focus_id}.md"
    fp = load_focus_point(fp_path)
    if fp is None:
        return JSONResponse(err(f"focus point {focus_id} not found in package {package_id}"), status_code=404)

    hints_text = "\n".join(f"- {h['suggestion']}" for h in hints)
    improve_prompt = (
        f"你是一名AI评审专家，负责改进以下审查关注点的 Prompt。\n\n"
        f"当前 Prompt（focus:{fp.id} - {fp.name} v{fp.version}）：\n\n"
        f"{fp.prompt}\n\n"
        f"使用者反馈的改进建议：\n{hints_text}\n\n"
        f"请根据以上建议，重写这个 Prompt。要求：\n"
        f"1. 保留原有的分析步骤框架\n"
        f"2. 融入反馈中有价值的改进点\n"
        f"3. 保持简洁专业，用中文输出\n"
        f"4. 只输出新的 Prompt 正文，不要包含任何解释"
    )

    try:
        cfg = _build_text_llm_config(_conn(), timeout_s=60.0)
        provider = get_provider(cfg.provider)
        result = provider.chat(
            system="你是一名专业AI系统设计师，专注于审查类Prompt工程。",
            user=improve_prompt,
            config=cfg,
        )
        new_prompt = result.text.strip()
    except Exception as e:
        return JSONResponse(err(f"LLM call failed: {e}"), status_code=500)

    if body.dry_run:
        return JSONResponse(ok({
            "focus_id": focus_id,
            "dry_run": True,
            "current_version": fp.version,
            "suggested_prompt": new_prompt,
            "hints_used": len(hints),
        }))

    # Save the improved focus point
    try:
        new_fp = evolve_focus_point(
            fp,
            new_prompt=new_prompt,
            note=body.note or f"LLM-improved using {len(hints)} hint(s)",
            package_dir=pkg_d,
            repo_root=rr,
        )
        clear_hints_for_focus(rr, focus_id)
    except Exception as e:
        return JSONResponse(err(str(e)), status_code=500)

    return JSONResponse(ok({
        "focus_id": focus_id,
        "dry_run": False,
        "new_version": new_fp.version,
        "hints_cleared": len(hints),
    }))


@app.post("/api/v1/settings/review-domain/restore-default-skills-template")
def restore_default_skills_template() -> JSONResponse:
    """将 default_skills.md 复制为当前活动审查技能包的 review_domain.md。"""
    src = _default_skills_template_path()
    if not src.is_file():
        return JSONResponse(err("仓库内不存在 default_skills.md，无法从模板恢复"), status_code=404)
    dst = _active_review_domain_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(f"写入 review_domain.md 失败：{e}"), status_code=500)
    conn = _conn()
    current = _build_settings_payload(conn)
    _, parse_error = _read_settings_from_review_domain()
    current["review_domain_error"] = parse_error
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


@app.get("/api/v1/projects/{project_id}/ingest-status")
def get_project_ingest_status(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    md_out = project_md_out_dir(prj.id)
    md_out_exists = md_out.exists() and md_out.is_dir()
    chunk_count = int(dbm.count_project_chunks(conn, project_id=prj.id))
    review_runs_count = int(dbm.count_project_completed_outputs(conn, project_id=prj.id))
    return JSONResponse(
        ok(
            {
                "project_id": prj.id,
                "md_out": str(md_out),
                "md_out_exists": bool(md_out_exists),
                "chunk_count": int(chunk_count),
                "initialized": bool(md_out_exists and chunk_count > 0),
                "has_review_records": bool(review_runs_count > 0),
            }
        )
    )


@app.delete("/api/v1/projects/{project_id}")
def delete_project(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    # 只允许删除"已初始化但没有审查记录"的项目
    if int(dbm.count_project_completed_outputs(conn, project_id=prj.id)) > 0:
        return JSONResponse(
            err("项目已有已完成审查产物（conversation_outputs），为保护历史不可删除"),
            status_code=409,
        )
    # 先清理文件系统产物（失败不阻断 DB 删除）
    try:
        shutil.rmtree(project_md_out_dir(project_id), ignore_errors=True)
    except Exception:
        pass
    try:
        shutil.rmtree(project_export_dir(project_id), ignore_errors=True)
    except Exception:
        pass
    ok_del = dbm.delete_project(conn, project_id=project_id)
    return JSONResponse(ok({"deleted": bool(ok_del)}))


class CreateConversationBody(BaseModel):
    analysis_type: str = Field(min_length=1)
    title: str | None = None
    preset_id: str | None = None


@app.get("/api/v1/projects/{project_id}/conversations")
def list_conversations(project_id: int, limit: int = 50) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    items = dbm.list_conversations(conn, project_id=project_id, limit=int(limit))
    return JSONResponse(
        ok(
            {
                "conversations": [
                    {
                        "id": c.id,
                        "analysis_type": c.analysis_type,
                        "title": c.title,
                        "created_at": c.created_at,
                        "updated_at": c.updated_at,
                        "preset_id": c.preset_id,
                    }
                    for c in items
                ]
            }
        )
    )


@app.get("/api/v1/projects/{project_id}/conversations/preset-history")
def get_preset_history(project_id: int, preset_id: str = Query(..., min_length=1)) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    latest = dbm.find_latest_conversation_with_analysis_for_preset(
        conn, project_id=project_id, preset_id=preset_id
    )
    if latest is None:
        return JSONResponse(
            ok(
                {
                    "has_reviewed_history": False,
                    "latest_conversation": None,
                }
            )
        )
    return JSONResponse(
        ok(
            {
                "has_reviewed_history": True,
                "latest_conversation": {
                    "id": latest.id,
                    "title": latest.title,
                    "updated_at": latest.updated_at,
                },
            }
        )
    )


@app.get("/api/v1/projects/{project_id}/conversations/{conversation_id}")
def get_conversation_detail(project_id: int, conversation_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)
    last_run = dbm.get_latest_analysis_run(conn, conversation_id=conversation_id)
    has_analysis_run = last_run is not None
    last_focus: list[str] | None = None
    if last_run is not None:
        try:
            raw = json.loads(last_run.focus_points_json or "[]")
        except json.JSONDecodeError:
            raw = []
        if isinstance(raw, list):
            last_focus = [str(x).strip() for x in raw if str(x).strip()]
        else:
            last_focus = []
    last_run_meta: dict[str, Any] | None = None
    if last_run is not None and getattr(last_run, "run_metadata_json", None):
        try:
            parsed_m = json.loads(str(last_run.run_metadata_json))
            if isinstance(parsed_m, dict):
                last_run_meta = parsed_m
        except json.JSONDecodeError:
            last_run_meta = None
    payload_detail: dict[str, Any] = {
        "id": conv.id,
        "analysis_type": conv.analysis_type,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "preset_id": conv.preset_id,
        "has_analysis_run": has_analysis_run,
        "last_analysis_focus_points": last_focus,
    }
    if last_run_meta is not None:
        payload_detail["last_run_metadata"] = last_run_meta
    return JSONResponse(ok(payload_detail))


@app.get("/api/v1/projects/{project_id}/conversations/{conversation_id}/messages")
def list_conversation_messages(project_id: int, conversation_id: int, limit: int = 200) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)
    items = dbm.list_messages(conn, conversation_id=conversation_id, limit=int(limit))
    return JSONResponse(
        ok(
            {
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                    }
                    for m in items
                ]
            }
        )
    )


@app.post("/api/v1/projects/{project_id}/conversations")
def create_conversation(project_id: int, payload: CreateConversationBody) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    at = str(payload.analysis_type).strip()
    title = str(payload.title).strip() if payload.title is not None else ""
    if not title:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"{at} - {ts}"
    pid = str(payload.preset_id).strip() if payload.preset_id is not None else None
    preset_kw: dict[str, str | None] = {}
    if pid:
        preset_kw["preset_id"] = pid
    c = dbm.create_conversation(conn, project_id=project_id, analysis_type=at, title=title, **preset_kw)
    return JSONResponse(
        ok(
            {
                "id": c.id,
                "analysis_type": c.analysis_type,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "preset_id": c.preset_id,
            }
        )
    )


@app.delete("/api/v1/projects/{project_id}/conversations/{conversation_id}")
def delete_conversation(project_id: int, conversation_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)
    ok_del = dbm.delete_conversation(conn, conversation_id=conversation_id)
    return JSONResponse(ok({"deleted": bool(ok_del)}))


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


def _sse_stage(name: str, state: str, *, detail: str | None = None) -> str:
    payload: dict[str, Any] = {"type": "stage", "name": name, "state": state}
    if detail:
        payload["detail"] = detail
    return _sse_line(payload)

def _strip_think_blocks(text: str) -> str:
    """去除模型输出中的 <think>…</think> 块，避免对外展示或扰动后续处理。"""
    return re.sub(r"<think>[\s\S]*?</think>", "", (text or ""), flags=re.IGNORECASE).strip()


class AnalyzeStreamBody(BaseModel):
    chunk_limit: int = Field(default=40, ge=1, le=500)
    focus_points: list[str] = Field(min_length=1)
    incremental_user_notes: str | None = Field(default=None)
    review_role: str | None = Field(default=None)
    review_goals_principles: str | None = Field(default=None)
    output_requirements: str | None = Field(default=None)
    skill_id: str | None = Field(default=None)
    skill_version: str | None = Field(default=None)
    memory_snippets: list[dict[str, Any]] | None = Field(default=None)
    skill_meta: dict[str, Any] | None = Field(default=None)
    memory_query: str | None = Field(default=None)
    already_surfaced: list[str] | None = Field(default=None)
    # Sprint 2+5: multi-turn + deferred doc
    deferred_doc: bool = Field(default=False)   # True = 不自动生成文档，仅存发现到 metadata
    deep_mode: bool = Field(default=False)       # True = 分析后追加自我批评轮次
    user_message: str | None = Field(default=None)  # 用户原始输入，用于意图分类


class FollowupStreamBody(BaseModel):
    question: str = Field(min_length=1)


class AgentStreamBody(BaseModel):
    message: str = Field(min_length=1)


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    s = (text or "").strip()
    if not s:
        return None
    # 常见情况：模型输出前后夹杂解释；尽量提取第一个 JSON 对象
    start = s.find("{")
    if start < 0:
        return None
    # 简单括号配对
    depth = 0
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end <= start:
        return None
    raw = s[start:end]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _agent_event(kind: str, data: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"type": kind}
    if data:
        payload.update(data)
    return _sse_line(payload)


def _resolve_focus_definitions_for_subset(conn: Any, focus_names: list[str]) -> tuple[list[dict[str, str]], str | None]:
    """按名称从已加载关注点定义中解析本次审查子集（顺序去重）。"""
    if not focus_names:
        return [], "focus_points 不能为空"
    all_defs = _get_focus_points()
    by_name = {d["name"]: d for d in all_defs}
    seen: set[str] = set()
    ordered_names: list[str] = []
    for n in focus_names:
        n = str(n).strip()
        if not n or n in seen:
            continue
        seen.add(n)
        ordered_names.append(n)
    if not ordered_names:
        return [], "focus_points 不能为空"
    out: list[dict[str, str]] = []
    for n in ordered_names:
        if n not in by_name:
            return [], f"未知关注点：{n}（请从设置中已加载的关注点中选择）"
        d = by_name[n]
        fid = str(d["id"])
        prompt = str(d.get("prompt") or "")
        # Apply personal focus override if present (S6-3)
        personal_override = load_personal_focus_override(fid)
        if personal_override:
            prompt = personal_override
        out.append({"id": fid, "name": str(d["name"]), "prompt": prompt})
    return out, None


def _normalize_model_markdown(text: str) -> str:
    """当前只接受模型输出的 Markdown/纯文本（不再兼容 legacy JSON blocks）。"""
    cleaned = _strip_think_blocks(text)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned


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
                vl_api_key=_get_vl_llm_api_key_effective(),
                vl_model=_get_vl_model(),
                vl_base_url=_get_vl_base_url(),
                disable_image_parse=_get_disable_image_parse(),
            ):
                yield _sse_line({"type": "log", "text": line.rstrip("\n")})
            yield _sse_line({"type": "complete", "md_out": str(out_dir)})
        except Docs2MdError as e:
            yield _sse_line({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _embed_project_chunks(conn: Any, project_id: int, batch_size: int = 50) -> int:
    """
    Embed any document chunks that lack embeddings. Returns count of newly embedded chunks.
    Silently skips on embedding errors to keep indexing non-fatal.
    """
    if not embeddings_configured():
        return 0
    em = _get_embedding_model()
    rows = conn.execute(
        """
        SELECT c.id, c.text FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.project_id=? AND (c.embedding IS NULL OR c.embed_model != ?)
        LIMIT ?
        """,
        (int(project_id), em, batch_size),
    ).fetchall()
    count = 0
    for r in rows:
        try:
            text = str(r["text"] or "")
            vec = embed_text(text[:4000])
            dbm.update_chunk_embedding(
                conn,
                chunk_id=int(r["id"]),
                embedding_bytes=vec_to_bytes(vec),
                embed_model=em,
            )
            count += 1
        except Exception:
            continue
    if count:
        conn.commit()
    return count


@app.post("/api/v1/projects/{project_id}/index-md")
def index_md(project_id: int) -> JSONResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    md_root = project_md_out_dir(project_id)
    if not md_root.is_dir():
        return JSONResponse(err("md_out does not exist; run convert-md first"), status_code=400)
    n = sync_project_md_root(
        conn,
        project=prj,
        md_root=md_root,
        chunk_strategy=_get_chunk_strategy(),
        full_resync=_get_md_index_mode() == MD_INDEX_MODE_FULL,
    )
    embedded_chunks = 0
    if embeddings_configured():
        embedded_chunks = _embed_project_chunks(conn, project_id)
    return JSONResponse(ok({"indexed_documents": n, "embedded_chunks": embedded_chunks}))


def _safe_slug(text: str) -> str:
    s = re.sub(r"\s+", "_", str(text or "").strip())
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "analysis"


@app.post("/api/v1/projects/{project_id}/conversations/{conversation_id}/analyze/stream")
def analyze_conversation_stream(project_id: int, conversation_id: int, payload: AnalyzeStreamBody) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        raise HTTPException(status_code=404, detail="conversation not found")

    resolved, err = _resolve_focus_definitions_for_subset(conn, payload.focus_points)
    if err:
        raise HTTPException(status_code=400, detail=err)

    entries = dbm.list_chunk_entries(conn, project_id=project_id, limit=payload.chunk_limit)
    if not entries:
        raise HTTPException(status_code=400, detail="no chunks; run index-md after convert-md")

    rules_hash, rules_fn = _review_domain_file_hash_and_name()
    rr_meta = repository_root()
    sp_active = _get_active_skill_package_id()
    pkg_ver = package_version_for_hash(rr_meta, sp_active)
    mem_root = memory_root_under_repo(repository_root())
    snippets: list[dict[str, Any]] = []
    if payload.memory_snippets:
        for x in payload.memory_snippets:
            if isinstance(x, dict):
                snippets.append(
                    {
                        "id": str(x.get("id") or "").strip(),
                        "title": str(x.get("title") or "").strip(),
                        "body": str(x.get("body") or ""),
                    }
                )
    surf: set[str] = set(payload.already_surfaced or [])
    for s in snippets:
        sid = str(s.get("id") or "").strip()
        if sid:
            surf.add(sid)
    fq = " ".join(str(x) for x in payload.focus_points)
    mq = (payload.memory_query or fq).strip()
    embed_query_vec: list[float] | None = None
    if embeddings_configured() and mq:
        try:
            embed_query_vec = embed_text(mq[:500])
        except Exception:
            embed_query_vec = None
    recalled = recall_memory_snippets(
        memory_root=mem_root,
        project_id=project_id,
        query=mq,
        already_surfaced=surf,
        limit=4,
        db_conn=conn,
        embed_query_vec=embed_query_vec,
    )
    # Also recall from personal memory (~/.aika/memory/)
    personal_recalled = recall_personal_memory(
        mq,
        already_surfaced=surf | {str(s.get("id") or "") for s in recalled},
        limit=2,
        embed_query_vec=embed_query_vec,
    )
    recalled = recalled + personal_recalled
    snippets.extend(recalled)
    _recalled_meta = [
        {
            "id": str(s.get("id") or ""),
            "title": str(s.get("title") or ""),
            "score": float(s.get("score") or 0),
            "excerpt": str(s.get("body") or "")[:240],
            "source": str(s.get("source") or "project"),
        }
        for s in recalled
        if isinstance(s, dict) and str(s.get("id") or "").strip()
    ]

    skill_meta_payload: dict[str, Any] = dict(payload.skill_meta or {})
    skill_meta_payload.setdefault("skill_id", (payload.skill_id or "").strip())
    skill_meta_payload.setdefault("skill_version", (payload.skill_version or "").strip())
    skill_meta_payload.setdefault("active_skill_package_id", sp_active)
    skill_meta_payload.setdefault("package_manifest_version", pkg_ver)
    skill_meta_payload.setdefault("review_domain_ref", rules_fn)
    skill_meta_payload.setdefault("package_version_hash", rules_hash)
    skill_meta_payload.setdefault("rules_hash", rules_hash)

    hook_ctx: dict[str, Any] = {
        "project_id": project_id,
        "conversation_id": conversation_id,
        "focus_points": list(payload.focus_points),
        "chunk_limit": int(payload.chunk_limit),
        "extra_memory_snippets": [],
    }
    run_before_analyze_hooks(hook_ctx)
    _hook_extra_count = 0
    for extra in hook_ctx.get("extra_memory_snippets") or []:
        if isinstance(extra, dict) and (extra.get("body") or "").strip():
            _hook_extra_count += 1
            snippets.append(
                {
                    "id": str(extra.get("id") or "").strip() or "hook",
                    "title": str(extra.get("title") or "").strip(),
                    "body": str(extra.get("body") or ""),
                }
            )

    # --- Intent classification & state machine ---
    user_msg = (payload.user_message or payload.incremental_user_notes or "").strip()
    intent = classify_intent(user_msg) if user_msg else None
    if intent is not None:
        fsm_transition(conn, conversation_id=conversation_id, intent=intent, deep_mode=payload.deep_mode)

    # --- Rolling context: collect prior messages for multi-turn ---
    all_prior_rows = dbm.list_recent_messages(
        conn, conversation_id=conversation_id, limit=_MULTITURN_RECENT_LIMIT
    )
    prior_tuples = build_rolling_context(all_prior_rows)

    # --- Collect existing open findings to inject into system prompt ---
    open_findings = collect_open_findings(all_prior_rows)
    findings_ctx = format_open_findings_for_prompt(open_findings)

    # --- Focus IDs for finding extraction ---
    focus_ids_used = [str(d.get("id") or "") for d in resolved]

    cfg = _build_text_llm_config(conn, timeout_s=300.0)
    system = build_system_prompt(
        None,
        focus_definitions=resolved,
        review_role=payload.review_role,
        review_goals_principles=payload.review_goals_principles,
        output_requirements=payload.output_requirements,
        memory_snippets=snippets or None,
        skill_meta=skill_meta_payload or None,
    )
    # Append findings context + finding instruction to system prompt
    if findings_ctx:
        system = system + "\n\n" + findings_ctx
    system = system + "\n\n" + FINDING_INSTRUCTION

    user, used_entries = build_user_prompt_from_entries(entries)
    idx_lines_md = format_chunk_index_lines_markdown(used_entries)
    notes = (payload.incremental_user_notes or "").strip()
    if notes:
        user = "【用户补充说明（含重新审查时的增量信息）】\n" + notes + "\n\n" + user

    # 记录"本次运行"的用户侧请求（便于历史追溯）
    dbm.insert_message(
        conn,
        conversation_id=conversation_id,
        role="system",
        content=f"分析请求：focus_points={json.dumps(payload.focus_points, ensure_ascii=False)}; chunk_limit={int(payload.chunk_limit)}; deep_mode={payload.deep_mode}",
    )

    exp_dir = project_export_dir(project_id)
    exp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = _safe_slug(conv.title)
    kind = "rereview" if notes else "analyze"
    files = make_outputs_filenames(
        kind=kind,
        safe_base=base,
        ts=ts,
        include_fragments_index=bool(idx_lines_md.strip()),
    )
    out_path = exp_dir / files.final_filename
    milestones_path = exp_dir / files.milestones_filename
    fragments_index_path = (exp_dir / files.fragments_index_filename) if files.fragments_index_filename else None
    init_milestones_file(milestones_path)
    if idx_lines_md.strip() and fragments_index_path is not None:
        fragments_index_path.write_text(idx_lines_md, encoding="utf-8")

    def gen():
        try:
            # Explainability: skills/tools/hooks/memory used (persist to milestones + stream to UI)
            explain_stage = {"type": "stage", "stage": "评审策略", "status": "start"}
            append_milestone_event(milestones_path, explain_stage)
            yield _sse_stage("评审策略", "start")

            focus_sel = [{"id": str(d.get("id") or ""), "name": str(d.get("name") or "")} for d in resolved]
            tools_available = []
            try:
                from backend.tools.registry import list_tool_names as _list_tool_names

                tools_available = _list_tool_names()
            except Exception:
                tools_available = []
            hooks_available = list_hook_names()

            payload_skill = {
                "type": "explain_skills",
                "active_skill_package_id": sp_active,
                "review_domain_ref": rules_fn,
                "package_version_hash": rules_hash,
                "focus_points": focus_sel,
            }
            payload_tools = {"type": "explain_tools", "tools": tools_available}
            payload_hooks = {
                "type": "explain_hooks",
                "hooks": hooks_available,
                "extra_memory_snippets_count": int(_hook_extra_count),
            }
            payload_mem = {
                "type": "explain_memory",
                "query": mq,
                "items": _recalled_meta,
            }
            for p in (payload_skill, payload_tools, payload_hooks, payload_mem):
                append_milestone_event(milestones_path, p)
                yield _sse_line(p)

            explain_end = {"type": "stage", "stage": "评审策略", "status": "end"}
            append_milestone_event(milestones_path, explain_end)
            yield _sse_stage("评审策略", "end")

            ev = {"type": "stage", "stage": "解析文档", "status": "start", "detail": f"chunks={len(used_entries)}"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("解析文档", "start", detail=f"chunks={len(used_entries)}")
            ev = {"type": "stage", "stage": "解析文档", "status": "end"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("解析文档", "end")
            if idx_lines_md.strip():
                ev = {"type": "stage", "stage": "片段与来源索引", "status": "start"}
                append_milestone_event(milestones_path, ev)
                yield _sse_stage("片段与来源索引", "start")
                chunk_idx_payload = {
                    "type": "chunk_index",
                    "markdown": idx_lines_md,
                    "index_file_path": str(fragments_index_path) if fragments_index_path is not None else None,
                }
                append_milestone_event(milestones_path, chunk_idx_payload)
                yield _sse_line(
                    {
                        "type": "chunk_index",
                        "markdown": idx_lines_md,
                        "index_file_path": str(fragments_index_path) if fragments_index_path is not None else None,
                    }
                )
                ev = {"type": "stage", "stage": "片段与来源索引", "status": "end"}
                append_milestone_event(milestones_path, ev)
                yield _sse_stage("片段与来源索引", "end")
            ev = {"type": "stage", "stage": "思考分析", "status": "start", "detail": f"model={cfg.model}"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("思考分析", "start", detail=f"model={cfg.model}")
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(
                system=system, user=user, config=cfg, prior_messages=prior_tuples or None
            ):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            ev = {"type": "stage", "stage": "思考分析", "status": "end"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("思考分析", "end")
            _mem_milestone_items = [{"id": s.get("id"), "title": s.get("title")} for s in snippets]
            if _mem_milestone_items:
                append_milestone_event(
                    milestones_path,
                    {"type": "memory_injected", "items": _mem_milestone_items},
                )
            ev = {"type": "stage", "stage": "呈现结果", "status": "start"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("呈现结果", "start")
            body = _normalize_model_markdown("".join(acc))

            # --- Extract structured findings from LLM output ---
            new_findings = extract_findings_from_markdown(body, open_findings, focus_ids_used)
            for f in new_findings:
                yield _sse_line({"type": "finding", "finding": f.to_dict()})
            # Extract evolve hints and write to evolution queue (S7-1)
            evolve_hints = extract_evolve_hints(body)
            if evolve_hints:
                from backend.evolution_queue import append_evolve_hint
                turn_n = dbm.count_messages(conn, conversation_id=conversation_id) if hasattr(dbm, "count_messages") else 0
                for hint in evolve_hints:
                    try:
                        append_evolve_hint(
                            repository_root(),
                            focus_id=hint["focus_id"],
                            suggestion=hint["suggestion"],
                            conversation_id=conversation_id,
                            turn=turn_n,
                        )
                    except Exception:
                        pass

            # --- deep mode: self-critique pass ---
            critique_summary: str | None = None
            if payload.deep_mode and new_findings:
                yield _sse_line({"type": "status", "msg": "深度模式：正在进行自我审查…"})
                try:
                    critique_prompt = (
                        "请审查上述分析，指出：1) 可能的遗漏；2) 证据不足的发现；3) 过度解读的地方。"
                        "如分析已足够充分，回复\"分析已充分\"。请用一段话简短回复。"
                    )
                    critique_parts: list[str] = []
                    for piece in provider.chat_stream(
                        system="你是一名严谨的项目评审专家，负责对已完成的分析进行质量审查。",
                        user=body[:3000] + "\n\n" + critique_prompt,
                        config=cfg,
                        prior_messages=None,
                    ):
                        critique_parts.append(piece)
                    critique_summary = "".join(critique_parts).strip()
                    yield _sse_line({"type": "critique", "summary": critique_summary})
                except Exception:
                    pass

            run_meta = build_run_metadata(
                skill_id=payload.skill_id,
                skill_version=payload.skill_version,
                rules_hash=rules_hash,
                memory_injected=[{"id": s.get("id"), "title": s.get("title")} for s in snippets],
                rules_filename="review_domain.md",
                extra={
                    "active_skill_package_id": sp_active,
                    "package_manifest_version": pkg_ver,
                    "review_domain_ref": rules_fn,
                    "package_version_hash": rules_hash,
                    "findings_count": len(new_findings),
                    "deep_mode": payload.deep_mode,
                },
            )

            # --- Store findings in message metadata ---
            msg_metadata = MessageMetadata(
                mode=conv.mode,
                focus_points_used=focus_ids_used,
                findings=new_findings,
                refinement_round=0,
                self_critique_summary=critique_summary,
                deep_mode=payload.deep_mode,
            )

            if payload.deferred_doc:
                # 延迟文档生成模式：只存发现，不写文件
                dbm.insert_analysis_run(
                    conn,
                    conversation_id=conversation_id,
                    job_id=None,
                    focus_points=list(payload.focus_points),
                    chunk_limit=int(payload.chunk_limit),
                    chunk_strategy=_get_chunk_strategy(),
                    used_entries=list(used_entries),
                    output_markdown_path="",   # 无文件
                    run_metadata=run_meta,
                )
                dbm.insert_message(
                    conn, conversation_id=conversation_id, role="assistant",
                    content=body, metadata=msg_metadata.to_dict()
                )
                mark_awaiting(conn, conversation_id=conversation_id)
                append_milestone_event(milestones_path, {"type": "final", "deferred": True})
                yield _sse_line(
                    {
                        "type": "final",
                        "markdown": body,
                        "deferred_doc": True,
                        "findings": [f.to_dict() for f in new_findings],
                        "memory_files_injected": run_meta.get("memory_files_injected") or [],
                    }
                )
            else:
                # 传统模式：写文件 + 生成 conversation_output（向后兼容）
                out_path.write_text(body, encoding="utf-8")
                dbm.insert_analysis_run(
                    conn,
                    conversation_id=conversation_id,
                    job_id=None,
                    focus_points=list(payload.focus_points),
                    chunk_limit=int(payload.chunk_limit),
                    chunk_strategy=_get_chunk_strategy(),
                    used_entries=list(used_entries),
                    output_markdown_path=str(out_path),
                    run_metadata=run_meta,
                )
                run_after_analyze_hooks(
                    {
                        "project_id": project_id,
                        "conversation_id": conversation_id,
                        "focus_points": list(payload.focus_points),
                        "run_metadata": run_meta,
                        "output_markdown_path": str(out_path),
                    }
                )
                dbm.insert_message(
                    conn, conversation_id=conversation_id, role="assistant",
                    content=body, metadata=msg_metadata.to_dict()
                )
                dbm.insert_conversation_output(
                    conn,
                    conversation_id=conversation_id,
                    kind=kind,
                    final_filename=files.final_filename,
                    milestones_filename=files.milestones_filename,
                    fragments_index_filename=files.fragments_index_filename,
                )
                append_milestone_event(
                    milestones_path,
                    {"type": "final", "output_markdown_path": str(out_path)},
                )
                yield _sse_line(
                    {
                        "type": "final",
                        "markdown": body,
                        "output_markdown_path": str(out_path),
                        "output_fragments_index_path": (
                            str(fragments_index_path) if fragments_index_path is not None else None
                        ),
                        "findings": [f.to_dict() for f in new_findings],
                        "memory_files_injected": run_meta.get("memory_files_injected") or [],
                    }
                )

            # Token cost estimation (S7-5): Chinese ~2 chars/token, other ~4 chars/token
            def _estimate_tokens(s: str) -> int:
                cn = sum(1 for c in s if "一" <= c <= "鿿")
                rest = len(s) - cn
                return max(1, cn // 2 + rest // 4)

            input_text = system + user
            token_est = {
                "input_approx": _estimate_tokens(input_text),
                "output_approx": _estimate_tokens(body),
                "total_approx": _estimate_tokens(input_text + body),
                "deep_mode": payload.deep_mode,
            }
            yield _sse_line({"type": "pass_done", "pass": 1, "finding_count": len(new_findings), "token_est": token_est})
            ev = {"type": "stage", "stage": "呈现结果", "status": "end"}
            append_milestone_event(milestones_path, ev)
            yield _sse_stage("呈现结果", "end")
        except LLMError as e:
            append_milestone_event(
                milestones_path,
                {"type": "error", "message": str(e)},
            )
            yield _sse_line(
                {
                    "type": "error",
                    "message": f"[text-llm provider={cfg.provider} model={cfg.model} base_url={cfg.base_url or ''} repo_root={str(repository_root())}] {str(e)}",
                }
            )
        finally:
            try:
                finalize_milestones_file(milestones_path)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/v1/projects/{project_id}/conversations/{conversation_id}/followup/stream")
def followup_conversation_stream(project_id: int, conversation_id: int, payload: FollowupStreamBody) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        raise HTTPException(status_code=404, detail="conversation not found")

    q = str(payload.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question is empty")

    last_run = dbm.get_latest_analysis_run(conn, conversation_id=conversation_id)
    if last_run is None:
        raise HTTPException(status_code=400, detail="no prior analysis run; run analyze first")

    try:
        used_entries = json.loads(last_run.used_entries_json or "[]")
    except json.JSONDecodeError:
        used_entries = []
    if not isinstance(used_entries, list):
        used_entries = []

    prev_md = ""
    try:
        p = Path(str(last_run.output_markdown_path))
        if p.is_file():
            prev_md = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        prev_md = ""
    prev_excerpt = prev_md.strip()
    if len(prev_excerpt) > 6000:
        prev_excerpt = prev_excerpt[:6000] + "\n\n（上次结果已截断）\n"

    # 追问不再按关注点清单展开，改为通用"证据驱动"问答
    system = (
        "你是资深 IT 实施与项目评审顾问。用户将基于上一轮分析结果进行追问。\n"
        "要求：只输出可渲染的 Markdown 正文；必须使用简体中文（专有名词/缩写除外）。\n"
        "若引用证据，请标注片段编号（例如：片段 12），并与片段块头一致；若无证据，说明\"未在片段中发现\"。\n"
    )

    chunks_prompt, used_for_prompt = build_user_prompt_from_entries(used_entries)
    idx_followup_lines = format_chunk_index_lines_markdown(used_for_prompt)
    exp_fu = project_export_dir(project_id)
    exp_fu.mkdir(parents=True, exist_ok=True)
    ts_fu = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_fu = _safe_slug(conv.title)
    files_fu = make_outputs_filenames(
        kind="followup",
        safe_base=base_fu,
        ts=ts_fu,
        include_fragments_index=bool(idx_followup_lines.strip()),
    )
    followup_index_path = (
        (exp_fu / files_fu.fragments_index_filename) if files_fu.fragments_index_filename else None
    )
    if idx_followup_lines.strip() and followup_index_path is not None:
        followup_index_path.write_text(idx_followup_lines, encoding="utf-8")
    out_path = exp_fu / files_fu.final_filename
    milestones_path = exp_fu / files_fu.milestones_filename
    init_milestones_file(milestones_path)
    user = (
        "以下是上一轮分析结果（可能已截断）：\n\n"
        + prev_excerpt
        + "\n\n"
        + chunks_prompt
        + "\n\n用户追问：\n"
        + q
        + "\n"
    )

    dbm.insert_message(conn, conversation_id=conversation_id, role="user", content=q)

    recent_after = dbm.list_recent_messages(
        conn, conversation_id=conversation_id, limit=_MULTITURN_RECENT_LIMIT
    )
    prior_rows = recent_after[:-1] if recent_after else []
    prior_tuples = _message_rows_to_prior_tuples(prior_rows)

    cfg = _build_text_llm_config(conn, timeout_s=300.0)

    def gen():
        try:
            if idx_followup_lines.strip():
                append_milestone_event(
                    milestones_path, {"type": "stage", "stage": "片段与来源索引", "status": "start"}
                )
                yield _sse_stage("片段与来源索引", "start")
                append_milestone_event(
                    milestones_path,
                    {
                        "type": "chunk_index",
                        "markdown": idx_followup_lines,
                        "index_file_path": (
                            str(followup_index_path) if followup_index_path is not None else None
                        ),
                    },
                )
                yield _sse_line(
                    {
                        "type": "chunk_index",
                        "markdown": idx_followup_lines,
                        "index_file_path": (
                            str(followup_index_path) if followup_index_path is not None else None
                        ),
                    }
                )
                append_milestone_event(
                    milestones_path, {"type": "stage", "stage": "片段与来源索引", "status": "end"}
                )
                yield _sse_stage("片段与来源索引", "end")
            append_milestone_event(
                milestones_path,
                {"type": "stage", "stage": "追问", "status": "start", "detail": f"model={cfg.model}"},
            )
            yield _sse_stage("追问", "start", detail=f"model={cfg.model}")
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(
                system=system, user=user, config=cfg, prior_messages=prior_tuples or None
            ):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            append_milestone_event(milestones_path, {"type": "stage", "stage": "追问", "status": "end"})
            yield _sse_stage("追问", "end")
            body = _normalize_model_markdown("".join(acc))
            out_path.write_text(body, encoding="utf-8")
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=body)
            dbm.insert_conversation_output(
                conn,
                conversation_id=conversation_id,
                kind="followup",
                final_filename=files_fu.final_filename,
                milestones_filename=files_fu.milestones_filename,
                fragments_index_filename=files_fu.fragments_index_filename,
            )
            append_milestone_event(
                milestones_path,
                {
                    "type": "final",
                    "output_markdown_path": str(out_path),
                    "output_fragments_index_path": (
                        str(followup_index_path) if followup_index_path is not None else None
                    ),
                },
            )
            yield _sse_line({"type": "final", "markdown": body})
        except LLMError as e:
            append_milestone_event(milestones_path, {"type": "error", "message": str(e)})
            yield _sse_line(
                {
                    "type": "error",
                    "message": f"[text-llm provider={cfg.provider} model={cfg.model} base_url={cfg.base_url or ''} repo_root={str(repository_root())}] {str(e)}",
                }
            )
        finally:
            try:
                finalize_milestones_file(milestones_path)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/v1/projects/{project_id}/conversations/{conversation_id}/agent/stream")
def agent_conversation_stream(project_id: int, conversation_id: int, payload: AgentStreamBody) -> StreamingResponse:
    """
    自动编排（模式 C）：后端统一入口。模型先做路由决策（analyze/followup/clarify/need_ingest），
    不自动执行 convert/index；若语料不可用则提示用户去项目初始化页。
    """
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg = str(payload.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is empty")

    # 先写入用户消息，确保历史可回放
    dbm.insert_message(conn, conversation_id=conversation_id, role="user", content=msg)

    # 语料就绪检查：不自动补语料
    md_out = project_md_out_dir(project_id)
    md_out_exists = md_out.exists() and md_out.is_dir()
    chunk_count = int(dbm.count_project_chunks(conn, project_id=project_id))
    initialized = bool(md_out_exists and chunk_count > 0)

    cfg = _build_text_llm_config(conn, timeout_s=180.0)
    provider = get_provider(cfg.provider)

    # 路由候选：来自当前活动技能包（focus defs）
    focus_defs = _get_focus_points()
    focus_brief = [
        {"id": str(d.get("id") or ""), "name": str(d.get("name") or ""), "prompt": str(d.get("prompt") or "")}
        for d in focus_defs
        if str(d.get("id") or "").strip() and str(d.get("name") or "").strip()
    ]

    routing_system = (
        "你是审查编排助手。你的任务是根据用户输入，在不要求用户选择预设的前提下，"
        "从候选关注点中自动选择合适的关注点组合，并决定本轮应该执行：analyze（全文审查）、"
        "followup（基于已有结论追问）、clarify（需要用户澄清）、need_ingest（语料未初始化/已过期）。\n"
        "约束：\n"
        "- 你只能输出一个 JSON 对象，不要输出任何解释文字，不要使用代码围栏。\n"
        "- focus_ids 必须来自候选关注点的 id。\n"
        "- 如果发现用户问题缺少关键信息，应优先 intent=clarify，并给出 1-5 条澄清问题。\n"
        "- 如果语料不可用（索引缺失/过期）且用户要求基于文档审查，应 intent=need_ingest。\n"
        "输出 JSON 结构：\n"
        "{\n"
        '  \"intent\": \"analyze|followup|clarify|need_ingest\",\n'
        '  \"focus_ids\": [\"...\"] ,\n'
        '  \"memory_query\": \"\" ,\n'
        '  \"output_artifacts\": [\"review_md\",\"fragments_index_md\"],\n'
        '  \"clarify_questions\": [\"...\"]\n'
        "}\n"
    )
    routing_user = json.dumps(
        {
            "user_message": msg,
            "project_initialized": initialized,
            "candidate_focus_points": focus_brief,
        },
        ensure_ascii=False,
    )

    prior_rows = dbm.list_recent_messages(conn, conversation_id=conversation_id, limit=_MULTITURN_RECENT_LIMIT)
    prior_tuples = _message_rows_to_prior_tuples(prior_rows)

    def gen():
        # 1) routing
        yield _agent_event("agent_stage", {"stage": "routing", "state": "start"})
        acc: list[str] = []
        try:
            for piece in provider.chat_stream(system=routing_system, user=routing_user, config=cfg, prior_messages=prior_tuples or None):
                acc.append(piece)
        except LLMError as e:
            yield _agent_event("agent_stage", {"stage": "routing", "state": "end"})
            yield _agent_event("assistant_delta", {"text": f"路由失败：{str(e)}\n请尝试换一种表述，或先完成项目初始化。"})
            yield _agent_event("final", {"ok": False})
            return
        yield _agent_event("agent_stage", {"stage": "routing", "state": "end"})

        routing_raw = _strip_think_blocks("".join(acc))
        decision = _extract_first_json_object(routing_raw) or {}
        yield _agent_event("agent_decision", {"decision": decision})
        intent = str(decision.get("intent") or "").strip()
        focus_ids = decision.get("focus_ids")
        if not isinstance(focus_ids, list):
            focus_ids = []
        focus_ids = [str(x).strip() for x in focus_ids if str(x).strip()]
        memory_query = str(decision.get("memory_query") or "").strip()
        artifacts = decision.get("output_artifacts")
        if not isinstance(artifacts, list):
            artifacts = []
        artifacts = [str(x).strip() for x in artifacts if str(x).strip()]
        clarify_questions = decision.get("clarify_questions")
        if not isinstance(clarify_questions, list):
            clarify_questions = []
        clarify_questions = [str(x).strip() for x in clarify_questions if str(x).strip()]

        # 写入审计 system message（可复现）
        try:
            rules_hash, rules_fn = _review_domain_file_hash_and_name()
        except Exception:
            rules_hash, rules_fn = "", None
        skill_meta_payload = {
            "active_skill_package_id": _get_active_skill_package_id(),
            "review_domain_ref": rules_fn,
            "rules_hash": rules_hash,
            "agent_decision": decision,
        }
        dbm.insert_message(conn, conversation_id=conversation_id, role="system", content="agent_decision=" + json.dumps(skill_meta_payload, ensure_ascii=False))

        # 2) need_ingest / clarify
        if intent == "need_ingest" or (not initialized and intent in {"analyze", "followup"}):
            yield _agent_event(
                "need_ingest",
                {
                    "project_id": project_id,
                    "message": "语料未初始化或已过期：请先进入「项目初始化」完成转换与索引，然后再发起审查/追问。",
                },
            )
            dbm.insert_message(
                conn,
                conversation_id=conversation_id,
                role="assistant",
                content="语料未初始化或已过期：请先进入「项目初始化」完成转换与索引，然后再发起审查/追问。",
            )
            yield _agent_event("final", {"ok": True})
            return

        if intent == "clarify" or (not focus_ids and intent == "analyze"):
            qs = clarify_questions[:5]
            if not qs:
                qs = ["你希望我重点审查哪些方面？（例如：需求完整性、风险、接口与集成、里程碑/进度等）"]
            text = "为避免误审查，请先澄清以下问题：\n" + "\n".join([f"- {q}" for q in qs])
            yield _agent_event("agent_stage", {"stage": "clarifying", "state": "start"})
            yield _agent_event("assistant_delta", {"text": text})
            yield _agent_event("agent_stage", {"stage": "clarifying", "state": "end"})
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=text)
            yield _agent_event("final", {"ok": True})
            return

        # 3) execute analyze/followup（第一版：默认 analyze；followup 需要存在 last_run）
        last_run = dbm.get_latest_analysis_run(conn, conversation_id=conversation_id)
        if intent == "followup" and last_run is not None:
            # 复用 followup：直接调用现有 followup 逻辑太重，这里先用"追问"系统提示+上次结论片段
            q = msg
            try:
                used_entries = json.loads(last_run.used_entries_json or "[]")
            except json.JSONDecodeError:
                used_entries = []
            if not isinstance(used_entries, list):
                used_entries = []
            prev_md = ""
            try:
                p = Path(str(last_run.output_markdown_path))
                if p.is_file():
                    prev_md = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                prev_md = ""
            prev_excerpt = prev_md.strip()
            if len(prev_excerpt) > 6000:
                prev_excerpt = prev_excerpt[:6000] + "\n\n（上次结果已截断）\n"
            system = "你是资深 IT 实施与项目评审顾问。用户将基于既有审查结论进行追问，请直接回答，并引用必要的证据。"
            user = f"【上次审查结论摘要】\n{prev_excerpt}\n\n【用户追问】\n{q}\n"
            yield _agent_event("agent_stage", {"stage": "executing", "state": "start", "kind": "followup"})
            acc2: list[str] = []
            for piece in provider.chat_stream(system=system, user=user, config=cfg, prior_messages=prior_tuples or None):
                acc2.append(piece)
                yield _agent_event("assistant_delta", {"text": piece})
            body = _normalize_model_markdown("".join(acc2))
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=body)
            yield _agent_event("agent_stage", {"stage": "executing", "state": "end", "kind": "followup"})
            yield _agent_event("final", {"ok": True, "markdown": body})
            return

        # analyze
        resolved, err = _resolve_focus_definitions_for_subset(conn, focus_ids)
        if err:
            text = f"无法解析关注点：{err}\n请换一种表述，或在设置中检查当前审查技能包。"
            yield _agent_event("assistant_delta", {"text": text})
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=text)
            yield _agent_event("final", {"ok": False})
            return

        entries = dbm.list_chunk_entries(conn, project_id=project_id, limit=_get_chunk_limit())
        if not entries:
            yield _agent_event(
                "need_ingest",
                {
                    "project_id": project_id,
                    "message": "未检测到可用分块：请先进入「项目初始化」执行索引，然后再审查。",
                },
            )
            yield _agent_event("final", {"ok": True})
            return

        # 记忆召回：若路由给了 memory_query，用它；否则用关注点 id 拼接
        fq = " ".join(focus_ids)
        mq = (memory_query or fq).strip()
        mem_root = memory_root_under_repo(repository_root())
        _eq_vec: list[float] | None = None
        if embeddings_configured() and mq:
            try:
                _eq_vec = embed_text(mq[:500])
            except Exception:
                pass
        recalled = recall_memory_snippets(
            memory_root=mem_root, project_id=project_id, query=mq,
            already_surfaced=set(), limit=5,
            db_conn=conn, embed_query_vec=_eq_vec,
        )

        system = build_system_prompt(None, focus_definitions=resolved, memory_snippets=recalled or None, skill_meta=skill_meta_payload)
        user, used_entries = build_user_prompt_from_entries(entries)

        exp_dir = project_export_dir(project_id)
        exp_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = _safe_slug(conv.title)
        files = make_outputs_filenames(kind="analyze", safe_base=base, ts=ts, include_fragments_index=True)
        out_path = exp_dir / files.final_filename
        milestones_path = exp_dir / files.milestones_filename
        fragments_index_path = (exp_dir / files.fragments_index_filename) if files.fragments_index_filename else None
        init_milestones_file(milestones_path)

        idx_lines_md = format_chunk_index_lines_markdown(used_entries)
        if idx_lines_md.strip() and fragments_index_path is not None:
            fragments_index_path.write_text(idx_lines_md, encoding="utf-8")

        yield _agent_event("agent_stage", {"stage": "executing", "state": "start", "kind": "analyze"})
        if idx_lines_md.strip():
            yield _agent_event(
                "artifact_ready",
                {
                    "label": "片段索引.md",
                    "download_path": f"/api/v1/files/{project_id}/{files.fragments_index_filename}",
                    "placement_hint": "left",
                },
            )
        acc3: list[str] = []
        for piece in provider.chat_stream(system=system, user=user, config=cfg, prior_messages=prior_tuples or None):
            acc3.append(piece)
            yield _agent_event("assistant_delta", {"text": piece})
        body = _normalize_model_markdown("".join(acc3))
        out_path.write_text(body, encoding="utf-8")
        dbm.insert_analysis_run(
            conn,
            conversation_id=conversation_id,
            job_id=None,
            focus_points=list(focus_ids),
            chunk_limit=int(_get_chunk_limit()),
            chunk_strategy=_get_chunk_strategy(),
            used_entries=list(used_entries),
            output_markdown_path=str(out_path),
            run_metadata=build_run_metadata(
                skill_id=None,
                skill_version=None,
                rules_hash=skill_meta_payload.get("rules_hash") or "",
                memory_injected=[{"id": s.get("id"), "title": s.get("title")} for s in recalled],
                rules_filename="review_domain.md",
                extra={"active_skill_package_id": skill_meta_payload.get("active_skill_package_id")},
            ),
        )
        dbm.insert_conversation_output(
            conn,
            conversation_id=conversation_id,
            kind="analyze",
            final_filename=files.final_filename,
            milestones_filename=files.milestones_filename,
            fragments_index_filename=files.fragments_index_filename,
        )
        dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=body)
        finalize_milestones_file(milestones_path)

        yield _agent_event(
            "artifact_ready",
            {
                "label": "审查结果.md",
                "download_path": f"/api/v1/files/{project_id}/{files.final_filename}",
                "placement_hint": "left",
            },
        )
        yield _agent_event("agent_stage", {"stage": "executing", "state": "end", "kind": "analyze"})
        yield _agent_event("final", {"ok": True, "markdown": body})

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


class GenerateReportBody(BaseModel):
    title: str | None = Field(default=None)
    include_resolved: bool = Field(default=False)


@app.post("/api/v1/projects/{project_id}/conversations/{conversation_id}/generate-report")
def generate_conversation_report(
    project_id: int, conversation_id: int, payload: GenerateReportBody
) -> JSONResponse:
    """
    聚合本 conversation 的所有结构化发现，由 LLM 生成正式评审报告。
    只在用户显式触发时调用，不自动生成。
    """
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        return JSONResponse(err("project not found"), status_code=404)
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)

    messages = dbm.list_messages(conn, conversation_id=conversation_id)
    all_findings = collect_all_findings(messages)
    if not payload.include_resolved:
        all_findings = [f for f in all_findings if f.status != FindingStatus.RESOLVED]
    all_findings = deduplicate_findings(all_findings)

    if not all_findings:
        return JSONResponse(err("本次审查暂无发现，无法生成报告"), status_code=400)

    # 按严重程度排序：high → medium → low，再按 focus_id 分组
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_findings.sort(key=lambda f: (severity_order.get(f.severity, 9), f.focus_id))

    findings_text = "\n".join(
        f"- [{f.severity.upper()}] [{f.focus_id}] {f.title}：{f.evidence}"
        for f in all_findings
    )
    report_title = (payload.title or f"{conv.title} 评审报告").strip()

    report_system = (
        "你是一名专业项目评审报告撰写专家。"
        "请将以下结构化发现整理为正式的项目评审报告，使用规范的文档语气（非对话语气），"
        "按严重程度分节，每条发现展开说明影响和建议，输出标准 Markdown 格式。"
    )
    report_user = f"# {report_title}\n\n以下是本次审查发现的问题清单：\n\n{findings_text}\n\n请生成完整评审报告。"

    cfg = _build_text_llm_config(conn, timeout_s=300.0)
    provider = get_provider(cfg.provider)
    try:
        report_parts: list[str] = []
        for piece in provider.chat_stream(
            system=report_system, user=report_user, config=cfg, prior_messages=None
        ):
            report_parts.append(piece)
        report_body = _normalize_model_markdown("".join(report_parts))
    except LLMError as e:
        return JSONResponse(err(f"LLM error: {e}"), status_code=500)

    exp_dir = project_export_dir(project_id)
    exp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = _safe_slug(report_title)
    files = make_outputs_filenames(kind="report", safe_base=base, ts=ts, include_fragments_index=False)
    out_path = exp_dir / files.final_filename
    milestones_path = exp_dir / files.milestones_filename
    out_path.write_text(report_body, encoding="utf-8")
    init_milestones_file(milestones_path)
    finalize_milestones_file(milestones_path)

    dbm.insert_conversation_output(
        conn,
        conversation_id=conversation_id,
        kind="report",
        final_filename=files.final_filename,
        milestones_filename=files.milestones_filename,
    )

    return JSONResponse(
        ok(
            {
                "report_markdown": report_body,
                "output_markdown_path": str(out_path),
                "findings_count": len(all_findings),
                "download_path": f"/api/v1/outputs/{conversation_id}/download/{files.final_filename}",
            }
        )
    )


@app.get("/api/v1/projects/{project_id}/conversations/{conversation_id}/findings")
def get_conversation_findings(project_id: int, conversation_id: int) -> JSONResponse:
    """返回本 conversation 所有累积发现（供前端 findings 面板使用）。"""
    conn = _conn()
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)
    messages = dbm.list_messages(conn, conversation_id=conversation_id)
    findings = collect_all_findings(messages)
    findings = deduplicate_findings(findings)
    return JSONResponse(ok({"findings": [f.to_dict() for f in findings], "total": len(findings)}))


class UpdateFindingBody(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|resolved)$")


@app.patch("/api/v1/projects/{project_id}/conversations/{conversation_id}/findings/{finding_id}")
def update_finding_status(
    project_id: int, conversation_id: int, finding_id: str, payload: UpdateFindingBody
) -> JSONResponse:
    """更新某条发现的状态（open → acknowledged → resolved）。"""
    conn = _conn()
    conv = dbm.get_conversation(conn, conversation_id)
    if conv is None or conv.project_id != project_id:
        return JSONResponse(err("conversation not found"), status_code=404)

    messages = dbm.list_messages(conn, conversation_id=conversation_id)
    updated = False
    for msg in messages:
        if getattr(msg, "role", None) != "assistant":
            continue
        meta = MessageMetadata.from_json(getattr(msg, "metadata_json", None))
        for f in meta.findings:
            if f.id == finding_id:
                f.status = payload.status
                updated = True
        if updated:
            dbm.update_message_metadata(conn, message_id=msg.id, metadata=meta.to_dict())
            break

    if not updated:
        return JSONResponse(err(f"finding {finding_id} not found"), status_code=404)
    return JSONResponse(ok({"finding_id": finding_id, "status": payload.status}))


# 开发/本机部署：优先使用仓库内 `web/frontend/dist`（npm run build），避免 editable 安装仍沿用 wheel 里旧的 frontend_dist。
_dist = dev_dist_dir(_repo_root) or packaged_dist_dir()
if _dist is not None:
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
