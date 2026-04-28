"""
########################################################
# Description
# 시스템 서비스 (SystemService)
# 운영 관리 비즈니스 로직 담당
# - 대시보드 통계 (검색 로그 집계, 트렌드 측정)
# - SMB/DB 외부 데이터 수집 로직
# - 자동 색인 스케줄러 (백그라운드 주기적 동기화)
# - SSL 인증서 상태 조회/갱신
# - 볼륨(인덱스) 생성
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
########################################################
"""
from __future__ import annotations

import os
import json
import re
import ssl
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.utils.crypto import encrypt as _encrypt, decrypt as _decrypt

from app.core.database import CertificateStatus, DbSource, FileIndexState, IndexingHistory, NetworkEventLog, ScheduleEntry, SearchLog, SearchVolume, SmbSource, SmbSyncHistory, get_db_session
from app.core.opensearch import get_client
from app.services.db_service import DBService
from app.services.indexing_service import ALLOWED_EXTENSIONS, IndexingService


class SMBService:
    """
    SMB/CIFS 외부 공유 폴더 데이터 수집 서비스 (크로스플랫폼)
    - smbprotocol 기반 순수 Python SMB 클라이언트 (Windows/Linux/macOS)
    - 동기화 이력(SmbSyncHistory), 색인 이력(IndexingHistory),
      네트워크 이벤트(NetworkEventLog)를 DB에 기록
    """
    @staticmethod
    def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
        """등록된 SMB/SSH 소스 목록 조회 (active_only=True이면 활성 소스만)"""
        with get_db_session() as db:
            query = db.query(SmbSource)
            if active_only:
                query = query.filter(SmbSource.is_active.is_(True))
            rows = query.order_by(SmbSource.id.asc()).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "connection_type": row.connection_type or "smb",
                    "share_path": row.share_path,
                    "username": row.username,
                    "domain": row.domain,
                    "port": row.port,
                    "ssh_host": row.ssh_host,
                    "ssh_key_path": row.ssh_key_path,
                    "is_active": row.is_active,
                    "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                    "last_error": row.last_error,
                }
                for row in rows
            ]

    @staticmethod
    def upsert_source(
        name: str,
        share_path: str,
        username: str | None,
        password: str | None,
        connection_type: str = "smb",
        domain: str | None = None,
        port: int = 445,
        ssh_host: str | None = None,
        ssh_key_path: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        SMB/SSH 소스 등록/수정 (Upsert)
        - name 기준으로 기존 소스가 있으면 UPDATE, 없으면 INSERT
        """
        with get_db_session() as db:
            normalized_share_path = (share_path or "").strip().strip('"').strip("'")
            row = db.query(SmbSource).filter(SmbSource.name == name).first()
            now = datetime.now(timezone.utc)
            enc_password = _encrypt(password) if password else password
            if row:
                row.connection_type = connection_type
                row.share_path = normalized_share_path
                row.username = username
                row.password = enc_password
                row.domain = domain
                row.port = port
                row.ssh_host = ssh_host
                row.ssh_key_path = ssh_key_path
                row.is_active = is_active
                row.updated_at = now
            else:
                row = SmbSource(
                    name=name,
                    connection_type=connection_type,
                    share_path=normalized_share_path,
                    username=username,
                    password=enc_password,
                    domain=domain,
                    port=port,
                    ssh_host=ssh_host,
                    ssh_key_path=ssh_key_path,
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.flush()
            return {"id": row.id, "name": row.name, "connection_type": row.connection_type, "share_path": row.share_path, "is_active": row.is_active}

    @staticmethod
    def _log_network_event(db, source_type: str, source_name: str, event_type: str, detail: str | None = None) -> None:
        """네트워크 이벤트(단절/재연결 시도/성공/실패)를 DB에 기록"""
        db.add(NetworkEventLog(
            source_type=source_type,
            source_name=source_name,
            event_type=event_type,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        ))
        db.flush()

    @staticmethod
    def _log_indexing(db, source_type: str, source_name: str, file_name: str | None, action: str, status: str, message: str | None = None) -> None:
        """개별 파일 색인 이력을 DB에 기록"""
        db.add(IndexingHistory(
            source_type=source_type,
            source_name=source_name,
            file_name=file_name,
            action=action,
            status=status,
            message=message,
            created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _log_sync_summary(
        db,
        source_type: str,
        source_name: str,
        source_id: int | None,
        success_count: int,
        skipped_count: int,
        failed_count: int,
        unchanged_count: int,
        failed_files: list[str],
        trigger_type: str = "manual",
    ) -> None:
        """동기화 1회 실행 요약 이력 기록 (파일 건별 로그 대신)"""
        total = success_count + skipped_count + failed_count + unchanged_count
        if failed_count == 0:
            status = "success"
        elif success_count > 0 or skipped_count > 0:
            status = "partial"
        else:
            status = "fail"

        compact_failed = [f for f in failed_files if f][:8]
        failed_part = ", ".join(compact_failed)
        if len(failed_files) > len(compact_failed):
            failed_part += f" 외 {len(failed_files) - len(compact_failed)}건"

        source_id_part = f", source_id={source_id}" if source_id is not None else ""
        msg = f"trigger={trigger_type}{source_id_part}, total={total}, success={success_count}, skipped={skipped_count}, unchanged={unchanged_count}, failed={failed_count}"
        if failed_part:
            msg += f", failed_files={failed_part}"

        db.add(IndexingHistory(
            source_type=source_type,
            source_name=source_name,
            file_name=f"총 {total}건 (성공 {success_count} / 실패 {failed_count} / 스킵 {skipped_count} / 변경없음 {unchanged_count})",
            action="sync_summary",
            status=status,
            message=msg[:500],
            created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _compute_hash(content: bytes) -> str:
        """파일 콘텐츠의 SHA-256 해시 계산"""
        import hashlib
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _is_changed(db, source_type: str, source_name: str, file_path: str, content: bytes) -> bool:
        """
        증분 색인 판별 — 파일 해시가 변경되었는지 확인
        - file_index_states 테이블에서 이전 해시를 조회
        - 동일 해시이면 False (변경 없음), 다르면 True (변경됨)
        """
        new_hash = SMBService._compute_hash(content)
        state = (
            db.query(FileIndexState)
            .filter(
                FileIndexState.source_type == source_type,
                FileIndexState.source_name == source_name,
                FileIndexState.file_path == file_path,
            )
            .first()
        )
        if state and state.file_hash == new_hash:
            return False
        return True

    @staticmethod
    def _update_index_state(db, source_type: str, source_name: str, file_path: str, content: bytes) -> None:
        """파일 색인 상태(해시/크기) 업데이트 또는 신규 생성"""
        new_hash = SMBService._compute_hash(content)
        now = datetime.now(timezone.utc)
        state = (
            db.query(FileIndexState)
            .filter(
                FileIndexState.source_type == source_type,
                FileIndexState.source_name == source_name,
                FileIndexState.file_path == file_path,
            )
            .first()
        )
        if state:
            state.file_hash = new_hash
            state.file_size = len(content)
            state.indexed_at = now
        else:
            db.add(FileIndexState(
                source_type=source_type,
                source_name=source_name,
                file_path=file_path,
                file_hash=new_hash,
                file_size=len(content),
                indexed_at=now,
            ))

    @staticmethod
    def sync_source(source_id: int, max_files: int = 200, trigger_type: str = "manual", force_full: bool = False) -> dict[str, Any]:
        """
        SMB/SSH 소스 동기화 실행 (크로스플랫폼, 증분 색인)
        - connection_type에 따라 SMB(smbprotocol) 또는 SSH(paramiko SFTP) 사용
        - force_full=False: 파일 해시 비교로 변경분만 색인 (증분)
        - force_full=True: 해시 무시하고 전체 재색인
        """
        started_at = datetime.now(timezone.utc)

        with get_db_session() as db:
            source = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not source:
                return {"status": "fail", "message": "SMB/SSH source not found", "source_id": source_id}

            indexed = 0
            skipped = 0
            unchanged = 0
            failed = 0
            failed_files: list[str] = []
            password = _decrypt(source.password) if source.password else None
            source_name = source.name
            conn_type = source.connection_type or "smb"

            try:
                if conn_type == "ssh":
                    from app.utils.sftp_client import SFTPClient
                    client = SFTPClient(
                        host=source.ssh_host or "",
                        remote_path=source.share_path,
                        username=source.username,
                        password=password,
                        port=source.port or 22,
                        key_path=source.ssh_key_path,
                    )
                else:
                    from app.utils.smb_client import SMBClient
                    from smbprotocol.exceptions import SMBException
                    client = SMBClient(
                        share_path=source.share_path,
                        username=source.username,
                        password=password,
                        domain=source.domain,
                        port=source.port or 445,
                    )

                # 연결 시도
                try:
                    client.connect()
                except Exception as conn_exc:
                    SMBService._log_network_event(db, conn_type, source_name, "disconnect", str(conn_exc))
                    SMBService._log_network_event(db, conn_type, source_name, "reconnect_attempt", "자동 재연결 1차 시도")
                    try:
                        client.connect()
                        SMBService._log_network_event(db, conn_type, source_name, "reconnect_success", "재연결 성공")
                    except Exception as retry_exc:
                        SMBService._log_network_event(db, conn_type, source_name, "reconnect_fail", str(retry_exc))
                        raise FileNotFoundError(f"{conn_type.upper()} 경로 접근 실패: {source.share_path} — {retry_exc}") from retry_exc

                try:
                    for rel_path, full_path in client.walk(allowed_extensions=ALLOWED_EXTENSIONS):
                        if indexed + skipped + unchanged + failed >= max_files:
                            break
                        file_name = rel_path.split("\\")[-1].split("/")[-1]
                        try:
                            content = client.read_bytes(full_path)

                            if not force_full and not SMBService._is_changed(db, conn_type, source_name, rel_path, content):
                                unchanged += 1
                                continue

                            result = IndexingService.index_bytes(file_name, content, source_label=f"{conn_type}:{source_name}")
                            if result.get("status") == "success":
                                indexed += 1
                                SMBService._update_index_state(db, conn_type, source_name, rel_path, content)
                            elif result.get("status") == "skipped":
                                skipped += 1
                            else:
                                failed += 1
                                failed_files.append(file_name)
                        except Exception:
                            failed += 1
                            failed_files.append(file_name)
                finally:
                    client.disconnect()

                SMBService._log_sync_summary(
                    db=db,
                    source_type="smb",
                    source_name=source_name,
                    source_id=source_id,
                    success_count=indexed,
                    skipped_count=skipped,
                    failed_count=failed,
                    unchanged_count=unchanged,
                    failed_files=failed_files,
                    trigger_type=trigger_type,
                )

                finished_at = datetime.now(timezone.utc)
                duration_ms = int((finished_at - started_at).total_seconds() * 1000)

                source.last_seen_at = finished_at
                source.last_error = None
                source.updated_at = finished_at

                db.add(SmbSyncHistory(
                    source_id=source_id,
                    source_name=source_name,
                    status="success",
                    indexed=indexed,
                    skipped=skipped,
                    failed=failed,
                    trigger_type=trigger_type,
                    message=f"unchanged={unchanged}" if unchanged else None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                ))

                return {
                    "status": "success",
                    "source_id": source_id,
                    "indexed": indexed,
                    "skipped": skipped,
                    "unchanged": unchanged,
                    "failed": failed,
                    "duration_ms": duration_ms,
                }
            except Exception as exc:
                finished_at = datetime.now(timezone.utc)
                duration_ms = int((finished_at - started_at).total_seconds() * 1000)

                source.last_error = str(exc)
                source.updated_at = finished_at

                db.add(SmbSyncHistory(
                    source_id=source_id,
                    source_name=source_name,
                    status="fail",
                    indexed=indexed,
                    skipped=skipped,
                    failed=failed,
                    trigger_type=trigger_type,
                    message=str(exc)[:500],
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                ))

                return {"status": "fail", "source_id": source_id, "message": str(exc)}

    @staticmethod
    def sync_all_sources(max_files_per_source: int = 200, trigger_type: str = "manual") -> dict[str, Any]:
        """활성 SMB 소스 전체 즉시 동기화"""
        sources = SMBService.list_sources(active_only=True)
        results = [
            SMBService.sync_source(source_id=row["id"], max_files=max_files_per_source, trigger_type=trigger_type, force_full=False)
            for row in sources
        ]
        success = sum(1 for r in results if r.get("status") == "success")
        failed = len(results) - success
        return {
            "status": "success",
            "total_sources": len(sources),
            "success_sources": success,
            "failed_sources": failed,
            "results": results,
        }

    @staticmethod
    def delete_source(source_id: int) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "SMB 소스를 찾을 수 없습니다"}
            db.delete(row)
            return {"status": "success", "message": f"SMB 소스 ID {source_id} 삭제 완료"}

    @staticmethod
    def toggle_active(source_id: int, is_active: bool) -> dict[str, Any]:
        """SMB/SSH 소스 활성/비활성 토글 — 스케줄러 자동 등록/해제"""
        with get_db_session() as db:
            row = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "SMB 소스를 찾을 수 없습니다"}
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)
            db.flush()
            ScheduleService.auto_sync_entry(db, "smb", source_id, is_active)
            state = "활성" if is_active else "비활성"
            return {"status": "success", "id": row.id, "name": row.name, "is_active": row.is_active, "message": f"{row.name} 소스가 {state} 상태로 변경되었습니다. 스케줄러에 자동 반영됩니다."}

    @staticmethod
    def test_connection(source_id: int) -> dict[str, Any]:
        """SMB/SSH 연결 테스트 — 경로 접근 가능 여부 확인"""
        with get_db_session() as db:
            source = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not source:
                return {"status": "fail", "message": "SMB/SSH source not found"}

            password = _decrypt(source.password) if source.password else None
            conn_type = source.connection_type or "smb"

            try:
                if conn_type == "ssh":
                    from app.utils.sftp_client import SFTPClient
                    client = SFTPClient(
                        host=source.ssh_host or "",
                        remote_path=source.share_path,
                        username=source.username,
                        password=password,
                        port=source.port or 22,
                        key_path=source.ssh_key_path,
                    )
                else:
                    from app.utils.smb_client import SMBClient
                    from smbprotocol.exceptions import SMBException
                    client = SMBClient(
                        share_path=source.share_path,
                        username=source.username,
                        password=password,
                        domain=source.domain,
                        port=source.port or 445,
                    )

                client.connect()
                ok = client.test_connection()
                client.disconnect()
                if ok:
                    return {"status": "success", "message": f"{conn_type.upper()} 연결 성공"}
                return {"status": "fail", "message": "경로 접근 실패"}
            except Exception as exc:
                SMBService._log_network_event(db, conn_type, source.name, "disconnect", str(exc))
                return {"status": "fail", "message": str(exc)}

    @staticmethod
    def list_sync_history(source_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """SMB 동기화 이력 조회"""
        with get_db_session() as db:
            query = db.query(SmbSyncHistory)
            if source_id is not None:
                query = query.filter(SmbSyncHistory.source_id == source_id)
            rows = query.order_by(SmbSyncHistory.started_at.desc()).limit(limit).all()
            return [
                {
                    "id": row.id,
                    "source_id": row.source_id,
                    "source_name": row.source_name,
                    "status": row.status,
                    "indexed": row.indexed,
                    "skipped": row.skipped,
                    "failed": row.failed,
                    "trigger_type": row.trigger_type,
                    "message": row.message,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    "duration_ms": row.duration_ms,
                }
                for row in rows
            ]


class IndexingHistoryService:
    """색인 이력 조회 서비스"""

    @staticmethod
    def list_history(
        source_type: str | None = None,
        source_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """색인 이력 조회 (필터 선택 가능)"""
        with get_db_session() as db:
            # 통합 이력은 실행 회차 요약(sync_summary)만 노출
            query = db.query(IndexingHistory).filter(IndexingHistory.action == "sync_summary")
            if source_type:
                query = query.filter(IndexingHistory.source_type == source_type)
            if source_name:
                query = query.filter(IndexingHistory.source_name == source_name)
            if status:
                query = query.filter(IndexingHistory.status == status)
            rows = query.order_by(IndexingHistory.created_at.desc()).limit(limit).all()
            return [
                {
                    "id": row.id,
                    "source_type": row.source_type,
                    "source_name": row.source_name,
                    "file_name": row.file_name,
                    "action": row.action,
                    "status": row.status,
                    "message": row.message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    @staticmethod
    def delete_history(before_days: int = 30) -> dict[str, Any]:
        """지정 일수 이전의 색인 이력 삭제"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=before_days)
        with get_db_session() as db:
            count = db.query(IndexingHistory).filter(IndexingHistory.created_at < cutoff).delete()
            return {"status": "success", "deleted": count, "before_days": before_days}


class NetworkEventService:
    """네트워크 단절/재연결 이벤트 이력 조회 서비스"""

    @staticmethod
    def list_events(
        source_type: str | None = None,
        source_name: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """네트워크 이벤트 이력 조회 (필터 선택 가능)"""
        with get_db_session() as db:
            query = db.query(NetworkEventLog)
            if source_type:
                query = query.filter(NetworkEventLog.source_type == source_type)
            if source_name:
                query = query.filter(NetworkEventLog.source_name == source_name)
            if event_type:
                query = query.filter(NetworkEventLog.event_type == event_type)
            rows = query.order_by(NetworkEventLog.created_at.desc()).limit(limit).all()
            return [
                {
                    "id": row.id,
                    "source_type": row.source_type,
                    "source_name": row.source_name,
                    "event_type": row.event_type,
                    "detail": row.detail,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    @staticmethod
    def delete_events(before_days: int = 90) -> dict[str, Any]:
        """지정 일수 이전의 네트워크 이벤트 삭제"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=before_days)
        with get_db_session() as db:
            count = db.query(NetworkEventLog).filter(NetworkEventLog.created_at < cutoff).delete()
            return {"status": "success", "deleted": count, "before_days": before_days}


class FileWatcherService:
    """
    실시간 파일 변경 감지 서비스 (watchfiles 기반)
    - 등록된 SMB 소스의 로컬 마운트 경로 또는 로컬 폴더를 감시
    - 파일 생성/수정/삭제 이벤트 발생 시 자동 색인
    - 소스별 개별 감시 스레드로 백그라운드 실행
    """
    _threads: dict[int, threading.Thread] = {}       # source_id → thread
    _stop_events: dict[int, threading.Event] = {}    # source_id → stop_event
    _watched_paths: dict[str, int] = {}              # path → source_id
    _source_names: dict[int, str] = {}               # source_id → source_name

    @staticmethod
    def _normalize_path(path: str) -> str:
        """경로 비교를 위해 슬래시/대소문자를 정규화"""
        normalized = os.path.normcase((path or "").replace("/", "\\")).strip()
        return normalized.rstrip("\\")

    @classmethod
    def start(cls, paths: dict[str, int] | None = None) -> dict[str, Any]:
        """
        전체 활성 소스 감시 시작 (기존 호환)
        """
        if paths is None:
            paths = cls._load_watch_paths()
        if not paths:
            return {"status": "fail", "message": "감시할 경로가 없습니다"}

        all_names = {
            s["id"]: s["name"]
            for s in SMBService.list_sources(active_only=False)
            if s.get("id") is not None
        }
        started = []
        already = []
        for path, sid in paths.items():
            if sid in cls._threads and cls._threads[sid].is_alive():
                already.append(sid)
                continue
            cls._source_names[sid] = all_names.get(sid, f"source-{sid}")
            cls._start_source_thread(sid, path)
            started.append(sid)
        return {"status": "started", "started_sources": started, "already_running": already}

    @classmethod
    def stop(cls) -> dict[str, Any]:
        """전체 워처 중지"""
        stopped = []
        for sid in list(cls._stop_events.keys()):
            cls._stop_source(sid)
            stopped.append(sid)
        return {"status": "stopped", "stopped_sources": stopped}

    @classmethod
    def start_source(cls, source_id: int) -> dict[str, Any]:
        """개별 소스 감시 시작"""
        if source_id in cls._threads and cls._threads[source_id].is_alive():
            return {"status": "already-running", "source_id": source_id}
        sources = SMBService.list_sources(active_only=False)
        src = next((s for s in sources if s["id"] == source_id), None)
        if not src:
            return {"status": "fail", "message": f"소스 ID {source_id}를 찾을 수 없습니다"}
        path = src.get("share_path")
        if not path:
            return {"status": "fail", "message": "감시할 경로가 없습니다"}
        cls._source_names[source_id] = src.get("name", f"source-{source_id}")
        cls._start_source_thread(source_id, path)
        return {"status": "started", "source_id": source_id, "path": path}

    @classmethod
    def stop_source(cls, source_id: int) -> dict[str, Any]:
        """개별 소스 감시 중지"""
        if source_id not in cls._threads or not cls._threads[source_id].is_alive():
            return {"status": "already-stopped", "source_id": source_id}
        cls._stop_source(source_id)
        return {"status": "stopped", "source_id": source_id}

    @classmethod
    def _start_source_thread(cls, source_id: int, path: str) -> None:
        cls._watched_paths[path] = source_id
        stop_evt = threading.Event()
        cls._stop_events[source_id] = stop_evt
        t = threading.Thread(target=cls._watch_loop_single, args=(source_id, path, stop_evt), daemon=True)
        cls._threads[source_id] = t
        t.start()

    @classmethod
    def _stop_source(cls, source_id: int) -> None:
        evt = cls._stop_events.pop(source_id, None)
        if evt:
            evt.set()
        t = cls._threads.pop(source_id, None)
        if t:
            t.join(timeout=5)
        paths_to_remove = [p for p, sid in cls._watched_paths.items() if sid == source_id]
        for p in paths_to_remove:
            cls._watched_paths.pop(p, None)
        cls._source_names.pop(source_id, None)

    @classmethod
    def status(cls) -> dict[str, Any]:
        """파일 워처 현재 상태 조회"""
        running_sources = []
        for sid, t in list(cls._threads.items()):
            if t.is_alive():
                running_sources.append({
                    "source_id": sid,
                    "source_name": cls._source_names.get(sid, ""),
                })
        return {
            "running": len(running_sources) > 0,
            "running_sources": running_sources,
            "watched_paths": list(cls._watched_paths.keys()),
            "source_count": len(running_sources),
        }

    @classmethod
    def _load_watch_paths(cls) -> dict[str, int]:
        """활성 SMB 소스의 share_path → source_id 맵 생성"""
        sources = SMBService.list_sources(active_only=True)
        return {s["share_path"]: s["id"] for s in sources if s.get("share_path")}

    @classmethod
    def _watch_loop_single(cls, source_id: int, path: str, stop_event: threading.Event) -> None:
        """단일 소스 watchfiles 기반 파일 변경 감지 루프"""
        import watchfiles
        import logging
        logger = logging.getLogger(__name__)

        try:
            for changes in watchfiles.watch(
                path,
                stop_event=stop_event,
                recursive=True,
                step=1000,
            ):
                if stop_event.is_set():
                    break
                cls._process_changes(changes)
        except Exception as exc:
            logger.error("FileWatcher error (source_id=%s): %s", source_id, exc)

    @classmethod
    def _process_changes(cls, changes: set) -> None:
        """
        변경 이벤트 처리
        - watchfiles Change: (change_type, path)
        - change_type: 1=added, 2=modified, 3=deleted
        """
        import watchfiles

        action_map = {
            watchfiles.Change.added: "created",
            watchfiles.Change.modified: "modified",
            watchfiles.Change.deleted: "deleted",
        }

        stats: dict[tuple[int | None, str], dict[str, Any]] = {}

        def touch_stat(sid: int | None, sname: str) -> dict[str, Any]:
            key = (sid, sname)
            if key not in stats:
                stats[key] = {
                    "source_id": sid,
                    "source_name": sname,
                    "success": 0,
                    "skipped": 0,
                    "unchanged": 0,
                    "failed": 0,
                    "failed_files": [],
                }
            return stats[key]

        with get_db_session() as db:
            for change_type, file_path_str in changes:
                action = action_map.get(change_type, "modified")
                file_path = Path(file_path_str)
                file_name = file_path.name

                # 어떤 소스의 경로인지 판별
                source_name = "local"
                source_id = None
                normalized_file_path = cls._normalize_path(file_path_str)
                best_match_len = -1
                for watch_path, sid in cls._watched_paths.items():
                    normalized_watch = cls._normalize_path(watch_path)
                    if not normalized_watch:
                        continue
                    if (
                        normalized_file_path == normalized_watch
                        or normalized_file_path.startswith(normalized_watch + "\\")
                    ) and len(normalized_watch) > best_match_len:
                        source_id = sid
                        best_match_len = len(normalized_watch)

                if source_id is not None:
                    source_name = cls._source_names.get(source_id, source_name)

                stat = touch_stat(source_id, source_name)

                # 확장자 필터
                ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
                if ext and ext not in ALLOWED_EXTENSIONS:
                    stat["skipped"] += 1
                    continue

                if action == "deleted":
                    db.query(FileIndexState).filter(
                        FileIndexState.source_type == "smb",
                        FileIndexState.source_name == source_name,
                        FileIndexState.file_path == file_path_str,
                    ).delete()
                    stat["skipped"] += 1
                    continue

                try:
                    if not file_path.exists() or not file_path.is_file():
                        stat["skipped"] += 1
                        continue

                    content = file_path.read_bytes()
                    if not SMBService._is_changed(db, "smb", source_name, file_path_str, content):
                        stat["unchanged"] += 1
                        continue

                    result = IndexingService.index_bytes(file_name, content, source_label=f"smb:{source_name}")
                    if result.get("status") == "success":
                        SMBService._update_index_state(db, "smb", source_name, file_path_str, content)
                        stat["success"] += 1
                    elif result.get("status") == "skipped":
                        stat["skipped"] += 1
                    else:
                        stat["failed"] += 1
                        stat["failed_files"].append(file_name)
                except Exception:
                    stat["failed"] += 1
                    stat["failed_files"].append(file_name)

            for row in stats.values():
                total = row["success"] + row["skipped"] + row["unchanged"] + row["failed"]
                if total == 0:
                    continue
                SMBService._log_sync_summary(
                    db=db,
                    source_type="watcher",
                    source_name=row["source_name"],
                    source_id=row["source_id"],
                    success_count=row["success"],
                    skipped_count=row["skipped"],
                    failed_count=row["failed"],
                    unchanged_count=row["unchanged"],
                    failed_files=row["failed_files"],
                    trigger_type="watcher",
                )


class NetworkMonitorService:
    """
    SMB/DB/OpenSearch 네트워크 연결 상태를 주기적으로 점검하고,
    단절/복구 이벤트를 network_event_logs에 기록하는 서비스
    """
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None
    _interval_seconds: int = 30
    # 이전 상태 추적 — True=정상, False=단절
    _last_status: dict[str, bool] = {}

    @classmethod
    def start(cls, interval_seconds: int = 30) -> dict[str, Any]:
        """네트워크 모니터 시작"""
        if cls._thread and cls._thread.is_alive():
            return {"status": "already-running", "interval_seconds": cls._interval_seconds}

        cls._interval_seconds = max(10, interval_seconds)
        cls._stop_event = threading.Event()
        cls._last_status = {}
        cls._thread = threading.Thread(target=cls._monitor_loop, daemon=True)
        cls._thread.start()
        return {"status": "started", "interval_seconds": cls._interval_seconds}

    @classmethod
    def stop(cls) -> dict[str, Any]:
        """네트워크 모니터 중지"""
        if not cls._thread or not cls._thread.is_alive() or not cls._stop_event:
            return {"status": "already-stopped"}
        cls._stop_event.set()
        cls._thread.join(timeout=5)
        return {"status": "stopped"}

    @classmethod
    def status(cls) -> dict[str, Any]:
        """네트워크 모니터 현재 상태 조회"""
        return {
            "running": bool(cls._thread and cls._thread.is_alive()),
            "interval_seconds": cls._interval_seconds,
            "last_status": dict(cls._last_status),
        }

    @classmethod
    def _monitor_loop(cls) -> None:
        """백그라운드 모니터링 루프"""
        while cls._stop_event and not cls._stop_event.is_set():
            try:
                cls._check_opensearch()
                cls._check_database()
                cls._check_smb_sources()
            except Exception:
                # 개별 점검 오류로 모니터 스레드가 종료되지 않도록 보호
                pass
            cls._stop_event.wait(cls._interval_seconds)

    @classmethod
    def _write_event(cls, source_type: str, source_name: str, event_type: str, detail: str | None = None) -> None:
        """네트워크 이벤트 1건 기록 (DB 오류 시 무시)"""
        try:
            with get_db_session() as db:
                db.add(NetworkEventLog(
                    source_type=source_type,
                    source_name=source_name,
                    event_type=event_type,
                    detail=detail,
                    created_at=datetime.now(timezone.utc),
                ))
        except Exception:
            # 모니터 자체는 계속 동작해야 하므로 이벤트 기록 실패는 삼킴
            pass

    @classmethod
    def _handle_state_transition(
        cls,
        key: str,
        source_type: str,
        source_name: str,
        current_ok: bool,
        error_detail: str | None = None,
    ) -> None:
        """연결 상태 변화에 따라 표준 이벤트(disconnect/reconnect_*) 기록"""
        prev_ok = cls._last_status.get(key, True)

        if prev_ok and not current_ok:
            cls._write_event(source_type, source_name, "disconnect", error_detail)
        elif not prev_ok and current_ok:
            cls._write_event(source_type, source_name, "reconnect_success", f"{source_type} 연결 복구")
        elif not prev_ok and not current_ok:
            # 이미 단절 상태이면 재연결 시도/실패를 회차별로 기록
            cls._write_event(source_type, source_name, "reconnect_attempt", "자동 재연결 시도")
            cls._write_event(source_type, source_name, "reconnect_fail", error_detail)

        cls._last_status[key] = current_ok

    @classmethod
    def _check_opensearch(cls) -> None:
        """OpenSearch 연결 상태 점검"""
        key = "opensearch:default"
        error_detail: str | None = None
        try:
            client = get_client()
            info = client.info()
            current_ok = info is not None
        except Exception as exc:
            current_ok = False
            error_detail = str(exc)
        cls._handle_state_transition(
            key=key,
            source_type="opensearch",
            source_name="default",
            current_ok=current_ok,
            error_detail=error_detail,
        )

    @classmethod
    def _check_database(cls) -> None:
        """업무 DB 연결 상태 점검"""
        key = "db:primary"
        error_detail: str | None = None
        try:
            with get_db_session() as db:
                db.execute(text("SELECT 1"))
            current_ok = True
        except Exception as exc:
            current_ok = False
            error_detail = str(exc)
        cls._handle_state_transition(
            key=key,
            source_type="db",
            source_name="primary",
            current_ok=current_ok,
            error_detail=error_detail,
        )

    @classmethod
    def _check_smb_sources(cls) -> None:
        """활성 SMB 소스별 연결 상태 점검"""
        smb_client_cls = None
        try:
            from app.utils.smb_client import SMBClient
            smb_client_cls = SMBClient
        except Exception:
            smb_client_cls = None

        try:
            with get_db_session() as db:
                rows = (
                    db.query(SmbSource)
                    .filter(SmbSource.is_active.is_(True))
                    .order_by(SmbSource.id.asc())
                    .all()
                )
        except Exception:
            return

        active_keys: set[str] = set()
        for row in rows:
            key = f"smb:{row.id}"
            active_keys.add(key)

            error_detail: str | None = None
            current_ok = False
            client = None
            try:
                if smb_client_cls is not None:
                    password = _decrypt(row.password) if row.password else None
                    client = smb_client_cls(
                        share_path=row.share_path,
                        username=row.username,
                        password=password,
                        domain=row.domain,
                        port=row.port or 445,
                    )
                    client.connect()
                    current_ok = True
                else:
                    # 의존성 미설치 환경에서는 UNC 경로 접근 가능 여부로 최소 점검
                    current_ok = os.path.isdir(row.share_path)
                    if current_ok:
                        try:
                            os.listdir(row.share_path)
                        except Exception:
                            # 읽기 권한이 없어도 경로 접근 자체는 정상으로 간주
                            pass
                    else:
                        error_detail = f"path not reachable: {row.share_path}"
            except Exception as exc:
                error_detail = str(exc)
                current_ok = False
            finally:
                try:
                    if client is not None:
                        client.disconnect()
                except Exception:
                    pass

            cls._handle_state_transition(
                key=key,
                source_type="smb",
                source_name=row.name,
                current_ok=current_ok,
                error_detail=error_detail,
            )

        # 비활성/삭제된 SMB 소스의 상태 캐시는 정리
        stale_keys = [k for k in cls._last_status.keys() if k.startswith("smb:") and k not in active_keys]
        for k in stale_keys:
            cls._last_status.pop(k, None)


class DBIngestionService:
    """
    외부 DB 데이터 수집 서비스
    - SQLAlchemy engine으로 다양한 DB 타입(postgres/mysql/mssql 등) 접속
    - 대용량 DB 조회 시 fetchmany 스트리밍으로 부하 방지 (분할 수집)
    - 조회 결과를 텍스트로 변환하여 IndexingService로 색인
    """
    @staticmethod
    def _validate_query_text(query_text: str) -> str:
        """읽기 전용 SELECT 쿼리만 허용하여 위험한 실행을 차단합니다."""
        q = (query_text or "").strip()
        if not q:
            raise ValueError("query_text는 비어 있을 수 없습니다")

        # 주석 제거 후 검증
        q_no_comment = re.sub(r"--.*?$", "", q, flags=re.MULTILINE).strip()
        q_lower = q_no_comment.lower()

        if not q_lower.startswith("select"):
            raise ValueError("SELECT 쿼리만 허용됩니다")

        forbidden = [
            ";",
            "insert ",
            "update ",
            "delete ",
            "drop ",
            "alter ",
            "truncate ",
            "create ",
            "grant ",
            "revoke ",
            "execute ",
            "call ",
        ]
        if any(token in q_lower for token in forbidden):
            raise ValueError("위험한 SQL 키워드가 포함되어 있습니다")

        return q_no_comment

    @staticmethod
    def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
        """등록된 DB 소스 목록 조회 (active_only=True이면 활성 소스만)"""
        with get_db_session() as db:
            query = db.query(DbSource)
            if active_only:
                query = query.filter(DbSource.is_active.is_(True))
            rows = query.order_by(DbSource.id.asc()).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "db_type": row.db_type,
                    "target_volume": row.target_volume,
                    "is_active": row.is_active,
                    "chunk_size": row.chunk_size,
                    "title_column": row.title_column,
                    "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
                    "last_error": row.last_error,
                }
                for row in rows
            ]

    @staticmethod
    def get_source(source_id: int, include_secret: bool = False) -> dict[str, Any]:
        """DB 소스 단건 상세 조회 (수정 폼 채우기용)"""
        with get_db_session() as db:
            row = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "DB source not found", "source_id": source_id}

            result = {
                "id": row.id,
                "name": row.name,
                "db_type": row.db_type,
                "target_volume": row.target_volume,
                "title_column": row.title_column,
                "chunk_size": row.chunk_size,
                "is_active": row.is_active,
                "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
                "last_error": row.last_error,
            }
            if include_secret:
                result["connection_url"] = _decrypt(row.connection_url) if row.connection_url else None
                result["query_text"] = row.query_text
            return result

    @staticmethod
    def upsert_source(
        name: str,
        db_type: str,
        connection_url: str,
        query_text: str,
        target_volume: str | None = None,
        title_column: str | None = None,
        chunk_size: int = 500,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        DB 소스 등록/수정 (Upsert)
        - name 기준 기존 소스 있으면 UPDATE, 없으면 INSERT
        - chunk_size: 한 번에 가져올 로우 수 (분할 수집 단위)
        """
        with get_db_session() as db:
            safe_query_text = DBIngestionService._validate_query_text(query_text)
            normalized_target_volume = (target_volume or "").strip() or None
            if normalized_target_volume:
                volume = db.query(SearchVolume).filter(SearchVolume.alias_name == normalized_target_volume).first()
                if not volume:
                    volume = db.query(SearchVolume).filter(SearchVolume.index_name == normalized_target_volume).first()
                if not volume:
                    return {"status": "fail", "message": "target_volume not found", "target_volume": normalized_target_volume}
                if not volume.is_active:
                    return {"status": "fail", "message": "target_volume is inactive", "target_volume": normalized_target_volume}

            row = db.query(DbSource).filter(DbSource.name == name).first()
            now = datetime.now(timezone.utc)
            enc_url = _encrypt(connection_url)
            if row:
                row.db_type = db_type
                row.connection_url = enc_url
                row.query_text = safe_query_text
                row.target_volume = normalized_target_volume
                row.title_column = title_column
                row.chunk_size = chunk_size
                row.is_active = is_active
                row.updated_at = now
            else:
                row = DbSource(
                    name=name,
                    db_type=db_type,
                    connection_url=enc_url,
                    query_text=safe_query_text,
                    target_volume=normalized_target_volume,
                    title_column=title_column,
                    chunk_size=chunk_size,
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.flush()
            return {"id": row.id, "name": row.name, "db_type": row.db_type, "chunk_size": row.chunk_size, "target_volume": row.target_volume}

    @staticmethod
    def sync_source(source_id: int, max_rows: int = 5000) -> dict[str, Any]:
        """
        DB 소스 동기화 실행 (분할 수집)
        - stream_results=True로 메모리 최소화
        - fetchmany(chunk_size)로 나눠서 색인 → 대용량 테이블도 안정적 처리
        - max_rows 제한으로 무한 수집 방지
        """
        with get_db_session() as db:
            source = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not source:
                return {"status": "fail", "message": "DB source not found", "source_id": source_id}

            indexed = 0
            skipped = 0
            failed = 0
            failed_files: list[str] = []
            target_ref = (source.target_volume or "").strip() or None
            target_index = None

            if target_ref:
                volume = db.query(SearchVolume).filter(SearchVolume.alias_name == target_ref).first()
                if not volume:
                    volume = db.query(SearchVolume).filter(SearchVolume.index_name == target_ref).first()
                if not volume:
                    return {
                        "status": "fail",
                        "source_id": source_id,
                        "message": f"target_volume not found: {target_ref}",
                    }
                if not volume.is_active:
                    return {
                        "status": "fail",
                        "source_id": source_id,
                        "message": f"target_volume is inactive: {target_ref}",
                    }
                target_index = (volume.index_name or "").strip() or None

            try:
                safe_query_text = DBIngestionService._validate_query_text(source.query_text)
                engine = create_engine(_decrypt(source.connection_url))
                with engine.connect() as conn:
                    result = conn.execution_options(stream_results=True).execute(text(safe_query_text))
                    while indexed + skipped + failed < max_rows:
                        rows = result.fetchmany(source.chunk_size)
                        if not rows:
                            break
                        for row in rows:
                            if indexed + skipped + failed >= max_rows:
                                break
                            record = dict(row._mapping)
                            title_col = source.title_column or "title"
                            title = str(record.get(title_col) or f"{source.name}-{indexed + skipped + failed + 1}")
                            body_text = " ".join([str(v) for v in record.values() if v is not None])
                            try:
                                payload = f"{title}\n{body_text}".encode("utf-8", errors="ignore")
                                index_result = IndexingService.index_bytes(
                                    filename=f"{source.name}_{title}.txt",
                                    content=payload,
                                    source_label=f"db:{source.name}",
                                    index_name=target_index,
                                )
                                if index_result.get("status") == "success":
                                    indexed += 1
                                elif index_result.get("status") == "skipped":
                                    skipped += 1
                                else:
                                    failed += 1
                                    failed_files.append(title)
                            except Exception as file_exc:
                                failed += 1
                                failed_files.append(title)

                SMBService._log_sync_summary(
                    db=db,
                    source_type="db",
                    source_name=source.name,
                    source_id=source_id,
                    success_count=indexed,
                    skipped_count=skipped,
                    failed_count=failed,
                    unchanged_count=0,
                    failed_files=failed_files,
                    trigger_type="manual",
                )

                source.last_synced_at = datetime.now(timezone.utc)
                source.last_error = None
                source.updated_at = datetime.now(timezone.utc)
                return {
                    "status": "success",
                    "source_id": source_id,
                    "target_volume": target_ref,
                    "target_index": target_index,
                    "indexed": indexed,
                    "skipped": skipped,
                    "failed": failed,
                }
            except Exception as exc:
                source.last_error = str(exc)
                source.updated_at = datetime.now(timezone.utc)
                return {"status": "fail", "source_id": source_id, "message": str(exc)}

    @staticmethod
    def sync_all_sources(max_rows_per_source: int = 3000) -> dict[str, Any]:
        """활성 DB 소스 전체 즉시 동기화"""
        sources = DBIngestionService.list_sources(active_only=True)
        results = [DBIngestionService.sync_source(source_id=row["id"], max_rows=max_rows_per_source) for row in sources]
        success = sum(1 for r in results if r.get("status") == "success")
        failed = len(results) - success
        return {
            "status": "success",
            "total_sources": len(sources),
            "success_sources": success,
            "failed_sources": failed,
            "results": results,
        }

    @staticmethod
    def test_connection_url(connection_url: str) -> dict[str, Any]:
        """접속 URL로 DB 연결 테스트 (폼 입력값 직접 검증용)"""
        try:
            engine = create_engine(connection_url, connect_args={"connect_timeout": 5} if "postgresql" in connection_url else {})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"status": "success", "message": "DB 연결 성공"}
        except Exception as exc:
            return {"status": "fail", "message": str(exc)}

    @staticmethod
    def test_connection(source_id: int) -> dict[str, Any]:
        """등록된 DB 소스 ID로 연결 테스트"""
        with get_db_session() as db:
            row = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "DB 소스를 찾을 수 없습니다"}
            decrypted_url = _decrypt(row.connection_url)
            return DBIngestionService.test_connection_url(decrypted_url)

    @staticmethod
    def delete_source(source_id: int) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "DB 소스를 찾을 수 없습니다"}
            db.delete(row)
            return {"status": "success", "message": f"DB 소스 ID {source_id} 삭제 완료"}

    @staticmethod
    def toggle_active(source_id: int, is_active: bool) -> dict[str, Any]:
        """DB 소스 활성/비활성 토글 — 스케줄러 자동 등록/해제"""
        with get_db_session() as db:
            row = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "DB 소스를 찾을 수 없습니다"}
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)
            db.flush()
            ScheduleService.auto_sync_entry(db, "db", source_id, is_active)
            state = "활성" if is_active else "비활성"
            return {"status": "success", "id": row.id, "name": row.name, "is_active": row.is_active, "message": f"{row.name} 소스가 {state} 상태로 변경되었습니다. 스케줄러에 자동 반영됩니다."}


