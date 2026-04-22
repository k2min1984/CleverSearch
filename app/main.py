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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
import os

# 내부 API 라우터 임포트 (역할별 폴더 분리)
from app.api.user import search as user_search
from app.api.user import file as user_file
from app.api.admin import dashboard as admin_dashboard
from app.api.admin import system as admin_system
from app.api.admin import index as admin_index
from app.api.common import auth as common_auth

# [하위 호환] 기존 v1 라우터도 유지 (점진 마이그레이션용)
from app.api.v1 import search, index, file, admin, system, auth
from app.core.setup import create_index # 인덱스 초기화 함수
from app.core.config import settings
from app.core.database import init_database
from app.services.system_service import FileWatcherService, IngestionSchedulerService, NetworkMonitorService, bootstrap_sources_from_env

# --- [경로 설정] 프로젝트 루트 디렉터리 및 정적 파일 경로 확정 ---
# os.path.abspath(__file__) -> .../app/main.py
# dirname -> .../app
# dirname(dirname) -> .../ (프로젝트 루트)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def _startup_log(level: str, step: str, message: str, action: str = "") -> None:
    line = f"[STARTUP][{level}][{step}] {message}"
    if action:
        line += f" | 조치: {action}"
    print(line)


def _startup_action_guide(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()

    if "인증 실패(401)" in text or "authenticationexception" in lowered or "401" in lowered:
        return "OS_ADMIN/OS_PASSWORD를 OpenSearch 실제 계정과 일치시키고 앱을 재기동하세요."
    if "권한 부족(403)" in text or "authorizationexception" in lowered or "403" in lowered:
        return "인덱스 조회/생성 권한이 있는 계정으로 교체하거나 권한을 부여하세요."
    if "tls" in lowered or "ssl" in lowered or "인증서" in text:
        return "인증서 체인과 VERIFY_CERTS 설정을 점검하고 신뢰된 인증서를 적용하세요."
    if "연결 실패" in text or "connection" in lowered:
        return "OpenSearch 서비스 상태, URL/포트, 방화벽 정책을 확인하세요."
    if "[보안 설정 오류]" in text:
        return "운영 필수 환경변수(APP_ENV/JWT_SECRET/CORS/HOST/VERIFY_CERTS)를 교정하세요."
    return "직전 STARTUP 로그의 실패 단계를 기준으로 환경변수/네트워크/권한을 점검하세요."


def _validate_production_security() -> None:
    if settings.APP_ENV not in {"prod", "production"}:
        return

    violations = []
    if settings.JWT_SECRET == "change-this-in-production-at-least-32-chars" or len(settings.JWT_SECRET) < 32:
        violations.append("JWT_SECRET 은 운영에서 32자 이상 강력한 값으로 설정해야 합니다.")
    if settings.OS_PASSWORD.lower() in {"admin", "admin123!", "changeme"}:
        violations.append("OS_PASSWORD 가 기본값/약한 값입니다. 운영용 비밀번호로 교체하세요.")
    if "*" in settings.CORS_ALLOWED_ORIGINS:
        violations.append("CORS_ALLOWED_ORIGINS 에 '*' 사용 금지 (운영).")
    if settings.ENABLE_API_DOCS:
        violations.append("운영에서는 ENABLE_API_DOCS=false 권장/필수입니다.")
    if not settings.OPENSEARCH_VERIFY_CERTS:
        violations.append("운영에서는 OPENSEARCH_VERIFY_CERTS=true 로 TLS 검증을 활성화해야 합니다.")

    if violations:
        raise RuntimeError("[보안 설정 오류] " + " | ".join(violations))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 Lifecycle 관리: 서버 시작 시와 종료 시 실행될 로직 정의
    """
    # 1. 서버 시작 시: OpenSearch 인덱스 자동 생성 및 설정 확인
    _startup_log("INFO", "BOOT", "CleverSearch 시작", f"env={settings.APP_ENV}")
    strict_startup = settings.APP_ENV in {"prod", "production"}
    try:
        _startup_log("INFO", "SECURITY", "운영 보안 정책 점검 시작")
        _validate_production_security()
        _startup_log("PASS", "SECURITY", "운영 보안 정책 점검 통과")

        _startup_log("INFO", "DATABASE", "업무 DB 초기화 시작")
        init_database()
        _startup_log("PASS", "DATABASE", "업무 DB 초기화 완료")

        _startup_log("INFO", "BOOTSTRAP", "외부 소스 부트스트랩 시작")
        bootstrap_summary = bootstrap_sources_from_env(
            db_sources_json=settings.DB_SOURCES_JSON,
            smb_sources_json=settings.SMB_SOURCES_JSON,
        )
        _startup_log("PASS", "BOOTSTRAP", f"외부 소스 부트스트랩 완료: {bootstrap_summary}")

        # [주의] setup.py의 create_index도 DocumentUtils의 매핑을 따르도록 수정되어야 함
        _startup_log("INFO", "OPENSEARCH", "인덱스 초기화/검증 시작")
        create_index()
        _startup_log("PASS", "OPENSEARCH", "인덱스 초기화/검증 완료")

        if settings.AUTO_START_INGEST_SCHEDULER:
            _startup_log("INFO", "SCHEDULER", "자동 색인 스케줄러 시작")
            IngestionSchedulerService.start(settings.INGEST_SCHEDULER_INTERVAL_SECONDS)
            _startup_log("PASS", "SCHEDULER", "자동 색인 스케줄러 시작 완료")
        else:
            _startup_log("INFO", "SCHEDULER", "자동 색인 스케줄러 비활성화 상태")

        # 네트워크 모니터 자동 시작 (DB/OpenSearch 연결 감시)
        NetworkMonitorService.start(interval_seconds=30)
        _startup_log("PASS", "NETWORK", "네트워크 모니터 시작 완료")

        _startup_log("PASS", "READY", "서비스 기동 준비 완료")
    except Exception as e:
        action = _startup_action_guide(e)
        _startup_log("FAIL", "STARTUP", f"시작 점검 실패: {e}", action)
        if strict_startup:
            raise RuntimeError("운영 환경 시작 차단: OpenSearch/인덱스 초기화 실패") from e
        _startup_log("WARN", "DEV-MODE", "개발 환경이므로 서버는 계속 기동합니다")
    
    yield  # 서버 가동 중 (API 요청 처리)
    
    # 2. 서버 종료 시
    FileWatcherService.stop()
    NetworkMonitorService.stop()
    IngestionSchedulerService.stop()
    _startup_log("INFO", "SHUTDOWN", "CleverSearch 종료")

# --- FastAPI 인스턴스 설정 ---
app = FastAPI(
    title="CleverSearch API",
    description="OpenSearch 기반의 엔터프라이즈 통합 검색 'CleverSearch' API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

# --- CORS 설정: 허용 Origin 화이트리스트 기반 ---
allow_credentials = True
if "*" in settings.CORS_ALLOWED_ORIGINS:
    # CORS 표준상 '*' + credentials 조합은 허용되지 않습니다.
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

allowed_hosts = list(settings.ALLOWED_HOSTS or [])
if settings.APP_ENV in {"dev", "test", "local"} and "testserver" not in allowed_hosts:
    allowed_hosts.append("testserver")

if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Swagger/ReDoc 경로는 cdn.jsdelivr.net 리소스가 필요하므로 별도 CSP 적용
    _docs_paths = ("/docs", "/redoc", "/openapi.json")
    if settings.ENABLE_SECURITY_HEADERS:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if request.url.path in _docs_paths:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none';",
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
                "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' https:; "
                "frame-ancestors 'none';",
            )
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# --- 정적 파일 서빙: /static 경로로 UI 리소스 제공 ---
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    print(f"⚠️ [Warning] 정적 파일 경로를 찾을 수 없습니다: {STATIC_DIR}")

# --- 라우터 등록 (새 구조: 역할별 분리) ---
# 사용자 API
app.include_router(user_search.router, prefix="/api/v1/user/search", tags=["User-Search"])
app.include_router(user_file.router, prefix="/api/v1/user/file", tags=["User-File"])
# 관리자 API
app.include_router(admin_dashboard.router, prefix="/api/v1/admin", tags=["Admin-Dashboard"])
app.include_router(admin_system.router, prefix="/api/v1/admin/system", tags=["Admin-System"])
app.include_router(admin_index.router, prefix="/api/v1/admin/index", tags=["Admin-Index"])
# 공통 API
app.include_router(common_auth.router, prefix="/api/v1/common/auth", tags=["Common-Auth"])

# --- [하위 호환] 기존 /api/v1/ 경로 유지 (프론트 점진 전환용) ---
app.include_router(search.router, prefix="/api/v1/search", tags=["Search (Legacy)"])
app.include_router(index.router, prefix="/api/v1/index", tags=["Index (Legacy)"])
app.include_router(file.router, prefix="/api/v1/file", tags=["File (Legacy)"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin (Legacy)"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System (Legacy)"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth (Legacy)"])

# --- 루트 경로: 사용자 페이지 반환 ---
@app.get("/", summary="메인 페이지", include_in_schema=False)
async def root():
    """사용자가 접속 시 static/user/index.html 파일을 반환합니다."""
    # 새 경로 우선, 없으면 기존 경로 폴백
    new_path = os.path.join(STATIC_DIR, "user", "index.html")
    legacy_path = os.path.join(STATIC_DIR, "index.html")
    for p in [new_path, legacy_path]:
        if os.path.exists(p):
            return FileResponse(p)
    return {"status": "error", "message": "UI 메인 파일을 찾을 수 없습니다."}


@app.get("/admin", summary="관리자 페이지", include_in_schema=False)
async def admin_page():
    """관리자 페이지를 반환합니다."""
    admin_path = os.path.join(STATIC_DIR, "admin", "index.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return {"status": "error", "message": "관리자 페이지 파일을 찾을 수 없습니다."}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """브라우저 자동 favicon 요청 처리 (404 로그 방지)."""
    favicon_path = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe():
    """Chrome DevTools의 자동 probe 요청을 무응답(204) 처리."""
    return Response(status_code=204)