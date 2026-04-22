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
    FileWatcherService,
    IndexingHistoryService,
    IngestionSchedulerService,
    NetworkEventService,
    NetworkMonitorService,
    PopularConfigService,
    ScheduleService,
    ScoringConfigService,
    SMBService,
    VolumeSSLService,
)


router = APIRouter()


class SmbSourceRequest(BaseModel):
    name: str = Field(..., min_length=2)
    connection_type: str = Field(default="smb", pattern=r"^(smb|ssh)$")
    share_path: str = Field(..., min_length=1)
    username: str | None = None
    password: str | None = None
    domain: str | None = None
    port: int = Field(default=445, ge=1, le=65535)
    ssh_host: str | None = None
    ssh_key_path: str | None = None
    is_active: bool = True


class DbSourceRequest(BaseModel):
    name: str = Field(..., min_length=2)
    db_type: str = Field(..., min_length=2)
    connection_url: str = Field(..., min_length=5)
    query_text: str = Field(..., min_length=5)
    target_volume: str | None = None
    title_column: str | None = None
    chunk_size: int = Field(default=500, ge=50, le=5000)
    is_active: bool = True


class VolumeRequest(BaseModel):
    index_name: str = Field(..., min_length=2)
    shards: int = Field(default=1, ge=1, le=10)
    replicas: int = Field(default=1, ge=0, le=5)


class VolumeUpdateRequest(BaseModel):
    alias_name: str = Field(..., min_length=2)
    replicas: int = Field(default=1, ge=0, le=5)


class RenewRunRequest(BaseModel):
    script_path: str = Field(default="scripts/renew_certs.ps1", pattern=r"^scripts[\\/]+renew_certs\.ps1$")


class VolumeActiveRequest(BaseModel):
    is_active: bool = True


@router.post("/smb/sources", dependencies=[Depends(require_role("operator"))], summary="SMB/SSH 소스 등록/수정")
async def upsert_smb_source(req: SmbSourceRequest):
    return SMBService.upsert_source(
        name=req.name,
        connection_type=req.connection_type,
        share_path=req.share_path,
        username=req.username,
        password=req.password,
        domain=req.domain,
        port=req.port,
        ssh_host=req.ssh_host,
        ssh_key_path=req.ssh_key_path,
        is_active=req.is_active,
    )


@router.get("/smb/sources", dependencies=[Depends(require_role("viewer"))], summary="SMB 소스 조회")
async def list_smb_sources(active_only: bool = Query(False)):
    return SMBService.list_sources(active_only=active_only)


@router.delete("/smb/sources/{source_id}", dependencies=[Depends(require_role("operator"))], summary="SMB 소스 삭제")
async def delete_smb_source(source_id: int):
    return SMBService.delete_source(source_id=source_id)


@router.patch("/smb/sources/{source_id}/active", dependencies=[Depends(require_role("operator"))], summary="SMB 소스 활성/비활성 토글")
async def toggle_smb_source_active(source_id: int, is_active: bool = Query(...)):
    return SMBService.toggle_active(source_id=source_id, is_active=is_active)


@router.post("/smb/sources/{source_id}/sync", dependencies=[Depends(require_role("operator"))], summary="SMB 즉시 동기화")
async def sync_smb_source(source_id: int, max_files: int = Query(200, ge=1, le=2000), force_full: bool = Query(False)):
    return SMBService.sync_source(source_id=source_id, max_files=max_files, force_full=force_full)


@router.post("/smb/sources/sync-all", dependencies=[Depends(require_role("operator"))], summary="SMB 전체 즉시 동기화")
async def sync_all_smb_sources(max_files_per_source: int = Query(200, ge=1, le=2000)):
    return SMBService.sync_all_sources(max_files_per_source=max_files_per_source)


@router.post("/smb/sources/{source_id}/test", dependencies=[Depends(require_role("operator"))], summary="SMB 연결 테스트")
async def test_smb_connection(source_id: int):
    return SMBService.test_connection(source_id=source_id)


