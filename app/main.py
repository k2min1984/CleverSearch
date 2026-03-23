"""
########################################################
# Description
# FastAPI 기반의 검색 엔진 메인 엔트리 포인트. 
# 라우터 등록, CORS 설정 및 정적 파일 서빙
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / 경로 설정 안정화 및 Lifespan 최적화
########################################################
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

# 내부 API 라우터 임포트
from app.api.v1 import search
from app.api.v1 import index
from app.api.v1 import file
from app.api.v1 import admin
from app.api.v1 import system
from app.api.v1 import auth
from app.core.setup import create_index # 인덱스 초기화 함수
from app.core.config import settings
from app.core.database import init_database
from app.services.system_service import IngestionSchedulerService, bootstrap_sources_from_env

# --- [경로 설정] 프로젝트 루트 디렉터리 및 정적 파일 경로 확정 ---
# os.path.abspath(__file__) -> .../app/main.py
# dirname -> .../app
# dirname(dirname) -> .../ (프로젝트 루트)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 Lifecycle 관리: 서버 시작 시와 종료 시 실행될 로직 정의
    """
    # 1. 서버 시작 시: OpenSearch 인덱스 자동 생성 및 설정 확인
    print("🚀 [System] CleverSearch 엔진 시동 중...")
    try:
        init_database()
        print("✅ [System] 업무 DB 테이블 초기화 완료")

        bootstrap_summary = bootstrap_sources_from_env(
            db_sources_json=settings.DB_SOURCES_JSON,
            smb_sources_json=settings.SMB_SOURCES_JSON,
        )
        print(f"✅ [System] 소스 부트스트랩 완료: {bootstrap_summary}")

        # [주의] setup.py의 create_index도 DocumentUtils의 매핑을 따르도록 수정되어야 함
        create_index() 
        print("✅ [System] 인덱스 설정 및 확인 완료")

        if settings.AUTO_START_INGEST_SCHEDULER:
            IngestionSchedulerService.start(settings.INGEST_SCHEDULER_INTERVAL_SECONDS)
            print("✅ [System] 자동 색인 스케줄러 시작 완료")
    except Exception as e:
        print(f"❌ [System] 인덱스 초기화 실패: {e}")
    
    yield  # 서버 가동 중 (API 요청 처리)
    
    # 2. 서버 종료 시
    IngestionSchedulerService.stop()
    print("👋 [System] CleverSearch 엔진 종료")

# --- FastAPI 인스턴스 설정 ---
app = FastAPI(
    title="CleverSearch API",
    description="OpenSearch 기반의 엔터프라이즈 통합 검색 'CleverSearch' API",
    version="1.0.0",
    lifespan=lifespan
)

# --- CORS 설정: 모든 Origin 허용 (개발 편의성) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# --- 정적 파일 서빙: /static 경로로 UI 리소스 제공 ---
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    print(f"⚠️ [Warning] 정적 파일 경로를 찾을 수 없습니다: {STATIC_DIR}")

# --- 라우터 등록 ---
app.include_router(search.router, prefix="/api/v1/search", tags=["Search"])
app.include_router(index.router, prefix="/api/v1/index", tags=["Index"])
app.include_router(file.router, prefix="/api/v1/file", tags=["File"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])

# --- 루트 경로: index.html 반환 ---
@app.get("/", summary="메인 페이지", include_in_schema=False)
async def root():
    """사용자가 접속 시 static/index.html 파일을 반환합니다."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "error", "message": "UI 메인 파일을 찾을 수 없습니다."}


@app.get("/admin", summary="관리자 페이지", include_in_schema=False)
async def admin_page():
    """관리자 목록 페이지를 반환합니다."""
    admin_path = os.path.join(STATIC_DIR, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return {"status": "error", "message": "관리자 페이지 파일을 찾을 수 없습니다."}