class ScheduleService:
    """
    스케줄 엔트리 CRUD 서비스
    - schedule_entries 테이블에 대한 조회/등록/수정/삭제
    - 소스 활성화 시 자동 등록, 비활성화 시 자동 비활성
    """

    @staticmethod
    def list_entries() -> list[dict[str, Any]]:
        """전체 스케줄 엔트리 목록 (소스 이름 포함, 미등록 활성 소스 자동 등록)"""
        ScheduleService.bootstrap_active_sources()
        with get_db_session() as db:
            entries = db.query(ScheduleEntry).order_by(ScheduleEntry.source_type, ScheduleEntry.source_id).all()
            result = []
            for e in entries:
                source_name = ""
                if e.source_type == "smb":
                    src = db.query(SmbSource).filter(SmbSource.id == e.source_id).first()
                    source_name = src.name if src else "(삭제됨)"
                elif e.source_type == "db":
                    src = db.query(DbSource).filter(DbSource.id == e.source_id).first()
                    source_name = src.name if src else "(삭제됨)"
                result.append({
                    "id": e.id,
                    "source_type": e.source_type,
                    "source_id": e.source_id,
                    "source_name": source_name,
                    "interval_minutes": e.interval_minutes,
                    "next_run_at": e.next_run_at.isoformat() if e.next_run_at else None,
                    "last_run_at": e.last_run_at.isoformat() if e.last_run_at else None,
                    "is_enabled": e.is_enabled,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "updated_at": e.updated_at.isoformat() if e.updated_at else None,
                })
            return result

    @staticmethod
    def upsert_entry(source_type: str, source_id: int, interval_minutes: int = 1440, is_enabled: bool = True) -> dict[str, Any]:
        """스케줄 엔트리 업서트 (등록 또는 수정)"""
        if source_type not in ("smb", "db"):
            return {"status": "fail", "message": "source_type은 smb 또는 db만 가능합니다"}
        if interval_minutes < 1:
            return {"status": "fail", "message": "interval_minutes는 1 이상이어야 합니다"}
        now = datetime.now(timezone.utc)
        with get_db_session() as db:
            entry = db.query(ScheduleEntry).filter(
                ScheduleEntry.source_type == source_type,
                ScheduleEntry.source_id == source_id,
            ).first()
            if entry:
                entry.interval_minutes = interval_minutes
                entry.is_enabled = is_enabled
                entry.updated_at = now
                if is_enabled and not entry.next_run_at:
                    entry.next_run_at = now + timedelta(minutes=interval_minutes)
            else:
                entry = ScheduleEntry(
                    source_type=source_type,
                    source_id=source_id,
                    interval_minutes=interval_minutes,
                    is_enabled=is_enabled,
                    next_run_at=now + timedelta(minutes=interval_minutes),
                    created_at=now,
                    updated_at=now,
                )
                db.add(entry)
            db.flush()
            return {"status": "success", "id": entry.id, "message": f"{source_type}/{source_id} 스케줄 {'등록' if not entry.last_run_at else '수정'} 완료"}

    @staticmethod
    def delete_entry(entry_id: int) -> dict[str, Any]:
        """스케줄 엔트리 삭제"""
        with get_db_session() as db:
            entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
            if not entry:
                return {"status": "fail", "message": "스케줄 엔트리를 찾을 수 없습니다"}
            db.delete(entry)
            return {"status": "success", "message": f"스케줄 ID {entry_id} 삭제 완료"}

    @staticmethod
    def bootstrap_active_sources() -> dict[str, Any]:
        """기존 활성 소스 중 스케줄 미등록 건을 일괄 등록 (서버 기동 또는 수동 호출)"""
        now = datetime.now(timezone.utc)
        created = 0
        with get_db_session() as db:
            for src in db.query(SmbSource).filter(SmbSource.is_active == True).all():
                exists = db.query(ScheduleEntry).filter(
                    ScheduleEntry.source_type == "smb", ScheduleEntry.source_id == src.id
                ).first()
                if not exists:
                    db.add(ScheduleEntry(source_type="smb", source_id=src.id, interval_minutes=1440,
                                         is_enabled=True, next_run_at=now + timedelta(minutes=1440),
                                         created_at=now, updated_at=now))
                    created += 1
            for src in db.query(DbSource).filter(DbSource.is_active == True).all():
                exists = db.query(ScheduleEntry).filter(
                    ScheduleEntry.source_type == "db", ScheduleEntry.source_id == src.id
                ).first()
                if not exists:
                    db.add(ScheduleEntry(source_type="db", source_id=src.id, interval_minutes=1440,
                                         is_enabled=True, next_run_at=now + timedelta(minutes=1440),
                                         created_at=now, updated_at=now))
                    created += 1
        return {"status": "success", "created": created, "message": f"활성 소스 {created}건 스케줄 자동 등록 완료"}

    @staticmethod
    def auto_sync_entry(db, source_type: str, source_id: int, is_active: bool) -> None:
        """소스 활성/비활성 시 자동으로 스케줄 엔트리 등록/비활성 처리 (외부 세션 사용)"""
        now = datetime.now(timezone.utc)
        entry = db.query(ScheduleEntry).filter(
            ScheduleEntry.source_type == source_type,
            ScheduleEntry.source_id == source_id,
        ).first()
        if is_active:
            if not entry:
                entry = ScheduleEntry(
                    source_type=source_type,
                    source_id=source_id,
                    interval_minutes=1440,
                    is_enabled=True,
                    next_run_at=now + timedelta(minutes=1440),
                    created_at=now,
                    updated_at=now,
                )
                db.add(entry)
            else:
                entry.is_enabled = True
                entry.updated_at = now
                if not entry.next_run_at:
                    entry.next_run_at = now + timedelta(minutes=entry.interval_minutes)
        else:
            if entry:
                entry.is_enabled = False
                entry.updated_at = now
        db.flush()


