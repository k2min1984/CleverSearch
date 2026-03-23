"""
########################################################
# Description
# 인증 API 라우터
# JWT 기반 로그인/로그아웃 및 토큰 관리
# - 로그인 (아이디/비밀번호 → Access + Refresh 토큰 발급)
# - 토큰 갱신 (Refresh → 새 Access 토큰)
# - 로그아웃 (토큰 폐기)
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.core.security import authenticate_user, issue_token_pair, refresh_access_token, revoke_token


router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=2)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


@router.post("/login", summary="JWT 로그인")
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    pair = issue_token_pair(subject=user["username"], role=user["role"])
    return {
        **pair,
        "username": user["username"],
        "role": user["role"],
    }


@router.post("/refresh", summary="JWT 재발급")
async def refresh(req: RefreshRequest):
    return refresh_access_token(req.refresh_token)


@router.post("/logout", summary="JWT 로그아웃(토큰 폐기)")
async def logout(req: LogoutRequest | None = None, authorization: str | None = Header(default=None, alias="Authorization")):
    revoked_items = []
    if not authorization or not authorization.lower().startswith("bearer "):
        if not req or not req.refresh_token:
            return {"status": "noop", "message": "폐기할 토큰 없음"}
    else:
        token = authorization.split(" ", 1)[1].strip()
        revoked_items.append(revoke_token(token))

    if req and req.refresh_token:
        revoked_items.append(revoke_token(req.refresh_token))

    return {"status": "success", "revoked": revoked_items}
