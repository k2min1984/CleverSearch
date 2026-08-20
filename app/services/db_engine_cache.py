"""
########################################################
# Description
# 외부 DB 엔진 캐시 + 증분 쿼리 래퍼
# - DbSource 별로 SQLAlchemy Engine 을 프로세스 전역에 캐시하여
#   매 색인 실행마다 create_engine() / TCP 재연결을 반복하지 않도록 한다.
# - 관리자 등록 query_text 를 수정하지 않고 서브쿼리로 감싸서
#   cursor_column 기준 증분 SELECT 만 수행하도록 한다.
#
# 설계 근거: docs/증분색인_설계_20260424_현승준.md §4.2, §4.4
#
# Modified History
# 현승준 / 2026-04-27 / 최초생성 (Phase 2)
########################################################
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.engine import Engine

from app.core.database import DbSource
from app.utils.crypto import decrypt as _decrypt

_logger = logging.getLogger(__name__)

# 식별자(컬럼명/테이블명) 화이트리스트 — SQL injection 방지
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_engine_cache: dict[int, Engine] = {}
_engine_lock = threading.Lock()


def _safe_ident(ident: str, label: str) -> str:
    if not ident or not _IDENT_RE.match(ident):
        raise ValueError(f"잘못된 식별자({label}): {ident!r}. 영문/숫자/밑줄만 허용")
    return ident


def get_cached_engine(source: DbSource) -> Engine:
    """DbSource.id 단위로 Engine 을 캐시. pool_size 작게(2) + pre_ping + recycle 30분.

    설계서 §4.4 권장값: pool_size=2, max_overflow=2, pre_ping=True, recycle=1800.
    """
    eng = _engine_cache.get(source.id)
    if eng is not None:
        return eng
    with _engine_lock:
        eng = _engine_cache.get(source.id)
        if eng is not None:
            return eng
        url = _decrypt(source.connection_url)
        eng = create_engine(
            url,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        _engine_cache[source.id] = eng
        _logger.info("[db_engine_cache] new engine cached: source_id=%s name=%s", source.id, source.name)
        return eng


def invalidate_engine(source_id: int) -> None:
    """DbSource 변경/삭제 시 호출. 캐시된 엔진을 dispose 하고 제거."""
    with _engine_lock:
        eng = _engine_cache.pop(source_id, None)
    if eng is not None:
        try:
            eng.dispose()
        except Exception as exc:
            _logger.warning("[db_engine_cache] dispose 실패(무시) source_id=%s: %s", source_id, exc)


def clear_all() -> None:
    """앱 종료 시 호출하여 모든 엔진을 정리."""
    with _engine_lock:
        engines = list(_engine_cache.values())
        _engine_cache.clear()
    for eng in engines:
        try:
            eng.dispose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 증분 쿼리 래핑
# ---------------------------------------------------------------------------
def _coerce_cursor_value(cursor_type: str, raw: str | None) -> Any | None:
    """cursor_value(문자열) → 실제 비교용 파이썬 값으로 변환."""
    if raw is None or raw == "":
        return None
    t = (cursor_type or "").lower()
    if t == "int":
        return int(raw)
    if t == "datetime":
        # ISO 8601 포맷 가정 (저장 측에서 isoformat() 사용)
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            # 일부 DB 가 microsecond 없는 형식으로 반환할 수 있어 재시도
            return datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
    return str(raw)


def _stringify_cursor_value(cursor_type: str, value: Any) -> str:
    """DB 에서 가져온 값(파이썬 객체) → SyncJob.cursor_value(TEXT) 로 저장할 문자열."""
    if value is None:
        return ""
    t = (cursor_type or "").lower()
    if t == "datetime":
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
    return str(value)


def build_incremental_query(query_text: str, cursor_column: str, cursor_value_present: bool) -> str:
    """관리자 등록 query_text 를 서브쿼리로 감싸서 증분 SELECT 로 변환.

    설계서 §4.2:
        SELECT * FROM ( {query_text} ) AS __src
        WHERE __src.{cursor_column} > :cursor
        ORDER BY __src.{cursor_column} ASC
        LIMIT :chunk

    - cursor_value 가 비어 있을 때(첫 실행)는 WHERE 절을 생략 → 전체 처음부터
    - LIMIT/ORDER BY 는 항상 cursor_column 기준
    - DB 별 LIMIT 문법 차이는 SQLAlchemy LIMIT 가 표준화 처리 (Oracle 은 별도 처리)
    """
    safe_col = _safe_ident(cursor_column, "cursor_column")
    inner = (query_text or "").strip().rstrip(";")
    where_clause = f"WHERE __src.{safe_col} > :cursor" if cursor_value_present else ""
    return (
        f"SELECT * FROM ( {inner} ) AS __src "
        f"{where_clause} "
        f"ORDER BY __src.{safe_col} ASC "
        f"LIMIT :chunk"
    )


def fetch_next_chunk(
    engine: Engine,
    *,
    inner_query: str,
    cursor_column: str,
    cursor_type: str,
    cursor_value: str | None,
    chunk_size: int,
    db_type: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """증분 1 chunk 를 가져와 (rows, new_cursor_value) 로 반환.

    Oracle 처럼 LIMIT 미지원 DB 는 fetchmany(chunk_size) 로 대체한다.
    """
    safe_col = _safe_ident(cursor_column, "cursor_column")
    cursor_value_present = bool(cursor_value)
    typed_cursor = _coerce_cursor_value(cursor_type, cursor_value) if cursor_value_present else None

    db_t = (db_type or "").lower()
    use_limit = db_t not in {"oracle"}  # Oracle 11g 이하 LIMIT 미지원 → fetchmany 사용

    if use_limit:
        wrapped = build_incremental_query(inner_query, safe_col, cursor_value_present)
        params: dict[str, Any] = {"chunk": chunk_size}
        if cursor_value_present:
            params["cursor"] = typed_cursor
        with engine.connect() as conn:
            result = conn.execute(sql_text(wrapped), params)
            rows = [dict(r._mapping) for r in result.fetchall()]
    else:
        # Oracle: WHERE + ORDER BY 만 적용하고 fetchmany 로 chunk 크기만큼 컷
        inner = inner_query.strip().rstrip(";")
        where_clause = f"WHERE __src.{safe_col} > :cursor" if cursor_value_present else ""
        wrapped = (
            f"SELECT * FROM ( {inner} ) __src "
            f"{where_clause} "
            f"ORDER BY __src.{safe_col} ASC"
        )
        params = {}
        if cursor_value_present:
            params["cursor"] = typed_cursor
        with engine.connect() as conn:
            result = conn.execution_options(stream_results=True).execute(sql_text(wrapped), params)
            rows = [dict(r._mapping) for r in result.fetchmany(chunk_size)]

    if not rows:
        return [], cursor_value

    last_value = rows[-1].get(safe_col)
    new_cursor = _stringify_cursor_value(cursor_type, last_value)
    return rows, new_cursor
