"""
Automated smoke tests covering user manual acceptance scenarios T01-T16.

T01  Login success/failure
T02  First-time expert profile completion (4 questions, multi-select)
T03  Subsequent entry auto-loads profile
T04  Update profile, next session uses new data
T05  New session with profile → opening references direction
T06  Session created without LLM call (opening msg already present)
T07  Fuzzy signal detection is embedded in system prompt
T08  AI pauses to show knowledge card (pending card exists after stream final event)
T09  Edit card (修改后入库) → status becomes "edited"
T10  Reject card (不采纳) → status becomes "rejected"
T11  Confirm card writes personal + org files
T12  (Document upload - UI-only, skipped in backend tests)
T13  (Document flow - UI-only, skipped)
T14  End session returns summary + filename
T15  History list returns past sessions with card count
T16  Session MD file has correct structure
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest


# ── Fixtures ──────────────────────────────────────────────────

def _create_user(client, username, password, display_name):
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    dbm.create_user(conn, username=username, display_name=display_name, password_hash=pw_hash)
    return conn


def _login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["data"]


# ── T01: Login ────────────────────────────────────────────────

def test_T01_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "bad"})
    assert r.status_code == 401


def test_T01_login_correct(client):
    _create_user(client, "t01user", "correctpass", "T01 用户")
    user = _login(client, "t01user", "correctpass")
    assert user["username"] == "t01user"
    assert user["display_name"] == "T01 用户"


# ── T02: First-time profile completion ────────────────────────

@pytest.mark.skip(reason="DB-based per-user profile replaced by file-based profile in upstream merge")
def test_T02_profile_completion(client):
    _create_user(client, "t02user", "pass", "T02")
    _login(client, "t02user", "pass")

    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["profile_completed"] is False

    profile_data = {
        "industries": ["汽车零部件", "通用机械"],
        "production_modes": ["批量离散制造"],
        "functional_modules": ["计划排程", "质量管理"],
        "focus_areas": ["上线陪跑与验收"],
    }
    r = client.put("/api/v1/expert-profile", json=profile_data)
    assert r.status_code == 200
    assert r.json()["data"]["profile_completed"] is True

    # Verify all 4 fields stored correctly
    r2 = client.get("/api/v1/expert-profile")
    data = r2.json()["data"]
    assert "汽车零部件" in data["industries"]
    assert "通用机械" in data["industries"]
    assert "批量离散制造" in data["production_modes"]
    assert "计划排程" in data["functional_modules"]
    assert "上线陪跑与验收" in data["focus_areas"]


# ── T03: Subsequent entry auto-loads profile ──────────────────

@pytest.mark.skip(reason="DB-based per-user profile replaced by file-based profile in upstream merge")
def test_T03_profile_auto_loads(client):
    _create_user(client, "t03user", "pass", "T03")
    _login(client, "t03user", "pass")
    client.put("/api/v1/expert-profile", json={
        "industries": ["航空航天"],
        "production_modes": ["高变异小批量定制"],
        "functional_modules": ["设备管理"],
        "focus_areas": ["蓝图确认阶段"],
    })

    # Simulate re-login (new GET /me)
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["profile_completed"] is True

    # Profile still accessible
    prof = client.get("/api/v1/expert-profile").json()["data"]
    assert "航空航天" in prof["industries"]


# ── T04: Update profile ───────────────────────────────────────

@pytest.mark.skip(reason="DB-based per-user profile replaced by file-based profile in upstream merge")
def test_T04_profile_update(client):
    _create_user(client, "t04user", "pass", "T04")
    _login(client, "t04user", "pass")
    client.put("/api/v1/expert-profile", json={
        "industries": ["汽车整车"],
        "production_modes": [],
        "functional_modules": [],
        "focus_areas": ["售前与方案设计"],
    })
    # Update focus area
    client.put("/api/v1/expert-profile", json={
        "industries": ["汽车整车"],
        "production_modes": [],
        "functional_modules": [],
        "focus_areas": ["上线陪跑与验收"],
    })
    prof = client.get("/api/v1/expert-profile").json()["data"]
    assert prof["focus_areas"] == ["上线陪跑与验收"]


# ── T05: Opening message references profile direction ─────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T05_opening_references_direction(client):
    _create_user(client, "t05user", "pass", "张工")
    _login(client, "t05user", "pass")
    client.put("/api/v1/expert-profile", json={
        "industries": ["汽车零部件"],
        "production_modes": [],
        "functional_modules": [],
        "focus_areas": ["上线陪跑与验收"],
    })
    r = client.post("/api/v1/extraction/sessions", json={"title": "T05会话"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["profile_completed"] is True
    opening = data["opening"]
    # Opening should mention the expert name or direction
    assert "张工" in opening or "上线陪跑" in opening or "汽车零部件" in opening


# ── T06: Session created with opening message ─────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T06_session_has_opening_message(client):
    _create_user(client, "t06user", "pass", "T06")
    _login(client, "t06user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T06"})
    session_id = r.json()["data"]["session_id"]

    detail = client.get(f"/api/v1/extraction/sessions/{session_id}").json()["data"]
    messages = detail["messages"]
    assert len(messages) >= 1
    assert messages[0]["role"] == "assistant"
    assert len(messages[0]["content"]) > 20


# ── T07: System prompt contains questioning strategies ─────────

def test_T07_system_prompt_has_strategies():
    from aika.db import ExpertProfileRow
    from backend.extraction_prompt import build_extraction_system_prompt
    prompt = build_extraction_system_prompt(None)
    # Should contain all 6 strategy names
    assert "关键事件法" in prompt
    assert "对比法" in prompt
    assert "规则边界法" in prompt
    assert "反事实法" in prompt
    assert "协议分析法" in prompt
    assert "文档交叉验证法" in prompt
    # Should contain fuzzy signal triggers
    assert "通常" in prompt
    assert "要看情况" in prompt
    # Should contain ki marker instruction
    assert "<!-- ki:" in prompt


# ── T08: Pending card created after stream ────────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T08_card_created_as_pending(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t08user", "pass", "T08")
    _login(client, "t08user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T08"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    # Insert pending card directly (SSE stream not testable without LLM)
    card = dbm.insert_knowledge_card(
        conn, conversation_id=session_id, card_index=1,
        card_type="risk_signal", title="风险卡片", content="当...时",
        confidence="medium", status="pending",
    )

    cards_r = client.get(f"/api/v1/extraction/sessions/{session_id}/cards")
    cards = cards_r.json()["data"]["cards"]
    assert len(cards) == 1
    assert cards[0]["status"] == "pending"
    assert cards[0]["card_type"] == "risk_signal"


# ── T09: Edit card (修改后入库) ───────────────────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T09_edit_card(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t09user", "pass", "T09")
    _login(client, "t09user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T09"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    card = dbm.insert_knowledge_card(
        _conn(), conversation_id=session_id, card_index=1,
        card_type="rule", title="原标题", content="原内容",
        confidence="low", status="pending",
    )

    r = client.put(
        f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}",
        json={"title": "修改后标题", "confidence": "high"},
    )
    assert r.status_code == 200
    updated = r.json()["data"]["card"]
    assert updated["status"] == "edited"
    assert updated["title"] == "修改后标题"
    assert updated["confidence"] == "high"
    assert updated["content"] == "原内容"  # unchanged field

    # Should also write to personal knowledge
    personal_cards = list((tmp_path / "personal" / "extraction-sessions" / "t09user" / "cards").glob("*.md"))
    assert len(personal_cards) == 1


# ── T10: Reject card (不采纳) ─────────────────────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T10_reject_card(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t10user", "pass", "T10")
    _login(client, "t10user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T10"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    card = dbm.insert_knowledge_card(
        _conn(), conversation_id=session_id, card_index=1,
        card_type="rule", title="要拒绝的卡片", content="内容",
        confidence="low", status="pending",
    )

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}/reject")
    assert r.status_code == 200
    assert r.json()["data"]["card"]["status"] == "rejected"


# ── T11: Confirm card writes to personal + org ────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T11_confirm_card_writes_both(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t11user", "pass", "T11")
    _login(client, "t11user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T11"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    card = dbm.insert_knowledge_card(
        _conn(), conversation_id=session_id, card_index=1,
        card_type="best_practice", title="T11最佳实践", content="内容",
        confidence="high", status="pending",
    )

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}/confirm")
    assert r.status_code == 200
    assert r.json()["data"]["card"]["status"] == "confirmed"

    # Personal knowledge card file
    personal_cards = list((tmp_path / "personal" / "extraction-sessions" / "t11user" / "cards").glob("*.md"))
    assert len(personal_cards) == 1

    # Org pending queue
    pending = list((tmp_path / ".aika" / "pending-knowledge").glob("*.json"))
    assert len(pending) == 1
    data = json.loads(pending[0].read_text())
    assert data["submitted_by"] == "t11user"


# ── T14: End session returns summary and filename ─────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T14_end_session(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t14user", "pass", "李四")
    _login(client, "t14user", "pass")
    client.put("/api/v1/expert-profile", json={
        "industries": [], "production_modes": [],
        "functional_modules": [], "focus_areas": ["蓝图确认阶段"],
    })
    r = client.post("/api/v1/extraction/sessions", json={"title": "T14会话"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    for i, status in enumerate(["confirmed", "confirmed", "edited", "rejected"], 1):
        dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=i,
                                  card_type="rule", title=f"卡片{i}", content=f"内容{i}",
                                  confidence="medium", status=status)

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/end")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["filename"] != ""
    assert "知识提取" in d["filename"]
    s = d["summary"]
    assert s["confirmed"] == 2
    assert s["edited"] == 1
    assert s["rejected"] == 1
    assert s["total"] == 4


# ── T15: History list ─────────────────────────────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T15_history_list(client):
    _create_user(client, "t15user", "pass", "T15")
    _login(client, "t15user", "pass")
    client.post("/api/v1/extraction/sessions", json={"title": "历史会话A"})
    client.post("/api/v1/extraction/sessions", json={"title": "历史会话B"})

    r = client.get("/api/v1/extraction/sessions")
    sessions = r.json()["data"]["sessions"]
    assert len(sessions) >= 2
    titles = [s["title"] for s in sessions]
    assert "历史会话A" in titles
    assert "历史会话B" in titles
    # Each session has card count
    for s in sessions:
        assert "confirmed_cards" in s
        assert "total_cards" in s


# ── T16: Session MD file structure ───────────────────────────

@pytest.mark.skip(reason="Session-based extraction API replaced by stateless API in upstream merge")
def test_T16_session_md_structure(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    _create_user(client, "t16user", "pass", "王五")
    _login(client, "t16user", "pass")
    r = client.post("/api/v1/extraction/sessions", json={"title": "T16会话"})
    session_id = r.json()["data"]["session_id"]

    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    dbm.insert_message(conn, conversation_id=session_id, role="user", content="我的项目遇到了问题")
    dbm.insert_message(conn, conversation_id=session_id, role="assistant", content="请详细说明是什么问题")
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=1,
                              card_type="rule", title="项目规则", content="IF X THEN Y",
                              confidence="high", status="confirmed",
                              applicable_scope="项目实施阶段")

    client.post(f"/api/v1/extraction/sessions/{session_id}/end")

    md_files = list((tmp_path / "personal" / "extraction-sessions" / "t16user").glob("知识提取_*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")

    # Must have header section
    assert "# 知识提取会话记录" in content
    assert "王五" in content
    # Must have dialog section
    assert "## 对话记录" in content
    assert "我的项目遇到了问题" in content
    # Must have cards section
    assert "## 已确认知识卡片" in content
    assert "项目规则" in content
    assert "IF X THEN Y" in content
    assert "项目实施阶段" in content
