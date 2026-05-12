from __future__ import annotations
from pathlib import Path
import pytest

def test_login_success(client):
    import hashlib
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"testpass").hexdigest()
    dbm.create_user(conn, username="testuser", display_name="Test", password_hash=pw_hash)

    r = client.post("/api/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert r.status_code == 200
    assert r.json()["data"]["username"] == "testuser"

def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong"})
    assert r.status_code == 401

def test_me_unauthenticated(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401

def test_profile_upsert_and_get(client):
    import hashlib
    from backend.main import _conn
    from aika import db as dbm
    conn = _conn()
    pw_hash = hashlib.sha256(b"pass2").hexdigest()
    dbm.create_user(conn, username="profuser", display_name="Prof", password_hash=pw_hash)

    login_r = client.post("/api/v1/auth/login", json={"username": "profuser", "password": "pass2"})
    assert login_r.status_code == 200

    profile_data = {
        "industries": ["汽车零部件", "通用机械"],
        "production_modes": ["批量离散制造"],
        "functional_modules": ["计划排程", "质量管理"],
        "focus_areas": ["蓝图确认阶段"],
    }
    r = client.put("/api/v1/expert-profile", json=profile_data)
    assert r.status_code == 200

    r2 = client.get("/api/v1/expert-profile")
    assert r2.status_code == 200
    data = r2.json()["data"]
    assert "汽车零部件" in data["industries"]
    assert data["profile_completed"] is True