class IngestionSchedulerService:
    """
    소스별 자동 색인 스케줄러 (백그라운드)
    - daemon 스레드로 실행, 서버 종료 시 자동 정리
    - schedule_entries 테이블 기준으로 각 소스별 개별 주기 동기화
    - 60초마다 due 엔트리 확인 후 실행
    """
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None
    _last_run_at: datetime | None = None
    _last_summary: dict[str, Any] = {}

    @classmethod
    def _loop(cls) -> None:
        """백그라운드 루프: schedule_entries에서 due 엔트리 찾아 개별 동기화"""
        while cls._stop_event and not cls._stop_event.is_set():
            now = datetime.now(timezone.utc)
            cls._last_run_at = now
            smb_results: list[dict] = []
            db_results: list[dict] = []
            try:
                with get_db_session() as db:
                    due_entries = db.query(ScheduleEntry).filter(
                        ScheduleEntry.is_enabled == True,
                        ScheduleEntry.next_run_at <= now,
                    ).all()
                    for entry in due_entries:
                        try:
                            if entry.source_type == "smb":
                                result = SMBService.sync_source(entry.source_id, trigger_type="scheduler")
                                smb_results.append(result)
                            elif entry.source_type == "db":
                                result = DBIngestionService.sync_source(entry.source_id)
                                db_results.append(result)
                            entry.last_run_at = datetime.now(timezone.utc)
                            entry.next_run_at = entry.last_run_at + timedelta(minutes=entry.interval_minutes)
                            entry.updated_at = entry.last_run_at
                        except Exception:
                            entry.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=entry.interval_minutes)
                    db.flush()
            except Exception:
                pass
            cls._last_summary = {
                "ran_at": now.isoformat(),
                "smb_results": smb_results,
                "db_results": db_results,
            }
            cls._stop_event.wait(60)

    @classmethod
    def start(cls) -> dict[str, Any]:
        """스케줄러 시작"""
        if cls._thread and cls._thread.is_alive():
            return {"status": "already-running"}

        cls._stop_event = threading.Event()
        cls._thread = threading.Thread(target=cls._loop, daemon=True)
        cls._thread.start()
        return {"status": "started"}

    @classmethod
    def stop(cls) -> dict[str, Any]:
        """스케줄러 정지"""
        if not cls._thread or not cls._thread.is_alive() or not cls._stop_event:
            return {"status": "already-stopped"}
        cls._stop_event.set()
        cls._thread.join(timeout=3)
        return {"status": "stopped"}

    @classmethod
    def status(cls) -> dict[str, Any]:
        """스케줄러 현재 상태 조회"""
        return {
            "running": bool(cls._thread and cls._thread.is_alive()),
            "last_run_at": cls._last_run_at.isoformat() if cls._last_run_at else None,
            "last_summary": cls._last_summary,
        }


