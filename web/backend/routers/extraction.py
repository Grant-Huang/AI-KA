"""
Knowledge Extraction API.

Phase 1: Post-review extraction (审查后追问)
  POST /api/v1/projects/{pid}/conversations/{cid}/post-review-extraction/stream

Phase 2: Active extraction from Review Queue
  POST /api/v1/extraction/stream

Phase 4: Document upload extraction
  POST /api/v1/extraction/upload-material   — upload and index a document
  POST /api/v1/extraction/doc-stream        — extraction stream from uploaded doc

Knowledge Items CRUD:
  GET    /api/v1/knowledge-items
  GET    /api/v1/knowledge-items/{kid}
  PATCH  /api/v1/knowledge-items/{kid}
  POST   /api/v1/knowledge-items/{kid}/submit

Expert Profile:
  GET  /api/v1/expert-profile
  PUT  /api/v1/expert-profile
"""
from __future__ import annotations

import json

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from aika import db as dbm
from aika.paths import db_path
from backend.deps import get_conn
from backend.knowledge_models import ExpertProfile, next_ki_id
from backend.ki_parser import KI_INSTRUCTION, extract_clarify, extract_ki_items, extract_satisfaction
from backend.personal_memory import personal_aika_dir
from backend.repo_paths import repository_root
from backend.response import err, ok

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SATISFACTION_THRESHOLD = 0.85
_MAX_ROUNDS_PER_ITEM = 5

_EXTRACTION_STRATEGIES = {
    "fuzzy_signal": (
        "【策略：模糊信号追问】\n"
        "专家回答中出现'通常/一般/除非/基本上/这要看情况'等词时，必须追问：\n"
        "- 您说'通常'——在什么情况下会不一样？\n"
        "- '这要看情况'——请具体说说哪些因素会影响判断？"
    ),
    "gap_based": (
        "【策略：规则空白填充】\n"
        "向专家展示当前已有规则，然后问：\n"
        "- 这套规则里，您认为最容易漏掉什么场景？\n"
        "- 如果一个新顾问只用这套规则，他会在哪里栽跟头？"
    ),
    "critical_incident": (
        "【策略：关键事件技术】\n"
        "从具体案例倒推规则：\n"
        "- 您能举一个项目，当时很多人没发现问题，但您察觉到了风险？是什么让您察觉的？\n"
        "- 有没有遇到过看似正常最后出问题的项目？能说说吗？"
    ),
    "reverse_validation": (
        "【策略：反向验证】\n"
        "对现有规则做压力测试：\n"
        "- 我们有一条规则：[xxx]。在什么情况下这条规则是错的或有害的？\n"
        "- 哪类项目不应该应用这条规则？"
    ),
}


