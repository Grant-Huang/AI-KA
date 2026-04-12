from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Iterator
from pathlib import Path

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


app = FastAPI(title="AI-KA Web", version="0.1.0")
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
DEFAULT_MINIMAX_TEXT_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_DASHSCOPE_COMPAT_BASE_URL_CN = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return ok({"ok": True})


def _active_rules_filename() -> str:
    """
    当前唯一使用的规则文件 basename（位于 AIKA_REPO_ROOT 下）。
    环境变量 AIKA_RULES_FILENAME，默认 rules.md。可改为 rules_new2.md 等；各文件彼此独立，同时只加载其中一个。
    仅允许 [A-Za-z0-9._-]+.md，禁止路径片段。
    """
    raw = (os.environ.get("AIKA_RULES_FILENAME") or "rules.md").strip()
    if not raw:
        return "rules.md"
    if os.path.basename(raw) != raw or ".." in raw:
        return "rules.md"
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.md", raw):
        return "rules.md"
    return raw


def _rules_md_path() -> Path:
    return repository_root() / _active_rules_filename()


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


MD_INDEX_MODE_INCREMENTAL = "incremental"
MD_INDEX_MODE_FULL = "full"


def _normalize_md_index_mode(v: Any) -> str:
    if isinstance(v, str) and v.strip().lower() == MD_INDEX_MODE_FULL:
        return MD_INDEX_MODE_FULL
    return MD_INDEX_MODE_INCREMENTAL


