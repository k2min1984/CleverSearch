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

# 전역에서 import하여 사용할 수 있도록 인스턴스 생성
settings = Settings()