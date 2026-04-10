from __future__ import annotations

import json
import re
from typing import Any, Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
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
    format_chunk_index_markdown,
    merge_rules,
)
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
DEFAULT_CHUNK_STRATEGY = CHUNK_STRATEGY_BLANK
DEFAULT_TEXT_MODEL = "qwen3"
DEFAULT_VL_MODEL = "qwen3-vl-plus"
DEFAULT_TEXT_PROVIDER = "openai_compatible"
DEFAULT_MINIMAX_TEXT_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_DASHSCOPE_COMPAT_BASE_URL_CN = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return ok({"ok": True})


def _rules_md_path() -> Path:
    return repository_root() / "rules.md"


def _default_rules_md_path() -> Path:
    return repository_root() / "default_rules.md"


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


def _write_app_settings_md(payload: dict[str, Any]) -> None:
    p = _app_settings_md_path()
    obj = {
        "chunk_limit": int(payload.get("chunk_limit") or DEFAULT_CHUNK_LIMIT),
        "chunk_strategy": _normalize_chunk_strategy(payload.get("chunk_strategy")),
        "disable_image_parse": bool(payload.get("disable_image_parse", True)),
        "llm_settings": payload.get("llm_settings") if isinstance(payload.get("llm_settings"), dict) else {},
        "llm_text_api_key": str(payload.get("llm_text_api_key") or ""),
        "llm_vl_api_key": str(payload.get("llm_vl_api_key") or ""),
    }
    text = "# 应用设置\n\n```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```\n"
    p.write_text(text, encoding="utf-8")

def _helpme_md_path() -> Path:
    root = repository_root()
    direct = root / "helpme.md"
    if direct.is_file():
        return direct
    return root / "docs" / "helpme.md"


def _build_settings_payload(conn: Any) -> dict[str, Any]:
    return {
        "focus_points": _get_focus_points(),
        "focus_presets": _get_focus_presets(),
        "chunk_limit": _get_chunk_limit(),
        "chunk_strategy": _get_chunk_strategy(),
        "disable_image_parse": _get_disable_image_parse(),
        "llm_settings": _get_llm_settings(),
    }


def _read_settings_from_rules_md() -> tuple[dict[str, Any] | None, str | None]:
    """
    Read settings from rules.md. If missing/invalid, fallback to default_rules.md.
    """
    p = _rules_md_path()
    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
        parsed, err = _read_settings_from_rules_text(text)
        if parsed and not err:
            return parsed, None
        # fallback
        fallback = _default_rules_md_path()
        if fallback.is_file():
            ft = fallback.read_text(encoding="utf-8", errors="replace")
            parsed2, err2 = _read_settings_from_rules_text(ft)
            if parsed2 and not err2:
                return parsed2, f"rules.md 解析失败，已回退 default_rules.md：{err}"
        return None, err
    fallback = _default_rules_md_path()
    if fallback.is_file():
        ft = fallback.read_text(encoding="utf-8", errors="replace")
        parsed2, err2 = _read_settings_from_rules_text(ft)
        if parsed2 and not err2:
            return parsed2, "rules.md 不存在，已回退 default_rules.md"
        return None, err2
    return None, "rules.md 与 default_rules.md 均不存在"


