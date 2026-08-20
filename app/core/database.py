"""
########################################################
# Description
# 데이터베이스 설정 및 ORM 모델 정의
# SQLAlchemy 엔진/세션 생성 및 테이블 스키마 정의
# - 사용자 테이블 (auth_users, auth_roles)
# - 문서 목록 테이블 (indexed_documents)
# - 검색 로그 테이블 (search_logs)
# - 사전 테이블 (dictionary_entries)
# - 토큰 블랙리스트 (revoked_access/refresh_tokens)
#
# Modified History
# 강광민 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


DATABASE_URL = settings.DATABASE_URL

# DB 타입별 엔진 옵션 분기
_db_type = settings.DB_TYPE

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
elif _db_type == "oracle":
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        # Oracle: CLOB 등 LOB 바인딩 최적화
        thick_mode=False,
    )
elif _db_type in ("mysql", "mariadb"):
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        # MySQL/MariaDB: 연결 끊김 방지를 위한 짧은 recycle 권장
    )
else:
    # PostgreSQL (기본)
    _pg_connect_args: dict = {}
    if settings.DB_SCHEMA:
        # 세션 search_path 고정 → 모든 쿼리가 지정 스키마를 우선 조회
        _pg_connect_args["options"] = f"-csearch_path={settings.DB_SCHEMA},public"
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        connect_args=_pg_connect_args,
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SearchLog(Base):
    # 검색 실행 이력을 저장하여 인기검색/실패검색/추천검색의 원천 데이터로 사용합니다.
    __tablename__ = "search_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, default="anonymous", index=True)
    query = Column(String(300), nullable=False, index=True)
    total_hits = Column(Integer, nullable=False, default=0)
    is_failed = Column(Boolean, nullable=False, default=False, index=True)
    search_type = Column(String(50), nullable=False, default="manual_search")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class RecentSearch(Base):
    # 사용자별 최근 검색어를 별도로 관리하여 빠른 조회/삭제를 지원합니다.
    __tablename__ = "recent_searches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    query = Column(String(300), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class IndexedDocument(Base):
    # OpenSearch에 적재한 문서를 업무 DB에도 보관하여 관리자 조회/감사 추적에 사용합니다.
    __tablename__ = "indexed_documents"

    id = Column(Integer, primary_key=True, index=True)
    os_doc_id = Column(String(120), nullable=True, unique=True, index=True)
    origin_file = Column(String(260), nullable=False, index=True)
    file_ext = Column(String(20), nullable=False, index=True)
    doc_category = Column(String(50), nullable=False, index=True)
    content_hash = Column(String(600), nullable=False, unique=True, index=True)
    title = Column(String(300), nullable=False)
    all_text = Column(Text, nullable=False)
    indexed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class SmbSource(Base):
    # SMB/SSH 경로별 동기화 설정과 상태를 저장합니다.
    __tablename__ = "smb_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    connection_type = Column(String(10), nullable=False, default="smb", index=True)  # smb / ssh
    share_path = Column(String(400), nullable=False)
    username = Column(String(200), nullable=True)
    password = Column(String(200), nullable=True)
    domain = Column(String(100), nullable=True)
    port = Column(Integer, nullable=False, default=445)
    ssh_host = Column(String(200), nullable=True)       # SSH 서버 호스트
    ssh_key_path = Column(String(400), nullable=True)    # SSH 개인키 경로 (선택)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class DbSource(Base):
    # 다중 DB 수집 대상(Oracle/MySQL/PostgreSQL 등) 연결 정보를 저장합니다.
    __tablename__ = "db_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    db_type = Column(String(40), nullable=False, index=True)
    connection_url = Column(String(600), nullable=False)
    # [뷰/테이블 기반 색인]
    # 임의 SELECT 저장을 폐지하고, 운영자가 미리 만든 뷰 또는 테이블 이름과
    # 텍스트 컬럼 목록만 받아 백엔드가 안전하게 SELECT 를 자동 조립한다.
    # source_table  : 스키마.테이블 또는 단순 테이블/뷰 이름 (식별자 화이트리스트 검증)
    # select_columns: 색인 대상 텍스트 컬럼 콤마 구분 (각각 식별자 검증)
    source_table = Column(String(200), nullable=True)
    select_columns = Column(String(1000), nullable=True)
    target_volume = Column(String(120), nullable=True, index=True)
    title_column = Column(String(120), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    chunk_size = Column(Integer, nullable=False, default=500)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    # [증분 색인] 설계서 §4.1
    cursor_column = Column(String(128), nullable=True)        # 증분 기준 컬럼 (예: id, updated_at)
    cursor_type = Column(String(16), nullable=True)           # int | datetime | string
    last_cursor_value = Column(Text, nullable=True)           # 마지막 색인 완료 지점
    pk_column = Column(String(128), nullable=True)            # OpenSearch _id 생성용 PK 컬럼
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class SearchVolume(Base):
    # 검색 볼륨(인덱스) 등록/활성 상태를 관리합니다.
    __tablename__ = "search_volumes"

    id = Column(Integer, primary_key=True, index=True)
    index_name = Column(String(120), nullable=False, unique=True, index=True)
    alias_name = Column(String(120), nullable=True, unique=True, index=True)
    shards = Column(Integer, nullable=False, default=1)
    replicas = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class SmbSyncHistory(Base):
    # SMB 소스 동기화 실행 이력을 저장합니다.
    __tablename__ = "smb_sync_history"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("smb_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    source_name = Column(String(120), nullable=False, index=True)
    status = Column(String(20), nullable=False, index=True)  # success / fail
    indexed = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    trigger_type = Column(String(20), nullable=False, default="manual", index=True)  # manual / scheduler / watcher
    message = Column(String(500), nullable=True)
    started_at = Column(DateTime, nullable=False, index=True)
    finished_at = Column(DateTime, nullable=False, index=True)
    duration_ms = Column(Integer, nullable=False, default=0)


class IndexingHistory(Base):
    # 파일 변경 감지 및 자동 색인 실행 이력을 저장합니다.
    __tablename__ = "indexing_history"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, index=True)  # smb / db / upload
    source_name = Column(String(120), nullable=False, index=True)
    file_name = Column(String(260), nullable=True)
    action = Column(String(20), nullable=False, index=True)  # created / modified / deleted / sync
    status = Column(String(20), nullable=False, index=True)  # success / fail / skipped
    message = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class NetworkEventLog(Base):
    # 네트워크 단절/재연결 이벤트 이력을 저장합니다.
    __tablename__ = "network_event_logs"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, index=True)  # smb / db / opensearch
    source_name = Column(String(120), nullable=False, index=True)
    event_type = Column(String(30), nullable=False, index=True)  # disconnect / reconnect_attempt / reconnect_success / reconnect_fail
    detail = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class FileIndexState(Base):
    # 파일별 색인 상태(해시/수정시간)를 저장하여 증분 색인을 지원합니다.
    __tablename__ = "file_index_states"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, index=True)   # smb / ssh / local
    source_name = Column(String(120), nullable=False, index=True)
    file_path = Column(String(600), nullable=False)
    file_hash = Column(String(64), nullable=False)                 # SHA-256
    file_size = Column(Integer, nullable=False, default=0)
    last_modified = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    # [Phase 3] 설계서 §5.1
    mtime = Column(DateTime, nullable=True)                        # 원격 파일 수정 시각
    last_seen_at = Column(DateTime, nullable=True)                 # 최근 walk 관찰 시각
    os_doc_id = Column(String(64), nullable=True)                  # OpenSearch 문서 ID (PK upsert)

    __table_args__ = (
        Index("ix_file_state_src", "source_type", "source_name"),
        Index("ix_file_state_lookup", "source_type", "source_name", "file_path"),
    )


class SyncJob(Base):
    # 증분 색인용 작업 큐. 워커가 폴링하며 chunk 단위로 처리하고 cursor_value로 재개합니다.
    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(16), nullable=False, index=True)         # db | smb | ssh
    source_id = Column(Integer, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)  # pending | running | done | failed | paused
    mode = Column(String(16), nullable=False, default="incremental")     # incremental | full
    cursor_value = Column(Text, nullable=True)                           # DB: pk 값 / SMB: 마지막 파일 경로
    total_estimated = Column(BigInteger, nullable=True)
    processed = Column(BigInteger, nullable=False, default=0)
    indexed = Column(BigInteger, nullable=False, default=0)
    skipped = Column(BigInteger, nullable=False, default=0)
    failed = Column(BigInteger, nullable=False, default=0)
    worker_id = Column(String(64), nullable=True, index=True)
    lease_until = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    trigger_type = Column(String(16), nullable=False, default="manual")  # manual | schedule | boot
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_sync_jobs_status_created", "status", "created_at"),
        Index("ix_sync_jobs_source", "source_type", "source_id"),
    )


class DictionaryEntry(Base):
    # 동의어/불용어/사용자 사전 항목을 저장합니다.
    __tablename__ = "dictionary_entries"

    id = Column(Integer, primary_key=True, index=True)
    dict_type = Column(String(40), nullable=False, index=True)  # synonym|stopword|user
    term = Column(String(300), nullable=False, index=True)
    replacement = Column(String(300), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class ScheduleEntry(Base):
    # 소스별 동기화 스케줄 관리 테이블
    __tablename__ = "schedule_entries"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_schedule_source"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, index=True)  # smb / db
    source_id = Column(Integer, nullable=False, index=True)
    interval_minutes = Column(Integer, nullable=False, default=1440)  # 기본 24시간
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class CertificateStatus(Base):
    # 인증서 만료 추적용 상태를 저장합니다.
    __tablename__ = "certificate_status"

    id = Column(Integer, primary_key=True, index=True)
    cert_name = Column(String(260), nullable=False, unique=True, index=True)
    cert_path = Column(String(500), nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)
    days_left = Column(Integer, nullable=True, index=True)
    health_status = Column(String(40), nullable=False, default="unknown", index=True)
    last_checked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    message = Column(String(500), nullable=True)


class AuthRole(Base):
    # 역할 권한 정의 테이블
    __tablename__ = "auth_roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class AuthUser(Base):
    # 사용자 계정 및 권한 매핑 테이블
    __tablename__ = "auth_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(120), nullable=False, unique=True, index=True)
    password_hash = Column(String(400), nullable=False)
    role_id = Column(Integer, ForeignKey("auth_roles.id"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    # [보안] 초기 비밀번호 강제 변경 플래그. 시드 계정은 True. 첫 로그인 후 False.
    must_change_password = Column(Boolean, nullable=False, default=False, index=True)
    last_password_changed_at = Column(DateTime, nullable=True)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True, index=True)
    # [M-4] MFA(TOTP) 시크릿. 활성화 후 발급/검증.
    mfa_secret = Column(String(64), nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class AuthPasswordHistory(Base):
    # [M-3] 비밀번호 변경 이력 — 직전 N개 재사용 차단
    __tablename__ = "auth_password_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    password_hash = Column(String(400), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class AuditLog(Base):
    # [M-5] 감사 로그 — 인증/권한/관리 작업의 영속 기록
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, index=True)
    occurred_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    actor = Column(String(120), nullable=True, index=True)         # 사용자명 (인증 전이면 NULL)
    actor_role = Column(String(40), nullable=True, index=True)
    action = Column(String(80), nullable=False, index=True)        # login_success, login_fail, password_change, role_grant, ...
    target = Column(String(200), nullable=True, index=True)        # 대상 (대상 사용자명/리소스 ID/path)
    status = Column(String(20), nullable=False, default="success", index=True)  # success | fail | warn
    ip = Column(String(64), nullable=True, index=True)
    user_agent = Column(String(400), nullable=True)
    detail = Column(Text, nullable=True)                            # JSON 텍스트


class RevokedAccessToken(Base):
    # Access token 블랙리스트 테이블
    __tablename__ = "revoked_access_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(120), nullable=False, unique=True, index=True)
    subject = Column(String(120), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class RevokedRefreshToken(Base):
    # Refresh token 블랙리스트 테이블
    __tablename__ = "revoked_refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(120), nullable=False, unique=True, index=True)
    subject = Column(String(120), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


def hash_password(raw_password: str) -> str:
    # PBKDF2(SHA-256) 해시 문자열 생성.
    # OWASP 2026 권고치(>=600,000) 적용. 환경변수로 조정 가능.
    salt = os.urandom(16).hex()
    iterations = max(600_000, int(os.getenv("AUTH_PBKDF2_ITERATIONS", "600000")))
    digest = hashlib.pbkdf2_hmac("sha256", (raw_password or "").encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(raw_password: str, stored_hash: str) -> bool:
    try:
        algo, iter_text, salt, digest = (stored_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", (raw_password or "").encode("utf-8"), salt.encode("utf-8"), int(iter_text)).hex()
        return hmac.compare_digest(calc, digest)
    except Exception:
        return False


def validate_password_policy(raw: str, *, username: str | None = None) -> tuple[bool, str]:
    """[M-3] 비밀번호 정책 검증 — 길이/문자종/이름 포함 등.

    Returns (ok, message). 실패 시 사용자에게 알릴 사유를 한국어로.
    """
    pw = raw or ""
    if len(pw) < settings.AUTH_PW_MIN_LENGTH:
        return False, f"비밀번호는 최소 {settings.AUTH_PW_MIN_LENGTH}자 이상이어야 합니다"
    classes = 0
    if any(c.isupper() for c in pw):
        classes += 1
    if any(c.islower() for c in pw):
        classes += 1
    if any(c.isdigit() for c in pw):
        classes += 1
    if any(not c.isalnum() for c in pw):
        classes += 1
    if classes < settings.AUTH_PW_REQUIRE_CHARS_COUNT:
        return False, (
            f"비밀번호는 영대/영소/숫자/특수문자 중 {settings.AUTH_PW_REQUIRE_CHARS_COUNT}종 이상 포함해야 합니다"
        )
    if username and username.lower() in pw.lower():
        return False, "비밀번호에 사용자 ID 가 포함될 수 없습니다"
    # 단순 반복/연속 차단
    if any(seq in pw.lower() for seq in ("123456", "abcdef", "qwerty", "password", "admin")):
        return False, "취약한 비밀번호 패턴이 포함되어 있습니다"
    return True, "ok"


def is_password_in_history(user_id: int, raw: str) -> bool:
    """직전 N개 비밀번호 재사용 여부 확인."""
    n = max(0, int(settings.AUTH_PW_HISTORY_COUNT or 0))
    if n <= 0:
        return False
    with get_db_session() as db:
        rows = (
            db.query(AuthPasswordHistory)
            .filter(AuthPasswordHistory.user_id == user_id)
            .order_by(AuthPasswordHistory.created_at.desc())
            .limit(n)
            .all()
        )
        for r in rows:
            if verify_password(raw, r.password_hash):
                return True
    return False


def change_password(user_id: int, new_raw: str) -> dict:
    """비밀번호 변경 + 정책 검증 + history 기록 + must_change_password 해제."""
    with get_db_session() as db:
        user = db.query(AuthUser).filter(AuthUser.id == user_id, AuthUser.is_active.is_(True)).first()
        if not user:
            return {"status": "fail", "message": "사용자를 찾을 수 없습니다"}
        ok, msg = validate_password_policy(new_raw, username=user.username)
        if not ok:
            return {"status": "fail", "message": msg}
        if is_password_in_history(user.id, new_raw):
            return {"status": "fail", "message": f"직전 {settings.AUTH_PW_HISTORY_COUNT}개 비밀번호와 동일합니다"}
        if verify_password(new_raw, user.password_hash):
            return {"status": "fail", "message": "현재 비밀번호와 동일합니다"}

        now = datetime.now(timezone.utc)
        # 기존 hash 를 history 에 보관
        db.add(AuthPasswordHistory(user_id=user.id, password_hash=user.password_hash, created_at=now))
        # 갱신
        user.password_hash = hash_password(new_raw)
        user.must_change_password = False
        user.last_password_changed_at = now
        user.failed_login_count = 0
        user.locked_until = None
        user.updated_at = now
        # 보관 N개 초과 시 cleanup
        n = max(0, int(settings.AUTH_PW_HISTORY_COUNT or 0))
        if n > 0:
            old = (
                db.query(AuthPasswordHistory)
                .filter(AuthPasswordHistory.user_id == user.id)
                .order_by(AuthPasswordHistory.created_at.desc())
                .offset(n)
                .all()
            )
            for r in old:
                db.delete(r)
        db.flush()
        return {"status": "ok", "message": "비밀번호가 변경되었습니다"}


def write_audit_log(
    *,
    actor: str | None,
    actor_role: str | None,
    action: str,
    target: str | None = None,
    status: str = "success",
    ip: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """[M-5] audit_logs 영속 기록 — 실패해도 호출자 흐름은 끊지 않는다."""
    try:
        with get_db_session() as db:
            db.add(
                AuditLog(
                    actor=(actor or None),
                    actor_role=(actor_role or None),
                    action=(action or "")[:80],
                    target=(target or None) if target is None else str(target)[:200],
                    status=(status or "success")[:20],
                    ip=(ip or None) if ip is None else str(ip)[:64],
                    user_agent=(user_agent or None) if user_agent is None else str(user_agent)[:400],
                    detail=detail,
                )
            )
    except Exception:
        # audit 실패가 비즈니스 흐름을 끊지 않도록 보호
        pass


def _bootstrap_auth_seed() -> None:
    """초기 역할/계정 자동 등록.

    [보안 정책]
    - 운영 환경(prod/production)에서는 사용자 자동 시드를 차단한다 (역할만 등록).
      운영 첫 부팅 시 admin 계정은 INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD
      환경변수를 명시했을 때만 1회 생성하며 must_change_password=True 로 강제 변경 유도.
    - dev/local/test 환경에서도 시드 계정에 must_change_password=True 를 부여해
      배포/공유 시 우발적 권한 탈취 위험을 줄인다.
    """
    from app.core.config import settings  # 순환참조 회피 위해 함수 내부 import

    with get_db_session() as db:
        role_map = {}
        role_specs = [
            ("viewer", "조회 전용"),
            ("operator", "운영 작업"),
            ("admin", "관리자 전체 권한"),
        ]
        now = datetime.now(timezone.utc)

        for role_name, desc in role_specs:
            row = db.query(AuthRole).filter(AuthRole.name == role_name).first()
            if not row:
                row = AuthRole(name=role_name, description=desc, is_active=True, created_at=now)
                db.add(row)
                db.flush()
            role_map[role_name] = row.id

        is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}

        if is_prod:
            # 운영: 환경변수로 명시된 admin 1명만 생성 (없으면 사용자 생성 안 함)
            init_user = (os.getenv("INITIAL_ADMIN_USERNAME", "") or "").strip()
            init_pw = os.getenv("INITIAL_ADMIN_PASSWORD", "") or ""
            if init_user and init_pw and not db.query(AuthUser).filter(AuthUser.username == init_user).first():
                db.add(
                    AuthUser(
                        username=init_user,
                        password_hash=hash_password(init_pw),
                        role_id=role_map["admin"],
                        is_active=True,
                        must_change_password=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            return

        # dev/local/test: 편의 시드 (각 계정에 must_change_password=True 부여)
        user_specs = [
            ("viewer", "viewer123!", "viewer"),
            ("operator", "operator123!", "operator"),
            ("admin", "admin123!", "admin"),
        ]
        for username, password, role_name in user_specs:
            row = db.query(AuthUser).filter(AuthUser.username == username).first()
            if not row:
                db.add(
                    AuthUser(
                        username=username,
                        password_hash=hash_password(password),
                        role_id=role_map[role_name],
                        is_active=True,
                        must_change_password=True,
                        created_at=now,
                        updated_at=now,
                    )
                )


def _migrate_add_missing_columns() -> None:
    """기존 환경의 테이블에 신규 컬럼이 누락된 경우 ALTER TABLE ADD COLUMN 으로 보완합니다.

    `Base.metadata.create_all()` 은 이미 존재하는 테이블을 건드리지 않으므로,
    설계 변경으로 추가된 컬럼은 별도 ALTER 가 필요합니다 (Alembic 미사용 환경 한정).
    누락된 것만 추가하므로 반복 실행해도 안전합니다 (idempotent).
    """
    from sqlalchemy import inspect

    # (table_name, column_name, ddl_type, nullable) — DDL 은 SQLAlchemy 가 호환 처리
    targets = [
        ("db_sources", "cursor_column", "VARCHAR(128)", True),
        ("db_sources", "cursor_type", "VARCHAR(16)", True),
        ("db_sources", "last_cursor_value", "TEXT", True),
        ("db_sources", "pk_column", "VARCHAR(128)", True),
        # Phase 3 — file_index_states
        ("file_index_states", "mtime", "DATETIME", True),
        ("file_index_states", "last_seen_at", "DATETIME", True),
        ("file_index_states", "os_doc_id", "VARCHAR(64)", True),
    ]
    # 보조 인덱스 (table, name, columns) — CREATE INDEX IF NOT EXISTS 가능 DB 만 적용
    target_indexes = [
        ("file_index_states", "ix_file_state_src", ["source_type", "source_name"]),
        ("file_index_states", "ix_file_state_lookup", ["source_type", "source_name", "file_path"]),
    ]

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())

    # 핵심: DDL 마다 독립 트랜잭션으로 처리.
    # PostgreSQL 같은 DB 는 한 트랜잭션 안에서 DDL 하나가 실패하면 전체가 abort 되어
    # 이후 모든 DDL 이 'current transaction is aborted' 로 묻힌다.
    # 한 컬럼 ALTER 가 실패해도 다음 컬럼은 시도되도록 분리한다.
    for table_name, column_name, ddl_type, nullable in targets:
        if table_name not in existing_tables:
            continue
        # 매번 inspect 를 새로 — 직전 ALTER 가 성공했을 수 있으므로 캐시를 재사용하지 않는다.
        try:
            cols = {c["name"] for c in inspect(engine).get_columns(table_name)}
        except Exception as exc:
            print(f"[MIGRATE][WARN] inspect 실패: {table_name} -> {exc}")
            continue
        if column_name in cols:
            continue
        null_clause = "" if nullable else " NOT NULL"
        ddl = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}{null_clause}"
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(ddl)
        except Exception as exc:
            print(f"[MIGRATE][WARN] ADD COLUMN 실패: {table_name}.{column_name} -> {exc}")

    # 보조 인덱스 — 누락된 것만 생성 (각 인덱스도 독립 트랜잭션)
    for table_name, idx_name, idx_cols in target_indexes:
        if table_name not in existing_tables:
            continue
        try:
            existing_idx = {i["name"] for i in inspect(engine).get_indexes(table_name)}
        except Exception as exc:
            print(f"[MIGRATE][WARN] inspect 인덱스 실패: {table_name} -> {exc}")
            continue
        if idx_name in existing_idx:
            continue
        cols_csv = ", ".join(idx_cols)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"CREATE INDEX {idx_name} ON {table_name} ({cols_csv})")
        except Exception as exc:
            print(f"[MIGRATE][WARN] CREATE INDEX 실패: {table_name}.{idx_name} -> {exc}")


def init_database() -> None:
    # 로컬 개발 환경에서는 마이그레이션 전에도 최소 테이블이 자동 생성되도록 유지합니다.
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()
    _bootstrap_auth_seed()


@contextmanager
def get_db_session():
    # 서비스 계층에서 공통으로 사용하는 세션 컨텍스트입니다.
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
