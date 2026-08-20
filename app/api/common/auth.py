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
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.security import (
    authenticate_user,
    check_login_rate_limit,
    decode_access_token,
    get_claims_from_request,
    issue_token_pair,
    record_login_attempt,
    refresh_access_token,
    require_role,
    revoke_token,
    verify_totp,
    enroll_totp,
    confirm_totp,
)
from app.core.config import settings
from app.core.database import (
    AuthUser,
    change_password,
    get_db_session,
    verify_password,
    write_audit_log,
)


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
    mfa_code: str | None = Field(default=None, min_length=4, max_length=10)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


class MfaConfirmRequest(BaseModel):
    secret: str = Field(..., min_length=8)
    code: str = Field(..., min_length=4, max_length=10)


def _client_ip(request: Request) -> str:
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "unknown")


@router.post("/login", summary="JWT 로그인")
async def login(req: LoginRequest, request: Request, response: Response):
    client_ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    check_login_rate_limit(req.username, client_ip)
    try:
        user = authenticate_user(req.username, req.password)
    except HTTPException as e:
        record_login_attempt(req.username, client_ip, success=False)
        write_audit_log(
            actor=req.username, actor_role=None, action="login_fail",
            target=req.username, status="fail", ip=client_ip, user_agent=ua,
            detail=getattr(e, "detail", None) and str(e.detail),
        )
        raise

    record_login_attempt(req.username, client_ip, success=True)

    # [M-4] MFA 검증: 활성화되었거나 admin 강제 정책 시 mfa_code 필수
    with get_db_session() as db:
        u = db.query(AuthUser).filter(AuthUser.username == user["username"]).first()
        mfa_required = bool(u and (u.mfa_enabled or (settings.MFA_REQUIRED_FOR_ADMIN and user["role"] == "admin")))
        mfa_secret_set = bool(u and u.mfa_secret)
        must_change = bool(u and u.must_change_password)

    if mfa_required and mfa_secret_set:
        if not req.mfa_code or not verify_totp(u.mfa_secret, req.mfa_code):
            write_audit_log(
                actor=user["username"], actor_role=user["role"], action="login_fail",
                target=user["username"], status="fail", ip=client_ip, user_agent=ua,
                detail="mfa_invalid",
            )
            raise HTTPException(status_code=401, detail="MFA 코드가 필요하거나 올바르지 않습니다")

    pair = issue_token_pair(subject=user["username"], role=user["role"])
    _set_auth_cookies(
        response=response,
        request=request,
        access_token=pair["access_token"],
        refresh_token=pair["refresh_token"],
    )
    write_audit_log(
        actor=user["username"], actor_role=user["role"], action="login_success",
        target=user["username"], status="success", ip=client_ip, user_agent=ua,
    )
    return {
        **pair,
        "username": user["username"],
        "role": user["role"],
        "must_change_password": must_change,
        "mfa_enabled": mfa_secret_set,
        "mfa_required": mfa_required,
    }


@router.post("/password", dependencies=[Depends(require_role("viewer"))], summary="비밀번호 변경")
async def change_password_endpoint(
    req: PasswordChangeRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    access_cookie_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
):
    payload = get_claims_from_request(authorization=authorization, access_cookie_token=access_cookie_token)
    username = str(payload.get("sub", ""))
    role = str(payload.get("role", "viewer"))
    client_ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.username == username, AuthUser.is_active.is_(True)).first()
        if not user:
            raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")
        if not verify_password(req.current_password, user.password_hash):
            write_audit_log(actor=username, actor_role=role, action="password_change", target=username,
                            status="fail", ip=client_ip, user_agent=ua, detail="current_invalid")
            raise HTTPException(status_code=401, detail="현재 비밀번호가 일치하지 않습니다")
        user_id = user.id
    result = change_password(user_id=user_id, new_raw=req.new_password)
    if result.get("status") != "ok":
        write_audit_log(actor=username, actor_role=role, action="password_change", target=username,
                        status="fail", ip=client_ip, user_agent=ua, detail=result.get("message"))
        raise HTTPException(status_code=400, detail=result.get("message") or "비밀번호 변경 실패")
    write_audit_log(actor=username, actor_role=role, action="password_change", target=username,
                    status="success", ip=client_ip, user_agent=ua)
    return result


@router.post("/mfa/enroll", dependencies=[Depends(require_role("viewer"))], summary="MFA(TOTP) 등록 시작")
async def mfa_enroll(
    authorization: str | None = Header(default=None, alias="Authorization"),
    access_cookie_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
):
    payload = get_claims_from_request(authorization=authorization, access_cookie_token=access_cookie_token)
    username = str(payload.get("sub", ""))
    return enroll_totp(username=username)


@router.post("/mfa/confirm", dependencies=[Depends(require_role("viewer"))], summary="MFA(TOTP) 등록 확정")
async def mfa_confirm(
    req: MfaConfirmRequest,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    access_cookie_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
):
    payload = get_claims_from_request(authorization=authorization, access_cookie_token=access_cookie_token)
    username = str(payload.get("sub", ""))
    role = str(payload.get("role", "viewer"))
    client_ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.username == username, AuthUser.is_active.is_(True)).first()
        if not user:
            raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")
        uid = user.id
    result = confirm_totp(user_id=uid, secret_b32=req.secret, code=req.code)
    write_audit_log(actor=username, actor_role=role, action="mfa_confirm", target=username,
                    status=result.get("status", "fail"), ip=client_ip, user_agent=ua)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message") or "MFA 등록 실패")
    return result


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
