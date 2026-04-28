"""
########################################################
# Description
# 보안 모듈 (JWT + RBAC)
# 인증/인가 전체 로직 담당
# - JWT Access/Refresh 토큰 발급 및 검증
# - PBKDF2-SHA256 비밀번호 해싱/검증
# - RBAC 역할 기반 접근 제어 (admin > operator > viewer)
# - 토큰 폐기 (Revoke) 처리
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

import jwt
from fastapi import Cookie, Header, HTTPException

from app.core.config import settings
from app.core.database import (
    AuthRole,
    AuthUser,
    RevokedAccessToken,
    RevokedRefreshToken,
    get_db_session,
    verify_password,
)


ROLE_ORDER = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
}

_LOGIN_ATTEMPTS: dict[tuple[str, str], dict[str, float | int]] = {}
_LOGIN_ATTEMPTS_LOCK = Lock()


def _login_attempt_key(username: str, client_ip: str) -> tuple[str, str]:
    return ((username or "").strip().lower(), (client_ip or "unknown").strip())


def check_login_rate_limit(username: str, client_ip: str) -> None:
    key = _login_attempt_key(username, client_ip)
    now = monotonic()
    with _LOGIN_ATTEMPTS_LOCK:
        state = _LOGIN_ATTEMPTS.get(key)
        if not state:
            return
        blocked_until = float(state.get("blocked_until", 0.0))
        if blocked_until > now:
            wait_seconds = int(blocked_until - now)
            raise HTTPException(status_code=429, detail=f"로그인 시도 제한 중입니다. {wait_seconds}초 후 다시 시도하세요.")


def record_login_attempt(username: str, client_ip: str, success: bool) -> None:
    key = _login_attempt_key(username, client_ip)
    now = monotonic()
    with _LOGIN_ATTEMPTS_LOCK:
        if success:
            _LOGIN_ATTEMPTS.pop(key, None)
            return

        state = _LOGIN_ATTEMPTS.get(key)
        if not state:
            _LOGIN_ATTEMPTS[key] = {
                "fails": 1,
                "window_start": now,
                "blocked_until": 0.0,
            }
            return

        window_start = float(state.get("window_start", now))
        fails = int(state.get("fails", 0))

        if now - window_start > settings.AUTH_RATE_LIMIT_WINDOW_SECONDS:
            window_start = now
            fails = 0

        fails += 1
        blocked_until = float(state.get("blocked_until", 0.0))

        if fails >= settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS:
            blocked_until = now + settings.AUTH_RATE_LIMIT_BLOCK_SECONDS

        _LOGIN_ATTEMPTS[key] = {
            "fails": fails,
            "window_start": window_start,
            "blocked_until": blocked_until,
        }

def authenticate_user(username: str, password: str) -> dict:
    uname = (username or "").strip()
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.username == uname, AuthUser.is_active.is_(True)).first()
        if not user:
            raise HTTPException(status_code=401, detail="로그인 실패")

        if not verify_password(password or "", user.password_hash):
            raise HTTPException(status_code=401, detail="로그인 실패")

        role = db.query(AuthRole).filter(AuthRole.id == user.role_id, AuthRole.is_active.is_(True)).first()
        if not role:
            raise HTTPException(status_code=401, detail="권한 정보 없음")

        return {"username": user.username, "role": role.name}


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "iss": "cleversearch",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_REFRESH_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "iss": "cleversearch",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str, expected_type: str | None = None) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], issuer="cleversearch")

        token_type = str(payload.get("type", "")).strip()
        if expected_type and token_type != expected_type:
            raise HTTPException(status_code=401, detail=f"{expected_type} token 필요")

        jti = str(payload.get("jti", "")).strip()
        if jti:
            with get_db_session() as db:
                if token_type == "access":
                    revoked = db.query(RevokedAccessToken).filter(RevokedAccessToken.jti == jti).first()
                elif token_type == "refresh":
                    revoked = db.query(RevokedRefreshToken).filter(RevokedRefreshToken.jti == jti).first()
                else:
                    revoked = None
                if revoked:
                    raise HTTPException(status_code=401, detail="폐기된 토큰")
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")


def revoke_token(token: str) -> dict:
    payload = decode_access_token(token)
    jti = str(payload.get("jti", "")).strip()
    exp = payload.get("exp")
    token_type = str(payload.get("type", "")).strip()
    subject = str(payload.get("sub", "")).strip()
    if not jti:
        raise HTTPException(status_code=400, detail="폐기할 수 없는 토큰")

    if isinstance(exp, (int, float)):
        expires_at = datetime.fromtimestamp(float(exp), tz=timezone.utc)
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    with get_db_session() as db:
        if token_type == "access":
            exists = db.query(RevokedAccessToken).filter(RevokedAccessToken.jti == jti).first()
            if not exists:
                db.add(RevokedAccessToken(jti=jti, subject=subject, expires_at=expires_at))
        elif token_type == "refresh":
            exists = db.query(RevokedRefreshToken).filter(RevokedRefreshToken.jti == jti).first()
            if not exists:
                db.add(RevokedRefreshToken(jti=jti, subject=subject, expires_at=expires_at))
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 토큰 타입")
    return {"revoked_jti": jti, "expires_at": expires_at.isoformat(), "token_type": token_type}


def issue_token_pair(subject: str, role: str) -> dict:
    access_token = create_access_token(subject=subject, role=role)
    refresh_token = create_refresh_token(subject=subject, role=role)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def refresh_access_token(refresh_token: str) -> dict:
    payload = decode_access_token(refresh_token, expected_type="refresh")
    revoke_token(refresh_token)
    subject = str(payload.get("sub", ""))
    role = str(payload.get("role", "viewer"))
    return issue_token_pair(subject=subject, role=role)


def get_role_from_request(authorization: str | None, x_role: str | None) -> str:
    # 1순위 JWT
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_access_token(token)
        return str(payload.get("role", "viewer")).lower()

    # 하위호환: dev/local/test에서만 X-Role 허용
    if settings.ALLOW_LEGACY_X_ROLE and x_role:
        legacy_role = str(x_role).strip().lower()
        if legacy_role in ROLE_ORDER:
            return legacy_role

    raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")


def get_claims_from_request(authorization: str | None, access_cookie_token: str | None) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return decode_access_token(token, expected_type="access")

    if access_cookie_token:
        return decode_access_token(access_cookie_token, expected_type="access")

    raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")


def require_role(min_role: str):
    # JWT(access token) 또는 HttpOnly 쿠키 기반 access token만 허용
    def _checker(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_role: str | None = Header(default=None, alias="X-Role"),
        access_cookie_token: str | None = Cookie(default=None, alias="cs_access_token"),
    ):
        if authorization and authorization.lower().startswith("bearer "):
            incoming = get_role_from_request(authorization=authorization, x_role=x_role)
        elif settings.ALLOW_LEGACY_X_ROLE and x_role:
            incoming = get_role_from_request(authorization=None, x_role=x_role)
        elif access_cookie_token:
            payload = decode_access_token(access_cookie_token, expected_type="access")
            incoming = str(payload.get("role", "viewer")).lower()
        else:
            raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다")
        if ROLE_ORDER.get(incoming, 0) < ROLE_ORDER.get(min_role, 0):
            raise HTTPException(status_code=403, detail=f"권한 부족: {min_role} 이상 필요")
        return incoming

    return _checker
