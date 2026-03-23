"""
########################################################
# Description
# 시스템 관리 API 라우터
# 운영에 필요한 관리 기능을 REST API로 제공
# - 사전 관리 (동의어/불용어/사용자사전 CRUD)
# - 대시보드 통계 (검색 로그 추이, 인기 키워드)
# - SMB/DB 외부 데이터 수집 소스 관리
# - 자동 색인 스케줄러 (시작/중지/상태)
# - SSL 인증서 상태 조회 및 갱신
# - 볼륨(인덱스) 생성
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.core.security import require_role
from app.services.dictionary_service import DictionaryService
from app.services.system_service import (
    DBIngestionService,
    DashboardService,
    IngestionSchedulerService,
    SMBService,
    VolumeSSLService,
)


router = APIRouter()


class SmbSourceRequest(BaseModel):
    name: str = Field(..., min_length=2)
    share_path: str = Field(..., min_length=3)
    username: str | None = None
    password: str | None = None
    is_active: bool = True


class DbSourceRequest(BaseModel):
    name: str = Field(..., min_length=2)
    db_type: str = Field(..., min_length=2)
    connection_url: str = Field(..., min_length=5)
    query_text: str = Field(..., min_length=5)
    title_column: str | None = None
    chunk_size: int = Field(default=500, ge=50, le=5000)
    is_active: bool = True


class VolumeRequest(BaseModel):
    index_name: str = Field(..., min_length=2)
    shards: int = Field(default=1, ge=1, le=10)
    replicas: int = Field(default=1, ge=0, le=5)


class RenewRunRequest(BaseModel):
    script_path: str = Field(default="scripts/renew_certs.ps1")


@router.post("/smb/sources", dependencies=[Depends(require_role("operator"))], summary="SMB 소스 등록/수정")
async def upsert_smb_source(req: SmbSourceRequest):
    return SMBService.upsert_source(
        name=req.name,
        share_path=req.share_path,
        username=req.username,
        password=req.password,
        is_active=req.is_active,
    )


@router.get("/smb/sources", dependencies=[Depends(require_role("viewer"))], summary="SMB 소스 조회")
async def list_smb_sources(active_only: bool = Query(False)):
    return SMBService.list_sources(active_only=active_only)


@router.post("/smb/sources/{source_id}/sync", dependencies=[Depends(require_role("operator"))], summary="SMB 즉시 동기화")
async def sync_smb_source(source_id: int, max_files: int = Query(200, ge=1, le=2000)):
    return SMBService.sync_source(source_id=source_id, max_files=max_files)


@router.post("/db/sources", dependencies=[Depends(require_role("operator"))], summary="DB 소스 등록/수정")
async def upsert_db_source(req: DbSourceRequest):
    return DBIngestionService.upsert_source(
        name=req.name,
        db_type=req.db_type,
        connection_url=req.connection_url,
        query_text=req.query_text,
        title_column=req.title_column,
        chunk_size=req.chunk_size,
        is_active=req.is_active,
    )


@router.get("/db/sources", dependencies=[Depends(require_role("viewer"))], summary="DB 소스 조회")
async def list_db_sources(active_only: bool = Query(False)):
    return DBIngestionService.list_sources(active_only=active_only)


@router.post("/db/sources/{source_id}/sync", dependencies=[Depends(require_role("operator"))], summary="DB 즉시 동기화")
async def sync_db_source(source_id: int, max_rows: int = Query(3000, ge=100, le=20000)):
    return DBIngestionService.sync_source(source_id=source_id, max_rows=max_rows)


@router.post("/scheduler/start", dependencies=[Depends(require_role("operator"))], summary="자동 색인 스케줄러 시작")
async def start_scheduler(interval_seconds: int = Query(120, ge=10, le=3600)):
    return IngestionSchedulerService.start(interval_seconds=interval_seconds)


@router.post("/scheduler/stop", dependencies=[Depends(require_role("operator"))], summary="자동 색인 스케줄러 중지")
async def stop_scheduler():
    return IngestionSchedulerService.stop()


@router.get("/scheduler/status", dependencies=[Depends(require_role("viewer"))], summary="자동 색인 스케줄러 상태")
async def scheduler_status():
    return IngestionSchedulerService.status()


@router.post("/dictionary/upload", dependencies=[Depends(require_role("operator"))], summary="사전 엑셀 업로드")
async def upload_dictionary_excel(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    counts = DictionaryService.ingest_excel(tmp_path)
    return {"status": "success", "counts": counts}


@router.post("/dictionary/entry", dependencies=[Depends(require_role("operator"))], summary="사전 단건 업서트")
async def upsert_dictionary_entry(dict_type: str, term: str, replacement: str | None = None, is_active: bool = True):
    try:
        return DictionaryService.upsert_entry(dict_type=dict_type, term=term, replacement=replacement, is_active=is_active)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dictionary/entries", dependencies=[Depends(require_role("viewer"))], summary="사전 조회")
async def list_dictionary_entries(dict_type: str | None = None, active_only: bool = True):
    return DictionaryService.list_entries(dict_type=dict_type, active_only=active_only)


@router.get("/dashboard/summary", dependencies=[Depends(require_role("viewer"))], summary="대시보드 요약 지표")
async def dashboard_summary(days: int = Query(7, ge=1, le=365)):
    return DashboardService.summary(days=days)


@router.get("/dashboard/trend", dependencies=[Depends(require_role("viewer"))], summary="대시보드 추이")
async def dashboard_trend(days: int = Query(14, ge=1, le=365)):
    return DashboardService.trend(days=days)


@router.get("/health/overview", dependencies=[Depends(require_role("viewer"))], summary="운영 상태 요약")
async def health_overview():
    return DashboardService.health_overview()


@router.get("/dashboard/alerts", dependencies=[Depends(require_role("viewer"))], summary="운영 알림 배지")
async def dashboard_alert_badges(
    cert_warn_days: int = Query(7, ge=1, le=30),
    spike_ratio: float = Query(1.5, ge=1.1, le=5.0),
):
    return DashboardService.alert_badges(cert_warn_days=cert_warn_days, spike_ratio=spike_ratio)


@router.post("/volume/create", dependencies=[Depends(require_role("admin"))], summary="검색 볼륨(인덱스) 생성")
async def create_search_volume(req: VolumeRequest):
    return VolumeSSLService.create_search_volume(req.index_name, shards=req.shards, replicas=req.replicas)


@router.get("/ssl/certificates", dependencies=[Depends(require_role("viewer"))], summary="인증서 상태 조회")
async def get_cert_status(cert_dir: str = Query("cert"), warn_days: int = Query(30, ge=1, le=180)):
    return VolumeSSLService.scan_certificates(cert_dir=cert_dir, warn_days=warn_days)


@router.post("/ssl/renew-script", dependencies=[Depends(require_role("admin"))], summary="인증서 갱신 스크립트 생성")
async def generate_renew_script(output_path: str = Query("scripts/renew_certs.ps1")):
    return VolumeSSLService.generate_renew_script(output_path=output_path)


@router.post("/ssl/renew-run", dependencies=[Depends(require_role("admin"))], summary="인증서 갱신 스크립트 실행")
async def run_renew_script(req: RenewRunRequest):
    return VolumeSSLService.execute_renew_script(script_path=req.script_path)


@router.post("/ops/run-smoke-test", dependencies=[Depends(require_role("admin"))], summary="시스템 스모크 테스트 실행")
async def run_system_smoke_test():
    proc = subprocess.run(
        [sys.executable, "scripts/run_system_smoke_tests.py"],
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
