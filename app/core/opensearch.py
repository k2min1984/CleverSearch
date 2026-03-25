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
from threading import Lock
from app.core.config import settings

_client = None
_client_lock = Lock()

def get_client():
    """
    OpenSearch 클라이언트 싱글톤 반환.
    최초 호출 시 1회만 생성하고, 이후 동일 객체를 재사용합니다.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        _client = OpenSearch(
            hosts=[settings.OPENSEARCH_URL],
            http_auth=(settings.OS_ADMIN, settings.OS_PASSWORD),

            # [SSL/TLS 보안 설정]
            use_ssl=settings.OPENSEARCH_USE_SSL,
            verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
            ssl_assert_hostname=settings.OPENSEARCH_SSL_ASSERT_HOSTNAME,
            ssl_show_warn=settings.OPENSEARCH_SSL_SHOW_WARN,

            # 네트워크/타임아웃/재시도 정책
            timeout=settings.OPENSEARCH_TIMEOUT_SECONDS,
            max_retries=settings.OPENSEARCH_MAX_RETRIES,
            retry_on_timeout=settings.OPENSEARCH_RETRY_ON_TIMEOUT,

            # 전송 최적화 및 커넥션 풀
            http_compress=settings.OPENSEARCH_HTTP_COMPRESS,
            pool_maxsize=settings.OPENSEARCH_POOL_MAXSIZE
        )
    return _client