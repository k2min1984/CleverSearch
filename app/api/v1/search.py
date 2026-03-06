"""
########################################################
# Description
# 검색 API 라우터 (Controller)
# 클라이언트의 검색 요청을 받아 Service 계층으로 로직 위임
# - 일반 검색 (Query)
# - 자동완성 (Autocomplete)
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / DocumentUtils 방역 로직 통합 및 고도화
########################################################
"""

from fastapi import APIRouter, Query
from app.schemas.search_schema import SearchRequest
from app.services.search_service import SearchService
from app.common.utils import DocumentUtils  # [추가] 공통 방역 유틸

router = APIRouter()

@router.post("/query", summary="메인 검색 요청 처리")
async def search(req: SearchRequest):
    """
    사용자의 검색 조건(키워드, 필터 등)을 받아 검색 결과를 반환합니다.
    - DocumentUtils를 사용하여 검색어에 포함된 제어문자를 제거(방역) 후 처리합니다.
    """
    # 1. 검색어 방역 (업로드 시와 동일한 규칙 적용하여 검색 정확도 일치)
    if req.query:
        req.query = DocumentUtils.sanitize_text(req.query)
    
    # 2. 비즈니스 로직 위임 (SearchService에서 가중치 및 필터 쿼리 생성)
    return await SearchService.execute_search(req)


@router.get("/autocomplete", summary="검색어 자동완성")
async def autocomplete(q: str = Query(..., min_length=1)):
    """
    사용자가 입력 중인 키워드(Prefix)를 받아 추천 검색어를 반환합니다.
    - 입력값 방역 후 서비스를 호출합니다.
    """
    # 1. 입력 문자열 방역
    safe_q = DocumentUtils.sanitize_text(q)
    
    if not safe_q:
        return []
        
    # 2. 자동완성 로직 위임
    return await SearchService.get_autocomplete(safe_q)

@router.get("/popular", summary="실시간 인기 검색어 조회")
async def get_popular():
    """
    현재 색인된 문서들 중 가장 빈도가 높은 키워드 5개를 반환합니다.
    화면 상단의 인기 검색어 해시태그에 연동됩니다.
    """
    return await SearchService.get_popular_keywords()

@router.get("/read/{doc_id}", summary="문서 상세 조회")
async def read_document(doc_id: str):
    """
    특정 문서의 전체 본문 및 상세 정보를 조회합니다.
    """
    return await SearchService.get_document_detail(doc_id)


# ==========================================
# [수정된 부분] 뚱뚱했던 코드를 지우고 딱 1줄로 깔끔하게 처리!
# ==========================================
@router.get("/failed-analysis", summary="검색 실패 키워드 통계")
async def get_failed_analysis(days: int = 7):
    """최근 N일간 결과가 0건이었던 검색어들을 집계하여 빈도순으로 반환"""
    return await SearchService.get_failed_analysis(days)

@router.post("/setup-hybrid", summary="[관리자용] 하이브리드 벡터 DB 세팅")
async def setup_hybrid_db():
    return await SearchService.setup_hybrid_index()