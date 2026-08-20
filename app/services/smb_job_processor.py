"""
########################################################
# Description
# SMB/SSH 색인 SyncJob 처리기 (Phase 3)
# - IndexingWorker 가 점유한 SyncJob(source_type='smb' 또는 'ssh') 을 위임받아
#   3단계 필터(메타 → 메모리 dict 비교 → 변경 후보만 read_bytes → 해시 비교)로
#   네트워크 read_bytes 호출을 최소화한 뒤 IndexingService.index_bulk 로 색인.
# - 파일 상태(FileIndexState) 는 batch UPSERT(300건) 로 일괄 반영.
# - 체크포인트는 SyncJob.cursor_value 에 마지막 처리 파일 경로(rel_path)로 저장.
#
# 설계 근거: docs/증분색인_설계_20260424_현승준.md §5.1 ~ §5.7
#
# Modified History
# 현승준 / 2026-04-27 / 최초생성 (Phase 3)
########################################################
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.config import settings
from app.core.database import (
    FileIndexState,
    SearchVolume,
    SessionLocal,
    SmbSource,
    SmbSyncHistory,
    SyncJob,
)
from app.core.opensearch import get_client
from app.services.indexing_service import ALLOWED_EXTENSIONS, IndexingService
from app.services.worker_service import IndexingWorker, register_handler
from app.utils.crypto import decrypt as _decrypt
from app.utils.file_entry import FileEntry

_logger = logging.getLogger(__name__)

# 한 chunk 안에서 OpenSearch 색인 + FileIndexState UPSERT 를 묶을 단위
INDEX_CHUNK_SIZE = 50          # read_bytes + index_bulk 묶음 (메모리 보호)
STATE_UPSERT_CHUNK = 300       # FileIndexState 배치 UPSERT 단위 (설계서 §5.5)
HARD_MAX_FILES_PER_JOB = 200_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# 짧은 트랜잭션 헬퍼
# ---------------------------------------------------------------------------
def _resolve_target_index(target_volume: str | None) -> str | None:
    target_ref = (target_volume or "").strip() or None
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


def _load_state_index(source_type: str, source_name: str) -> dict[str, dict[str, Any]]:
    """walk 시작 시점에 file_index_states 를 1회 SELECT 하여 메모리 dict 로 로드.

    설계서 §5.3 단계 2: 파일별 개별 SELECT 폭증을 막기 위한 핵심 최적화.
    반환: {file_path: {hash, size, mtime, os_doc_id, id}}
    """
    session = SessionLocal()
    try:
        rows = (
            session.query(FileIndexState)
            .filter(FileIndexState.source_type == source_type)
            .filter(FileIndexState.source_name == source_name)
            .all()
        )
        return {
            r.file_path: {
                "id": r.id,
                "hash": r.file_hash,
                "size": r.file_size or 0,
                "mtime": r.mtime,
                "os_doc_id": r.os_doc_id,
            }
            for r in rows
        }
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
    """SyncJob 진행률 + cursor 갱신 (chunk 1회당 1 트랜잭션)."""
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


def _batch_upsert_states(
    source_type: str,
    source_name: str,
    states: list[dict[str, Any]],
) -> None:
    """FileIndexState 배치 UPSERT.

    설계서 §5.5 — DB 별 ON CONFLICT 구문이 다르므로 dialect 분기.
    SQLite/PostgreSQL: ON CONFLICT (...) DO UPDATE
    MySQL/MariaDB:    ON DUPLICATE KEY UPDATE
    Oracle:           MERGE
    fallback:         존재 여부 SELECT 후 UPDATE/INSERT (이상적이지는 않지만 동작 보장)

    각 state dict 키:
      file_path, file_hash, file_size, mtime, last_seen_at, indexed_at, os_doc_id
    """
    if not states:
        return
    session = SessionLocal()
    try:
        dialect = session.bind.dialect.name
        # source_type+source_name+file_path 조합이 논리적 유니크.
        # 현재 스키마에는 UNIQUE 제약이 없으므로(설계서 §5.1 인덱스만 있음),
        # ON CONFLICT 의 충돌 키로 사용할 수 없다 → SELECT 후 UPDATE/INSERT 분기.
        # (UNIQUE 제약은 추후 별도 마이그레이션으로 검토)
        existing_paths = {
            r[0]: (r[1], r[2])  # file_path -> (id, indexed_at)
            for r in (
                session.query(FileIndexState.file_path, FileIndexState.id, FileIndexState.indexed_at)
                .filter(FileIndexState.source_type == source_type)
                .filter(FileIndexState.source_name == source_name)
                .filter(FileIndexState.file_path.in_([s["file_path"] for s in states]))
                .all()
            )
        }

        new_rows: list[FileIndexState] = []
        update_count = 0
        for s in states:
            fp = s["file_path"]
            if fp in existing_paths:
                row_id, _ = existing_paths[fp]
                session.query(FileIndexState).filter(FileIndexState.id == row_id).update(
                    {
                        FileIndexState.file_hash: s["file_hash"],
                        FileIndexState.file_size: s["file_size"],
                        FileIndexState.mtime: s.get("mtime"),
                        FileIndexState.last_seen_at: s.get("last_seen_at"),
                        FileIndexState.indexed_at: s.get("indexed_at"),
                        FileIndexState.os_doc_id: s.get("os_doc_id"),
                    },
                    synchronize_session=False,
                )
                update_count += 1
            else:
                new_rows.append(
                    FileIndexState(
                        source_type=source_type,
                        source_name=source_name,
                        file_path=fp,
                        file_hash=s["file_hash"],
                        file_size=s["file_size"],
                        mtime=s.get("mtime"),
                        last_seen_at=s.get("last_seen_at"),
                        indexed_at=s.get("indexed_at"),
                        os_doc_id=s.get("os_doc_id"),
                    )
                )
        if new_rows:
            session.bulk_save_objects(new_rows)
        session.commit()
        _logger.debug("[smb_job] state upsert: insert=%d update=%d dialect=%s",
                      len(new_rows), update_count, dialect)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_history(
    source_id: int, source_name: str, conn_type: str,
    started_at: datetime, finished_at: datetime, *,
    status: str, indexed: int, skipped: int, failed: int, unchanged: int,
    message: str | None, trigger_type: str,
) -> None:
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    summary = f"unchanged={unchanged}"
    final_msg = (message or "")[:500] if message else summary
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
                message=final_msg,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        _logger.warning("[smb_job] 이력 기록 실패(무시) source=%s: %s", source_name, exc)
    finally:
        session.close()


def _set_last_error(source_id: int, message: str) -> None:
    session = SessionLocal()
    try:
        src = session.query(SmbSource).filter(SmbSource.id == source_id).first()
        if src is not None:
            src.last_error = message[:500]
            src.updated_at = _utcnow()
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 클라이언트 생성 (SMB / SFTP)
# ---------------------------------------------------------------------------
def _build_client(source: SmbSource):
    password = _decrypt(source.password) if source.password else None
    conn_type = (source.connection_type or "smb").lower()
    if conn_type == "ssh":
        from app.utils.sftp_client import SFTPClient
        return SFTPClient(
            host=source.ssh_host or "",
            remote_path=source.share_path,
            username=source.username,
            password=password,
            port=source.port or 22,
            key_path=source.ssh_key_path,
        ), conn_type
    from app.utils.smb_client import SMBClient
    return SMBClient(
        share_path=source.share_path,
        username=source.username,
        password=password,
        domain=source.domain,
        port=source.port or 445,
    ), conn_type


# ---------------------------------------------------------------------------
# 3단계 필터 — 메타 비교
# ---------------------------------------------------------------------------
def _is_meta_unchanged(state: dict[str, Any] | None, entry: FileEntry) -> bool:
    """state(이전 상태) 와 entry(walk 결과) 의 size/mtime 이 동일하면 True (변경 없음).

    설계서 §5.3 단계 3: "로컬 있음 + size & mtime 동일 → SKIP".
    mtime 비교는 양쪽 다 datetime 인 경우만, None 이면 미일치로 간주(읽어서 해시 비교).
    """
    if state is None:
        return False
    if (state.get("size") or 0) != (entry.size or 0):
        return False
    s_mtime = state.get("mtime")
    e_mtime = entry.mtime
    if s_mtime is None or e_mtime is None:
        return False
    # tz-aware 보정
    if s_mtime.tzinfo is None and e_mtime.tzinfo is not None:
        s_mtime = s_mtime.replace(tzinfo=timezone.utc)
    if e_mtime.tzinfo is None and s_mtime.tzinfo is not None:
        e_mtime = e_mtime.replace(tzinfo=timezone.utc)
    # 1초 이내 오차는 동일 (DB 포맷별 microsecond 차이 흡수)
    return abs((s_mtime - e_mtime).total_seconds()) < 1.0


# ---------------------------------------------------------------------------
# 메인 처리 루프
# ---------------------------------------------------------------------------
def process_smb_job(job_id: int) -> dict[str, Any]:
    """SMB/SSH 색인 Job 1건 처리."""
    started_at = _utcnow()

    # ---- 0) Job + 소스 정보 로드 ----------------------------------------
    session = SessionLocal()
    try:
        job = session.query(SyncJob).filter(SyncJob.id == job_id).first()
        if job is None:
            return {"status": "failed", "error": f"job not found: {job_id}"}
        if job.source_type not in {"smb", "ssh"}:
            return {"status": "failed", "error": f"unexpected source_type: {job.source_type}"}

        source = session.query(SmbSource).filter(SmbSource.id == job.source_id).first()
        if source is None:
            return {"status": "failed", "error": f"smb source not found: {job.source_id}"}

        source_id = source.id
        source_name = source.name
        target_volume = None  # SmbSource 에는 target_volume 컬럼이 없음 → 기본 인덱스 사용
        trigger_type = job.trigger_type or "manual"
        cursor_value = None if job.mode == "full" else (job.cursor_value or None)
        # detached 후에도 사용할 source 사본 유지
        source_obj = source
        client_kwargs_holder = {"source_obj": source_obj}
    finally:
        session.close()

    # 클라이언트 생성 + 연결
    try:
        client, conn_type = _build_client(client_kwargs_holder["source_obj"])
    except Exception as exc:
        return _finalize(
            job_id=job_id, source_id=source_id, source_name=source_name,
            conn_type=(client_kwargs_holder["source_obj"].connection_type or "smb"),
            started_at=started_at, status="failed", trigger_type=trigger_type,
            indexed=0, skipped=0, failed=0, unchanged=0,
            final_cursor=cursor_value, message=f"클라이언트 초기화 실패: {exc}",
        )

    try:
        client.connect()
    except Exception as exc:
        return _finalize(
            job_id=job_id, source_id=source_id, source_name=source_name,
            conn_type=conn_type, started_at=started_at, status="failed",
            trigger_type=trigger_type,
            indexed=0, skipped=0, failed=0, unchanged=0,
            final_cursor=cursor_value, message=f"{conn_type.upper()} 연결 실패: {exc}",
        )

    target_index = None
    try:
        # SmbSource 에 target_volume 이 없으니 OpenSearch 기본 인덱스 사용
        target_index = _resolve_target_index(target_volume)
    except Exception as exc:
        client.disconnect()
        return _finalize(
            job_id=job_id, source_id=source_id, source_name=source_name,
            conn_type=conn_type, started_at=started_at, status="failed",
            trigger_type=trigger_type,
            indexed=0, skipped=0, failed=0, unchanged=0,
            final_cursor=cursor_value, message=f"target_volume 해석 실패: {exc}",
        )

    # 단계 2: 로컬 상태 1회 bulk SELECT → 메모리 dict (설계서 §5.3)
    state_index = _load_state_index(conn_type, source_name)

    total_indexed = 0
    total_skipped = 0
    total_failed = 0
    total_unchanged = 0
    total_processed = 0
    final_cursor = cursor_value
    last_error_msg: str | None = None

    pending_items: list[dict[str, Any]] = []
    pending_states: list[dict[str, Any]] = []
    skipping_to_cursor = bool(cursor_value)  # 재개 시 cursor 까지 빠르게 스킵
    last_path_processed: str | None = None

    try:
        for entry in client.walk(allowed_extensions=ALLOWED_EXTENSIONS):
            if total_processed >= HARD_MAX_FILES_PER_JOB:
                last_error_msg = f"HARD_MAX_FILES_PER_JOB({HARD_MAX_FILES_PER_JOB}) 도달"
                break

            # 체크포인트 재개: cursor 까지 빠르게 skip (메타 read 도 안 함)
            if skipping_to_cursor:
                if entry.rel_path <= cursor_value:  # type: ignore[operator]
                    continue
                skipping_to_cursor = False

            file_name = entry.rel_path.split("\\")[-1].split("/")[-1]
            state = state_index.get(entry.rel_path)

            # 단계 3-a: 로컬 있고 메타 동일 → SKIP (read_bytes 회피, 핵심 최적화)
            if _is_meta_unchanged(state, entry):
                total_unchanged += 1
                total_processed += 1
                last_path_processed = entry.rel_path
                # last_seen_at 만 갱신할 필요는 있지만, batch UPSERT 가 무거워지므로
                # 메타 동일은 굳이 row 를 업데이트하지 않는다 (mtime 만 그대로 유지).
                continue

            # 단계 3-b/3-c: 메타 다름 → read_bytes 후 해시 비교
            # 단, 파일 크기 상한 초과면 read 자체를 회피 (네트워크/메모리/OS bulk 부하 모두 절감)
            max_size = getattr(settings, "INDEX_MAX_FILE_SIZE_BYTES", 0) or 0
            if max_size > 0 and (entry.size or 0) > max_size:
                _logger.info(
                    "[smb_job] skip oversized: %s size=%d > limit=%d",
                    entry.full_path, entry.size or 0, max_size,
                )
                total_skipped += 1
                total_processed += 1
                last_path_processed = entry.rel_path
                continue

            try:
                content = client.read_bytes(entry.full_path)
            except Exception as exc:
                _logger.warning("[smb_job] read_bytes 실패: %s — %s", entry.full_path, exc)
                total_failed += 1
                total_processed += 1
                last_path_processed = entry.rel_path
                continue

            new_hash = _compute_hash(content)
            if state and state.get("hash") == new_hash:
                # 단계 3-c: 해시 동일 → 색인 스킵, mtime/size 만 갱신
                total_unchanged += 1
                total_processed += 1
                last_path_processed = entry.rel_path
                pending_states.append({
                    "file_path": entry.rel_path,
                    "file_hash": new_hash,
                    "file_size": len(content),
                    "mtime": entry.mtime,
                    "last_seen_at": _utcnow(),
                    "indexed_at": state.get("indexed_at") if state else _utcnow(),
                    "os_doc_id": state.get("os_doc_id") if state else None,
                })
                if len(pending_states) >= STATE_UPSERT_CHUNK:
                    _batch_upsert_states(conn_type, source_name, pending_states)
                    pending_states = []
                continue

            # 단계 3-c (해시 다름) 또는 신규: 실제 색인 대상
            try:
                text_content, ext = IndexingService._extract_text(file_name, content)
                if not text_content.strip():
                    total_skipped += 1
                    total_processed += 1
                    last_path_processed = entry.rel_path
                    continue
            except Exception as exc:
                _logger.warning("[smb_job] 텍스트 추출 실패 %s: %s", file_name, exc)
                total_failed += 1
                total_processed += 1
                last_path_processed = entry.rel_path
                continue

            os_doc_id = f"{conn_type}:{source_name}:{entry.rel_path}"
            pending_items.append({
                "filename": file_name,
                "text": text_content,
                "ext": ext,
                "doc_id": os_doc_id,
                "source_label": f"{conn_type}:{source_name}",
                "content_hash": new_hash,
            })
            pending_states.append({
                "file_path": entry.rel_path,
                "file_hash": new_hash,
                "file_size": len(content),
                "mtime": entry.mtime,
                "last_seen_at": _utcnow(),
                "indexed_at": _utcnow(),
                "os_doc_id": os_doc_id,
            })
            last_path_processed = entry.rel_path

            # INDEX_CHUNK_SIZE 도달 시 즉시 색인 + commit (설계서 §4.5/§5 흐름)
            if len(pending_items) >= INDEX_CHUNK_SIZE:
                stats = _flush_index_chunk(target_index, pending_items)
                total_indexed += stats["indexed"]
                total_skipped += stats["skipped"]
                total_failed += stats["failed"]
                total_processed += len(pending_items)
                pending_items = []

                if len(pending_states) >= STATE_UPSERT_CHUNK:
                    _batch_upsert_states(conn_type, source_name, pending_states)
                    pending_states = []

                final_cursor = last_path_processed or final_cursor
                _commit_chunk_progress(
                    job_id,
                    new_cursor=final_cursor,
                    add_processed=stats["indexed"] + stats["skipped"] + stats["failed"],
                    add_indexed=stats["indexed"],
                    add_skipped=stats["skipped"],
                    add_failed=stats["failed"],
                )
                IndexingWorker.renew_lease(job_id)
                time.sleep(0.05)

        # 루프 종료 — 잔여분 flush
        if pending_items:
            stats = _flush_index_chunk(target_index, pending_items)
            total_indexed += stats["indexed"]
            total_skipped += stats["skipped"]
            total_failed += stats["failed"]
            total_processed += len(pending_items)
            pending_items = []
            final_cursor = last_path_processed or final_cursor
            _commit_chunk_progress(
                job_id,
                new_cursor=final_cursor,
                add_processed=stats["indexed"] + stats["skipped"] + stats["failed"],
                add_indexed=stats["indexed"],
                add_skipped=stats["skipped"],
                add_failed=stats["failed"],
            )

        if pending_states:
            _batch_upsert_states(conn_type, source_name, pending_states)
            pending_states = []

    except Exception as exc:
        _logger.exception("[smb_job] 처리 중 예외 job_id=%s: %s", job_id, exc)
        last_error_msg = f"처리 실패: {exc}"
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    # OpenSearch refresh 1회 (설계서 §3.3)
    if target_index and (total_indexed > 0):
        try:
            get_client().indices.refresh(index=target_index)
        except Exception as exc:
            _logger.warning("[smb_job] refresh 실패(무시) index=%s: %s", target_index, exc)

    # SmbSource.last_seen_at 갱신 (성공 시)
    if last_error_msg is None:
        try:
            session = SessionLocal()
            try:
                src = session.query(SmbSource).filter(SmbSource.id == source_id).first()
                if src is not None:
                    src.last_seen_at = _utcnow()
                    src.last_error = None
                    src.updated_at = _utcnow()
                    session.commit()
            finally:
                session.close()
        except Exception:
            pass

    return _finalize(
        job_id=job_id, source_id=source_id, source_name=source_name,
        conn_type=conn_type, started_at=started_at,
        status="failed" if last_error_msg else "done",
        trigger_type=trigger_type,
        indexed=total_indexed, skipped=total_skipped, failed=total_failed,
        unchanged=total_unchanged, final_cursor=final_cursor, message=last_error_msg,
    )


def _flush_index_chunk(target_index: str | None, items: list[dict[str, Any]]) -> dict[str, int]:
    """OpenSearch _bulk 색인 1회 호출의 결과 카운트만 추출."""
    try:
        res = IndexingService.index_bulk(items, index_name=target_index, refresh=False)
        return {
            "indexed": int(res.get("indexed", 0)),
            "skipped": int(res.get("skipped", 0)),
            "failed": int(res.get("failed", 0)),
        }
    except Exception as exc:
        _logger.exception("[smb_job] index_bulk 실패: %s", exc)
        return {"indexed": 0, "skipped": 0, "failed": len(items)}


def _finalize(*, job_id: int, source_id: int, source_name: str, conn_type: str,
              started_at: datetime, status: str, trigger_type: str,
              indexed: int, skipped: int, failed: int, unchanged: int,
              final_cursor: str | None, message: str | None) -> dict[str, Any]:
    finished_at = _utcnow()
    _record_history(
        source_id=source_id, source_name=source_name, conn_type=conn_type,
        started_at=started_at, finished_at=finished_at,
        status="success" if status == "done" else "fail",
        indexed=indexed, skipped=skipped, failed=failed, unchanged=unchanged,
        message=message, trigger_type=trigger_type,
    )
    if status == "failed" and message:
        _set_last_error(source_id, message)
    return {
        "status": status,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "unchanged": unchanged,
        "cursor": final_cursor,
        "error": message if status == "failed" else None,
    }


# ---------------------------------------------------------------------------
# 핸들러 등록 (import 시점 1회)
# ---------------------------------------------------------------------------
register_handler("smb", process_smb_job)
register_handler("ssh", process_smb_job)
