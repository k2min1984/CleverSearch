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
import base64
import hashlib
import hmac as _hmac
import os
import secrets
import struct
import time as _time
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
    """사용자 인증 + DB 기반 잠금 정책.

    - 메모리 카운터(_LOGIN_ATTEMPTS) 가 워커별이라 분산/재시작 시 우회 가능했던 문제를
      AuthUser.failed_login_count / locked_until 컬럼으로 영속화.
    - 실패 누적 5회 도달 시 15분 잠금. 성공 시 카운터 리셋.
    """
    uname = (username or "").strip()
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.username == uname, AuthUser.is_active.is_(True)).first()
        if not user:
            # username enumeration 방지: 동일 메시지/지연
            raise HTTPException(status_code=401, detail="로그인 실패")

        if user.locked_until and user.locked_until > now:
            wait = int((user.locked_until - now).total_seconds())
            raise HTTPException(status_code=429, detail=f"계정 잠김 — {wait}초 후 다시 시도하세요")

        if not verify_password(password or "", user.password_hash):
            user.failed_login_count = int(user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.AUTH_RATE_LIMIT_MAX_ATTEMPTS:
                user.locked_until = now + timedelta(seconds=settings.AUTH_RATE_LIMIT_BLOCK_SECONDS)
                user.failed_login_count = 0
            user.updated_at = now
            db.flush()
            raise HTTPException(status_code=401, detail="로그인 실패")

        role = db.query(AuthRole).filter(AuthRole.id == user.role_id, AuthRole.is_active.is_(True)).first()
        if not role:
            raise HTTPException(status_code=401, detail="권한 정보 없음")

        # 성공 → 카운터 리셋
        if user.failed_login_count or user.locked_until:
            user.failed_login_count = 0
            user.locked_until = None
            user.updated_at = now
            db.flush()

        return {"username": user.username, "role": role.name}


def _access_minutes_for(role: str) -> int:
    r = (role or "").lower()
    if r == "admin":
        return int(settings.JWT_ACCESS_MINUTES_ADMIN or settings.JWT_EXPIRE_MINUTES)
    if r == "operator":
        return int(settings.JWT_ACCESS_MINUTES_OPERATOR or settings.JWT_EXPIRE_MINUTES)
    if r == "viewer":
        return int(settings.JWT_ACCESS_MINUTES_VIEWER or settings.JWT_EXPIRE_MINUTES)
    return int(settings.JWT_EXPIRE_MINUTES)


def _refresh_minutes_for(role: str) -> int:
    r = (role or "").lower()
    if r == "admin":
        return int(settings.JWT_REFRESH_MINUTES_ADMIN or settings.JWT_REFRESH_EXPIRE_MINUTES)
    if r == "operator":
        return int(settings.JWT_REFRESH_MINUTES_OPERATOR or settings.JWT_REFRESH_EXPIRE_MINUTES)
    if r == "viewer":
        return int(settings.JWT_REFRESH_MINUTES_VIEWER or settings.JWT_REFRESH_EXPIRE_MINUTES)
    return int(settings.JWT_REFRESH_EXPIRE_MINUTES)


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_access_minutes_for(role))
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
    expire = datetime.now(timezone.utc) + timedelta(minutes=_refresh_minutes_for(role))
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


_LAST_REVOKED_CLEANUP_AT = 0.0


def _b32_secret(length: int = 20) -> str:
    """RFC 4648 Base32 시크릿 (TOTP 표준 길이)."""
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8))
    msg = struct.pack(">Q", counter)
    digest = _hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = ((digest[offset] & 0x7F) << 24) | (digest[offset + 1] << 16) | (digest[offset + 2] << 8) | digest[offset + 3]
    return str(code % (10 ** digits)).zfill(digits)


def _totp_now(secret_b32: str, *, period: int = 30, digits: int = 6) -> str:
    return _hotp(secret_b32, int(_time.time()) // period, digits)


def verify_totp(secret_b32: str, code: str, *, drift: int = 1, period: int = 30) -> bool:
    """RFC 6238 TOTP 검증. drift 윈도 ±1 (총 90초)."""
    if not secret_b32 or not code:
        return False
    try:
        cur = int(_time.time()) // period
        for off in range(-drift, drift + 1):
            if _hmac.compare_digest(_hotp(secret_b32, cur + off), code.strip()):
                return True
    except Exception:
        return False
    return False


def enroll_totp(username: str) -> dict:
    """[M-4] 사용자에게 임시 secret 발급 → otpauth:// URL 반환. 확정은 confirm_totp."""
    secret = _b32_secret(20)
    issuer = settings.MFA_ISSUER or "CleverSearch"
    label = f"{issuer}:{username}"
    otpauth = (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    )
    return {"secret": secret, "otpauth_url": otpauth}


def confirm_totp(user_id: int, secret_b32: str, code: str) -> dict:
    """등록 단계: 사용자가 secret 으로 첫 코드 검증을 통과하면 mfa_enabled=True 저장."""
    if not verify_totp(secret_b32, code):
        return {"status": "fail", "message": "코드가 일치하지 않습니다"}
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
        if not user:
            return {"status": "fail", "message": "사용자를 찾을 수 없습니다"}
        user.mfa_secret = secret_b32
        user.mfa_enabled = True
        user.updated_at = datetime.now(timezone.utc)
        db.flush()
    return {"status": "ok", "message": "MFA 등록 완료"}


def cleanup_expired_revoked_tokens(force: bool = False) -> dict:
    """폐기 토큰 테이블에서 만료 시각이 지난 row 제거 — 무한 누적 차단."""
    global _LAST_REVOKED_CLEANUP_AT
    now_ts = monotonic()
    # 호출 빈도 보호: 최소 5분 간격 (force=True 면 무시)
    if not force and now_ts - _LAST_REVOKED_CLEANUP_AT < 300:
        return {"status": "skipped", "reason": "throttled"}
    _LAST_REVOKED_CLEANUP_AT = now_ts

    deleted_access = 0
    deleted_refresh = 0
    cutoff = datetime.now(timezone.utc)
    try:
        with get_db_session() as db:
            deleted_access = db.query(RevokedAccessToken).filter(RevokedAccessToken.expires_at < cutoff).delete(synchronize_session=False)
            deleted_refresh = db.query(RevokedRefreshToken).filter(RevokedRefreshToken.expires_at < cutoff).delete(synchronize_session=False)
    except Exception as exc:
        return {"status": "fail", "message": str(exc)}
    return {"status": "ok", "deleted_access": deleted_access, "deleted_refresh": deleted_refresh}


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
