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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
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
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
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
    # SMB 경로별 동기화 설정과 상태를 저장합니다.
    __tablename__ = "smb_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    share_path = Column(String(400), nullable=False)
    username = Column(String(200), nullable=True)
    password = Column(String(200), nullable=True)
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
    query_text = Column(Text, nullable=False)
    title_column = Column(String(120), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    chunk_size = Column(Integer, nullable=False, default=500)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


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
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


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
    # PBKDF2(SHA-256) 해시 문자열 생성
    salt = os.urandom(16).hex()
    iterations = 200_000
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


def _bootstrap_auth_seed() -> None:
    # 초기 역할/계정 자동 등록
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
                        created_at=now,
                        updated_at=now,
                    )
                )


def init_database() -> None:
    # 로컬 개발 환경에서는 마이그레이션 전에도 최소 테이블이 자동 생성되도록 유지합니다.
    Base.metadata.create_all(bind=engine)
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