@router.get("/smb/sync-history", dependencies=[Depends(require_role("viewer"))], summary="SMB 동기화 이력 조회")
async def list_smb_sync_history(source_id: int | None = None, limit: int = Query(50, ge=1, le=500)):
    return SMBService.list_sync_history(source_id=source_id, limit=limit)


# ────────── 색인 이력 관리 ──────────

@router.get("/indexing/history", dependencies=[Depends(require_role("viewer"))], summary="색인 이력 조회")
async def list_indexing_history(
    source_type: str | None = None,
    source_name: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    return IndexingHistoryService.list_history(source_type=source_type, source_name=source_name, status=status, limit=limit)


@router.delete("/indexing/history", dependencies=[Depends(require_role("admin"))], summary="색인 이력 정리")
async def delete_indexing_history(before_days: int = Query(30, ge=1, le=365)):
    return IndexingHistoryService.delete_history(before_days=before_days)


# ────────── 네트워크 이벤트 이력 관리 ──────────

@router.get("/network/events", dependencies=[Depends(require_role("viewer"))], summary="네트워크 이벤트 이력 조회")
async def list_network_events(
    source_type: str | None = None,
    source_name: str | None = None,
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    return NetworkEventService.list_events(source_type=source_type, source_name=source_name, event_type=event_type, limit=limit)


@router.delete("/network/events", dependencies=[Depends(require_role("admin"))], summary="네트워크 이벤트 이력 정리")
async def delete_network_events(before_days: int = Query(90, ge=1, le=365)):
    return NetworkEventService.delete_events(before_days=before_days)


# ────────── 파일 워처 관리 ──────────

@router.post("/watcher/start", dependencies=[Depends(require_role("operator"))], summary="파일 변경 감지 워처 시작")
async def start_file_watcher():
    return FileWatcherService.start()


@router.post("/watcher/stop", dependencies=[Depends(require_role("operator"))], summary="파일 변경 감지 워처 중지")
async def stop_file_watcher():
    return FileWatcherService.stop()


@router.get("/watcher/status", dependencies=[Depends(require_role("viewer"))], summary="파일 변경 감지 워처 상태")
async def file_watcher_status():
    return FileWatcherService.status()


@router.post("/watcher/source/{source_id}/start", dependencies=[Depends(require_role("operator"))], summary="개별 소스 감시 시작")
async def start_source_watcher(source_id: int):
    return FileWatcherService.start_source(source_id)


@router.post("/watcher/source/{source_id}/stop", dependencies=[Depends(require_role("operator"))], summary="개별 소스 감시 중지")
async def stop_source_watcher(source_id: int):
    return FileWatcherService.stop_source(source_id)


# ────────── 네트워크 모니터 관리 ──────────

@router.post("/monitor/start", dependencies=[Depends(require_role("operator"))], summary="네트워크 모니터 시작")
async def start_network_monitor(interval_seconds: int = Query(30, ge=10, le=600)):
    return NetworkMonitorService.start(interval_seconds=interval_seconds)


@router.post("/monitor/stop", dependencies=[Depends(require_role("operator"))], summary="네트워크 모니터 중지")
async def stop_network_monitor():
    return NetworkMonitorService.stop()


@router.get("/monitor/status", dependencies=[Depends(require_role("viewer"))], summary="네트워크 모니터 상태")
async def network_monitor_status():
    return NetworkMonitorService.status()


@router.post("/db/sources", dependencies=[Depends(require_role("operator"))], summary="DB 소스 등록/수정")
async def upsert_db_source(req: DbSourceRequest):
    result = DBIngestionService.upsert_source(
        name=req.name,
        db_type=req.db_type,
        connection_url=req.connection_url,
        query_text=req.query_text,
        target_volume=req.target_volume,
        title_column=req.title_column,
        chunk_size=req.chunk_size,
        is_active=req.is_active,
    )
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "DB source upsert failed")
    return result


@router.get("/db/sources", dependencies=[Depends(require_role("viewer"))], summary="DB 소스 조회")
async def list_db_sources(active_only: bool = Query(False)):
    return DBIngestionService.list_sources(active_only=active_only)


@router.get("/db/sources/{source_id}", dependencies=[Depends(require_role("operator"))], summary="DB 소스 단건 상세 조회")
async def get_db_source(source_id: int):
    return DBIngestionService.get_source(source_id=source_id, include_secret=True)


@router.delete("/db/sources/{source_id}", dependencies=[Depends(require_role("operator"))], summary="DB 소스 삭제")
async def delete_db_source(source_id: int):
    return DBIngestionService.delete_source(source_id=source_id)


@router.patch("/db/sources/{source_id}/active", dependencies=[Depends(require_role("operator"))], summary="DB 소스 활성/비활성 토글")
async def toggle_db_source_active(source_id: int, is_active: bool = Query(...)):
    return DBIngestionService.toggle_active(source_id=source_id, is_active=is_active)


@router.post("/db/sources/{source_id}/sync", dependencies=[Depends(require_role("operator"))], summary="DB 즉시 동기화")
async def sync_db_source(source_id: int, max_rows: int = Query(3000, ge=100, le=20000)):
    result = DBIngestionService.sync_source(source_id=source_id, max_rows=max_rows)
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "DB sync failed")
    return result


