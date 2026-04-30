from __future__ import annotations

from typing import Any

from aika import db as dbm
from .conversation_models import ConversationMode, ConversationState, UserIntent


def transition(
    conn: Any,
    *,
    conversation_id: int,
    intent: UserIntent,
    deep_mode: bool = False,
) -> tuple[ConversationMode, ConversationState]:
    """
    根据用户意图计算下一个 (mode, state)，写入 DB 并返回。
    """
    mode_map: dict[UserIntent, ConversationMode] = {
        UserIntent.ANALYZE_NEW:    ConversationMode.REVIEWING,
        UserIntent.CLARIFY:        ConversationMode.CLARIFYING,
        UserIntent.REFINE:         ConversationMode.REFINING,
        UserIntent.UPDATE_FINDING: ConversationMode.REVIEWING,
        UserIntent.GENERATE_DOC:   ConversationMode.GENERATING,
        UserIntent.CHAT:           ConversationMode.CLARIFYING,
    }
    mode = mode_map.get(intent, ConversationMode.REVIEWING)
    state = ConversationState.IN_PROGRESS
    dbm.update_conversation_state(conn, conversation_id=conversation_id, state=state, mode=mode)
    return mode, state


def mark_awaiting(conn: Any, *, conversation_id: int) -> None:
    dbm.update_conversation_state(
        conn, conversation_id=conversation_id, state=ConversationState.AWAITING_INPUT
    )


def mark_done(conn: Any, *, conversation_id: int) -> None:
    dbm.update_conversation_state(
        conn, conversation_id=conversation_id, state=ConversationState.DONE
    )