def _sse_line(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _get_llm_provider():
    """Build LLM provider + config from app_settings.md (same source as analysis routes)."""
    from aika.llm import LLMConfig, get_provider
    from backend.main import (  # reuse the same readers used by analysis routes
        _get_text_provider,
        _get_text_model,
        _get_text_base_url,
        _get_text_llm_api_key_effective,
    )
    cfg = LLMConfig(
        provider=_get_text_provider(),
        model=_get_text_model(),
        base_url=_get_text_base_url() or None,
        api_key=_get_text_llm_api_key_effective(),
        timeout_s=120.0,
    )
    return get_provider(cfg.provider), cfg


def _expert_profile_path() -> Path:
    return personal_aika_dir() / "memory" / "user" / "expert_profile.md"


def _load_expert_profile() -> ExpertProfile:
    path = _expert_profile_path()
    if not path.is_file():
        return ExpertProfile()
    try:
        text = path.read_text(encoding="utf-8")
        import re as _re
        domains_m = _re.search(r"domains:\s*\[(.*?)\]", text, _re.DOTALL)
        bg_m = _re.search(r"background:\s*(.*?)(?:\n\n|\Z)", text, _re.DOTALL)
        domains = []
        if domains_m:
            raw = domains_m.group(1)
            domains = [d.strip().strip('"').strip("'") for d in raw.split(",") if d.strip()]
        background = bg_m.group(1).strip() if bg_m else ""
        return ExpertProfile(domains=domains, background=background)
    except Exception:
        return ExpertProfile()


def _save_expert_profile(profile: ExpertProfile) -> None:
    path = _expert_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat()
    domains_str = ", ".join(f'"{d}"' for d in profile.domains)
    content = (
        f"---\nmemory_type: user\ntitle: 专家档案\nupdated_at: {now}\n---\n\n"
        f"domains: [{domains_str}]\n\nbackground: {profile.background}\n"
    )
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Expert Profile
# ---------------------------------------------------------------------------

class ExpertProfileUpdate(BaseModel):
    domains: list[str] | None = None
    background: str | None = None


@router.get("/api/v1/expert-profile")
def get_expert_profile() -> JSONResponse:
    profile = _load_expert_profile()
    return ok(profile.to_dict())


@router.put("/api/v1/expert-profile")
def update_expert_profile(body: ExpertProfileUpdate) -> JSONResponse:
    profile = _load_expert_profile()
    if body.domains is not None:
        profile.domains = body.domains
    if body.background is not None:
        profile.background = body.background
    profile.updated_at = datetime.utcnow().isoformat()
    _save_expert_profile(profile)
    return ok(profile.to_dict())


# ---------------------------------------------------------------------------
# Knowledge Items CRUD
# ---------------------------------------------------------------------------

class KnowledgeItemPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    content: str | None = None
    scope_note: str | None = None
    applicable_when: dict[str, Any] | None = None
    not_applicable_when: dict[str, Any] | None = None


_VALID_KI_STATUSES = {"pending", "approved", "rejected", "active"}


@router.get("/api/v1/knowledge-items")
def list_knowledge_items(
    status: str | None = None,
    project_id: int | None = None,
    limit: int = 100,
) -> JSONResponse:
    conn = get_conn()
    items = dbm.list_knowledge_items(conn, status=status, project_id=project_id, limit=limit)
    return ok({"items": items, "total": len(items)})


@router.get("/api/v1/knowledge-items/{kid}")
def get_knowledge_item(kid: str) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return ok(item)


@router.patch("/api/v1/knowledge-items/{kid}")
def patch_knowledge_item(kid: str, body: KnowledgeItemPatch) -> JSONResponse:
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    if body.status and body.status not in _VALID_KI_STATUSES:
        return err(f"Invalid status: {body.status}")
    if body.status:
        dbm.update_knowledge_item_status(conn, kid, status=body.status)
    return ok(dbm.get_knowledge_item(conn, kid))


@router.post("/api/v1/knowledge-items/{kid}/submit")
def submit_knowledge_item(kid: str) -> JSONResponse:
    """Move a knowledge item from 'pending' to 'approved' (Pending → ready for rule writing)."""
    conn = get_conn()
    item = dbm.get_knowledge_item(conn, kid)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    dbm.update_knowledge_item_status(conn, kid, status="approved")
    return ok({"submitted": kid, "status": "approved"})


# ---------------------------------------------------------------------------
# Phase 1: Post-Review Extraction Stream
# ---------------------------------------------------------------------------

class PostReviewBody(BaseModel):
    user_input: str
    prior_messages: list[dict[str, str]] | None = None
    findings_summary: list[dict[str, Any]] | None = None


def _build_post_review_system_prompt(
    findings_summary: list[dict[str, Any]] | None,
    expert_profile: ExpertProfile,
    existing_ki_count: int,
    domain_intro: str = "",
) -> str:
    profile_str = ""
    if expert_profile.domains:
        profile_str = f"专家领域：{', '.join(expert_profile.domains)}\n"
    if expert_profile.background:
        profile_str += f"背景：{expert_profile.background}\n"

    domain_str = f"【当前审查域背景】\n{domain_intro}\n\n" if domain_intro else ""

    findings_str = ""
    if findings_summary:
        lines = []
        for f in findings_summary[:10]:
            sev = f.get("severity", "")
            title = f.get("title", "")
            lines.append(f"  - [{sev}] {title}")
        findings_str = "本次审查发现（供参考）：\n" + "\n".join(lines) + "\n\n"

    return f"""你是知识工程师，负责从资深顾问的反馈中提取隐性知识并结构化为可复用规则。

{profile_str}
{domain_str}{findings_str}你的任务：
1. 了解顾问认为本次审查遗漏了哪些问题，以及 LLM 为什么没有发现
2. 从遗漏原因中提炼出可泛化的规则（适用于未来类似项目的规则）
3. 区分"这个项目特有的情况"和"可复用的行业/领域规律"

提问策略：
- 若顾问说「一般来说/通常/除非」→ 追问例外条件（模糊信号策略）
- 主动问："这个遗漏是只在这类项目才会出现，还是普遍规律？"
- 提炼出规则后，追问适用范围："这条规则适用于哪类项目？"

{KI_INSTRUCTION}

已提取条目数：{existing_ki_count}（不重复已有规则）
""".strip()


@router.post(
    "/api/v1/projects/{project_id}/conversations/{conversation_id}/post-review-extraction/stream"
)
def post_review_extraction_stream(
    project_id: int,
    conversation_id: int,
    body: PostReviewBody,
) -> StreamingResponse:
    conn = get_conn()
    expert_profile = _load_expert_profile()
    existing_items = dbm.list_knowledge_items(
        conn, project_id=project_id, limit=50
    )
    domain_intro, _ = _get_domain_context()

    def gen() -> Iterator[str]:
        try:
            provider, cfg = _get_llm_provider()
        except Exception as e:
            yield _sse_line({"type": "error", "message": f"LLM 初始化失败: {e}"})
            return

        system_prompt = _build_post_review_system_prompt(
            body.findings_summary, expert_profile, len(existing_items),
            domain_intro=domain_intro,
        )
        prior: list[tuple[str, str]] = []
        if body.prior_messages:
            prior = [(m["role"], m["content"]) for m in body.prior_messages]

        yield _sse_line({"type": "status", "msg": "提取知识中…"})
        acc: list[str] = []
        try:
            for chunk in provider.chat_stream(
                system=system_prompt,
                user=body.user_input,
                config=cfg,
                prior_messages=prior or None,
            ):
                if isinstance(chunk, dict):
                    text = chunk.get("content") or chunk.get("text") or ""
                else:
                    text = str(chunk)
                acc.append(text)
                yield _sse_line({"type": "text", "text": text})
        except Exception as e:
            yield _sse_line({"type": "error", "message": str(e)})
            return

        full_text = "".join(acc)

        # Parse ki items
        ki_items = extract_ki_items(full_text)
        clarify = extract_clarify(full_text)
        satisfaction = extract_satisfaction(full_text)

        # Persist ki items to DB and yield events
        new_kids: list[str] = []
        for ki in ki_items:
            all_existing = dbm.list_knowledge_items(conn, project_id=project_id, limit=200)
            kid = next_ki_id(all_existing)
            try:
                dbm.insert_knowledge_item(
                    conn,
                    id=kid,
                    extraction_focus_id=ki["focus_id"] or "general",
                    title=ki["title"],
                    content=ki["content"],
                    source_evidence=ki["source_evidence"],
                    confidence=ki["confidence"],
                    applicable_when=ki["applicable_when"],
                    not_applicable_when=ki["not_applicable_when"],
                    scope_note=ki["scope_note"],
                    source_role="senior_expert",
                    source_type="post_review",
                    extraction_strategy=ki["extraction_strategy"],
                    project_id=project_id,
                    conversation_id=conversation_id,
                )
                new_kids.append(kid)
                yield _sse_line({"type": "ki", "kid": kid, "item": dbm.get_knowledge_item(conn, kid)})

                # Also write to review_queue for senior expert review
                rq_id = f"rq-{uuid.uuid4().hex[:12]}"
                dbm.upsert_review_queue_item(
                    conn,
                    id=rq_id,
                    focus_id=ki["focus_id"] or "general",
                    suggestion=ki["title"] + ": " + ki["content"][:120],
                    source_role="senior_expert",
                    source_type="post_review",
                    project_id=project_id,
                    conversation_id=conversation_id,
                )
            except Exception:
                pass

        if clarify:
            yield _sse_line({"type": "clarify", "clarify": clarify})

        yield _sse_line({
            "type": "final",
            "new_ki_count": len(new_kids),
            "satisfaction": satisfaction,
            "needs_followup": satisfaction is None or satisfaction < _SATISFACTION_THRESHOLD,
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Phase 2: Active Extraction Stream (Review Queue driven)
# ---------------------------------------------------------------------------

class ActiveExtractionBody(BaseModel):
    user_input: str
    review_queue_item_id: str | None = None
    strategy: str = "gap_based"
    prior_messages: list[dict[str, str]] | None = None
    round_number: int = 1


def _build_active_extraction_system_prompt(
    rq_item: dict[str, Any] | None,
    strategy: str,
    expert_profile: ExpertProfile,
    existing_ki_count: int,
    current_rules_summary: str,
    domain_intro: str = "",
) -> str:
    strategy_hint = _EXTRACTION_STRATEGIES.get(strategy, _EXTRACTION_STRATEGIES["gap_based"])
    profile_str = ""
    if expert_profile.domains:
        profile_str = f"专家领域：{', '.join(expert_profile.domains)}\n"
    if expert_profile.background:
        profile_str += f"背景：{expert_profile.background}\n"

    domain_str = ""
    if domain_intro:
        domain_str = f"【当前审查域背景】\n{domain_intro}\n\n"

    rq_str = ""
    if rq_item:
        rq_str = (
            f"【当前审核候选条目】\n"
            f"关注点：{rq_item.get('focus_id', '')}\n"
            f"候选规律：{rq_item.get('suggestion', '')}\n\n"
        )

    return f"""你是知识工程师，专门从资深顾问的陈述中提取隐性知识，结构化为可复用的审查规则。

{profile_str}
{domain_str}{rq_str}【现有相关规则摘要】
{current_rules_summary or '（暂无相关规则）'}

{strategy_hint}

你的目标：
1. 帮助专家将直觉和经验转化为清晰的 IF-THEN 规则
2. 确保每条规则都有明确的适用范围
3. 追问例外条件，避免规则过于绝对

{KI_INSTRUCTION}

满意度判断标准（内部用）：
- 规则有具体 IF 条件 +0.3
- 规则有明确 THEN 结果 +0.2
- 有适用范围限定 +0.2
- 有具体案例佐证 +0.2
- 与现有规则有明确关系（补充/例外）+0.1
满意度 ≥ 0.85 时输出 <!-- satisfaction: x.xx -->

已提取条目数：{existing_ki_count}（不重复已有规则）
""".strip()


@router.post("/api/v1/extraction/stream")
def active_extraction_stream(body: ActiveExtractionBody) -> StreamingResponse:
    conn = get_conn()
    expert_profile = _load_expert_profile()
    existing_items = dbm.list_knowledge_items(conn, limit=100)
    rq_item = None
    if body.review_queue_item_id:
        rq_item = dbm.get_review_queue_item(conn, body.review_queue_item_id)

    domain_intro, current_rules_summary = _get_domain_context()

    def gen() -> Iterator[str]:
        try:
            provider, cfg = _get_llm_provider()
        except Exception as e:
            yield _sse_line({"type": "error", "message": f"LLM 初始化失败: {e}"})
            return

        system_prompt = _build_active_extraction_system_prompt(
            rq_item, body.strategy, expert_profile,
            len(existing_items), current_rules_summary,
            domain_intro=domain_intro,
        )
        prior: list[tuple[str, str]] = []
        if body.prior_messages:
            prior = [(m["role"], m["content"]) for m in body.prior_messages]

        yield _sse_line({"type": "status", "msg": "提取知识中…"})
        acc: list[str] = []
        try:
            for chunk in provider.chat_stream(
                system=system_prompt,
                user=body.user_input,
                config=cfg,
                prior_messages=prior or None,
            ):
                if isinstance(chunk, dict):
                    text = chunk.get("content") or chunk.get("text") or ""
                else:
                    text = str(chunk)
                acc.append(text)
                yield _sse_line({"type": "text", "text": text})
        except Exception as e:
            yield _sse_line({"type": "error", "message": str(e)})
            return

        full_text = "".join(acc)
        ki_items = extract_ki_items(full_text)
        clarify = extract_clarify(full_text)
        satisfaction = extract_satisfaction(full_text)

        new_kids: list[str] = []
        for ki in ki_items:
            all_existing = dbm.list_knowledge_items(conn, limit=200)
            kid = next_ki_id(all_existing)
            try:
                dbm.insert_knowledge_item(
                    conn,
                    id=kid,
                    extraction_focus_id=ki["focus_id"] or "general",
                    title=ki["title"],
                    content=ki["content"],
                    source_evidence=ki["source_evidence"],
                    confidence=ki["confidence"],
                    applicable_when=ki["applicable_when"],
                    not_applicable_when=ki["not_applicable_when"],
                    scope_note=ki["scope_note"],
                    source_role="senior_expert",
                    source_type="extraction",
                    extraction_strategy=body.strategy,
                    review_queue_item_id=body.review_queue_item_id,
                )
                new_kids.append(kid)
                yield _sse_line({"type": "ki", "kid": kid, "item": dbm.get_knowledge_item(conn, kid)})
            except Exception:
                pass

        # Mark review queue item as in_review if we got a satisfying response
        if rq_item and satisfaction and satisfaction >= _SATISFACTION_THRESHOLD:
            dbm.update_review_queue_status(conn, body.review_queue_item_id, status="in_review")

        if clarify:
            yield _sse_line({"type": "clarify", "clarify": clarify})

        auto_advance = (satisfaction is not None and satisfaction >= _SATISFACTION_THRESHOLD) or (
            body.round_number >= _MAX_ROUNDS_PER_ITEM
        )
        yield _sse_line({
            "type": "final",
            "new_ki_count": len(new_kids),
            "satisfaction": satisfaction,
            "auto_advance": auto_advance,
            "round_number": body.round_number,
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


def _get_domain_context() -> tuple[str, str]:
    """Return (domain_intro, rules_summary) from the active skill package."""
    try:
        from backend.skills import skill_packages_root, list_skill_packages
        from backend.skills.review_domain_io import (
            read_settings_from_package_dir, extract_domain_intro_preamble
        )
        from backend.skills.packages import package_dir

        root = skill_packages_root()
        packages = list_skill_packages(root)
        if not packages:
            return "", ""
        pkg = packages[0]
        pkg_dir = package_dir(root, pkg["id"])

        # Try to read preamble from review_domain.md
        domain_intro = ""
        domain_f = pkg_dir / "review_domain.md"
        if domain_f.is_file():
            text = domain_f.read_text(encoding="utf-8", errors="replace")
            preamble = extract_domain_intro_preamble(text)
            if preamble:
                domain_intro = preamble[:600].strip()

        settings, _ = read_settings_from_package_dir(pkg_dir)
        if not settings:
            return domain_intro, ""
        fps = (settings or {}).get("focus_points", [])
        if not fps:
            return domain_intro, ""
        lines = [f"- {fp.get('id', '')}: {fp.get('name', '')}" for fp in fps[:12]]
        return domain_intro, "\n".join(lines)
    except Exception:
        return "", ""


def _get_current_rules_summary() -> str:
    _, summary = _get_domain_context()
    return summary


# ---------------------------------------------------------------------------
# Phase 4: Document Upload Extraction
# ---------------------------------------------------------------------------

from fastapi import UploadFile, File, Form
import tempfile
import shutil


@router.post("/api/v1/extraction/upload-material")
async def upload_extraction_material(
    file: UploadFile = File(...),
    title: str = Form(default=""),
) -> JSONResponse:
    """Upload a document (PDF/DOCX/MD/TXT) as extraction material.

    Returns a material_id that can be used with /api/v1/extraction/doc-stream.
    The file is stored in a temp staging area; text extraction is done on-demand.
    """
    allowed_exts = {".pdf", ".docx", ".doc", ".md", ".txt"}
    original_name = file.filename or "upload"
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_exts:
        return err(f"Unsupported file type: {suffix}. Allowed: {sorted(allowed_exts)}")

    # Store in ~/.aika/extraction-materials/
    materials_dir = personal_aika_dir() / "extraction-materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    material_id = uuid.uuid4().hex[:16]
    dest = materials_dir / f"{material_id}{suffix}"

    content = await file.read()
    dest.write_bytes(content)

    return ok({
        "material_id": material_id,
        "original_name": original_name,
        "suffix": suffix,
        "size_bytes": len(content),
        "title": title or original_name,
        "path": str(dest),
    })


class DocExtractionBody(BaseModel):
    material_id: str
    user_input: str = ""
    strategy: str = "gap_based"
    prior_messages: list[dict[str, str]] | None = None


@router.post("/api/v1/extraction/doc-stream")
def doc_extraction_stream(body: DocExtractionBody) -> StreamingResponse:
    """Stream knowledge extraction from an uploaded document.

    Uses gap_based and reverse_validation strategies against existing rules.
    """
    materials_dir = personal_aika_dir() / "extraction-materials"
    # Find material file
    material_path: Path | None = None
    for p in materials_dir.glob(f"{body.material_id}*"):
        material_path = p
        break

    conn = get_conn()
    expert_profile = _load_expert_profile()
    existing_items = dbm.list_knowledge_items(conn, limit=100)
    domain_intro, current_rules_summary = _get_domain_context()

    def gen() -> Iterator[str]:
        if material_path is None or not material_path.is_file():
            yield _sse_line({"type": "error", "message": f"Material {body.material_id} not found"})
            return

        # Extract text from document
        yield _sse_line({"type": "status", "msg": "读取文档内容…"})
        doc_text = _extract_doc_text(material_path)
        if not doc_text:
            yield _sse_line({"type": "error", "message": "无法提取文档文本内容"})
            return

        try:
            provider, cfg = _get_llm_provider()
        except Exception as e:
            yield _sse_line({"type": "error", "message": f"LLM 初始化失败: {e}"})
            return

        strategy_hint = _EXTRACTION_STRATEGIES.get(body.strategy, _EXTRACTION_STRATEGIES["gap_based"])
        profile_str = ""
        if expert_profile.domains:
            profile_str = f"专家领域：{', '.join(expert_profile.domains)}\n"
        domain_str = f"【当前审查域背景】\n{domain_intro}\n\n" if domain_intro else ""

        system_prompt = f"""你是知识工程师，负责从规则文档中提取隐性知识并对照现有规则进行澄清。

{profile_str}
{domain_str}【现有相关规则摘要】
{current_rules_summary or '（暂无相关规则）'}

{strategy_hint}

你的任务：
1. 读取下方文档内容
2. 识别文档中明确或隐含的规则/判断原则
3. 对照现有规则，找出：(a) 新增内容；(b) 与现有规则的差异；(c) 文档中未说明适用条件的规则
4. 对每条提取到的规则，追问适用范围

{KI_INSTRUCTION}

已提取条目数：{len(existing_items)}（不重复已有规则）
""".strip()

        doc_section = f"\n\n【文档内容】\n{doc_text[:6000]}"
        user_msg = (body.user_input or "请分析此文档中的规则和判断原则，提取可复用的知识条目。") + doc_section

        yield _sse_line({"type": "status", "msg": "分析文档中…"})
        acc: list[str] = []
        prior: list[tuple[str, str]] = []
        if body.prior_messages:
            prior = [(m["role"], m["content"]) for m in body.prior_messages]
        try:
            for chunk in provider.chat_stream(
                system=system_prompt,
                user=user_msg,
                config=cfg,
                prior_messages=prior or None,
            ):
                if isinstance(chunk, dict):
                    text = chunk.get("content") or chunk.get("text") or ""
                else:
                    text = str(chunk)
                acc.append(text)
                yield _sse_line({"type": "text", "text": text})
        except Exception as e:
            yield _sse_line({"type": "error", "message": str(e)})
            return

        full_text = "".join(acc)
        ki_items = extract_ki_items(full_text)
        clarify = extract_clarify(full_text)
        satisfaction = extract_satisfaction(full_text)

        new_kids: list[str] = []
        for ki in ki_items:
            all_existing = dbm.list_knowledge_items(conn, limit=200)
            kid = next_ki_id(all_existing)
            try:
                dbm.insert_knowledge_item(
                    conn,
                    id=kid,
                    extraction_focus_id=ki["focus_id"] or "general",
                    title=ki["title"],
                    content=ki["content"],
                    source_evidence=ki["source_evidence"],
                    confidence=ki["confidence"],
                    applicable_when=ki["applicable_when"],
                    not_applicable_when=ki["not_applicable_when"],
                    scope_note=ki["scope_note"],
                    source_role="senior_expert",
                    source_type="extraction",
                    extraction_strategy=body.strategy,
                )
                new_kids.append(kid)
                yield _sse_line({"type": "ki", "kid": kid, "item": dbm.get_knowledge_item(conn, kid)})
            except Exception:
                pass

        if clarify:
            yield _sse_line({"type": "clarify", "clarify": clarify})
        yield _sse_line({
            "type": "final",
            "new_ki_count": len(new_kids),
            "satisfaction": satisfaction,
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


def _extract_doc_text(path: Path) -> str:
    """Extract plain text from a document file."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".md", ".txt"):
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix in (".docx", ".doc"):
            try:
                import docx
                doc = docx.Document(str(path))
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                return path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                parts = [page.extract_text() or "" for page in reader.pages]
                return "\n".join(parts)
            except ImportError:
                return ""
    except Exception:
        return ""
    return ""
