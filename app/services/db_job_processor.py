"""
########################################################
# Description
# DB 색인 SyncJob 처리기 (Phase 2)
# - IndexingWorker 가 점유한 SyncJob(source_type='db') 을 위임받아
#   chunk 단위로 외부 DB 에서 증분 SELECT → IndexingService.index_bulk → cursor 갱신.
# - 호출 빈도가 잦은 로컬 DB 작업은 chunk 1회당 1 트랜잭션으로 묶는다.
# - 처리 완료 시 OpenSearch refresh 1회 + DbSource.last_cursor_value 승격 +
#   동기화 이력(SmbSyncHistory 통합 테이블) 요약 기록.
#
# 설계 근거: docs/증분색인_설계_20260424_현승준.md §4.5
#
# Modified History
# 현승준 / 2026-04-27 / 최초생성 (Phase 2)
########################################################
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.core.database import DbSource, SearchVolume, SessionLocal, SmbSyncHistory, SyncJob
from app.core.opensearch import get_client
from app.services.db_engine_cache import fetch_next_chunk, get_cached_engine
from app.services.indexing_service import IndexingService
from app.services.worker_service import IndexingWorker, register_handler

_logger = logging.getLogger(__name__)

# chunk 1회당 최대 row 수 — DbSource.chunk_size 우선, 없으면 이 값
DEFAULT_CHUNK_SIZE = 500
# 1 Job 당 최대 처리 row (안전장치) — cursor 가 잘못 박혀 무한 루프가 발생해도
# 워커가 영원히 잡혀있지 않도록 상한.
HARD_MAX_ROWS_PER_JOB = 1_000_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 외부 DB 데이터 → OpenSearch 입력 변환
# ---------------------------------------------------------------------------
def _row_to_index_item(source: DbSource, row: dict[str, Any]) -> dict[str, Any]:
    """외부 DB row → IndexingService.index_bulk 입력 dict 로 변환."""
    title_col = source.title_column or "title"
    pk_col = source.pk_column or "id"
    pk_value = row.get(pk_col)
    title = str(row.get(title_col) or f"{source.name}-{pk_value}")
    body_text = " ".join([str(v) for v in row.values() if v is not None])
    item: dict[str, Any] = {
        "filename": f"{source.name}_{title}.txt",
        "text": f"{title}\n{body_text}",
        "ext": "txt",
        "source_label": f"db:{source.name}",
    }
    if pk_value is not None:
        # 설계서 §4.3: doc_id = "{source.name}:{pk}" → 자동 덮어쓰기
        item["doc_id"] = f"{source.name}:{pk_value}"
    return item


# ---------------------------------------------------------------------------
# 짧은 트랜잭션 헬퍼 — chunk 단위 / Job 단위 진행 갱신
# ---------------------------------------------------------------------------
def _resolve_target_index(source: DbSource) -> str | None:
    target_ref = (source.target_volume or "").strip() or None
    if not target_ref:
        return None
    session = SessionLocal()
    try:
        volume = (
            session.query(SearchVolume).filter(SearchVolume.alias_name == target_ref).first()
            or session.query(SearchVolume).filter(SearchVolume.index_name == target_ref).first()
        )
        if not volume or not volume.is_active:
            raise RuntimeError(f"target_volume not available: {target_ref}")
        return (volume.index_name or "").strip() or None
    finally:
        session.close()


def _commit_chunk_progress(
    job_id: int,
    *,
    new_cursor: str | None,
    add_processed: int,
    add_indexed: int,
    add_skipped: int,
    add_failed: int,
) -> None:
    """chunk 1회 처리 결과 + cursor 갱신을 1 트랜잭션으로 commit (설계서 §4.5)."""
    now = _utcnow()
    session = SessionLocal()
    try:
        job = session.query(SyncJob).filter(SyncJob.id == job_id).first()
        if job is None:
            return
        if new_cursor is not None:
            job.cursor_value = new_cursor
        job.processed = (job.processed or 0) + add_processed
        job.indexed = (job.indexed or 0) + add_indexed
        job.skipped = (job.skipped or 0) + add_skipped
        job.failed = (job.failed or 0) + add_failed
        job.updated_at = now
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _promote_cursor_to_source(source_id: int, final_cursor: str | None) -> None:
    """Job 완료 시 SyncJob.cursor_value → DbSource.last_cursor_value 승격."""
    if final_cursor is None or final_cursor == "":
        return
    session = SessionLocal()
    try:
        src = session.query(DbSource).filter(DbSource.id == source_id).first()
        if src is None:
            return
        src.last_cursor_value = final_cursor
        src.last_synced_at = _utcnow()
        src.last_error = None
        src.updated_at = _utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_history(source_id: int, source_name: str, started_at: datetime,
                    finished_at: datetime, *, status: str,
                    indexed: int, skipped: int, failed: int,
                    message: str | None, trigger_type: str) -> None:
    """기존 동기화 이력 테이블(SmbSyncHistory) 에 결과 요약을 기록.

    설계서 §4.5: "IndexingHistory / SmbSyncHistory 에 결과 요약 기록 (기존 경로 유지)".
    DB 색인의 결과도 같은 테이블에 기록하여 이력 화면을 단일화한다.
    """
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    session = SessionLocal()
    try:
        session.add(
            SmbSyncHistory(
                source_id=source_id,
                source_name=source_name,
                status=status,
                indexed=indexed,
                skipped=skipped,
                failed=failed,
                trigger_type=trigger_type,
                message=(message[:500] if message else None),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        _logger.warning("[db_job] 이력 기록 실패(무시) source=%s: %s", source_name, exc)
    finally:
        session.close()


def _set_last_error(source_id: int, message: str) -> None:
    session = SessionLocal()
    try:
        src = session.query(DbSource).filter(DbSource.id == source_id).first()
        if src is not None:
            src.last_error = message[:500]
            src.updated_at = _utcnow()
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 메인 처리 루프
# ---------------------------------------------------------------------------
def process_db_job(job_id: int) -> dict[str, Any]:
    """DB 색인 Job 1건 처리.

    반환: {"status": "done"|"failed", "indexed", "skipped", "failed", "cursor", "error"}
    """
    started_at = _utcnow()

    # ---- 0) Job + 소스 정보 로드 (짧은 트랜잭션으로 분리) -----------------
    session = SessionLocal()
    try:
        job = session.query(SyncJob).filter(SyncJob.id == job_id).first()
        if job is None:
            return {"status": "failed", "error": f"job not found: {job_id}"}
        if job.source_type != "db":
            return {"status": "failed", "error": f"unexpected source_type: {job.source_type}"}

        source = session.query(DbSource).filter(DbSource.id == job.source_id).first()
        if source is None:
            return {"status": "failed", "error": f"db source not found: {job.source_id}"}
        if not (source.cursor_column and source.cursor_type and source.pk_column):
            msg = "DbSource 의 cursor_column/cursor_type/pk_column 이 설정되지 않음 — 관리자 화면에서 지정 필요"
            return _finalize(
                job_id=job_id, source_id=source.id, source_name=source.name,
                started_at=started_at, status="failed",
                trigger_type=job.trigger_type or "manual",
                indexed=0, skipped=0, failed=0,
                final_cursor=None, message=msg,
            )

        source_id = source.id
        source_name = source.name
        chunk_size = source.chunk_size or DEFAULT_CHUNK_SIZE
        cursor_column = source.cursor_column
        cursor_type = source.cursor_type
        db_type = source.db_type or ""
        # 뷰/테이블 모드: 식별자 화이트리스트로 안전하게 SELECT 조립.
        if not source.source_table:
            return _finalize(
                job_id=job_id, source_id=source.id, source_name=source.name,
                started_at=started_at, status="failed",
                trigger_type=job.trigger_type or "manual",
                indexed=0, skipped=0, failed=0,
                final_cursor=None,
                message="DbSource.source_table 미설정 — 관리자 화면에서 뷰/테이블 이름을 입력하세요",
            )
        try:
            from app.services.system_service import DBIngestionService
            inner_query = DBIngestionService._build_select_query(
                source_table=source.source_table,
                select_columns=source.select_columns,
                pk_column=source.pk_column,
                cursor_column=source.cursor_column,
                title_column=source.title_column,
            )
        except ValueError as build_exc:
            return _finalize(
                job_id=job_id, source_id=source.id, source_name=source.name,
                started_at=started_at, status="failed",
                trigger_type=job.trigger_type or "manual",
                indexed=0, skipped=0, failed=0,
                final_cursor=None,
                message=f"SELECT 자동 조립 실패: {build_exc}",
            )
        trigger_type = job.trigger_type or "manual"
        # 모드별 시작 cursor: full=초기화, incremental=Job 의 진행값(없으면 source 기준값)
        if job.mode == "full":
            current_cursor: str | None = None
        else:
            current_cursor = job.cursor_value or source.last_cursor_value or None

        # SQLAlchemy detached 사용 위해 엔진 캐시 키만 미리 가져오기
        engine = get_cached_engine(source)
    finally:
        session.close()

    # target_index 해석은 별도 짧은 세션
    try:
        target_index = _resolve_target_index_by_id(source_id)
    except Exception as exc:
        return _finalize(
            job_id=job_id, source_id=source_id, source_name=source_name,
            started_at=started_at, status="failed", trigger_type=trigger_type,
            indexed=0, skipped=0, failed=0, final_cursor=current_cursor,
            message=f"target_volume 해석 실패: {exc}",
        )

    # ---- 1) 메인 chunk 루프 -------------------------------------------------
    total_indexed = 0
    total_skipped = 0
    total_failed = 0
    total_processed = 0
    final_cursor = current_cursor
    last_error_msg: str | None = None

    while True:
        if total_processed >= HARD_MAX_ROWS_PER_JOB:
            last_error_msg = f"HARD_MAX_ROWS_PER_JOB({HARD_MAX_ROWS_PER_JOB}) 도달 — 다음 Job 으로 분할 필요"
            break

        try:
            rows, new_cursor = fetch_next_chunk(
                engine,
                inner_query=inner_query,
                cursor_column=cursor_column,
                cursor_type=cursor_type,
                cursor_value=current_cursor,
                chunk_size=chunk_size,
                db_type=db_type,
            )
        except Exception as exc:
            _logger.exception("[db_job] fetch_next_chunk 실패 job_id=%s: %s", job_id, exc)
            return _finalize(
                job_id=job_id, source_id=source_id, source_name=source_name,
                started_at=started_at, status="failed", trigger_type=trigger_type,
                indexed=total_indexed, skipped=total_skipped, failed=total_failed + 1,
                final_cursor=final_cursor, message=f"외부 DB 조회 실패: {exc}",
            )

        if not rows:
            break

        # 외부 DB row → bulk 입력 변환 (detached source 다시 로드)
        loaded = _load_source_brief(source_id)
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                items.append(_row_to_index_item(loaded, row))
            except Exception as exc:
                _logger.warning("[db_job] row 변환 실패: %s", exc)
                total_failed += 1

        try:
            bulk_res = IndexingService.index_bulk(items, index_name=target_index, refresh=False)
        except Exception as exc:
            _logger.exception("[db_job] index_bulk 실패 job_id=%s: %s", job_id, exc)
            return _finalize(
                job_id=job_id, source_id=source_id, source_name=source_name,
                started_at=started_at, status="failed", trigger_type=trigger_type,
                indexed=total_indexed, skipped=total_skipped,
                failed=total_failed + len(items),
                final_cursor=final_cursor,
                message=f"OpenSearch 색인 실패: {exc}",
            )

        chunk_indexed = bulk_res.get("indexed", 0)
        chunk_skipped = bulk_res.get("skipped", 0)
        chunk_failed = bulk_res.get("failed", 0)
        chunk_processed = chunk_indexed + chunk_skipped + chunk_failed

        total_indexed += chunk_indexed
        total_skipped += chunk_skipped
        total_failed += chunk_failed
        total_processed += chunk_processed
        final_cursor = new_cursor or final_cursor

        # 진행률 + cursor 1 트랜잭션 commit (설계서 §4.5)
        try:
            _commit_chunk_progress(
                job_id,
                new_cursor=new_cursor,
                add_processed=chunk_processed,
                add_indexed=chunk_indexed,
                add_skipped=chunk_skipped,
                add_failed=chunk_failed,
            )
        except Exception as exc:
            _logger.exception("[db_job] cursor commit 실패 job_id=%s: %s", job_id, exc)
            return _finalize(
                job_id=job_id, source_id=source_id, source_name=source_name,
                started_at=started_at, status="failed", trigger_type=trigger_type,
                indexed=total_indexed, skipped=total_skipped, failed=total_failed,
                final_cursor=final_cursor, message=f"cursor commit 실패: {exc}",
            )

        # lease 연장 (긴 Job 대비). 워커 점유시 셋팅된 lease 시간 기준으로 연장.
        IndexingWorker.renew_lease(job_id)

        # 부하 제어
        time.sleep(0.05)

        # chunk_size 미만으로 왔으면 더 가져올 데이터 없음 → 종료
        if len(rows) < chunk_size:
            current_cursor = final_cursor
            break

        current_cursor = final_cursor

    # ---- 2) Job 완료 처리: cursor 승격 + OpenSearch refresh 1회 ------------
    try:
        _promote_cursor_to_source(source_id, final_cursor)
    except Exception as exc:
        _logger.warning("[db_job] cursor 승격 실패(무시) source_id=%s: %s", source_id, exc)

    if target_index:
        try:
            get_client().indices.refresh(index=target_index)
        except Exception as exc:
            _logger.warning("[db_job] refresh 실패(무시) index=%s: %s", target_index, exc)

    return _finalize(
        job_id=job_id, source_id=source_id, source_name=source_name,
        started_at=started_at, status="done", trigger_type=trigger_type,
        indexed=total_indexed, skipped=total_skipped, failed=total_failed,
        final_cursor=final_cursor, message=last_error_msg,
    )


# ---------------------------------------------------------------------------
# 작은 헬퍼들
# ---------------------------------------------------------------------------
def _load_source_brief(source_id: int) -> DbSource:
    session = SessionLocal()
    try:
        return session.query(DbSource).filter(DbSource.id == source_id).first()
    finally:
        session.close()


def _resolve_target_index_by_id(source_id: int) -> str | None:
    src = _load_source_brief(source_id)
    if src is None:
        raise RuntimeError(f"db source not found: {source_id}")
    return _resolve_target_index(src)


def _finalize(*, job_id: int, source_id: int, source_name: str, started_at: datetime,
              status: str, trigger_type: str,
              indexed: int, skipped: int, failed: int,
              final_cursor: str | None, message: str | None) -> dict[str, Any]:
    finished_at = _utcnow()
    _record_history(
        source_id=source_id, source_name=source_name,
        started_at=started_at, finished_at=finished_at,
        status="success" if status == "done" else "fail",
        indexed=indexed, skipped=skipped, failed=failed,
        message=message, trigger_type=trigger_type,
    )
    if status == "failed" and message:
        _set_last_error(source_id, message)
    return {
        "status": status,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "cursor": final_cursor,
        "error": message if status == "failed" else None,
    }


# ---------------------------------------------------------------------------
# 핸들러 등록 (import 시점 1회) — Phase 2 진입점
# ---------------------------------------------------------------------------
register_handler("db", process_db_job)
