from __future__ import annotations
import hashlib, secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from aika import db as dbm
from backend.response import ok, err

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _conn():
    from backend.main import _conn as main_conn
    return main_conn()

class LoginBody(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(body: LoginBody) -> JSONResponse:
    conn = _conn()
    user = dbm.get_user_by_username(conn, body.username)
    if user is None or user.password_hash != _hash_password(body.password):
        return JSONResponse(err("用户名或密码错误"), status_code=401)
    token = secrets.token_hex(32)
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    dbm.create_auth_session(conn, user_id=user.id, token=token, expires_at=expires_at)
    resp = JSONResponse(ok({"user_id": user.id, "username": user.username, "display_name": user.display_name}))
    resp.set_cookie("aika_token", token, httponly=True, samesite="lax", max_age=7*24*3600)
    return resp

@router.post("/logout")
def logout(aika_token: str | None = Cookie(default=None)) -> JSONResponse:
    if aika_token:
        dbm.delete_auth_session(_conn(), aika_token)
    resp = JSONResponse(ok({"logged_out": True}))
    resp.delete_cookie("aika_token")
    return resp

@router.get("/me")
def me(aika_token: str | None = Cookie(default=None)) -> JSONResponse:
    if not aika_token:
        return JSONResponse(err("未登录"), status_code=401)
    conn = _conn()
    user_id = dbm.get_session_user_id(conn, aika_token)
    if user_id is None:
        return JSONResponse(err("会话已过期"), status_code=401)
    user = dbm.get_user_by_id(conn, user_id)
    profile = dbm.get_expert_profile(conn, user_id)
    return JSONResponse(ok({
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "profile_completed": profile.profile_completed if profile else False,
    }))