class DashboardService:
    """
    검색 트렌드 및 통계 시각화 대시보드 서비스
    - summary: 전체/실패 로그 수, 실패률, 인기/실패 키워드 TOP 10
    - trend: 날짜별 성공/실패 건수 버킷팅 (트렌드 차트용)
    - health_overview: 운영 상태 요약 (SMB/DB/스케줄러/인증서)
    - alert_badges: 위험 신호 배지 (인증서 만료, 실패률 급등, 스케줄러 중지)
    """
    @staticmethod
    def summary(days: int = 7) -> dict[str, Any]:
        """검색 통계 요약 (최근 N일 기준, 전체/실패 로그 수 + 인기/실패 TOP 10)"""
        popular = DBService.get_popular_keyword_stats(days=days, limit=10)
        failed = DBService.get_failed_keywords(days=days, limit=10)
        with get_db_session() as db:
            total_logs = db.query(SearchLog).count()
            failed_logs = db.query(SearchLog).filter(SearchLog.total_hits <= 0).count()

        return {
            "days": days,
            "total_logs": total_logs,
            "failed_logs": failed_logs,
            "failure_rate": (failed_logs / total_logs) if total_logs else 0,
            "top_keywords": popular,
            "top_failed_keywords": failed,
        }

    @staticmethod
    def trend(days: int = 14) -> list[dict[str, Any]]:
        """날짜별 검색 성공/실패 건수 버킷팅 (트렌드 차트 데이터)"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        buckets: dict[str, dict[str, int]] = {}
        with get_db_session() as db:
            rows = db.query(SearchLog).filter(SearchLog.created_at >= cutoff).all()
            for row in rows:
                key = row.created_at.strftime("%Y-%m-%d") if row.created_at else "unknown"
                if key not in buckets:
                    buckets[key] = {"total": 0, "failed": 0}
                buckets[key]["total"] += 1
                if (row.total_hits or 0) <= 0:
                    buckets[key]["failed"] += 1

        return [
            {
                "date": key,
                "total": val["total"],
                "failed": val["failed"],
                "success": val["total"] - val["failed"],
            }
            for key, val in sorted(buckets.items(), key=lambda x: x[0])
        ]

    @staticmethod
    def health_overview() -> dict[str, Any]:
        """운영 상태 요약 (스케줄러/SMB/DB 소스 수/인증서 현황)"""
        # 관리자 화면에서 한 번에 볼 수 있는 운영 상태 요약
        with get_db_session() as db:
            smb_total = db.query(SmbSource).count()
            smb_active = db.query(SmbSource).filter(SmbSource.is_active.is_(True)).count()
            db_total = db.query(DbSource).count()
            db_active = db.query(DbSource).filter(DbSource.is_active.is_(True)).count()
            dict_total = db.query(CertificateStatus).count()

        scheduler = IngestionSchedulerService.status()

        return {
            "scheduler": scheduler,
            "sources": {
                "smb_total": smb_total,
                "smb_active": smb_active,
                "db_total": db_total,
                "db_active": db_active,
            },
            "certificate_rows": dict_total,
        }

    @staticmethod
    def alert_badges(cert_warn_days: int = 7, spike_ratio: float = 1.5) -> list[dict[str, Any]]:
        """
        운영 위험 신호 배지 반환
        - 스케줄러 중지 → critical
        - 인증서 만료/임박 → critical/warning
        - 실패률 급등 (spike_ratio 배 초과) → warning
        - 모두 정상이면 healthy info 반환
        """
        # 운영 위험 신호를 배지 형태로 반환
        badges: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        with get_db_session() as db:
            cert_warn_count = (
                db.query(CertificateStatus)
                .filter(
                    CertificateStatus.days_left.isnot(None),
                    CertificateStatus.days_left >= 0,
                    CertificateStatus.days_left <= cert_warn_days,
                )
                .count()
            )
            cert_expired_count = (
                db.query(CertificateStatus)
                .filter(CertificateStatus.days_left.isnot(None), CertificateStatus.days_left < 0)
                .count()
            )

            last_24h = now - timedelta(hours=24)
            prev_7d_start = now - timedelta(days=8)
            prev_7d_end = now - timedelta(days=1)

            last_rows = db.query(SearchLog).filter(SearchLog.created_at >= last_24h).all()
            prev_rows = (
                db.query(SearchLog)
                .filter(SearchLog.created_at >= prev_7d_start, SearchLog.created_at < prev_7d_end)
                .all()
            )

            last_total = len(last_rows)
            prev_total = len(prev_rows)
            last_fail_count = sum(1 for row in last_rows if (row.total_hits or 0) <= 0)
            prev_fail_count = sum(1 for row in prev_rows if (row.total_hits or 0) <= 0)

        scheduler_running = IngestionSchedulerService.status().get("running", False)
        if not scheduler_running:
            badges.append({"code": "scheduler_stopped", "severity": "critical", "message": "자동 색인 스케줄러 중지"})

        if cert_expired_count > 0:
            badges.append({
                "code": "certificate_expired",
                "severity": "critical",
                "message": f"만료 인증서 {cert_expired_count}건",
            })
        elif cert_warn_count > 0:
            badges.append({
                "code": "certificate_due",
                "severity": "warning",
                "message": f"{cert_warn_days}일 내 만료 인증서 {cert_warn_count}건",
            })

        last_fail_rate = (last_fail_count / last_total) if last_total else 0.0
        prev_fail_rate = (prev_fail_count / prev_total) if prev_total else 0.0

        # 기준 데이터가 있는 경우에만 급등 판정
        if prev_total >= 10 and last_total >= 5 and prev_fail_rate > 0:
            ratio = last_fail_rate / prev_fail_rate
            if ratio >= spike_ratio:
                badges.append(
                    {
                        "code": "failure_rate_spike",
                        "severity": "warning",
                        "message": f"실패율 급등 감지 {ratio:.2f}배",
                        "current": round(last_fail_rate, 4),
                        "baseline": round(prev_fail_rate, 4),
                    }
                )

        if not badges:
            badges.append({"code": "healthy", "severity": "info", "message": "운영 상태 정상"})

        return badges


class VolumeSSLService:
    """
    볼륨(인덱스) 생성 및 SSL 인증서 관리 서비스
    - OpenSearch 인덱스 생성 (샤드/레플리카 설정)
    - cert 폴더 PEM 파일 스캔 → 만료일/남은 일수/상태 판정
    - PowerShell 기반 인증서 갱신 스크립트 동적 생성/실행
    """
    @staticmethod
    def create_search_volume(index_name: str, shards: int = 1, replicas: int = 1) -> dict[str, Any]:
        """검색 볼륨(인덱스) 생성 — 이미 존재하면 exists 반환"""
        client = get_client()
        normalized_index = (index_name or "").strip()
        if not normalized_index:
            return {"status": "fail", "message": "index_name is required"}

        already_exists = client.indices.exists(index=normalized_index)

        if not already_exists:
            body = {
                "settings": {
                    "number_of_shards": shards,
                    "number_of_replicas": replicas,
                    "refresh_interval": "1s",
                }
            }
            client.indices.create(index=normalized_index, body=body)

        # 기본 정책: alias는 index와 동일 이름으로 1:1 매핑
        try:
            client.indices.put_alias(index=normalized_index, name=normalized_index)
        except Exception:
            pass

        now = datetime.now(timezone.utc)
        with get_db_session() as db:
            row = db.query(SearchVolume).filter(SearchVolume.index_name == normalized_index).first()
            if row:
                row.shards = shards
                row.replicas = replicas
                if not row.alias_name:
                    row.alias_name = normalized_index
                row.updated_at = now
            else:
                row = SearchVolume(
                    index_name=normalized_index,
                    alias_name=normalized_index,
                    shards=shards,
                    replicas=replicas,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()

            return {
                "status": "exists" if already_exists else "created",
                "id": row.id,
                "index": row.index_name,
                "shards": row.shards,
                "replicas": row.replicas,
                "is_active": row.is_active,
            }

    @staticmethod
    def list_volumes(active_only: bool = False) -> list[dict[str, Any]]:
        with get_db_session() as db:
            query = db.query(SearchVolume)
            if active_only:
                query = query.filter(SearchVolume.is_active.is_(True))
            rows = query.order_by(SearchVolume.index_name.asc()).all()
            return [
                {
                    "id": r.id,
                    "index_name": r.index_name,
                    "alias_name": r.alias_name,
                    "shards": r.shards,
                    "replicas": r.replicas,
                    "is_active": r.is_active,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]

    @staticmethod
    def update_volume(volume_id: int, alias_name: str, replicas: int) -> dict[str, Any]:
        """검색 볼륨 설정 수정 (index_name/shards 고정, alias/replicas만 변경)"""
        with get_db_session() as db:
            row = db.query(SearchVolume).filter(SearchVolume.id == volume_id).first()
            if not row:
                return {"status": "fail", "message": "volume not found", "volume_id": volume_id}

            normalized_alias = (alias_name or "").strip()
            if not normalized_alias:
                return {"status": "fail", "message": "alias_name is required"}

            duplicate_alias = (
                db.query(SearchVolume)
                .filter(SearchVolume.alias_name == normalized_alias, SearchVolume.id != volume_id)
                .first()
            )
            if duplicate_alias:
                return {"status": "fail", "message": "alias_name already in use", "alias_name": normalized_alias}

            index_name = (row.index_name or "").strip()
            client = get_client()
            if not client.indices.exists(index=index_name):
                return {"status": "fail", "message": "index not found", "index_name": index_name}

            settings = client.indices.get_settings(index=index_name)
            idx_settings = settings.get(index_name, {}).get("settings", {}).get("index", {})
            current_replicas = int(idx_settings.get("number_of_replicas", row.replicas or 1))

            old_alias = (row.alias_name or "").strip() or index_name
            if normalized_alias != old_alias:
                actions = [{"remove": {"index": index_name, "alias": old_alias}}, {"add": {"index": index_name, "alias": normalized_alias}}]
                try:
                    client.indices.update_aliases(body={"actions": actions})
                except Exception:
                    # remove 실패(별칭 미존재) 가능성을 고려해 add 단독 재시도
                    client.indices.update_aliases(body={"actions": [{"add": {"index": index_name, "alias": normalized_alias}}]})

            if replicas != current_replicas:
                client.indices.put_settings(index=index_name, body={"index": {"number_of_replicas": replicas}})

            # DB source는 target_volume(alias) 참조이므로 alias 변경시 함께 업데이트
            db.query(DbSource).filter(DbSource.target_volume == old_alias).update(
                {DbSource.target_volume: normalized_alias},
                synchronize_session=False,
            )

            row.alias_name = normalized_alias
            row.replicas = replicas
            row.updated_at = datetime.now(timezone.utc)

            return {
                "status": "success",
                "id": row.id,
                "index_name": row.index_name,
                "alias_name": row.alias_name,
                "shards": row.shards,
                "replicas": row.replicas,
            }

    @staticmethod
    def set_volume_active(volume_id: int, is_active: bool) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(SearchVolume).filter(SearchVolume.id == volume_id).first()
            if not row:
                return {"status": "fail", "message": "volume not found", "volume_id": volume_id}
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)
            return {
                "status": "success",
                "id": row.id,
                "index_name": row.index_name,
                "is_active": row.is_active,
            }

    @staticmethod
    def delete_volume(volume_id: int) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(SearchVolume).filter(SearchVolume.id == volume_id).first()
            if not row:
                return {"status": "fail", "message": "volume not found", "volume_id": volume_id}

            index_name = (row.index_name or "").strip()
            alias_name = (row.alias_name or "").strip() or index_name
            if index_name == "cleversearch-docs":
                return {"status": "fail", "message": "default volume cannot be deleted"}

            linked_count = db.query(DbSource).filter(DbSource.target_volume == alias_name).count()
            if linked_count > 0:
                return {
                    "status": "fail",
                    "message": f"volume is in use by {linked_count} db source(s)",
                    "linked_db_sources": linked_count,
                }

            client = get_client()
            deleted_index = False
            if client.indices.exists(index=index_name):
                client.indices.delete(index=index_name)
                deleted_index = True

            db.delete(row)
            return {
                "status": "success",
                "id": volume_id,
                "index_name": index_name,
                "alias_name": alias_name,
                "deleted_index": deleted_index,
            }

    @staticmethod
    def scan_certificates(cert_dir: str = "cert", warn_days: int = 30) -> list[dict[str, Any]]:
        """
        cert 폴더의 PEM 인증서 스캔
        - ssl._ssl._test_decode_cert로 만료일 추출
        - healthy/warning/expired/invalid 상태 판정
        - CertificateStatus DB 테이블에 동기화
        """
        target = Path(cert_dir)
        if not target.exists():
            return []

        results = []
        now = datetime.now(timezone.utc)

        with get_db_session() as db:
            for file_path in sorted(target.glob("*.pem")):
                if file_path.name.lower().endswith("-key.pem"):
                    continue
                status = "unknown"
                expires_at = None
                days_left = None
                message = None
                subject = None

                try:
                    decoded = ssl._ssl._test_decode_cert(str(file_path))
                    subject_items = decoded.get("subject") or []
                    subject_parts: list[str] = []
                    for group in subject_items:
                        if isinstance(group, (list, tuple)):
                            for pair in group:
                                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                                    subject_parts.append(f"{pair[0]}={pair[1]}")
                    subject = ", ".join(subject_parts) if subject_parts else None
                    expires_text = decoded.get("notAfter")
                    if expires_text:
                        expires_at = datetime.strptime(expires_text, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                        days_left = (expires_at - now).days
                        if days_left < 0:
                            status = "expired"
                        elif days_left <= warn_days:
                            status = "warning"
                        else:
                            status = "healthy"
                except Exception as exc:
                    status = "invalid"
                    message = str(exc)

                row = db.query(CertificateStatus).filter(CertificateStatus.cert_name == file_path.name).first()
                if row:
                    row.cert_path = str(file_path)
                    row.expires_at = expires_at
                    row.days_left = days_left
                    row.health_status = status
                    row.last_checked_at = now
                    row.message = message
                else:
                    row = CertificateStatus(
                        cert_name=file_path.name,
                        cert_path=str(file_path),
                        expires_at=expires_at,
                        days_left=days_left,
                        health_status=status,
                        last_checked_at=now,
                        message=message,
                    )
                    db.add(row)

                results.append(
                    {
                        "cert_name": file_path.name,
                        "cert_path": str(file_path),
                        "subject": subject,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                        "days_left": days_left,
                        "health_status": status,
                        "message": message,
                    }
                )

        return results

    @staticmethod
    def generate_renew_script(cert_dir: str = "cert", output_path: str = "scripts/renew_certs.ps1") -> dict[str, Any]:
        """인증서 갱신용 PowerShell 스크립트 동적 생성 (OpenSSL 기반)"""
        script = """param(
    [string]$OpenSslExe = \"openssl\",
    [string]$OutDir = \"cert\"
)