@router.post("/db/sources/sync-all", dependencies=[Depends(require_role("operator"))], summary="DB 전체 즉시 동기화")
async def sync_all_db_sources(max_rows_per_source: int = Query(3000, ge=100, le=20000)):
    return DBIngestionService.sync_all_sources(max_rows_per_source=max_rows_per_source)


class DbTestConnectionRequest(BaseModel):
    connection_url: str = Field(..., min_length=5)


@router.post("/db/test-connection", dependencies=[Depends(require_role("operator"))], summary="DB 연결 테스트 (URL 직접 입력)")
async def test_db_connection_url(req: DbTestConnectionRequest):
    return DBIngestionService.test_connection_url(req.connection_url)


@router.post("/db/sources/{source_id}/test", dependencies=[Depends(require_role("operator"))], summary="DB 소스 연결 테스트")
async def test_db_source_connection(source_id: int):
    return DBIngestionService.test_connection(source_id)


@router.post("/scheduler/start", dependencies=[Depends(require_role("operator"))], summary="자동 색인 스케줄러 시작")
async def start_scheduler():
    return IngestionSchedulerService.start()


@router.post("/scheduler/stop", dependencies=[Depends(require_role("operator"))], summary="자동 색인 스케줄러 중지")
async def stop_scheduler():
    return IngestionSchedulerService.stop()


@router.get("/scheduler/status", dependencies=[Depends(require_role("viewer"))], summary="자동 색인 스케줄러 상태")
async def scheduler_status():
    return IngestionSchedulerService.status()


@router.get("/scheduler/entries", dependencies=[Depends(require_role("viewer"))], summary="스케줄 엔트리 목록")
async def list_schedule_entries():
    return ScheduleService.list_entries()


class ScheduleEntryRequest(BaseModel):
    source_type: str = Field(..., pattern=r"^(smb|db)$")
    source_id: int = Field(..., ge=1)
    interval_minutes: int = Field(1440, ge=1)
    is_enabled: bool = True


@router.put("/scheduler/entries", dependencies=[Depends(require_role("operator"))], summary="스케줄 엔트리 등록/수정")
async def upsert_schedule_entry(req: ScheduleEntryRequest):
    return ScheduleService.upsert_entry(
        source_type=req.source_type,
        source_id=req.source_id,
        interval_minutes=req.interval_minutes,
        is_enabled=req.is_enabled,
    )


@router.delete("/scheduler/entries/{entry_id}", dependencies=[Depends(require_role("operator"))], summary="스케줄 엔트리 삭제")
async def delete_schedule_entry(entry_id: int):
    return ScheduleService.delete_entry(entry_id)


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


