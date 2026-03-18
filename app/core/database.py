from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


DATABASE_URL = settings.DATABASE_URL
# SQLite는 개발 편의용 기본값이고, 운영에서는 PostgreSQL URL로 교체됩니다.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
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


def init_database() -> None:
    # 로컬 개발 환경에서는 마이그레이션 전에도 최소 테이블이 자동 생성되도록 유지합니다.
    Base.metadata.create_all(bind=engine)


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