def _is_combo_suggestions_heading(line: str) -> bool:
    """识别「组合使用建议」类二级标题（允许空格差异、括号说明等）。"""
    s = line.strip()
    m = re.match(r"^##\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    if "组合" not in title:
        return False
    # 与「组合」相关且像「建议/预设」节，避免误匹配正文里的「字符组合」等
    return any(x in title for x in ("建议", "预设", "搭配", "使用"))


def _normalize_table_line(raw: str) -> str:
    return raw.strip().replace("｜", "|")


def _is_md_table_separator_row(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False

    def cell_is_sep(c: str) -> bool:
        t = c.strip().replace(" ", "")
        return bool(t) and all(ch in "-:" for ch in t)

    return all(cell_is_sep(c) for c in cells)


def _extract_focus_combo_tips_from_rules_text(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    start = -1
    for i, raw in enumerate(lines):
        if _is_combo_suggestions_heading(raw):
            start = i
            break
    if start < 0:
        return []

    rows: list[dict[str, str]] = []
    in_table = False
    for raw in lines[start + 1 :]:
        line = _normalize_table_line(raw)
        if not line:
            continue
        if line.startswith("## ") and in_table:
            break
        if not line.startswith("|"):
            if in_table:
                break
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if _is_md_table_separator_row(cells):
            in_table = True
            continue
        # 表头：首列含「评审」或「阶段」等
        c0, c1 = cells[0], cells[1]
        if not in_table and ("评审" in c0 or "阶段" in c0 or "节点" in c0) and ("推荐" in c1 or "关注点" in c1):
            in_table = True
            continue
        if c0 in {"评审节点", "---"} and not in_table:
            in_table = True
            continue
        if c0.startswith("---") and len(c0) <= 5:
            in_table = True
            continue
        in_table = True
        stage = c0
        recommended = c1
        if stage and recommended:
            rows.append({"stage": stage, "recommended": recommended})
    return rows


def _read_focus_combo_tips_from_rules_md() -> list[dict[str, str]]:
    p = _rules_md_path()
    if not p.is_file():
        p = _default_rules_md_path()
        if not p.is_file():
            return []
    text = p.read_text(encoding="utf-8", errors="replace")
    return _extract_focus_combo_tips_from_rules_text(text)


def _slugify_id(text: str) -> str:
    s = re.sub(r"\s+", "_", (text or "").strip())
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "preset"


def _parse_focus_ids_from_recommended(text: str) -> list[str]:
    """
    rules.md 的推荐组合通常形如：`focus:req` + `` `focus:一审-文档结构` `` + ...
    支持 ASCII / 中文等 id，与 ### focus:<id> | 名称 一致即可映射。
    按在文本中出现的顺序去重。
    """
    t = str(text or "")
    out: list[str] = []
    seen: set[str] = set()
    # 优先匹配反引号块，避免与裸 focus: 重复计数；单次扫描保证顺序
    pat = re.compile(r"`\s*focus:([^`]+?)\s*`|focus:([^\s+|`]+)")
    for m in pat.finditer(t):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        x = str(raw or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _derive_focus_presets_from_combo_tips(
    combo_tips: list[dict[str, str]], focus_defs: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """
    将 rules.md 的“组合使用建议”转换为可保存/可选用的 focus_presets。
    主页与后端 analyze 接口使用的是关注点 name，因此这里把 focus:id 映射为 name。
    """
    id_to_name = {str(d.get("id") or "").strip(): str(d.get("name") or "").strip() for d in focus_defs if isinstance(d, dict)}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in combo_tips:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "").strip()
        recommended = str(row.get("recommended") or "").strip()
        if not stage or not recommended:
            continue
        fid_list = _parse_focus_ids_from_recommended(recommended)
        names = [id_to_name.get(fid) for fid in fid_list]
        focus_points = [n for n in names if n]
        if not focus_points:
            continue
        pid = f"rules_{_slugify_id(stage)}"
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid, "name": stage, "focus_points": focus_points})
    return out


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

    focus_presets = payload.get("focus_presets")
    if not isinstance(focus_presets, list):
        focus_presets = []

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

    # Preserve any custom tail content after combo section (best-effort).
    existing_suffix = ""
    if p.is_file():
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = -1
        for i, raw in enumerate(lines):
            if _is_combo_suggestions_heading(raw):
                start = i
                break
        if start >= 0:
            j = start + 1
            in_table = False
            while j < len(lines):
                line = lines[j].strip()
                if line.startswith("|"):
                    in_table = True
                    j += 1
                    continue
                if in_table:
                    # table ended; preserve the rest
                    break
                j += 1
            existing_suffix = "\n".join(lines[j:]).strip()

    combo_lines: list[str] = []
    if focus_presets:
        combo_lines.append("## 组合使用建议\n")
        combo_lines.append("| 评审节点 | 推荐组合的关注点 |")
        combo_lines.append("|---|---|")
        for it in focus_presets:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            fps = it.get("focus_points")
            if not name or not isinstance(fps, list):
                continue
            # 保存为 focus:id 的形式，便于人读与稳定
            # 这里假设 focus_points 存的是 name，先反查 id
            by_name = {str(d.get("name") or ""): str(d.get("id") or "") for d in focus_points if isinstance(d, dict)}
            ids = [by_name.get(str(x), "") for x in fps]
            ids = [x for x in ids if x]
            if not ids:
                continue
            rec = " + ".join(f"`focus:{x}`" for x in ids)
            combo_lines.append(f"| {name} | {rec} |")
        combo_lines.append("")

    md = (
        "# 分析规则配置\n\n"
        "该文件由 AI-KA 自动维护，用于保存关注点及其 Prompt。\n\n"
        "## 关注点块\n\n"
        + "\n".join(blocks)
    )
    if combo_lines:
        md = md.rstrip() + "\n\n---\n\n" + "\n".join(combo_lines).rstrip() + "\n"
    if existing_suffix:
        md = md.rstrip() + "\n\n" + existing_suffix.strip() + "\n"
    p.write_text(md, encoding="utf-8")


def _get_focus_points() -> list[dict[str, str]]:
    parsed, _ = _read_settings_from_rules_md()
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
    return DEFAULT_FOCUS_POINTS


def _get_focus_presets() -> list[dict[str, Any]]:
    parsed, _ = _read_settings_from_rules_md()
    tips = _read_focus_combo_tips_from_rules_md()
    focus_defs = _get_focus_points()
    derived = _derive_focus_presets_from_combo_tips(tips, focus_defs)
    # If future rules.md adds explicit presets, prefer that. For now derived is authoritative.
    return derived


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
    # model-aware fallback (avoid confusing "base_url required" errors)
    model = str((raw.get("text_model") if isinstance(raw, dict) else None) or "").strip()
    if model.lower().startswith("minimax-"):
        return DEFAULT_MINIMAX_TEXT_BASE_URL
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
    # model-aware fallback for qwen-vl on DashScope openai-compatible endpoint (CN)
    model = str((raw.get("vl_model") if isinstance(raw, dict) else None) or "").strip()
    if model.lower() in {"qwen3-vl-plus"}:
        return DEFAULT_DASHSCOPE_COMPAT_BASE_URL_CN
    return str(get_settings().llm_base_url or "").strip()


def _get_llm_settings() -> dict[str, Any]:
    return {
        "text_provider": _get_text_provider(),
        "text_base_url": _get_text_base_url(),
        "text_model": _get_text_model(),
        "vl_model": _get_vl_model(),
        "vl_base_url": _get_vl_base_url(),
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
    file_data, parse_error = _read_settings_from_rules_md()
    combo_tips = _read_focus_combo_tips_from_rules_md()
    payload = _build_settings_payload(conn)
    payload["focus_combo_tips"] = combo_tips
    payload["rules_md_error"] = parse_error
    app_cfg, app_err, app_src = _read_app_settings_md_debug()
    payload["app_settings_error"] = app_err
    payload["app_settings_source"] = app_src
    payload["repo_root"] = str(repository_root())
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
                cleaned.append({"id": pid, "name": name, "focus_points": focus_points})
                seen.add(pid)
            current["focus_presets"] = cleaned
    if "llm_settings" in payload:
        raw_llm = payload.get("llm_settings")
        if not isinstance(raw_llm, dict):
            return JSONResponse(err("llm_settings must be an object"), status_code=400)
        text_provider = str(raw_llm.get("text_provider") or "").strip() or DEFAULT_TEXT_PROVIDER
        text_base_url = str(raw_llm.get("text_base_url") or "").strip()
        text_model = str(raw_llm.get("text_model") or "").strip() or DEFAULT_TEXT_MODEL
        vl_model = str(raw_llm.get("vl_model") or "").strip() or DEFAULT_VL_MODEL
        vl_base_url = str(raw_llm.get("vl_base_url") or "").strip()
        current["llm_settings"] = {
            "text_provider": text_provider,
            "text_base_url": text_base_url,
            "text_model": text_model,
            "vl_model": vl_model,
            "vl_base_url": vl_base_url,
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
        }

    # API Key: 保存到 rules.md（不再写数据库）
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

    _write_settings_to_rules_md(current)
    _write_app_settings_md(app_cfg)
    current["rules_md_error"] = None
    # 与 GET /settings 对齐：保存后从 rules.md 再读一遍，避免前端拿不到 Tips/预设
    current["focus_combo_tips"] = _read_focus_combo_tips_from_rules_md()
    current["focus_presets"] = _get_focus_presets()
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


class CreateConversationBody(BaseModel):
    analysis_type: str = Field(min_length=1)
    title: str | None = None


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
                    {"id": c.id, "analysis_type": c.analysis_type, "title": c.title}
                    for c in items
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
    c = dbm.create_conversation(conn, project_id=project_id, analysis_type=at, title=title)
    return JSONResponse(ok({"id": c.id, "analysis_type": c.analysis_type, "title": c.title}))


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


def _extract_first_json_object_text(raw: str) -> str | None:
    s = raw.strip()
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


class AnalyzeStreamBody(BaseModel):
    chunk_limit: int = Field(default=40, ge=1, le=500)
    focus_points: list[str] = Field(min_length=1)


class FollowupStreamBody(BaseModel):
    question: str = Field(min_length=1)


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
        out.append(
            {
                "id": str(d["id"]),
                "name": str(d["name"]),
                "prompt": str(d.get("prompt") or ""),
            }
        )
    return out, None


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


def _analysis_blocks_to_markdown(analysis: dict[str, Any]) -> str:
    """
    Convert the legacy structured blocks format into Markdown for display/export.
    Keep it resilient: never raise, and never expose raw JSON unless unavoidable.
    """
    title = str(analysis.get("title") or "").strip()
    blocks = analysis.get("blocks") if isinstance(analysis.get("blocks"), list) else []

    out: list[str] = []
    if title:
        out.append(f"# {title}\n")

    def add(s: str) -> None:
        s2 = (s or "").rstrip()
        if not s2:
            return
        out.append(s2 + "\n")

    for b in blocks:
        if not isinstance(b, dict):
            add(str(b))
            continue
        t = str(b.get("type") or "").lower()
        if t == "heading":
            level = int(b.get("level") or 2)
            level = max(1, min(6, level))
            add(f"{'#' * level} {str(b.get('text') or '').strip()}")
            continue
        if t == "paragraph":
            add(str(b.get("text") or "").strip())
            continue
        if t == "tags":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            tags = [str(x) for x in items if str(x).strip()]
            if tags:
                add(" ".join(f"`{x}`" for x in tags))
            continue
        if t == "table":
            headers = b.get("headers") if isinstance(b.get("headers"), list) else []
            rows = b.get("rows") if isinstance(b.get("rows"), list) else []
            hs = [str(x) for x in headers]
            if not hs:
                add(str(b))
                continue
            add("| " + " | ".join(hs) + " |")
            add("| " + " | ".join(["---"] * len(hs)) + " |")
            for r in rows:
                if not isinstance(r, list):
                    continue
                cells = [str(x) for x in r]
                # pad / trim
                if len(cells) < len(hs):
                    cells += [""] * (len(hs) - len(cells))
                if len(cells) > len(hs):
                    cells = cells[: len(hs)]
                add("| " + " | ".join(cells) + " |")
            add("")
            continue
        if t == "cards":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            for it in items:
                if not isinstance(it, dict):
                    add(str(it))
                    continue
                it_title = str(it.get("title") or "").strip() or "项"
                add(f"## {it_title}")
                body = str(it.get("body") or "").strip()
                if body:
                    add(body)
                tags = it.get("tags") if isinstance(it.get("tags"), list) else []
                tg = [str(x) for x in tags if str(x).strip()]
                if tg:
                    add(" ".join(f"`{x}`" for x in tg))
                add("")
            continue
        if t == "tabs":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            for it in items:
                if not isinstance(it, dict):
                    continue
                tab = str(it.get("tab") or "").strip() or "Tab"
                add(f"## {tab}")
                inner = it.get("blocks") if isinstance(it.get("blocks"), list) else []
                # recursive (shallow)
                inner_obj = {"title": "", "blocks": inner}
                add(_analysis_blocks_to_markdown(inner_obj))
            continue
        if t == "callout":
            c_title = str(b.get("title") or "").strip()
            c_text = str(b.get("text") or "").strip()
            header = f"**{c_title}**\n\n" if c_title else ""
            if c_text:
                add("> " + (header + c_text).replace("\n", "\n> "))
                add("")
            continue
        # fallback
        txt = str(b.get("text") or "").strip()
        if txt:
            add(txt)
        else:
            add(json.dumps(b, ensure_ascii=False))

    md = "\n".join(out).strip() + "\n"
    return md


def _coerce_model_output_to_markdown(full_text: str) -> str:
    """
    Best-effort: if output is JSON (legacy structured format), convert to Markdown.
    Otherwise treat it as Markdown/plain text.
    """
    cleaned = (full_text or "").strip()
    # Always drop <think> before any parsing/normalization so that:
    # - streamed preamble doesn't leak into final output
    # - JSON extraction is not disturbed by think blocks
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        cleaned = cleaned.strip()
    # Try parse as JSON object; tolerate leading "reasoning"/preamble text by extracting the first JSON object.
    obj = None
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        extracted = _extract_first_json_object_text(cleaned)
        if extracted:
            try:
                obj = json.loads(extracted)
            except json.JSONDecodeError:
                obj = None
    if obj is None:
        # Treat as Markdown/plain text.
        return cleaned + ("\n" if cleaned and not cleaned.endswith("\n") else "")
    # Parsed JSON
    analysis = _normalize_analysis_for_ui(obj)
    md = _analysis_blocks_to_markdown(analysis)
    md = re.sub(r"<think>[\s\S]*?</think>", "", md, flags=re.IGNORECASE).strip()
    return md + ("\n" if md and not md.endswith("\n") else "")


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
    )
    return JSONResponse(ok({"indexed_documents": n}))


@app.post("/api/v1/projects/{project_id}/analyze/stream")
def analyze_stream_post(project_id: int, payload: AnalyzeStreamBody) -> StreamingResponse:
    conn = _conn()
    prj = dbm.get_project_by_id(conn, project_id)
    if prj is None:
        raise HTTPException(status_code=404, detail="project not found")

    resolved, err = _resolve_focus_definitions_for_subset(conn, payload.focus_points)
    if err:
        raise HTTPException(status_code=400, detail=err)

    entries = dbm.list_chunk_entries(conn, project_id=project_id, limit=payload.chunk_limit)
    if not entries:
        raise HTTPException(status_code=400, detail="no chunks; run index-md after convert-md")

    cfg = _build_text_llm_config(conn, timeout_s=300.0)
    system = build_system_prompt(None, focus_definitions=resolved)
    user, used_entries = build_user_prompt_from_entries(entries)

    def gen():
        provider = get_provider(cfg.provider)
        acc: list[str] = []
        try:
            yield _sse_stage("解析文档", "start", detail=f"chunks={len(used_entries)}")
            yield _sse_stage("解析文档", "end")
            yield _sse_stage("分析内容", "start", detail=f"model={cfg.model}")
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("分析内容", "end")
            full = "".join(acc)
            yield _sse_stage("呈现结果", "start")
            markdown = _coerce_model_output_to_markdown(full) + format_chunk_index_markdown(used_entries)
            yield _sse_line({"type": "final", "markdown": markdown})
            yield _sse_stage("呈现结果", "end")
        except LLMError as e:
            yield _sse_line(
                {
                    "type": "error",
                    "message": f"[text-llm provider={cfg.provider} model={cfg.model} base_url={cfg.base_url or ''} repo_root={str(repository_root())}] {str(e)}",
                }
            )

    return StreamingResponse(gen(), media_type="text/event-stream")


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

    cfg = _build_text_llm_config(conn, timeout_s=300.0)
    system = build_system_prompt(None, focus_definitions=resolved)
    user, used_entries = build_user_prompt_from_entries(entries)
    # 记录“本次运行”的用户侧请求（便于历史追溯）
    dbm.insert_message(
        conn,
        conversation_id=conversation_id,
        role="system",
        content=f"分析请求：focus_points={json.dumps(payload.focus_points, ensure_ascii=False)}; chunk_limit={int(payload.chunk_limit)}",
    )

    exp_dir = project_export_dir(project_id)
    exp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = _safe_slug(conv.title)
    out_path = exp_dir / f"{base}-{ts}.md"

    def gen():
        provider = get_provider(cfg.provider)
        acc: list[str] = []
        try:
            yield _sse_stage("解析文档", "start", detail=f"chunks={len(used_entries)}")
            yield _sse_stage("解析文档", "end")
            yield _sse_stage("分析内容", "start", detail=f"model={cfg.model}")
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("分析内容", "end")
            full = "".join(acc)
            yield _sse_stage("呈现结果", "start")
            markdown = _coerce_model_output_to_markdown(full) + format_chunk_index_markdown(used_entries)
            out_path.write_text(markdown, encoding="utf-8")
            dbm.insert_analysis_run(
                conn,
                conversation_id=conversation_id,
                job_id=None,
                focus_points=list(payload.focus_points),
                chunk_limit=int(payload.chunk_limit),
                chunk_strategy=_get_chunk_strategy(),
                used_entries=list(used_entries),
                output_markdown_path=str(out_path),
            )
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=markdown)
            yield _sse_line({"type": "final", "markdown": markdown, "output_markdown_path": str(out_path)})
            yield _sse_stage("呈现结果", "end")
        except LLMError as e:
            yield _sse_line(
                {
                    "type": "error",
                    "message": f"[text-llm provider={cfg.provider} model={cfg.model} base_url={cfg.base_url or ''} repo_root={str(repository_root())}] {str(e)}",
                }
            )

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

    # 追问不再按关注点清单展开，改为通用“证据驱动”问答
    system = (
        "你是资深 IT 实施与项目评审顾问。用户将基于上一轮分析结果进行追问。\n"
        "要求：只输出可渲染的 Markdown 正文；必须使用简体中文（专有名词/缩写除外）。\n"
        "若引用证据，请标注片段编号（例如：片段 12），并与片段块头一致；若无证据，说明“未在片段中发现”。\n"
    )

    chunks_prompt, used_for_prompt = build_user_prompt_from_entries(used_entries)
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

    cfg = _build_text_llm_config(conn, timeout_s=300.0)

    def gen():
        provider = get_provider(cfg.provider)
        acc: list[str] = []
        try:
            yield _sse_stage("追问", "start", detail=f"model={cfg.model}")
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("追问", "end")
            full = "".join(acc)
            markdown = _coerce_model_output_to_markdown(full) + format_chunk_index_markdown(used_for_prompt)
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=markdown)
            yield _sse_line({"type": "final", "markdown": markdown})
        except LLMError as e:
            yield _sse_line(
                {
                    "type": "error",
                    "message": f"[text-llm provider={cfg.provider} model={cfg.model} base_url={cfg.base_url or ''} repo_root={str(repository_root())}] {str(e)}",
                }
            )

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