@router.delete("/dictionary/entry/{entry_id}", dependencies=[Depends(require_role("operator"))], summary="사전 항목 삭제")
async def delete_dictionary_entry(entry_id: int):
    return DictionaryService.delete_entry(entry_id=entry_id)


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
    result = VolumeSSLService.create_search_volume(req.index_name, shards=req.shards, replicas=req.replicas)
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "volume creation failed")
    return result


@router.get("/volume/list", dependencies=[Depends(require_role("viewer"))], summary="검색 볼륨 목록 조회")
async def list_search_volumes(active_only: bool = Query(False)):
    return VolumeSSLService.list_volumes(active_only=active_only)


@router.post("/volume/{volume_id}/active", dependencies=[Depends(require_role("admin"))], summary="검색 볼륨 사용여부 변경")
async def set_search_volume_active(volume_id: int, req: VolumeActiveRequest):
    result = VolumeSSLService.set_volume_active(volume_id=volume_id, is_active=req.is_active)
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "volume status change failed")
    return result


@router.put("/volume/{volume_id}", dependencies=[Depends(require_role("admin"))], summary="검색 볼륨 설정 수정(alias/replicas)")
async def update_search_volume(volume_id: int, req: VolumeUpdateRequest):
    result = VolumeSSLService.update_volume(volume_id=volume_id, alias_name=req.alias_name, replicas=req.replicas)
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "volume update failed")
    return result


@router.delete("/volume/{volume_id}", dependencies=[Depends(require_role("admin"))], summary="검색 볼륨 삭제")
async def delete_search_volume(volume_id: int):
    result = VolumeSSLService.delete_volume(volume_id=volume_id)
    if isinstance(result, dict) and result.get("status") == "fail":
        raise HTTPException(status_code=400, detail=result.get("message") or "volume delete failed")
    return result


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


# ────────── 인기검색 표시 설정 관리 ──────────

class PopularSettingsRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=365)
    limit: int = Field(..., ge=1, le=9)


@router.get("/popular/settings", dependencies=[Depends(require_role("viewer"))], summary="인기검색 표시 설정 조회")
async def get_popular_settings():
    return PopularConfigService.get_settings()


@router.put("/popular/settings", dependencies=[Depends(require_role("operator"))], summary="인기검색 표시 설정 저장")
async def update_popular_settings(req: PopularSettingsRequest):
    return PopularConfigService.update_settings(req.model_dump())


# ────────── 검색 가중치 관리 ──────────

class ScoringWeightsRequest(BaseModel):
    title_phrase: float = Field(default=20, ge=0, le=100)
    title_and: float = Field(default=10, ge=0, le=100)
    content_phrase: float = Field(default=5, ge=0, le=100)
    content_and: float = Field(default=1, ge=0, le=100)
    vector: float = Field(default=1.0, ge=0, le=50)
    chosung: float = Field(default=10, ge=0, le=100)
    min_score: float = Field(default=0.0058, ge=0, le=10)


class EvaluateRequest(BaseModel):
    test_cases: list[dict] = Field(
        ...,
        min_length=1,
        description="[{query, expected_title}]",
    )


@router.get("/scoring/weights", dependencies=[Depends(require_role("viewer"))], summary="검색 가중치 조회")
async def get_scoring_weights():
    return ScoringConfigService.get_weights()


@router.put("/scoring/weights", dependencies=[Depends(require_role("operator"))], summary="검색 가중치 수정")
async def update_scoring_weights(req: ScoringWeightsRequest):
    return ScoringConfigService.update_weights(req.model_dump())


@router.post("/scoring/reset", dependencies=[Depends(require_role("admin"))], summary="검색 가중치 초기화")
async def reset_scoring_weights():
    return ScoringConfigService.reset_weights()


@router.post("/scoring/evaluate", dependencies=[Depends(require_role("operator"))], summary="검색 품질 평가")
async def evaluate_search_quality(req: EvaluateRequest):
    return await ScoringConfigService.evaluate_quality(req.test_cases)
