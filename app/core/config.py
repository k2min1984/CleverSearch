"""
########################################################
# Description
# 솔루션 전역 환경 설정 관리 (Configuration)
# .env 파일 로드 및 환경 변수 매핑, 기본값 설정
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv


def _get_bool_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _get_csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

# .env 파일이 존재할 경우 내용을 로드하여 환경 변수로 설정합니다.
# Docker Compose 사용 시에는 docker-compose.yml의 environment 설정이 우선순위를 가집니다.
load_dotenv()

class Settings:
    """
    애플리케이션의 모든 설정을 관리하는 클래스입니다.
    os.getenv("KEY", "Default Value") 패턴을 사용하여,
    환경 변수가 없을 경우 안전하게 기본값으로 구동되도록 설계되었습니다.
    """
    
    # 솔루션 명칭 변경: HanSeek -> CleverSearch
    PROJECT_NAME = os.getenv("PROJECT_NAME", "CleverSearch")
    APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()

    # 민감 정보 암호화 키 (운영 환경에서는 반드시 변경 필요)
    CREDENTIAL_SECRET = os.getenv("CREDENTIAL_SECRET", "change-this-credential-secret-in-production")
    
    # OpenSearch 접속 정보
    # 주의: Docker 내부 통신 시 'localhost' 대신 서비스명(예: https://opensearch:9200)을 사용해야 할 수 있습니다.
    OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "https://localhost:9200")
    
    # 보안 인증 정보 (운영 환경에서는 반드시 강력한 비밀번호로 변경 필요)
    OS_ADMIN = os.getenv("OS_ADMIN", "admin")
    OS_PASSWORD = os.getenv("OS_PASSWORD", "Admin123!") # 대소문자+특수문자 규칙 준수 권장
    
    # 검색 엔에서 사용할 메인 인덱스 명칭 (file.py, index.py와 통일)
    OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "cleversearch-docs")

    # OpenSearch 클라이언트 운영 옵션
    OPENSEARCH_USE_SSL = _get_bool_env("OPENSEARCH_USE_SSL", "true")
    OPENSEARCH_VERIFY_CERTS = _get_bool_env("OPENSEARCH_VERIFY_CERTS", "false")
    OPENSEARCH_SSL_ASSERT_HOSTNAME = _get_bool_env("OPENSEARCH_SSL_ASSERT_HOSTNAME", "false")
    OPENSEARCH_SSL_SHOW_WARN = _get_bool_env("OPENSEARCH_SSL_SHOW_WARN", "false")
    OPENSEARCH_TIMEOUT_SECONDS = int(os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "30"))
    OPENSEARCH_HTTP_COMPRESS = _get_bool_env("OPENSEARCH_HTTP_COMPRESS", "true")
    OPENSEARCH_POOL_MAXSIZE = int(os.getenv("OPENSEARCH_POOL_MAXSIZE", "25"))
    OPENSEARCH_MAX_RETRIES = int(os.getenv("OPENSEARCH_MAX_RETRIES", "2"))
    OPENSEARCH_RETRY_ON_TIMEOUT = _get_bool_env("OPENSEARCH_RETRY_ON_TIMEOUT", "true")

    # ── 업무 데이터 저장용 DB 설정 ──────────────────────────────
    # DB_TYPE: postgres / mysql / mariadb / oracle 중 선택
    DB_TYPE = os.getenv("DB_TYPE", "postgres").strip().lower()

    # 개별 접속 정보 (DATABASE_URL 미지정 시 이 값으로 자동 조립)
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "")          # 빈 값이면 DB_TYPE별 기본 포트 사용
    DB_NAME = os.getenv("DB_NAME", "cleversearch")
    DB_USER = os.getenv("DB_USER", "cleversearch")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "cleversearch123")

    # Oracle 전용: SID 대신 서비스명 사용 시 True
    DB_ORACLE_USE_SERVICE_NAME = _get_bool_env("DB_ORACLE_USE_SERVICE_NAME", "false")

    # DB_TYPE → SQLAlchemy dialect+driver 매핑
    _DB_DIALECTS: dict[str, str] = {
        "postgres": "postgresql+psycopg2",
        "mysql": "mysql+pymysql",
        "mariadb": "mariadb+pymysql",
        "oracle": "oracle+oracledb",
    }
    _DB_DEFAULT_PORTS: dict[str, str] = {
        "postgres": "5432",
        "mysql": "3306",
        "mariadb": "3306",
        "oracle": "1521",
    }

    @classmethod
    def _build_database_url(cls) -> str:
        """DB_TYPE + 개별 접속 정보로 DATABASE_URL을 자동 조립합니다."""
        dialect = cls._DB_DIALECTS.get(cls.DB_TYPE)
        if dialect is None:
            raise ValueError(
                f"지원하지 않는 DB_TYPE: '{cls.DB_TYPE}'. "
                f"허용 값: {', '.join(cls._DB_DIALECTS)}"
            )
        port = cls.DB_PORT or cls._DB_DEFAULT_PORTS[cls.DB_TYPE]
        # 유저명/비밀번호에 @, !, # 등 특수문자가 포함될 수 있으므로 URL 인코딩
        safe_user = quote_plus(cls.DB_USER)
        safe_password = quote_plus(cls.DB_PASSWORD)

        if cls.DB_TYPE == "oracle":
            if cls.DB_ORACLE_USE_SERVICE_NAME:
                dsn = f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={cls.DB_HOST})(PORT={port}))(CONNECT_DATA=(SERVICE_NAME={cls.DB_NAME})))"
                return f"{dialect}://{safe_user}:{safe_password}@{dsn}"
            return f"{dialect}://{safe_user}:{safe_password}@{cls.DB_HOST}:{port}/{cls.DB_NAME}"

        charset_param = ""
        if cls.DB_TYPE in ("mysql", "mariadb"):
            charset_param = "?charset=utf8mb4"

        return f"{dialect}://{safe_user}:{safe_password}@{cls.DB_HOST}:{port}/{cls.DB_NAME}{charset_param}"

    # DATABASE_URL 환경변수가 직접 지정되면 그대로 사용, 아니면 자동 조립
    DATABASE_URL: str = os.getenv("DATABASE_URL") or ""

    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_RECYCLE_SECONDS = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))

    # 스케줄러 기본 동작 주기(초)
    INGEST_SCHEDULER_INTERVAL_SECONDS = int(os.getenv("INGEST_SCHEDULER_INTERVAL_SECONDS", "120"))
    AUTO_START_INGEST_SCHEDULER = os.getenv("AUTO_START_INGEST_SCHEDULER", "false").lower() == "true"

    # 인증서 상태 확인 기본 경로
    CERT_DIR = os.getenv("CERT_DIR", "cert")

    # 선택 설정: 다중 DB/SMB 사전 등록 JSON 문자열
    DB_SOURCES_JSON = os.getenv("DB_SOURCES_JSON", "")
    SMB_SOURCES_JSON = os.getenv("SMB_SOURCES_JSON", "")

    # JWT 인증 설정
    JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production-at-least-32-chars")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    JWT_REFRESH_EXPIRE_MINUTES = int(os.getenv("JWT_REFRESH_EXPIRE_MINUTES", "1440"))

    # API/웹 보안 설정
    CORS_ALLOWED_ORIGINS = _get_csv_env(
        "CORS_ALLOWED_ORIGINS",
        "https://localhost:8443,http://localhost:8443,https://127.0.0.1:8443,http://127.0.0.1:8443",
    )
    ALLOWED_HOSTS = _get_csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1")
    ENABLE_API_DOCS = _get_bool_env(
        "ENABLE_API_DOCS",
        "true" if APP_ENV in {"dev", "local", "test"} else "false",
    )
    ENABLE_SECURITY_HEADERS = _get_bool_env("ENABLE_SECURITY_HEADERS", "true")

    # 인증 시도 제한(브루트포스 완화)
    AUTH_RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_MAX_ATTEMPTS", "5"))
    AUTH_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "300"))
    AUTH_RATE_LIMIT_BLOCK_SECONDS = int(os.getenv("AUTH_RATE_LIMIT_BLOCK_SECONDS", "900"))

# 전역에서 import하여 사용할 수 있도록 인스턴스 생성
settings = Settings()
# DATABASE_URL 환경변수가 없으면 DB_TYPE + 개별 접속 정보로 자동 조립
if not settings.DATABASE_URL:
    settings.DATABASE_URL = Settings._build_database_url()