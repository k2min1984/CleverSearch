"""
########################################################
# Description
# 증분 색인 워커 서비스 (IndexingWorker)
# - SyncJob 테이블을 폴링하여 한 번에 한 Job을 점유(lease)하고
#   소스 타입별 핸들러로 위임 처리한다.
# - 외부 의존성(Redis/Celery 등) 없이 DB 기반 작업 큐로 동작.
# - 핸들러는 process_db_job(Phase 2), process_smb_job(Phase 3)이
#   register_handler()로 동적 등록되며, Phase 1 단계에서는
#   인프라(폴링/점유/lease/완료/실패 처리)만 갖춘다.
#
# 설계 근거: docs/증분색인_설계_20260424_현승준.md §3.2
#
# Modified History
# 현승준 / 2026-04-27 / 최초생성 (Phase 1 공통 인프라)
########################################################
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import socket
import threading
import time
import uuid
from typing import Callable, Optional

from sqlalchemy import or_, text as sql_text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionLocal, SyncJob

_logger = logging.getLogger(__name__)

# 핸들러 시그니처: (job_id) -> dict (처리 결과 요약)
JobHandler = Callable[[int], dict]
_HANDLERS: dict[str, JobHandler] = {}


def register_handler(source_type: str, handler: JobHandler) -> None:
    """source_type 별 Job 처리 핸들러 등록.

    Phase 2(DB 색인) / Phase 3(SMB 색인)에서 각 모듈이 import 시점에 호출.
    """
    _HANDLERS[source_type] = handler
    _logger.info("[IndexingWorker] handler registered: source_type=%s", source_type)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _supports_skip_locked() -> bool:
    """현재 DB 엔진이 FOR UPDATE SKIP LOCKED 를 지원하는지 추정.

    PostgreSQL / MySQL 8+ / Oracle 은 지원, SQLite 는 미지원.
    DB_TYPE 만으로 정확히 판단할 수 없는 경우(MySQL 5.7 등)는
    실패 시 fallback 경로로 자동 전환되도록 try/except 로 감싼다.
    """
    db_type = (settings.DB_TYPE or "").lower()
    return db_type in {"postgres", "postgresql", "mysql", "mariadb", "oracle"}


class IndexingWorker:
    """SyncJob 폴링 + 점유(lease) + 위임 처리 워커.

    pool_size 만큼의 데몬 스레드를 띄워 동시에 폴링하며,
    각 스레드는 한 번에 1개의 Job 만 점유해 처리한다.
    소스당 동시 1 Job 제약은 점유 시점 SQL 의 NOT EXISTS 절로 강제한다.
    """

    _instance: Optional["IndexingWorker"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        pool_size: int = 2,
        poll_interval: float = 3.0,
        lease_seconds: int = 300,
        idle_backoff_max: float | None = None,
    ) -> None:
        self.pool_size = max(1, int(pool_size))
        self.poll_interval = max(0.5, float(poll_interval))
        self.lease_seconds = max(30, int(lease_seconds))
        # 빈 큐 폴링 백오프: 연속 None 시 poll_interval → 2x → 4x ... 상한까지.
        backoff_max = (
            idle_backoff_max
            if idle_backoff_max is not None
            else getattr(settings, "INDEX_WORKER_IDLE_BACKOFF_MAX_SECONDS", 30.0)
        )
        self.idle_backoff_max = max(self.poll_interval, float(backoff_max))
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        # worker_id 는 호스트+pid+nano 로 충돌 가능성 최소화
        self.worker_base_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._supports_skip_locked = _supports_skip_locked()

    # ------------------------------------------------------------------
    # 라이프사이클
    # ------------------------------------------------------------------
    @classmethod
    def start(
        cls,
        pool_size: int | None = None,
        poll_interval: float | None = None,
        lease_seconds: int | None = None,
    ) -> "IndexingWorker":
        """프로세스 단위 싱글톤으로 워커를 기동한다.

        lifespan 에서 1회 호출. 이미 떠 있으면 그대로 반환.
        """
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            inst = cls(
                pool_size=pool_size if pool_size is not None else settings.INDEX_WORKER_POOL_SIZE,
                poll_interval=poll_interval if poll_interval is not None else settings.INDEX_WORKER_POLL_INTERVAL_SECONDS,
                lease_seconds=lease_seconds if lease_seconds is not None else settings.INDEX_WORKER_LEASE_SECONDS,
                idle_backoff_max=getattr(settings, "INDEX_WORKER_IDLE_BACKOFF_MAX_SECONDS", None),
            )
            inst._start_threads()
            cls._instance = inst
            return inst

    @classmethod
    def stop(cls) -> None:
        with cls._lock:
            inst = cls._instance
            if inst is None:
                return
            inst._stop_event.set()
            for t in inst._threads:
                t.join(timeout=5)
            cls._instance = None
            _logger.info("[IndexingWorker] stopped")

    def _start_threads(self) -> None:
        for i in range(self.pool_size):
            wid = f"{self.worker_base_id}#{i}"
            t = threading.Thread(target=self._run_loop, args=(wid,), name=f"IndexingWorker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        _logger.info(
            "[IndexingWorker] started: pool_size=%d poll=%.1fs idle_max=%.1fs lease=%ds skip_locked=%s",
            self.pool_size, self.poll_interval, self.idle_backoff_max,
            self.lease_seconds, self._supports_skip_locked,
        )

    # ------------------------------------------------------------------
    # 폴링 루프
    # ------------------------------------------------------------------
    def _run_loop(self, worker_id: str) -> None:
        idle_wait = self.poll_interval  # 빈 큐 누적 시 점진적으로 늘어남
        while not self._stop_event.is_set():
            try:
                job_id = self._claim_next_job(worker_id)
                if job_id is None:
                    self._stop_event.wait(idle_wait)
                    # 다음 폴링은 두 배 — DB SELECT 부담 완화
                    idle_wait = min(idle_wait * 2.0, self.idle_backoff_max)
                    continue
                idle_wait = self.poll_interval  # Job 도착 시 백오프 리셋
                self._process_job(worker_id, job_id)
            except Exception as exc:  # 워커 자체는 죽이지 않는다
                _logger.exception("[IndexingWorker:%s] loop error: %s", worker_id, exc)
                self._stop_event.wait(self.poll_interval)
                idle_wait = self.poll_interval

    # ------------------------------------------------------------------
    # Job 점유 (소스당 동시 1 Job + 죽은 워커 lease 회수)
    # ------------------------------------------------------------------
    def _claim_next_job(self, worker_id: str) -> int | None:
        if self._supports_skip_locked:
            try:
                return self._claim_with_skip_locked(worker_id)
            except OperationalError as exc:
                # SKIP LOCKED 미지원 등 일회성 실패는 fallback 으로 전환
                _logger.warning("[IndexingWorker] SKIP LOCKED 미지원 추정 — fallback 사용: %s", exc)
                self._supports_skip_locked = False
        return self._claim_with_optimistic_update(worker_id)

    def _claim_with_skip_locked(self, worker_id: str) -> int | None:
        """PostgreSQL/MySQL8+/Oracle 경로.

        후보 1건을 SKIP LOCKED 로 잠그고 같은 트랜잭션에서 status='running' 으로 갱신.
        소스당 동시 1 Job 제약은 NOT EXISTS 로 강제.
        """
        now = _now_utc()
        lease_until = now + timedelta(seconds=self.lease_seconds)
        select_sql = sql_text(
            """
            SELECT id FROM sync_jobs j
            WHERE (
                j.status = 'pending'
                OR (j.status = 'running' AND (j.lease_until IS NULL OR j.lease_until < :now))
            )
            AND NOT EXISTS (
                SELECT 1 FROM sync_jobs r
                WHERE r.source_type = j.source_type
                  AND r.source_id = j.source_id
                  AND r.status = 'running'
                  AND r.id <> j.id
                  AND (r.lease_until IS NULL OR r.lease_until > :now)
            )
            ORDER BY j.created_at ASC, j.id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        update_sql = sql_text(
            """
            UPDATE sync_jobs
            SET status = 'running',
                worker_id = :wid,
                lease_until = :lease_until,
                started_at = COALESCE(started_at, :now),
                updated_at = :now
            WHERE id = :id
            """
        )

        session = SessionLocal()
        try:
            with session.begin():
                row = session.execute(select_sql, {"now": now}).first()
                if not row:
                    return None
                job_id = int(row[0])
                session.execute(update_sql, {"wid": worker_id, "lease_until": lease_until, "now": now, "id": job_id})
                return job_id
        finally:
            session.close()

    def _claim_with_optimistic_update(self, worker_id: str) -> int | None:
        """SQLite 등 SKIP LOCKED 미지원 환경 fallback.

        후보 1건을 조회 → WHERE status=? AND id=? 조건부 UPDATE 로 경합 해결.
        rowcount==0 이면 다른 워커가 가져간 것으로 보고 다음 폴링까지 대기.
        """
        now = _now_utc()
        lease_until = now + timedelta(seconds=self.lease_seconds)
        session = SessionLocal()
        try:
            candidate = (
                session.query(SyncJob)
                .filter(
                    or_(
                        SyncJob.status == "pending",
                        (SyncJob.status == "running")
                        & ((SyncJob.lease_until == None) | (SyncJob.lease_until < now)),  # noqa: E711
                    )
                )
                .order_by(SyncJob.created_at.asc(), SyncJob.id.asc())
                .first()
            )
            if candidate is None:
                return None
            job_id = candidate.id

            # 같은 source 에 다른 running Job 이 있으면 패스
            busy = (
                session.query(SyncJob.id)
                .filter(
                    SyncJob.source_type == candidate.source_type,
                    SyncJob.source_id == candidate.source_id,
                    SyncJob.id != job_id,
                    SyncJob.status == "running",
                    or_(SyncJob.lease_until == None, SyncJob.lease_until > now),  # noqa: E711
                )
                .first()
            )
            if busy is not None:
                return None

            prev_status = candidate.status
            updated = (
                session.query(SyncJob)
                .filter(SyncJob.id == job_id, SyncJob.status == prev_status)
                .update(
                    {
                        SyncJob.status: "running",
                        SyncJob.worker_id: worker_id,
                        SyncJob.lease_until: lease_until,
                        SyncJob.started_at: candidate.started_at or now,
                        SyncJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            if updated == 0:
                return None
            return job_id
        except SQLAlchemyError as exc:
            session.rollback()
            _logger.exception("[IndexingWorker] claim fallback error: %s", exc)
            return None
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Job 처리 / 결과 반영
    # ------------------------------------------------------------------
    def _process_job(self, worker_id: str, job_id: int) -> None:
        source_type = self._get_source_type(job_id)
        if source_type is None:
            return  # 이미 누가 finalize 했거나 삭제된 Job

        handler = _HANDLERS.get(source_type)
        if handler is None:
            self._finalize_job(
                job_id,
                status="failed",
                last_error=f"등록된 핸들러 없음(source_type={source_type}). Phase 2/3 미가동 상태일 수 있음.",
            )
            _logger.warning("[IndexingWorker:%s] no handler for source_type=%s job_id=%d", worker_id, source_type, job_id)
            return

        try:
            result = handler(job_id) or {}
            status = result.get("status", "done")
            self._finalize_job(
                job_id,
                status=status,
                last_error=result.get("error"),
            )
            _logger.info("[IndexingWorker:%s] job %d finished: %s", worker_id, job_id, result)
        except Exception as exc:
            _logger.exception("[IndexingWorker:%s] job %d failed: %s", worker_id, job_id, exc)
            self._finalize_job(job_id, status="failed", last_error=str(exc))

    def _get_source_type(self, job_id: int) -> str | None:
        session = SessionLocal()
        try:
            job = session.query(SyncJob).filter(SyncJob.id == job_id).first()
            return job.source_type if job else None
        finally:
            session.close()

    def _finalize_job(self, job_id: int, status: str, last_error: str | None = None) -> None:
        now = _now_utc()
        session = SessionLocal()
        try:
            updates: dict = {
                SyncJob.status: status,
                SyncJob.updated_at: now,
            }
            if status in {"done", "failed"}:
                updates[SyncJob.finished_at] = now
                updates[SyncJob.lease_until] = None
            if last_error:
                updates[SyncJob.last_error] = last_error[:4000]
            session.query(SyncJob).filter(SyncJob.id == job_id).update(updates, synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            _logger.exception("[IndexingWorker] finalize error job_id=%d: %s", job_id, exc)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # 외부 헬퍼: lease 연장 (chunk 처리 중 핸들러가 호출)
    # ------------------------------------------------------------------
    @classmethod
    def renew_lease(cls, job_id: int, lease_seconds: int | None = None) -> None:
        """핸들러가 chunk 단위로 처리 진행 중일 때 lease 만료를 막기 위해 호출."""
        inst = cls._instance
        seconds = lease_seconds or (inst.lease_seconds if inst else settings.INDEX_WORKER_LEASE_SECONDS)
        now = _now_utc()
        new_lease = now + timedelta(seconds=seconds)
        session = SessionLocal()
        try:
            session.query(SyncJob).filter(SyncJob.id == job_id).update(
                {SyncJob.lease_until: new_lease, SyncJob.updated_at: now},
                synchronize_session=False,
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        finally:
            session.close()
