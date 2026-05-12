"""Tests for knowledge extraction API endpoints."""
from __future__ import annotations
import hashlib
import pytest


def _make_user(client, username="extuser", password="extpass", display_name="提取专家"):
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    dbm.create_user(conn, username=username, display_name=display_name, password_hash=pw_hash)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r


def test_create_session_unauthenticated(client):
    r = client.post("/api/v1/extraction/sessions", json={"title": "test"})
    assert r.status_code == 401


def test_create_session_no_profile(client):
    _make_user(client)
    r = client.post("/api/v1/extraction/sessions", json={"title": "测试会话"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert "session_id" in data
    assert "opening" in data
    assert data["profile_completed"] is False
    # Opening should mention profile not completed
    assert "画像" in data["opening"]


def test_create_session_with_profile(client):
    _make_user(client, username="user2", password="pass2", display_name="张工")
    client.put("/api/v1/expert-profile", json={
        "industries": ["汽车零部件"],
        "production_modes": ["批量离散制造"],
        "functional_modules": ["计划排程"],
        "focus_areas": ["上线陪跑与验收"],
    })
    r = client.post("/api/v1/extraction/sessions", json={"title": "新会话"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["profile_completed"] is True
    assert "汽车零部件" in data["opening"] or "张工" in data["opening"]


def test_list_sessions(client):
    _make_user(client, username="listuser", password="listpass")
    client.post("/api/v1/extraction/sessions", json={"title": "会话A"})
    client.post("/api/v1/extraction/sessions", json={"title": "会话B"})
    r = client.get("/api/v1/extraction/sessions")
    assert r.status_code == 200
    sessions = r.json()["data"]["sessions"]
    assert len(sessions) >= 2


def test_get_session(client):
    _make_user(client, username="getuser", password="getpass")
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "会话详情"})
    session_id = create_r.json()["data"]["session_id"]

    r = client.get(f"/api/v1/extraction/sessions/{session_id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["session_id"] == session_id
    assert len(data["messages"]) >= 1  # opening message
    assert data["messages"][0]["role"] == "assistant"


def test_get_session_not_found(client):
    _make_user(client, username="nfuser", password="nfpass")
    r = client.get("/api/v1/extraction/sessions/99999")
    assert r.status_code == 404


def test_card_confirm_and_reject(client):
    from backend.main import _conn
    from aika import db as dbm
    _make_user(client, username="carduser", password="cardpass")
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "卡片测试"})
    session_id = create_r.json()["data"]["session_id"]

    # Directly insert a card via DB
    conn = _conn()
    card = dbm.insert_knowledge_card(
        conn,
        conversation_id=session_id,
        card_index=1,
        card_type="rule",
        title="测试规则",
        content="IF 条件 THEN 行动",
        confidence="high",
        status="pending",
    )

    # Confirm card
    r = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}/confirm")
    assert r.status_code == 200
    assert r.json()["data"]["card"]["status"] == "confirmed"

    # Insert another card and reject it
    card2 = dbm.insert_knowledge_card(
        conn,
        conversation_id=session_id,
        card_index=2,
        card_type="risk_signal",
        title="风险信号",
        content="当...时，意味着...",
        confidence="medium",
        status="pending",
    )
    r2 = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card2.id}/reject")
    assert r2.status_code == 200
    assert r2.json()["data"]["card"]["status"] == "rejected"


def test_card_update(client):
    from backend.main import _conn
    from aika import db as dbm
    _make_user(client, username="updateuser", password="updatepass")
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "修改卡片"})
    session_id = create_r.json()["data"]["session_id"]

    conn = _conn()
    card = dbm.insert_knowledge_card(
        conn,
        conversation_id=session_id,
        card_index=1,
        card_type="rule",
        title="原标题",
        content="原内容",
        confidence="low",
        status="pending",
    )

    r = client.put(
        f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}",
        json={"title": "新标题", "confidence": "high"},
    )
    assert r.status_code == 200
    updated = r.json()["data"]["card"]
    assert updated["title"] == "新标题"
    assert updated["confidence"] == "high"
    assert updated["status"] == "edited"
    assert updated["content"] == "原内容"  # unchanged


def test_list_cards(client):
    from backend.main import _conn
    from aika import db as dbm
    _make_user(client, username="listcarduser", password="lcpass")
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "卡片列表"})
    session_id = create_r.json()["data"]["session_id"]

    conn = _conn()
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=1,
                              card_type="rule", title="A", content="内容A", confidence="high", status="pending")
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=2,
                              card_type="best_practice", title="B", content="内容B", confidence="medium", status="pending")

    r = client.get(f"/api/v1/extraction/sessions/{session_id}/cards")
    assert r.status_code == 200
    cards = r.json()["data"]["cards"]
    assert len(cards) == 2
    assert cards[0]["title"] == "A"
    assert cards[1]["title"] == "B"
