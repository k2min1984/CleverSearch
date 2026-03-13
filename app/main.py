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
from app.core.setup import create_index # 인덱스 초기화 함수
from app.utils.db import create_selected_db_connections, close_db_connections

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
        # [주의] setup.py의 create_index도 DocumentUtils의 매핑을 따르도록 수정되어야 함
        create_index() 
        print("✅ [System] 인덱스 설정 및 확인 완료")
    except Exception as e:
        print(f"❌ [System] 인덱스 초기화 실패: {e}")

    app.state.db_connections = {}
    try:
        app.state.db_connections = create_selected_db_connections()
        if app.state.db_connections:
            db_names = ", ".join(app.state.db_connections.keys())
            print(f"✅ [System] DB 연결 완료: {db_names}")
        else:
            print("ℹ️ [System] 활성화된 RDB 연결이 없습니다. (.env의 DB 설정 확인)")
    except Exception as e:
        print(f"❌ [System] DB 연결 초기화 실패: {e}")
        raise
    
    yield  # 서버 가동 중 (API 요청 처리)
    
    # 2. 서버 종료 시
    close_db_connections(getattr(app.state, "db_connections", {}))
    print("👋 [System] CleverSearch 엔진 종료")

# --- FastAPI 인스턴스 설정 ---
app = FastAPI(
    title="CleverSearch API",
    description="OpenSearch 기반의 엔터프라이즈 통합 검색 'HanSeek' API",
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

# --- 루트 경로: index.html 반환 ---
@app.get("/", summary="메인 페이지", include_in_schema=False)
async def root():
    """사용자가 접속 시 static/index.html 파일을 반환합니다."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "error", "message": "UI 메인 파일을 찾을 수 없습니다."}