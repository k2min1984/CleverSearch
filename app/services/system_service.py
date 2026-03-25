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
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.core.database import CertificateStatus, DbSource, SearchLog, SmbSource, get_db_session
from app.core.opensearch import get_client
from app.services.db_service import DBService
from app.services.indexing_service import ALLOWED_EXTENSIONS, IndexingService


class SMBService:
    """
    SMB/CIFS 외부 공유 폴더 데이터 수집 서비스
    - Windows net use 명령으로 SMB 경로 접속 및 자동 재연결
    - 파일 탐색 → 허용 확장자 필터 → IndexingService로 색인
    - DB에 소스 정보 저장 (SmbSource 테이블)
    """
    @staticmethod
    def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
        """등록된 SMB 소스 목록 조회 (active_only=True이면 활성 소스만)"""
        with get_db_session() as db:
            query = db.query(SmbSource)
            if active_only:
                query = query.filter(SmbSource.is_active.is_(True))
            rows = query.order_by(SmbSource.id.asc()).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "share_path": row.share_path,
                    "username": row.username,
                    "is_active": row.is_active,
                    "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                    "last_error": row.last_error,
                }
                for row in rows
            ]

    @staticmethod
    def upsert_source(name: str, share_path: str, username: str | None, password: str | None, is_active: bool = True) -> dict[str, Any]:
        """
        SMB 소스 등록/수정 (Upsert)
        - name 기준으로 기존 소스가 있으면 UPDATE, 없으면 INSERT
        """
        with get_db_session() as db:
            row = db.query(SmbSource).filter(SmbSource.name == name).first()
            now = datetime.now(timezone.utc)
            if row:
                row.share_path = share_path
                row.username = username
                row.password = password
                row.is_active = is_active
                row.updated_at = now
            else:
                row = SmbSource(
                    name=name,
                    share_path=share_path,
                    username=username,
                    password=password,
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.flush()
            return {"id": row.id, "name": row.name, "share_path": row.share_path, "is_active": row.is_active}

    @staticmethod
    def _try_reconnect(source: SmbSource) -> None:
        """
        네트워크 단절 시 자동 재연결 로직 (Windows 환경 전용)
        - net use 명령으로 SMB 경로 재접속 시도
        - 사용자명/암호 제공 시 자동 인증
        """
        # Windows 환경에서는 net use로 SMB 재연결을 시도합니다.
        if os.name != "nt":
            return
        cmd = ["net", "use", source.share_path]
        if source.password:
            cmd.append(source.password)
        if source.username:
            cmd.extend(["/user:" + source.username])
        cmd.append("/persistent:no")
        subprocess.run(cmd, capture_output=True, text=True, check=False)

    @staticmethod
    def sync_source(source_id: int, max_files: int = 200) -> dict[str, Any]:
        """
        SMB 소스 동기화 실행
        - 지정된 SMB 경로의 파일을 탐색하여 색인
        - 경로 접근 실패 시 _try_reconnect()로 자동 재연결 시도
        - max_files 제한으로 대량 파일 시 부하 방지
        """
        with get_db_session() as db:
            source = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not source:
                return {"status": "fail", "message": "SMB source not found", "source_id": source_id}

            indexed = 0
            skipped = 0
            failed = 0
            source_path = Path(source.share_path)

            if not source_path.exists():
                SMBService._try_reconnect(source)

            try:
                if not source_path.exists():
                    raise FileNotFoundError(f"경로 접근 실패: {source.share_path}")

                for root, _, files in os.walk(source.share_path):
                    for file_name in files:
                        if indexed + skipped + failed >= max_files:
                            break
                        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
                        if ext not in ALLOWED_EXTENSIONS:
                            continue
                        file_path = Path(root) / file_name
                        try:
                            content = file_path.read_bytes()
                            result = IndexingService.index_bytes(file_name, content, source_label=f"smb:{source.name}")
                            if result.get("status") == "success":
                                indexed += 1
                            elif result.get("status") == "skipped":
                                skipped += 1
                            else:
                                failed += 1
                        except Exception:
                            failed += 1

                source.last_seen_at = datetime.now(timezone.utc)
                source.last_error = None
                source.updated_at = datetime.now(timezone.utc)
                return {
                    "status": "success",
                    "source_id": source_id,
                    "indexed": indexed,
                    "skipped": skipped,
                    "failed": failed,
                }
            except Exception as exc:
                source.last_error = str(exc)
                source.updated_at = datetime.now(timezone.utc)
                return {"status": "fail", "source_id": source_id, "message": str(exc)}

    @staticmethod
    def delete_source(source_id: int) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(SmbSource).filter(SmbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "SMB 소스를 찾을 수 없습니다"}
            db.delete(row)
            return {"status": "success", "message": f"SMB 소스 ID {source_id} 삭제 완료"}


class DBIngestionService:
    """
    외부 DB 데이터 수집 서비스
    - SQLAlchemy engine으로 다양한 DB 타입(postgres/mysql/mssql 등) 접속
    - 대용량 DB 조회 시 fetchmany 스트리밍으로 부하 방지 (분할 수집)
    - 조회 결과를 텍스트로 변환하여 IndexingService로 색인
    """
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
                    "is_active": row.is_active,
                    "chunk_size": row.chunk_size,
                    "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
                    "last_error": row.last_error,
                }
                for row in rows
            ]

    @staticmethod
    def upsert_source(
        name: str,
        db_type: str,
        connection_url: str,
        query_text: str,
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
            row = db.query(DbSource).filter(DbSource.name == name).first()
            now = datetime.now(timezone.utc)
            if row:
                row.db_type = db_type
                row.connection_url = connection_url
                row.query_text = query_text
                row.title_column = title_column
                row.chunk_size = chunk_size
                row.is_active = is_active
                row.updated_at = now
            else:
                row = DbSource(
                    name=name,
                    db_type=db_type,
                    connection_url=connection_url,
                    query_text=query_text,
                    title_column=title_column,
                    chunk_size=chunk_size,
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.flush()
            return {"id": row.id, "name": row.name, "db_type": row.db_type, "chunk_size": row.chunk_size}

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

            try:
                engine = create_engine(source.connection_url)
                with engine.connect() as conn:
                    result = conn.execution_options(stream_results=True).execute(text(source.query_text))
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
                                    filename=f"{source.name}_{title}.txt", content=payload, source_label=f"db:{source.name}"
                                )
                                if index_result.get("status") == "success":
                                    indexed += 1
                                elif index_result.get("status") == "skipped":
                                    skipped += 1
                                else:
                                    failed += 1
                            except Exception:
                                failed += 1

                source.last_synced_at = datetime.now(timezone.utc)
                source.last_error = None
                source.updated_at = datetime.now(timezone.utc)
                return {
                    "status": "success",
                    "source_id": source_id,
                    "indexed": indexed,
                    "skipped": skipped,
                    "failed": failed,
                }
            except Exception as exc:
                source.last_error = str(exc)
                source.updated_at = datetime.now(timezone.utc)
                return {"status": "fail", "source_id": source_id, "message": str(exc)}

    @staticmethod
    def delete_source(source_id: int) -> dict[str, Any]:
        with get_db_session() as db:
            row = db.query(DbSource).filter(DbSource.id == source_id).first()
            if not row:
                return {"status": "fail", "message": "DB 소스를 찾을 수 없습니다"}
            db.delete(row)
            return {"status": "success", "message": f"DB 소스 ID {source_id} 삭제 완료"}


class IngestionSchedulerService:
    """
    자동 색인 스케줄러 (백그라운드 주기적 동기화)
    - daemon 스레드로 실행되어 서버 종료 시 자동 정리
    - 지정된 간격(interval_seconds)마다 모든 활성 SMB/DB 소스 동기화
    - start/stop/status API로 관리자 화면에서 제어
    """
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None
    _interval_seconds: int = 120
    _last_run_at: datetime | None = None
    _last_summary: dict[str, Any] = {}

    @classmethod
    def _loop(cls) -> None:
        """백그라운드 루프: 활성 SMB/DB 소스 전체 sync → 간격만큼 대기 → 반복"""
        while cls._stop_event and not cls._stop_event.is_set():
            cls._last_run_at = datetime.now(timezone.utc)
            smb_results = [SMBService.sync_source(row["id"]) for row in SMBService.list_sources(active_only=True)]
            db_results = [DBIngestionService.sync_source(row["id"]) for row in DBIngestionService.list_sources(active_only=True)]
            cls._last_summary = {
                "ran_at": cls._last_run_at.isoformat(),
                "smb_results": smb_results,
                "db_results": db_results,
            }
            cls._stop_event.wait(cls._interval_seconds)

    @classmethod
    def start(cls, interval_seconds: int = 120) -> dict[str, Any]:
        """스케줄러 시작 (이미 실행 중이면 already-running 반환)"""
        if cls._thread and cls._thread.is_alive():
            return {"status": "already-running", "interval_seconds": cls._interval_seconds}

        cls._interval_seconds = max(10, interval_seconds)
        cls._stop_event = threading.Event()
        cls._thread = threading.Thread(target=cls._loop, daemon=True)
        cls._thread.start()
        return {"status": "started", "interval_seconds": cls._interval_seconds}

    @classmethod
    def stop(cls) -> dict[str, Any]:
        """스케줄러 정지 (실행 중이 아니면 already-stopped 반환)"""
        if not cls._thread or not cls._thread.is_alive() or not cls._stop_event:
            return {"status": "already-stopped"}
        cls._stop_event.set()
        cls._thread.join(timeout=3)
        return {"status": "stopped"}

    @classmethod
    def status(cls) -> dict[str, Any]:
        """스케줄러 현재 상태 조회 (running, interval, last_run_at, last_summary)"""
        return {
            "running": bool(cls._thread and cls._thread.is_alive()),
            "interval_seconds": cls._interval_seconds,
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
            failed_logs = db.query(SearchLog).filter(SearchLog.is_failed.is_(True)).count()

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
                if row.is_failed:
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
            last_fail_count = sum(1 for row in last_rows if row.is_failed)
            prev_fail_count = sum(1 for row in prev_rows if row.is_failed)

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
        if client.indices.exists(index=index_name):
            return {"status": "exists", "index": index_name}

        body = {
            "settings": {
                "number_of_shards": shards,
                "number_of_replicas": replicas,
                "refresh_interval": "1s",
            }
        }
        client.indices.create(index=index_name, body=body)
        return {"status": "created", "index": index_name, "shards": shards, "replicas": replicas}

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
                status = "unknown"
                expires_at = None
                days_left = None
                message = None

                try:
                    decoded = ssl._ssl._test_decode_cert(str(file_path))
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

        proc = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "success" if proc.returncode == 0 else "fail",
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }


# ────────────────────────────────────────────────────────
# 인기검색 표시 설정 관리 서비스
# ────────────────────────────────────────────────────────
_POPULAR_CONFIG_PATH = Path("popular_settings.json")

_DEFAULT_POPULAR = {
    "days": 7,
    "limit": 10,
}


class PopularConfigService:
    """인기검색 표시 설정 (JSON 파일 기반) — 관리자가 저장한 days/limit을 유지"""

    @staticmethod
    def get_settings() -> dict:
        if _POPULAR_CONFIG_PATH.exists():
            try:
                data = json.loads(_POPULAR_CONFIG_PATH.read_text(encoding="utf-8"))
                return {**_DEFAULT_POPULAR, **data}
            except Exception:
                pass
        return dict(_DEFAULT_POPULAR)

    @staticmethod
    def update_settings(new_settings: dict) -> dict:
        current = PopularConfigService.get_settings()
        if "days" in new_settings:
            current["days"] = int(new_settings["days"])
        if "limit" in new_settings:
            current["limit"] = int(new_settings["limit"])
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
                    is_active=bool(row.get("is_active", True)),
                )
                smb_count += 1
        except Exception:
            pass

    return {"db_sources": db_count, "smb_sources": smb_count}
