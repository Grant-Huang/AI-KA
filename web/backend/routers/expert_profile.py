from __future__ import annotations
from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from aika import db as dbm
from backend.response import ok, err

router = APIRouter(prefix="/api/v1/expert-profile", tags=["expert-profile"])

def _conn():
    from backend.main import _conn as main_conn
    return main_conn()

def _require_user(aika_token: str | None) -> int:
    if not aika_token:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = dbm.get_session_user_id(_conn(), aika_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="会话已过期")
    return user_id

class ProfileBody(BaseModel):
    industries: list[str]
    production_modes: list[str]
    functional_modules: list[str]
    focus_areas: list[str]

@router.get("")
def get_profile(aika_token: str | None = Cookie(default=None)) -> JSONResponse:
    user_id = _require_user(aika_token)
    profile = dbm.get_expert_profile(_conn(), user_id)
    if profile is None:
        return JSONResponse(ok(None))
    return JSONResponse(ok({
        "industries": profile.industries,
        "production_modes": profile.production_modes,
        "functional_modules": profile.functional_modules,
        "focus_areas": profile.focus_areas,
        "profile_completed": profile.profile_completed,
    }))

@router.put("")
def upsert_profile(body: ProfileBody, aika_token: str | None = Cookie(default=None)) -> JSONResponse:
    user_id = _require_user(aika_token)
    profile = dbm.upsert_expert_profile(
        _conn(), user_id=user_id,
        industries=body.industries,
        production_modes=body.production_modes,
        functional_modules=body.functional_modules,
        focus_areas=body.focus_areas,
        profile_completed=True,
    )
    return JSONResponse(ok({"profile_completed": profile.profile_completed}))
