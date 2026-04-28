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
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.security import (
    authenticate_user,
    check_login_rate_limit,
    decode_access_token,
    get_claims_from_request,
    issue_token_pair,
    record_login_attempt,
    refresh_access_token,
    revoke_token,
)
from app.core.config import settings


router = APIRouter()

ACCESS_COOKIE_NAME = "cs_access_token"
REFRESH_COOKIE_NAME = "cs_refresh_token"


def _is_request_secure(request: Request) -> bool:
    if request.url.scheme == "https":
        return True

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto == "https":
        return True

    forwarded = (request.headers.get("forwarded") or "").lower()
    return "proto=https" in forwarded


def _set_auth_cookies(response: Response, request: Request, access_token: str, refresh_token: str) -> None:
    is_secure = _is_request_secure(request)
    access_age = max(60, int(settings.JWT_EXPIRE_MINUTES) * 60)
    refresh_age = max(access_age, int(settings.JWT_REFRESH_EXPIRE_MINUTES) * 60)

    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=access_age,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=refresh_age,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=2)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


@router.post("/login", summary="JWT 로그인")
async def login(req: LoginRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(req.username, client_ip)
    try:
        user = authenticate_user(req.username, req.password)
    except HTTPException:
        record_login_attempt(req.username, client_ip, success=False)
        raise

    record_login_attempt(req.username, client_ip, success=True)
    pair = issue_token_pair(subject=user["username"], role=user["role"])
    _set_auth_cookies(
        response=response,
        request=request,
        access_token=pair["access_token"],
        refresh_token=pair["refresh_token"],
    )
    return {
        **pair,
        "username": user["username"],
        "role": user["role"],
    }


@router.post("/refresh", summary="JWT 재발급")
async def refresh(
    request: Request,
    response: Response,
    req: RefreshRequest | None = None,
):
    refresh_token = (req.refresh_token if req else None) or request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="refresh token 필요")

    refreshed = refresh_access_token(refresh_token)
    _set_auth_cookies(
        response=response,
        request=request,
        access_token=refreshed["access_token"],
        refresh_token=refreshed["refresh_token"],
    )
    return refreshed


@router.post("/logout", summary="JWT 로그아웃(토큰 폐기)")
async def logout(
    request: Request,
    response: Response,
    req: LogoutRequest | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    revoked_items = []
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        revoked_items.append(revoke_token(token))
    else:
        access_cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
        if access_cookie_token:
            revoked_items.append(revoke_token(access_cookie_token))

    explicit_refresh = req.refresh_token if req else None
    refresh_candidate = explicit_refresh or request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_candidate:
        revoked_items.append(revoke_token(refresh_candidate))

    _clear_auth_cookies(response)

    if not revoked_items:
        return {"status": "noop", "message": "폐기할 토큰 없음"}

    return {"status": "success", "revoked": revoked_items}


@router.get("/me", summary="현재 로그인 세션 조회")
async def me(
    authorization: str | None = Header(default=None, alias="Authorization"),
    access_cookie_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
):
    payload = get_claims_from_request(authorization=authorization, access_cookie_token=access_cookie_token)
    return {
        "username": str(payload.get("sub", "")),
        "role": str(payload.get("role", "viewer")),
        "exp": payload.get("exp"),
    }
