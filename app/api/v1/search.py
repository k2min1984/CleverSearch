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
########################################################
"""

from fastapi import APIRouter
from app.schemas.search_schema import SearchRequest
from app.services.search_service import SearchService

router = APIRouter()

@router.post("/query", summary="메인 검색 요청 처리")
async def search(req: SearchRequest):
    """
    사용자의 검색 조건(키워드, 필터 등)을 받아 검색 결과를 반환합니다.
    Args: req (SearchRequest): 검색어 및 필터 조건이 담긴 DTO(Data Transfer Object)
    Returns: dict: OpenSearch 검색 결과 및 하이라이팅 정보
    """
    # 실제 검색 비즈니스 로직은 Service 계층에서 처리하여 유지보수성을 높입니다.
    return await SearchService.execute_search(req)


@router.get("/autocomplete", summary="검색어 자동완성")
async def autocomplete(q: str):
    """
    사용자가 검색창에 입력 중인 키워드(Prefix)를 받아 추천 검색어를 반환합니다.
    Args: q (str): 사용자가 현재 입력 중인 검색어
    Returns: list: 연관된 추천 검색어 리스트
    """
    # 빠르고 가벼운 쿼리 처리를 위해 별도의 서비스 메서드 호출
    return await SearchService.get_autocomplete(q)