New-Item -Path $OutDir -ItemType Directory -Force | Out-Null
$certPath = Join-Path $OutDir \"localhost-renewed.pem\"
$keyPath = Join-Path $OutDir \"localhost-renewed-key.pem\"
$subj = \"/C=KR/ST=Seoul/L=Seoul/O=CleverSearch/OU=Dev/CN=localhost\"

& $OpenSslExe req -x509 -nodes -days 365 -newkey rsa:2048 -keyout $keyPath -out $certPath -subj $subj
if ($LASTEXITCODE -ne 0) {
    throw \"인증서 갱신 실패\"
}
Write-Output \"인증서 생성 완료: $certPath\"
"""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
        return {"status": "generated", "script_path": str(target)}

    @staticmethod
    def execute_renew_script(script_path: str) -> dict[str, Any]:
        """생성된 갱신 스크립트 실행 (Windows PowerShell 환경 전용)"""
        if os.name != "nt":
            return {"status": "fail", "message": "Windows PowerShell 환경에서만 자동 실행 지원"}

        # 실행 가능한 스크립트를 작업공간 내 허용 경로로 제한
        candidate = Path(script_path).resolve()
        allowed_dir = Path("scripts").resolve()
        allowed_name = "renew_certs.ps1"
        if candidate.name != allowed_name or allowed_dir not in candidate.parents:
            return {"status": "fail", "message": "허용되지 않은 스크립트 경로입니다"}
        if not candidate.exists():
            return {"status": "fail", "message": "스크립트 파일을 찾을 수 없습니다"}

        openssl_exe = shutil.which("openssl")
        if not openssl_exe:
            for openssl_candidate in [
                r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
                r"C:\Program Files\OpenSSL-Win32\bin\openssl.exe",
                r"C:\Program Files\Git\usr\bin\openssl.exe",
            ]:
                if os.path.exists(openssl_candidate):
                    openssl_exe = openssl_candidate
                    break

        proc = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(candidate),
                "-OpenSslExe",
                openssl_exe or "openssl",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        result = {
            "status": "success" if proc.returncode == 0 else "fail",
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            if "openssl" in err.lower():
                result["message"] = "OpenSSL 실행 파일을 찾을 수 없습니다. OpenSSL 설치 또는 경로(PATH)를 확인하세요."
            elif err:
                result["message"] = err.splitlines()[-1][:300]
            else:
                result["message"] = "갱신 스크립트 실행 실패"
        return result


# ────────────────────────────────────────────────────────
# 인기검색 표시 설정 관리 서비스
# ────────────────────────────────────────────────────────
_POPULAR_CONFIG_PATH = Path("popular_settings.json")

_DEFAULT_POPULAR = {
    "days": 7,
}


class PopularConfigService:
    """인기검색 표시 설정 (JSON 파일 기반) — 관리자가 저장한 days/limit을 유지"""

    @staticmethod
    def _sanitize_settings(data: dict | None) -> dict:
        merged = {**_DEFAULT_POPULAR, **(data or {})}
        days = int(merged.get("days", _DEFAULT_POPULAR["days"]))
        sanitized = {
            "days": max(1, min(365, days)),
        }
        if merged.get("limit") is not None:
            limit = int(merged.get("limit"))
            sanitized["limit"] = max(1, min(9, limit))
        return sanitized

    @staticmethod
    def get_settings() -> dict:
        if _POPULAR_CONFIG_PATH.exists():
            try:
                data = json.loads(_POPULAR_CONFIG_PATH.read_text(encoding="utf-8"))
                return PopularConfigService._sanitize_settings(data)
            except Exception:
                pass
        return PopularConfigService._sanitize_settings(None)

    @staticmethod
    def update_settings(new_settings: dict) -> dict:
        current = PopularConfigService.get_settings()
        if "days" in new_settings:
            current["days"] = int(new_settings["days"])
        if "limit" in new_settings:
            current["limit"] = int(new_settings["limit"])
        current = PopularConfigService._sanitize_settings(current)
        _POPULAR_CONFIG_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current


# ────────────────────────────────────────────────────────
# 검색 가중치 동적 관리 서비스
# ────────────────────────────────────────────────────────
_SCORING_CONFIG_PATH = Path("scoring_weights.json")

_DEFAULT_WEIGHTS = {
    "title_phrase": 20,
    "title_and": 10,
    "content_phrase": 5,
    "content_and": 1,
    "vector": 1.0,
    "chosung": 10,
    "min_score": 0.0058,
}


class ScoringConfigService:
    """
    검색 가중치 동적 관리 서비스 (JSON 파일 기반)
    - scoring_weights.json에 가중치 저장/조회/초기화
    - 기본값: title_phrase=20, title_and=10, content_phrase=5, content_and=1, vector=1.0, chosung=10, min_score=0.0058
    - search_service.py의 build_weighted_query()에서 실시간 참조
    """

    @staticmethod
    def get_weights() -> dict:
        """현재 가중치 조회 (JSON 파일 없으면 기본값 반환, 있으면 기본값+파일 병합)"""
        if _SCORING_CONFIG_PATH.exists():
            try:
                data = json.loads(_SCORING_CONFIG_PATH.read_text(encoding="utf-8"))
                merged = {**_DEFAULT_WEIGHTS, **data}
                return merged
            except Exception:
                pass
        return dict(_DEFAULT_WEIGHTS)

    @staticmethod
    def update_weights(new_weights: dict) -> dict:
        """가중치 부분 업데이트 (전달된 키만 덤어쓰기, 나머지는 유지)"""
        current = ScoringConfigService.get_weights()
        for key in _DEFAULT_WEIGHTS:
            if key in new_weights:
                current[key] = float(new_weights[key])
        _SCORING_CONFIG_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current

    @staticmethod
    def reset_weights() -> dict:
        """가중치 초기화 (JSON 파일 삭제 → 기본값 복원)"""
        if _SCORING_CONFIG_PATH.exists():
            _SCORING_CONFIG_PATH.unlink()
        return dict(_DEFAULT_WEIGHTS)

    @staticmethod
    async def evaluate_quality(test_cases: list[dict]) -> dict:
        """
        검색 품질 평가 — 테스트 케이스별 기대 문서 포함 여부 확인
        test_cases: [{"query": "연구개발계획서", "expected_title": "연구개발계획서"}]
        """
        from app.schemas.search_schema import SearchRequest
        from app.services.search_service import SearchService

        results = []
        passed = 0
        total = len(test_cases)

        for tc in test_cases:
            query = tc.get("query", "")
            expected = tc.get("expected_title", "")
            req = SearchRequest(query=query, size=10, page=1)

            search_result = await SearchService.execute_search(req)

            items = search_result.get("items", [])
            titles = [item.get("content", {}).get("Title", "") for item in items]
            top_score = items[0]["score"] if items else 0

            found = any(expected.lower() in t.lower() for t in titles) if expected else (len(items) > 0)
            if found:
                passed += 1

            results.append({
                "query": query,
                "expected": expected,
                "found": found,
                "top_score": round(top_score, 4),
                "result_count": search_result.get("total", 0),
                "top_titles": titles[:3],
            })

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
            "details": results,
        }


def bootstrap_sources_from_env(db_sources_json: str = "", smb_sources_json: str = "") -> dict[str, Any]:
    db_count = 0
    smb_count = 0

    if db_sources_json and db_sources_json.strip():
        try:
            rows = json.loads(db_sources_json)
            for row in rows:
                DBIngestionService.upsert_source(
                    name=row.get("name"),
                    db_type=row.get("db_type", "unknown"),
                    connection_url=row.get("connection_url"),
                    query_text=row.get("query_text", "SELECT 1"),
                    target_volume=row.get("target_volume"),
                    title_column=row.get("title_column"),
                    chunk_size=int(row.get("chunk_size", 500)),
                    is_active=bool(row.get("is_active", True)),
                )
                db_count += 1
        except Exception:
            pass

    if smb_sources_json and smb_sources_json.strip():
        try:
            rows = json.loads(smb_sources_json)
            for row in rows:
                SMBService.upsert_source(
                    name=row.get("name"),
                    share_path=row.get("share_path"),
                    username=row.get("username"),
                    password=row.get("password"),
                    domain=row.get("domain"),
                    port=int(row.get("port", 445)),
                    is_active=bool(row.get("is_active", True)),
                )
                smb_count += 1
        except Exception:
            pass

    return {"db_sources": db_count, "smb_sources": smb_count}
