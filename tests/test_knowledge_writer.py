"""Tests for knowledge_writer: personal card write, org pending, session MD."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest


def _make_user_and_session(client):
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"pass").hexdigest()
    dbm.create_user(conn, username="writer_user", display_name="写入测试", password_hash=pw_hash)
    r = client.post("/api/v1/auth/login", json={"username": "writer_user", "password": "pass"})
    assert r.status_code == 200
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "写入测试会话"})
    assert create_r.status_code == 200
    session_id = create_r.json()["data"]["session_id"]
    return conn, session_id


def test_confirm_card_writes_personal(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import _conn
    from aika import db as dbm
    conn, session_id = _make_user_and_session(client)

    card = dbm.insert_knowledge_card(
        conn, conversation_id=session_id, card_index=1,
        card_type="rule", title="测试规则写入", content="IF A THEN B",
        confidence="high", status="pending",
    )

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}/confirm")
    assert r.status_code == 200
    assert r.json()["data"]["card"]["status"] == "confirmed"

    # Check personal dir was written
    personal_cards = list((tmp_path / "personal" / "extraction-sessions" / "writer_user" / "cards").glob("*.md"))
    assert len(personal_cards) == 1
    content = personal_cards[0].read_text(encoding="utf-8")
    assert "测试规则写入" in content
    assert "IF A THEN B" in content


def test_confirm_card_writes_org_pending(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    # need a new user since each test has fresh db
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"pass2").hexdigest()
    dbm.create_user(conn, username="org_user", display_name="组织测试", password_hash=pw_hash)
    client.post("/api/v1/auth/login", json={"username": "org_user", "password": "pass2"})
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "org测试"})
    session_id = create_r.json()["data"]["session_id"]
    card = dbm.insert_knowledge_card(
        conn, conversation_id=session_id, card_index=1,
        card_type="best_practice", title="组织最佳实践", content="做法内容",
        confidence="medium", status="pending",
    )

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/cards/{card.id}/confirm")
    assert r.status_code == 200

    pending_files = list((tmp_path / ".aika" / "pending-knowledge").glob("*.json"))
    assert len(pending_files) == 1
    payload = json.loads(pending_files[0].read_text(encoding="utf-8"))
    assert payload["title"] == "组织最佳实践"
    assert payload["submitted_by"] == "org_user"


def test_end_session_generates_md(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"pass3").hexdigest()
    dbm.create_user(conn, username="end_user", display_name="张三", password_hash=pw_hash)
    client.post("/api/v1/auth/login", json={"username": "end_user", "password": "pass3"})
    # Set profile with focus area
    client.put("/api/v1/expert-profile", json={
        "industries": ["汽车零部件"],
        "production_modes": [],
        "functional_modules": [],
        "focus_areas": ["上线陪跑与验收"],
    })
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "结束会话测试"})
    session_id = create_r.json()["data"]["session_id"]

    # Insert a confirmed card
    card = dbm.insert_knowledge_card(
        conn, conversation_id=session_id, card_index=1,
        card_type="rule", title="陪跑规则", content="IF 上线 THEN 检查清单",
        confidence="high", status="confirmed",
    )

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/end")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["filename"] != ""
    assert data["summary"]["confirmed"] == 1

    # Check session MD file exists in personal dir
    personal_dir = tmp_path / "personal" / "extraction-sessions" / "end_user"
    md_files = list(personal_dir.glob("知识提取_*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "张三" in content
    assert "陪跑规则" in content

    # Check org extraction-sessions copy
    org_dir = tmp_path / ".aika" / "extraction-sessions"
    org_files = list(org_dir.glob("知识提取_*.md"))
    assert len(org_files) == 1


def test_end_session_summary_stats(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"pass4").hexdigest()
    dbm.create_user(conn, username="stats_user", display_name="统计测试", password_hash=pw_hash)
    client.post("/api/v1/auth/login", json={"username": "stats_user", "password": "pass4"})
    create_r = client.post("/api/v1/extraction/sessions", json={"title": "统计测试"})
    session_id = create_r.json()["data"]["session_id"]

    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=1,
                              card_type="rule", title="确认", content="内容1",
                              confidence="high", status="confirmed")
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=2,
                              card_type="rule", title="修改", content="内容2",
                              confidence="medium", status="edited")
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=3,
                              card_type="rule", title="拒绝", content="内容3",
                              confidence="low", status="rejected")
    dbm.insert_knowledge_card(conn, conversation_id=session_id, card_index=4,
                              card_type="rule", title="待处理", content="内容4",
                              confidence="medium", status="pending")

    r = client.post(f"/api/v1/extraction/sessions/{session_id}/end")
    assert r.status_code == 200
    s = r.json()["data"]["summary"]
    assert s["confirmed"] == 1
    assert s["edited"] == 1
    assert s["rejected"] == 1
    assert s["pending"] == 1
    assert s["total"] == 4
