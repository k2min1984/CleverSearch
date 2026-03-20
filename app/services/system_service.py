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
    @staticmethod
    def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
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


class DBIngestionService:
    @staticmethod
    def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
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


class IngestionSchedulerService:
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None
    _interval_seconds: int = 120
    _last_run_at: datetime | None = None
    _last_summary: dict[str, Any] = {}

    @classmethod
    def _loop(cls) -> None:
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
        if cls._thread and cls._thread.is_alive():
            return {"status": "already-running", "interval_seconds": cls._interval_seconds}

        cls._interval_seconds = max(10, interval_seconds)
        cls._stop_event = threading.Event()
        cls._thread = threading.Thread(target=cls._loop, daemon=True)
        cls._thread.start()
        return {"status": "started", "interval_seconds": cls._interval_seconds}

    @classmethod
    def stop(cls) -> dict[str, Any]:
        if not cls._thread or not cls._thread.is_alive() or not cls._stop_event:
            return {"status": "already-stopped"}
        cls._stop_event.set()
        cls._thread.join(timeout=3)
        return {"status": "stopped"}

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "running": bool(cls._thread and cls._thread.is_alive()),
            "interval_seconds": cls._interval_seconds,
            "last_run_at": cls._last_run_at.isoformat() if cls._last_run_at else None,
            "last_summary": cls._last_summary,
        }


class DashboardService:
    @staticmethod
    def summary(days: int = 7) -> dict[str, Any]:
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
    @staticmethod
    def create_search_volume(index_name: str, shards: int = 1, replicas: int = 1) -> dict[str, Any]:
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
