"""Knowledge extraction router – AI-led expert interview with knowledge card extraction."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from aika import db as dbm
from aika.llm import LLMConfig, LLMError, get_provider
from backend.deps import get_conn
from backend.extraction_prompt import build_extraction_system_prompt
from backend.ki_parser import parse_ki_markers, strip_ki_markers
from backend.response import err, ok

router = APIRouter(prefix="/api/v1/extraction", tags=["extraction"])

_EXTRACTION_PROJECT_ID = 0  # sentinel: extraction conversations are not project-scoped


# ── Auth helper ──────────────────────────────────────────────

def _require_user(aika_token: str | None) -> int:
    if not aika_token:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = dbm.get_session_user_id(get_conn(), aika_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="会话已过期")
    return user_id


# ── SSE helpers ──────────────────────────────────────────────

def _sse(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


# ── LLM config ───────────────────────────────────────────────

def _llm_cfg(conn) -> LLMConfig:
    # Lazy import to avoid circular dependency (main imports extraction router)
    from backend.main import _build_text_llm_config  # type: ignore[attr-defined]
    return _build_text_llm_config(conn, timeout_s=300.0)


# ── Ensure extraction project exists ─────────────────────────

_EXTRACTION_PROJECT_NAME = "__extraction__"


def _ensure_extraction_project(conn) -> int:
    prj = dbm.get_project_by_name(conn, _EXTRACTION_PROJECT_NAME)
    if prj is not None:
        return prj.id
    prj = dbm.create_project(conn, _EXTRACTION_PROJECT_NAME, "__extraction__")
    return prj.id


# ── Models ───────────────────────────────────────────────────

class NewSessionBody(BaseModel):
    title: str = "知识提取会话"


class ChatBody(BaseModel):
    message: str


class CardUpdateBody(BaseModel):
    card_type: str | None = None
    title: str | None = None
    content: str | None = None
    applicable_scope: str | None = None
    exceptions: str | None = None
    confidence: str | None = None


# ── Card serializer ──────────────────────────────────────────

def _card_dict(card: dbm.KnowledgeCardRow) -> dict[str, Any]:
    return {
        "id": card.id,
        "conversation_id": card.conversation_id,
        "card_index": card.card_index,
        "card_type": card.card_type,
        "title": card.title,
        "content": card.content,
        "applicable_scope": card.applicable_scope,
        "exceptions": card.exceptions,
        "confidence": card.confidence,
        "status": card.status,
        "source_turn": card.source_turn,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


# ── Endpoints ────────────────────────────────────────────────

@router.post("/sessions")
def create_session(
    body: NewSessionBody,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    user_id = _require_user(aika_token)
    conn = get_conn()
    project_id = _ensure_extraction_project(conn)
    profile = dbm.get_expert_profile(conn, user_id)
    user = dbm.get_user_by_id(conn, user_id)
    display_name = user.display_name if user else "专家"
    title = body.title or f"知识提取_{display_name}"
    conv = dbm.create_conversation(
        conn,
        project_id=project_id,
        analysis_type="extraction",
        title=title,
        mode="extracting",
    )
    # Insert the opening AI message
    system_prompt = build_extraction_system_prompt(profile)
    opening = _build_opening(display_name, profile)
    dbm.insert_message(conn, conversation_id=conv.id, role="assistant", content=opening)
    return JSONResponse(ok({
        "session_id": conv.id,
        "title": conv.title,
        "opening": opening,
        "profile_completed": profile.profile_completed if profile else False,
    }))


def _build_opening(display_name: str, profile) -> str:
    if profile and profile.profile_completed:
        parts = []
        if profile.industries:
            parts.append(f"行业：{', '.join(profile.industries)}")
        if profile.focus_areas:
            parts.append(f"方向：{', '.join(profile.focus_areas)}")
        context = "；".join(parts) if parts else "通用"
        header = f"你好，{display_name}。根据你的背景（{context}），我已准备好开始今天的知识提取。\n\n"
    else:
        header = f"你好，{display_name}。请先完成专家画像设置，以便我能提出更有针对性的问题。\n\n"
    return (
        header
        + "今天想从哪里开始？\n\n"
        + "1. 我来问，你来答（AI 主导提问）\n"
        + "2. 分享一份你觉得做得好的文档\n"
        + "3. 分享一份有问题的文档\n"
        + "4. 直接说你想聊的内容"
    )


@router.get("/sessions")
def list_sessions(
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    user_id = _require_user(aika_token)
    conn = get_conn()
    project_id = _ensure_extraction_project(conn)
    conversations = dbm.list_conversations(conn, project_id=project_id)
    items = []
    for c in conversations:
        cards = dbm.list_knowledge_cards(conn, c.id)
        confirmed = [cd for cd in cards if cd.status in ("confirmed", "edited")]
        items.append({
            "session_id": c.id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "confirmed_cards": len(confirmed),
            "total_cards": len(cards),
        })
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return JSONResponse(ok({"sessions": items}))


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    user_id = _require_user(aika_token)
    conn = get_conn()
    conv = dbm.get_conversation(conn, session_id)
    if conv is None or conv.analysis_type != "extraction":
        raise HTTPException(status_code=404, detail="session not found")
    messages = dbm.list_recent_messages(conn, conversation_id=session_id, limit=200)
    cards = dbm.list_knowledge_cards(conn, session_id)
    return JSONResponse(ok({
        "session_id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at}
            for m in messages
        ],
        "cards": [_card_dict(c) for c in cards],
    }))


@router.post("/sessions/{session_id}/chat/stream")
def chat_stream(
    session_id: int,
    body: ChatBody,
    aika_token: str | None = Cookie(default=None),
) -> StreamingResponse:
    user_id = _require_user(aika_token)
    conn = get_conn()
    conv = dbm.get_conversation(conn, session_id)
    if conv is None or conv.analysis_type != "extraction":
        raise HTTPException(status_code=404, detail="session not found")

    user_msg = body.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message is empty")

    profile = dbm.get_expert_profile(conn, user_id)
    system_prompt = build_extraction_system_prompt(profile)

    dbm.insert_message(conn, conversation_id=session_id, role="user", content=user_msg)

    recent = dbm.list_recent_messages(conn, conversation_id=session_id, limit=40)
    prior_tuples = [
        (m.role, m.content) for m in recent[:-1]  # exclude the just-inserted user msg
        if m.role in ("user", "assistant")
    ]

    existing_cards = dbm.list_knowledge_cards(conn, session_id)
    next_card_index = len(existing_cards) + 1

    cfg = _llm_cfg(conn)

    def gen():
        try:
            yield _sse({"type": "stage", "name": "生成", "state": "start"})
            provider = get_provider(cfg.provider)
            acc: list[str] = []
            for piece in provider.chat_stream(
                system=system_prompt,
                user=user_msg,
                config=cfg,
                prior_messages=prior_tuples or None,
            ):
                acc.append(piece)
                yield _sse({"type": "delta", "text": piece})

            full_text = "".join(acc)
            yield _sse({"type": "stage", "name": "生成", "state": "end"})

            # Parse ki markers
            markers = parse_ki_markers(full_text)
            display_text = strip_ki_markers(full_text)

            # Save assistant message (display text without markers)
            dbm.insert_message(conn, conversation_id=session_id, role="assistant", content=display_text)

            # Persist extracted cards as pending
            new_cards = []
            card_idx = next_card_index
            for marker in markers:
                card = dbm.insert_knowledge_card(
                    conn,
                    conversation_id=session_id,
                    card_index=card_idx,
                    card_type=marker.card_type,
                    title=marker.title,
                    content=marker.content,
                    applicable_scope=marker.applicable_scope,
                    exceptions=marker.exceptions,
                    confidence=marker.confidence,
                    status="pending",
                    source_turn=len(recent),
                )
                new_cards.append(_card_dict(card))
                card_idx += 1

            yield _sse({
                "type": "final",
                "text": display_text,
                "new_cards": new_cards,
            })
        except LLMError as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/cards")
def list_cards(
    session_id: int,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_user(aika_token)
    conn = get_conn()
    conv = dbm.get_conversation(conn, session_id)
    if conv is None or conv.analysis_type != "extraction":
        raise HTTPException(status_code=404, detail="session not found")
    cards = dbm.list_knowledge_cards(conn, session_id)
    return JSONResponse(ok({"cards": [_card_dict(c) for c in cards]}))


@router.post("/sessions/{session_id}/cards/{card_id}/confirm")
def confirm_card(
    session_id: int,
    card_id: int,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_user(aika_token)
    conn = get_conn()
    card = dbm.get_knowledge_card(conn, card_id)
    if card is None or card.conversation_id != session_id:
        raise HTTPException(status_code=404, detail="card not found")
    updated = dbm.update_knowledge_card_status(conn, card_id, "confirmed")
    return JSONResponse(ok({"card": _card_dict(updated)}))


@router.post("/sessions/{session_id}/cards/{card_id}/reject")
def reject_card(
    session_id: int,
    card_id: int,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_user(aika_token)
    conn = get_conn()
    card = dbm.get_knowledge_card(conn, card_id)
    if card is None or card.conversation_id != session_id:
        raise HTTPException(status_code=404, detail="card not found")
    updated = dbm.update_knowledge_card_status(conn, card_id, "rejected")
    return JSONResponse(ok({"card": _card_dict(updated)}))


@router.put("/sessions/{session_id}/cards/{card_id}")
def update_card(
    session_id: int,
    card_id: int,
    body: CardUpdateBody,
    aika_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_user(aika_token)
    conn = get_conn()
    card = dbm.get_knowledge_card(conn, card_id)
    if card is None or card.conversation_id != session_id:
        raise HTTPException(status_code=404, detail="card not found")
    updated = dbm.update_knowledge_card_content(
        conn,
        card_id,
        card_type=body.card_type,
        title=body.title,
        content=body.content,
        applicable_scope=body.applicable_scope,
        exceptions=body.exceptions,
        confidence=body.confidence,
        status="edited",
    )
    return JSONResponse(ok({"card": _card_dict(updated)}))
