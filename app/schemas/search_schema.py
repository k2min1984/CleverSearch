"""
########################################################
# Description
# 검색 요청 파라미터 정의 및 검증 스키마 (DTO)
# Pydantic을 활용한 입력 데이터 유효성 검사 및 문서화
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from pydantic import BaseModel, Field
from typing import Optional, List

class SearchRequest(BaseModel):
    """
    [CleverSearch] 메인 검색 요청 모델
    프론트엔드에서 전달되는 검색 조건들을 정의하고 검증합니다.
    """
    
    # 1. 필수 검색어
    # Field(...)는 필수 항목임을 의미하며, API 문서에 설명을 추가합니다.
    query: str = Field(
        ..., 
        title="검색어",
        description="사용자가 입력한 메인 검색 키워드", 
        example="인공지능"
    )

    # 2. 상세 필터링 (포함/제외 키워드)
    # 기본값을 빈 리스트 []로 설정하여 선택적으로 입력받습니다.
    include_keywords: Optional[List[str]] = Field(
        default=[], 
        title="포함 키워드",
        description="검색 결과에 반드시 포함되어야 할 추가 키워드 (AND 조건)"
    )
    
    exclude_keywords: Optional[List[str]] = Field(
        default=[], 
        title="제외 키워드",
        description="검색 결과에서 제외할 키워드 (NOT 조건)"
    )

    # 3. 날짜 범위 필터
    # 문자열로 받지만 추후 YYYY-MM-DD 형식 검증 로직을 추가할 수 있습니다.
    start_date: Optional[str] = Field(
        default=None, 
        title="시작 날짜",
        description="검색 기간 시작일 (Format: YYYY-MM-DD)",
        example="2025-01-01"
    )
    
    end_date: Optional[str] = Field(
        default=None, 
        title="종료 날짜",
        description="검색 기간 종료일 (Format: YYYY-MM-DD)",
        example="2025-12-31"
    )

    # 4. 페이지네이션 (사이즈)
    # 서버 부하 방지를 위해 le(Less than or Equal) 옵션으로 최대 100개 제한을 둡니다.
    size: int = Field(
        default=10, 
        title="조회 개수",
        description="한 번에 반환할 검색 결과 문서의 개수",
        ge=1,   # 1개 이상
        le=100  # 100개 이하
    )