"""
########################################################
# Description
# FastAPI 기반의 검색 엔진 메인 엔트리 포인트. 
# 라우터 등록, CORS 설정 및 정적 파일 서빙
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

# 클레버서치(CleverSearch) 내부 API 라우터 임포트
from app.api.v1 import search
from app.api.v1 import index
from app.api.v1 import file
from app.core.setup import create_index # 인덱스 초기화 함수 임포트

# --- [경로 설정 수정] 프로젝트 루트 디렉터리 찾기 ---
# main.py의 위치: .../CleverSearch/app/main.py
# dirname(main.py) -> .../CleverSearch/app
# dirname(dirname(main.py)) -> .../CleverSearch (프로젝트 루트)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR,"static")

# [클레버클라우드] 검색엔진 솔루션: CleverSearch
# FastAPI 애플리케이션 인스턴스 초기화
# Lifespan (수명 주기) 이벤트 핸들러 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션이 시작될 때 실행되는 로직입니다.
    DB 연결 확인이나 인덱스 생성 등의 초기화 작업을 수행합니다.
    """
    # 1. 앱 시작 시 실행: OpenSearch 인덱스 자동 생성
    print("🚀 [System] CleverSearch 엔진 시동 중...")
    create_index()
    
    yield  # 애플리케이션 가동 (이 시점부터 API 요청을 받음)
    
    # 2. 앱 종료 시 실행: (필요 시 리소스 해제 로직 추가)
    print("👋 [System] CleverSearch 엔진 종료")

# --- FastAPI 앱 초기화 (메타데이터 및 Lifespan 적용) ---
app = FastAPI(
    title="CleverSearch API",
    description="OpenSearch 기반의 엔터프라이즈 검색 솔루션 '클레버서치' 프로토타입 API",
    version="1.0.0",
    lifespan=lifespan  # 수명 주기 핸들러 등록
)

# --- [보안 설정] CORS(Cross-Origin Resource Sharing) 설정 ---
# 프론트엔드(React, Vue 등)와 API 서버의 포트가 다르거나 도메인이 다를 때 발생하는 접근 차단 이슈를 해결합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # 모든 도메인에서의 접근을 허용 (운영 시에는 특정 도메인으로 제한 권장)
    allow_credentials=True,        # 쿠키 및 인증 정보 포함 허용
    allow_methods=["*"],           # 모든 HTTP 메서드(GET, POST, PUT, DELETE 등) 허용
    allow_headers=["*"],           # 클라이언트에서 보내는 모든 커스텀 헤더 허용
)

# --- [리소스 설정] 정적 파일 서빙 ---
# UI 소스(HTML, CSS, JS) 및 이미지 등 정적 리소스를 외부에서 접근할 수 있도록 /static 경로에 매핑합니다.
# 예: http://localhost:8000/static/logo.png
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- [라우팅 설정] 각 기능별 API 모듈 등록 ---
# 검색 관련 API (OpenSearch 쿼리 처리)
app.include_router(search.router, prefix="/api/v1/search", tags=["Search"])

# 색인 관련 API (데이터 등록, 수정, 삭제)
app.include_router(index.router, prefix="/api/v1/index", tags=["Index"])

# 파일 처리 관련 API (첨부파일 파싱 및 업로드)
app.include_router(file.router, prefix="/api/v1/file", tags=["File"])

# --- [엔트리 포인트] 루트 경로("/") 접속 시 메인 페이지 반환 ---
@app.get("/", summary="메인 인덱스 페이지", description="클레버서치 웹 인터페이스(index.html)를 반환합니다.")
async def root():
    """
    사용자가 루트 경로 접속 시 static 폴더의 index.html을 반환합니다.
    """
    # 수정된 STATIC_DIR 경로 사용
    index_path = os.path.join(STATIC_DIR, "index.html")
    
    # 해당 경로에 파일이 실제로 존재하는지 확인 후 반환
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    # 파일이 없을 경우 에러 메시지 반환 (디버깅용)
    return {"status": "error", "message": f"UI 메인 파일을 찾을 수 없습니다: {index_path}"}