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
from opensearchpy.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConnectionError as OpenSearchConnectionError,
    SSLError as OpenSearchSSLError,
)
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


def validate_opensearch_connection() -> None:
    """
    OpenSearch 인증/연결 상태를 시작 단계에서 명확히 검증합니다.
    실패 시 원인별 안내가 담긴 RuntimeError를 발생시킵니다.
    """
    client = get_client()
    try:
        if not client.ping():
            raise RuntimeError(
                "OpenSearch ping 실패: URL/네트워크/TLS 설정을 확인하세요. "
                "(OPENSEARCH_URL, OPENSEARCH_USE_SSL, OPENSEARCH_VERIFY_CERTS)"
            )
        client.info()
    except AuthenticationException as exc:
        raise RuntimeError(
            "OpenSearch 인증 실패(401): OS_ADMIN/OS_PASSWORD가 OpenSearch 계정과 일치하지 않습니다. "
            "환경변수 또는 .env 설정을 확인하세요."
        ) from exc
    except AuthorizationException as exc:
        raise RuntimeError(
            "OpenSearch 권한 부족(403): 계정 권한으로 인덱스 조회/생성이 불가능합니다."
        ) from exc
    except OpenSearchSSLError as exc:
        raise RuntimeError(
            "OpenSearch TLS/인증서 검증 실패: 인증서 신뢰체인 또는 VERIFY_CERTS 설정을 확인하세요."
        ) from exc
    except OpenSearchConnectionError as exc:
        raise RuntimeError(
            "OpenSearch 연결 실패: 서비스 기동 상태, URL, 포트, 방화벽을 확인하세요."
        ) from exc