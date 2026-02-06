"""
########################################################
# Description
# OpenSearch 클라이언트 연결 관리자
# SSL/TLS 설정 및 인증 처리, 클라이언트 객체 반환
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from opensearchpy import OpenSearch
from app.core.config import settings

def get_client():
    """
    OpenSearch 데이터베이스와 통신하기 위한 클라이언트 객체를 생성하여 반환합니다.
    
    Returns:
        OpenSearch: 설정된 접속 정보를 가진 클라이언트 인스턴스
    """
    client = OpenSearch(
        hosts=[settings.OPENSEARCH_URL],
        http_auth=(settings.OS_ADMIN, settings.OS_PASSWORD),
        
        # [SSL/TLS 보안 설정]
        # OpenSearch는 기본적으로 HTTPS를 강제합니다.
        use_ssl=True,
        
        # [개발/프로토타입 환경용 설정]
        # 자체 서명 인증서(Self-signed Certificate)를 사용하는 경우 인증서 검증을 건너뜁니다.
        # 실제 운영(Production) 환경에서는 유효한 인증서를 발급받고 True로 변경해야 합니다.
        verify_certs=False,       
        ssl_assert_hostname=False,
        ssl_show_warn=False,       # 콘솔에 보안 경고 로그가 너무 많이 뜨는 것을 방지
        
        # [추가 설정 - 부대표님 오더 반영]
        # 1. 대용량(7만 건 이상) 데이터 색인 시 연결 끊김 방지를 위해 타임아웃을 30초로 연장
        timeout=30,
        
        # 2. 데이터 압축 보내기: 엑셀처럼 글자가 많을 때 전송 속도를 높임
        http_compress=True,
        
        # 3. 전용 차선 10개 확보: 매번 새로 연결하지 않고 미리 뚫어놓은 통로 10개를 재사용함
        pool_maxsize=10        
    )
    return client