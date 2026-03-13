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
from dotenv import load_dotenv

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
    
    # OpenSearch 접속 정보
    # 주의: Docker 내부 통신 시 'localhost' 대신 서비스명(예: https://opensearch:9200)을 사용해야 할 수 있습니다.
    OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "https://localhost:9200")
    
    # 보안 인증 정보 (운영 환경에서는 반드시 강력한 비밀번호로 변경 필요)
    OS_ADMIN = os.getenv("OS_ADMIN", "admin")
    OS_PASSWORD = os.getenv("OS_PASSWORD", "Admin123!") # 대소문자+특수문자 규칙 준수 권장
    
    # 검색 엔에서 사용할 메인 인덱스 명칭 (file.py, index.py와 통일)
    OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "cleversearch-docs")

    # ------------------------------------------------------------------
    # RDB 설정 (Oracle / MySQL / PostgreSQL)
    # DB 예시: "oracle" 또는 "oracle,mysql,postgres"
    # ------------------------------------------------------------------
    DB = os.getenv("DB", "")

    # Oracle
    ORACLE_HOST = os.getenv("ORACLE_HOST", "localhost")
    ORACLE_PORT = int(os.getenv("ORACLE_PORT", "1521"))
    ORACLE_SERVICE_NAME = os.getenv("ORACLE_SERVICE_NAME", "")
    ORACLE_USER = os.getenv("ORACLE_USER", "")
    ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
    ORACLE_DSN = os.getenv("ORACLE_DSN", "")

    # MySQL
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")
    MYSQL_USER = os.getenv("MYSQL_USER", "")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

    # PostgreSQL
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# 전역에서 import하여 사용할 수 있도록 인스턴스 생성
settings = Settings()