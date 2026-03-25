"""
########################################################
# Description
# OpenSearch 클라이언트 연결 관리자
# SSL/TLS 설정 및 인증 처리, 싱글톤 클라이언트 객체 반환
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-03-25 / 싱글톤 패턴 + http_compress 활성화
########################################################
"""

from opensearchpy import OpenSearch
from app.core.config import settings

_client = None

def get_client():
    """
    OpenSearch 클라이언트 싱글톤 반환.
    최초 호출 시 1회만 생성하고, 이후 동일 객체를 재사용합니다.
    """
    global _client
    if _client is not None:
        return _client

    _client = OpenSearch(
        hosts=[settings.OPENSEARCH_URL],
        http_auth=(settings.OS_ADMIN, settings.OS_PASSWORD),
        
        # [SSL/TLS 보안 설정]
        use_ssl=True,
        verify_certs=False,       
        ssl_assert_hostname=False,
        ssl_show_warn=False,
        
        # 대용량 데이터 색인 시 연결 끊김 방지 (30초)
        timeout=30,
        
        # 데이터 압축 전송: 네트워크 대역폭 절약 및 응답 속도 개선
        http_compress=True,
        
        # 커넥션 풀 10개 재사용
        pool_maxsize=10        
    )
    return _client