def _write_app_settings_md(payload: dict[str, Any]) -> None:
    p = _app_settings_md_path()
    obj = {
        "chunk_limit": int(payload.get("chunk_limit") or DEFAULT_CHUNK_LIMIT),
        "chunk_strategy": _normalize_chunk_strategy(payload.get("chunk_strategy")),
        "disable_image_parse": bool(payload.get("disable_image_parse", True)),
        "md_index_mode": _normalize_md_index_mode(payload.get("md_index_mode")),
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
    derived = _get_focus_presets()
    overlay = _read_focus_preset_review_overlay()
    merged_presets = _merge_preset_review_into_derived(derived, overlay) if overlay else derived
    return {
        "focus_points": _get_focus_points(),
        "focus_presets": merged_presets,
        "chunk_limit": _get_chunk_limit(),
        "chunk_strategy": _get_chunk_strategy(),
        "disable_image_parse": _get_disable_image_parse(),
        "md_index_mode": _get_md_index_mode(),
        "llm_settings": _get_llm_settings(),
        # 便于前端排查「预设不显示」：实际读取的仓库根与 rules 路径、原始组合表行
        "repo_root": str(repository_root()),
        "rules_filename": _active_rules_filename(),
        "rules_md_path": str(_rules_md_path()),
        "focus_combo_tips": _read_focus_combo_tips_from_rules_md(),
        "rules_composer_hint": _read_rules_composer_hint_from_rules_md(),
    }


def _read_settings_from_rules_md() -> tuple[dict[str, Any] | None, str | None]:
    """
    仅从当前规则文件（AIKA_RULES_FILENAME）读取；不自动读取 default_rules.md。
    default_rules.md 仅作人工/「恢复默认模板」复制源，见 restore_default_rules_template。
    """
    fn = _active_rules_filename()
    p = _rules_md_path()
    if not p.is_file():
        return None, f"{fn} 不存在：{p}。可将仓库内 default_rules.md 复制为该文件后编辑，或使用恢复接口。"
    text = p.read_text(encoding="utf-8", errors="replace")
    parsed, err = _read_settings_from_rules_text(text)
    if parsed and not err:
        return parsed, None
    return None, f"{fn} 解析失败：{err}"


def _normalize_md_line_for_heading(line: str) -> str:
    """全角 # 等与 Markdown 标题比对时做 NFKC，避免行首 `＃＃` 无法识别为 ##。"""
    return unicodedata.normalize("NFKC", (line or "").strip())


# 二级节：仅允许「关注点块」节与含「组合使用建议」的组合节。
_RULES_H2_FOCUS_BLOCK_MARKER = "关注点块"
_RULES_H2_COMBO_MARKER = "组合使用建议"

# 三级节：仅允许 ### focus:<id> | <名称>
_RULES_FOCUS_HEADING_LINE_RE = re.compile(
    r"^###\s+focus:\s*([^\s|]+)\s*\|\s*(.+)$"
)


def _is_allowed_rules_h2_line(line: str) -> bool:
    s = _normalize_md_line_for_heading(line)
    m = re.match(r"^##(?!#)\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    if _RULES_H2_FOCUS_BLOCK_MARKER in title:
        return True
    if _RULES_H2_COMBO_MARKER in title:
        return True
    return False


def _is_focus_block_h2_line(line: str) -> bool:
    s = _normalize_md_line_for_heading(line)
    m = re.match(r"^##(?!#)\s+(.+)$", s)
    if not m:
        return False
    return _RULES_H2_FOCUS_BLOCK_MARKER in m.group(1).strip()


def _rules_strict_schema_error(text: str) -> str | None:
    """
    强校验：二级标题（##）仅允许含「关注点块」的节或含「组合使用建议」的组合节；
    三级标题（###）仅允许「### focus:<id> | <名称>」；
    首个「### focus:」之前须已出现含「关注点块」的二级标题（如 ## 关注点块）。
    """
    seen_focus_block_h2 = False
    for line in text.splitlines():
        s = _normalize_md_line_for_heading(line)
        if re.match(r"^##(?!#)", s):
            if not _is_allowed_rules_h2_line(line):
                return (
                    "规则文件格式无效：二级标题（##）仅允许「关注点块」节（如 ## 关注点块）"
                    "或含「组合使用建议」的组合节标题（如 ## 组合使用建议）。"
                )
            if _is_focus_block_h2_line(line):
                seen_focus_block_h2 = True
            continue
        if re.match(r"^###\s+", s) and not re.match(r"^####", s):
            if not _RULES_FOCUS_HEADING_LINE_RE.match(s):
                return (
                    "规则文件格式无效：三级标题（###）仅允许「### focus:<id> | <名称>」格式，"
                    "例如 ### focus:handover | 运维交接与知识转移。"
                )
            if not seen_focus_block_h2:
                return (
                    "规则文件格式无效：在首个「### focus:…」之前必须有含「关注点块」的二级标题（如 ## 关注点块）。"
                )
    return None


def _is_combo_suggestions_heading(line: str) -> bool:
    """识别「组合使用建议」二级标题（标题中须含专用词「组合使用建议」）。"""
    s = unicodedata.normalize("NFKC", (line or "").strip())
    m = re.match(r"^##\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    return _RULES_H2_COMBO_MARKER in title


def _is_combo_like_h3_heading(line: str) -> bool:
    """
    识别「组合使用建议」类三级标题（### …）。
    说明：不能用 `"###".startswith("##")` 这类判断混到二级标题逻辑里；否则 `### 组合…` 会被当作普通正文吞进最后一个关注点。
    """
    s = unicodedata.normalize("NFKC", (line or "").strip())
    m = re.match(r"^###\s+(.+)$", s)
    if not m:
        return False
    title = m.group(1).strip()
    if "组合" not in title:
        return False
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
    """解析固定五列表：评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求"""
    lines = text.splitlines()
    start = -1
    for i, raw in enumerate(lines):
        if _is_combo_suggestions_heading(raw) or _is_combo_like_h3_heading(raw):
            start = i
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
        c0, c1 = cells[0], cells[1] if len(cells) > 1 else ""
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
        if len(cells) < 5:
            continue
        stage = c0
        recommended = c1
        review_role = _combo_cell_decode(cells[2])
        review_goals_principles = _combo_cell_decode(cells[3])
        output_requirements = _combo_cell_decode(cells[4])
        if stage and recommended:
            rows.append(
                {
                    "stage": stage,
                    "recommended": recommended,
                    "review_role": review_role,
                    "review_goals_principles": review_goals_principles,
                    "output_requirements": output_requirements,
                }
            )
    return rows


def _rules_text_aligned_with_focus_parse() -> str | None:
    """与关注点同源：仅当当前规则文件能成功解析关注点时，才用其全文抽组合表。"""
    p = _rules_md_path()
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    parsed, err = _read_settings_from_rules_text(text)
    if parsed and not err:
        return text
    return None


def _read_focus_combo_tips_from_rules_md() -> list[dict[str, str]]:
    """从与关注点同源的全文解析「组合使用建议」表格（见 _rules_text_aligned_with_focus_parse）。"""
    raw = _rules_text_aligned_with_focus_parse()
    if not raw:
        return []
    return _extract_focus_combo_tips_from_rules_text(raw)


def _slugify_id(text: str) -> str:
    s = re.sub(r"\s+", "_", (text or "").strip())
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "preset"


def _combo_cell_encode(text: str) -> str:
    """表格单元格写回：竖线转义、换行转为 <br>。"""
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("|", "&#124;")
    return s.replace("\n", "<br>")


def _combo_cell_decode(text: str) -> str:
    """解析表格单元格：还原 <br> 与竖线。"""
    s = str(text or "").strip()
    s = s.replace("<br>", "\n").replace("<BR>", "\n")
    s = s.replace("&#124;", "|")
    return s


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


def _norm_focus_id(s: str) -> str:
    """统一空白与兼容字符（如全角/半角连字符），便于表格内 focus:id 与 ### focus: 行一致匹配。"""
    return unicodedata.normalize("NFKC", (s or "").strip())


def _derive_focus_presets_from_combo_tips(
    combo_tips: list[dict[str, str]], focus_defs: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """
    将 rules.md 的“组合使用建议”转换为可保存/可选用的 focus_presets。
    主页与后端 analyze 接口使用的是关注点 name，因此这里把 focus:id 映射为 name。
    """
    id_to_name: dict[str, str] = {}
    for d in focus_defs:
        if not isinstance(d, dict):
            continue
        pid = _norm_focus_id(str(d.get("id") or ""))
        name = str(d.get("name") or "").strip()
        if pid and name:
            id_to_name[pid] = name
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in combo_tips:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "").strip()
        # 表格单元格内常见 **加粗**，与关注点 name 展示对齐
        stage = re.sub(r"\*+", "", stage).strip()
        recommended = str(row.get("recommended") or "").strip()
        if not stage or not recommended:
            continue
        fid_list = _parse_focus_ids_from_recommended(recommended)
        names = [id_to_name.get(_norm_focus_id(fid)) for fid in fid_list]
        focus_points = [n for n in names if n]
        if not focus_points:
            continue
        pid = f"rules_{_slugify_id(stage)}"
        if pid in seen:
            continue
        seen.add(pid)
        row_obj: dict[str, Any] = {"id": pid, "name": stage, "focus_points": focus_points}
        for key in ("review_role", "review_goals_principles", "output_requirements"):
            v = str(row.get(key) or "").strip()
            if v:
                row_obj[key] = v
        out.append(row_obj)
    return out


def _read_focus_preset_review_overlay() -> list[dict[str, Any]]:
    """从 app_settings.md 读取预设的审查角色/目标/输出要求（组合表可能不含这些列）。"""
    app_cfg, _ = _read_app_settings_md()
    raw = app_cfg.get("focus_preset_review_overlay")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict) and x.get("id")]


def _merge_preset_review_into_derived(
    derived: list[dict[str, Any]], overlay: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """将本次保存请求中的审查角色/目标/输出要求合并回从组合表推导的预设（按 id 对齐）。"""
    by_id = {str(x.get("id")): x for x in overlay if isinstance(x, dict) and x.get("id")}
    out: list[dict[str, Any]] = []
    for p in derived:
        pid = str(p.get("id") or "")
        o = by_id.get(pid)
        merged = dict(p)
        if o:
            for k in ("review_role", "review_goals_principles", "output_requirements"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    merged[k] = v.strip()
        out.append(merged)
    return out


def _trim_accidental_combo_section_in_prompt(prompt: str) -> str:
    """
    防御：旧版解析或历史保存会把「## 组合使用建议」及表格留在 prompt 内；
    按行截断到首个「组合*建议」类二级标题。
    """
    if not prompt:
        return prompt
    lines = prompt.splitlines()
    out: list[str] = []
    for line in lines:
        st = _normalize_md_line_for_heading(line)
        # 注意：在 Python 中 `"### x".startswith("##")` 为 True，必须用 `^##(?!#)` 区分真正的二级标题
        if re.match(r"^##(?!#)", st) and _is_combo_suggestions_heading(st):
            break
        if _is_combo_like_h3_heading(line):
            break
        out.append(line)
    return "\n".join(out).strip()


def _extract_rules_intro_preamble(text: str) -> str | None:
    """
    提取「# 分析规则配置」标题行之后、首个二级标题（## …）之前的正文（可含多行），
    用于写回时保留「该文件由…」「目的：」等完整前言，避免保存时误删。
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        st = _normalize_md_line_for_heading(lines[i]).strip()
        if st.startswith("# ") and not st.startswith("##") and "分析规则配置" in st:
            i += 1
            parts: list[str] = []
            while i < len(lines):
                st2 = _normalize_md_line_for_heading(lines[i]).strip()
                if re.match(r"^##(?!#)", st2):
                    break
                parts.append(lines[i])
                i += 1
            out = "\n".join(parts).strip()
            return out or None
        i += 1
    return None


def _read_rules_composer_hint_from_text(text: str) -> str | None:
    """
    从 # 分析规则配置 与首个 ## 之间的前言中解析「目的：」后的说明（可在行首或行内，如「…。目的：xxx」）。
    """
    preamble = _extract_rules_intro_preamble(text)
    if not preamble:
        return None
    m = re.search(r"目的\s*[:：]\s*([^\n\r]+)", preamble)
    if not m:
        return None
    hint = m.group(1).strip()
    return hint or None


def _read_rules_composer_hint_from_rules_md() -> str | None:
    p = _rules_md_path()
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    return _read_rules_composer_hint_from_text(text)


def _read_settings_from_rules_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    strict_err = _rules_strict_schema_error(text)
    if strict_err:
        return None, strict_err

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
                st = _normalize_md_line_for_heading(nxt)
                if st.startswith("### focus:"):
                    break
                # 二级标题：必须用 ^##(?!#)，避免 "### x".startswith("##") 的 Python 陷阱把三级标题当成正文
                if re.match(r"^##(?!#)", st):
                    break
                if _is_combo_like_h3_heading(nxt):
                    break
                buf.append(nxt)
                j += 1
            prompt = _trim_accidental_combo_section_in_prompt("\n".join(buf).strip())
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
    elif len(focus_points) == 0:
        # 写入时避免生成空关注点文件；不读取 default_rules.md，仅用内置占位（与「恢复模板」无关）
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
        prm = _trim_accidental_combo_section_in_prompt(str(item.get("prompt") or "").strip())
        if not fid or not name:
            continue
        blocks.append(f"### focus:{fid} | {name}\n{prm}\n")

    # Preserve any custom tail content after combo section (best-effort).
    existing_suffix = ""
    intro_block = "该文件由 AI-KA 自动维护，用于保存关注点及其 Prompt。\n\n"
    if p.is_file():
        old_text = p.read_text(encoding="utf-8", errors="replace")
        preserved_intro = _extract_rules_intro_preamble(old_text)
        if preserved_intro:
            # 保留「该文件由…」「目的：」等完整前言，勿仅写回「目的：」一行以免误删其它说明
            intro_block = preserved_intro.rstrip() + "\n\n"
        lines = old_text.splitlines()
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
        combo_lines.append("| 评审节点 | 推荐组合的关注点 | 审查角色 | 审查目标与原则 | 输出要求 |")
        combo_lines.append("| --- | --- | --- | --- | --- |")
        for it in focus_presets:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            fps = it.get("focus_points")
            if not name or not isinstance(fps, list):
                continue
            by_name = {str(d.get("name") or ""): str(d.get("id") or "") for d in focus_points if isinstance(d, dict)}
            ids = [by_name.get(str(x), "") for x in fps]
            ids = [x for x in ids if x]
            if not ids:
                continue
            rec = " + ".join(f"`focus:{x}`" for x in ids)
            rr = _combo_cell_encode(str(it.get("review_role") or ""))
            rg = _combo_cell_encode(str(it.get("review_goals_principles") or ""))
            ro = _combo_cell_encode(str(it.get("output_requirements") or ""))
            n_enc = _combo_cell_encode(name)
            rec_enc = _combo_cell_encode(rec)
            combo_lines.append(f"| {n_enc} | {rec_enc} | {rr} | {rg} | {ro} |")
        combo_lines.append("")

    md = (
        "# 分析规则配置\n\n"
        + intro_block
        + "## 关注点块\n\n"
        + "\n".join(blocks)
    )
    if combo_lines:
        md = md.rstrip() + "\n\n---\n\n" + "\n".join(combo_lines).rstrip() + "\n"
    if existing_suffix:
        md = md.rstrip() + "\n\n" + existing_suffix.strip() + "\n"
    strict_err = _rules_strict_schema_error(md)
    if strict_err:
        raise ValueError(strict_err)
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
    return []


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
    _, parse_error = _read_settings_from_rules_md()
    payload = _build_settings_payload(conn)
    payload["rules_md_error"] = parse_error
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
                    if isinstance(v, str) and v.strip():
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
        _write_settings_to_rules_md(current)
    except ValueError as e:
        return JSONResponse(err(str(e)), status_code=400)
    _write_app_settings_md(app_cfg)
    current["rules_md_error"] = None
    # 与 GET /settings 对齐：保存后从 rules.md 再读一遍，避免前端拿不到 Tips/预设
    current["focus_combo_tips"] = _read_focus_combo_tips_from_rules_md()
    derived_presets = _get_focus_presets()
    if presets_style_overlay is not None:
        current["focus_presets"] = _merge_preset_review_into_derived(derived_presets, presets_style_overlay)
    else:
        current["focus_presets"] = derived_presets
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


@app.post("/api/v1/settings/rules-md/restore-default-template")
def restore_default_rules_template() -> JSONResponse:
    """将 default_rules.md 复制为当前活动规则文件；仅用于手动重置/恢复，不会在读取失败时自动执行。"""
    src = _default_rules_md_path()
    if not src.is_file():
        return JSONResponse(err("仓库内不存在 default_rules.md，无法从模板恢复"), status_code=404)
    dst = _rules_md_path()
    try:
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except OSError as e:
        return JSONResponse(err(f"写入规则文件失败：{e}"), status_code=500)
    conn = _conn()
    current = _build_settings_payload(conn)
    _, parse_error = _read_settings_from_rules_md()
    current["rules_md_error"] = parse_error
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
    return JSONResponse(
        ok(
            {
                "id": conv.id,
                "analysis_type": conv.analysis_type,
                "title": conv.title,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "preset_id": conv.preset_id,
                "has_analysis_run": has_analysis_run,
                "last_analysis_focus_points": last_focus,
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
    incremental_user_notes: str | None = Field(default=None)
    review_role: str | None = Field(default=None)
    review_goals_principles: str | None = Field(default=None)
    output_requirements: str | None = Field(default=None)


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
        full_resync=_get_md_index_mode() == MD_INDEX_MODE_FULL,
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
    system = build_system_prompt(
        None,
        focus_definitions=resolved,
        review_role=payload.review_role,
        review_goals_principles=payload.review_goals_principles,
        output_requirements=payload.output_requirements,
    )
    user, used_entries = build_user_prompt_from_entries(entries)
    idx_lines_md = format_chunk_index_lines_markdown(used_entries)
    exp_dir = project_export_dir(project_id)
    exp_dir.mkdir(parents=True, exist_ok=True)
    ts_idx = datetime.now().strftime("%Y%m%d-%H%M%S")
    index_only_path = exp_dir / f"fragments-index-{ts_idx}.md"
    if idx_lines_md.strip():
        index_only_path.write_text(idx_lines_md, encoding="utf-8")

    def gen():
        try:
            yield _sse_stage("解析文档", "start", detail=f"chunks={len(used_entries)}")
            yield _sse_stage("解析文档", "end")
            if idx_lines_md.strip():
                yield _sse_stage("片段与来源索引", "start")
                yield _sse_line(
                    {
                        "type": "chunk_index",
                        "markdown": idx_lines_md,
                        "index_file_path": str(index_only_path),
                    }
                )
                yield _sse_stage("片段与来源索引", "end")
            yield _sse_stage("思考分析", "start", detail=f"model={cfg.model}")
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(system=system, user=user, config=cfg):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("思考分析", "end")
            yield _sse_stage("呈现结果", "start")
            body = _coerce_model_output_to_markdown("".join(acc))
            yield _sse_line({"type": "final", "markdown": body})
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
    system = build_system_prompt(
        None,
        focus_definitions=resolved,
        review_role=payload.review_role,
        review_goals_principles=payload.review_goals_principles,
        output_requirements=payload.output_requirements,
    )
    user, used_entries = build_user_prompt_from_entries(entries)
    idx_lines_md = format_chunk_index_lines_markdown(used_entries)
    notes = (payload.incremental_user_notes or "").strip()
    if notes:
        user = "【用户补充说明（含重新审查时的增量信息）】\n" + notes + "\n\n" + user

    prior_rows = dbm.list_recent_messages(
        conn, conversation_id=conversation_id, limit=_MULTITURN_RECENT_LIMIT
    )
    prior_tuples = _message_rows_to_prior_tuples(prior_rows)

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
    fragments_index_path = exp_dir / f"{base}-{ts}-fragments-index.md"
    if idx_lines_md.strip():
        fragments_index_path.write_text(idx_lines_md, encoding="utf-8")

    def gen():
        try:
            yield _sse_stage("解析文档", "start", detail=f"chunks={len(used_entries)}")
            yield _sse_stage("解析文档", "end")
            if idx_lines_md.strip():
                yield _sse_stage("片段与来源索引", "start")
                yield _sse_line(
                    {
                        "type": "chunk_index",
                        "markdown": idx_lines_md,
                        "index_file_path": str(fragments_index_path),
                    }
                )
                yield _sse_stage("片段与来源索引", "end")
            yield _sse_stage("思考分析", "start", detail=f"model={cfg.model}")
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(
                system=system, user=user, config=cfg, prior_messages=prior_tuples or None
            ):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("思考分析", "end")
            yield _sse_stage("呈现结果", "start")
            body = _coerce_model_output_to_markdown("".join(acc))
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
            )
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=body)
            yield _sse_line(
                {
                    "type": "final",
                    "markdown": body,
                    "output_markdown_path": str(out_path),
                    "output_fragments_index_path": str(fragments_index_path) if idx_lines_md.strip() else None,
                }
            )
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
    idx_followup_lines = format_chunk_index_lines_markdown(used_for_prompt)
    exp_fu = project_export_dir(project_id)
    exp_fu.mkdir(parents=True, exist_ok=True)
    ts_fu = datetime.now().strftime("%Y%m%d-%H%M%S")
    followup_index_path = exp_fu / f"{_safe_slug(conv.title)}-{ts_fu}-followup-fragments-index.md"
    if idx_followup_lines.strip():
        followup_index_path.write_text(idx_followup_lines, encoding="utf-8")
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
                yield _sse_stage("片段与来源索引", "start")
                yield _sse_line(
                    {
                        "type": "chunk_index",
                        "markdown": idx_followup_lines,
                        "index_file_path": str(followup_index_path),
                    }
                )
                yield _sse_stage("片段与来源索引", "end")
            yield _sse_stage("追问", "start", detail=f"model={cfg.model}")
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(
                system=system, user=user, config=cfg, prior_messages=prior_tuples or None
            ):
                acc.append(piece)
                yield _sse_line({"type": "delta", "text": piece})
            yield _sse_stage("追问", "end")
            body = _coerce_model_output_to_markdown("".join(acc))
            dbm.insert_message(conn, conversation_id=conversation_id, role="assistant", content=body)
            yield _sse_line({"type": "final", "markdown": body})
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


# 开发/本机部署：优先使用仓库内 `web/frontend/dist`（npm run build），避免 editable 安装仍沿用 wheel 里旧的 frontend_dist。
_dist = dev_dist_dir(_repo_root) or packaged_dist_dir()
if _dist is not None:
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
