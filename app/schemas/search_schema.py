"""
########################################################
# Description
# 검색 요청 파라미터 정의 및 검증 스키마 (DTO)
# Pydantic을 활용한 입력 데이터 유효성 검사 및 문서화
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / doc_category 필드 추가 및 고도화
########################################################
"""

from pydantic import BaseModel, Field
from typing import Optional, List

class SearchRequest(BaseModel):
    """
    [HanSeek] 메인 검색 요청 모델
    프론트엔드에서 전달되는 검색 조건들을 정의하고 검증합니다.
    """
    
    # 1. 필수 검색어
    query: str = Field(
        ..., 
        title="검색어",
        description="사용자가 입력한 메인 검색 키워드", 
        example="인공지능"
    )

    # 2. 상세 필터링 (포함/제외 키워드)
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
    start_date: Optional[str] = Field(
        default=None, 
        title="시작 날짜",
        description="검색 기간 시작일 (Format: ISO8601 or YYYY-MM-DD)",
        example="2026-01-01"
    )
    
    end_date: Optional[str] = Field(
        default=None, 
        title="종료 날짜",
        description="검색 기간 종료일 (Format: YYYY-MM-DD)",
        example="2026-12-31"
    )

    # 4. 카테고리 필터 (중요: 탭 기능 연동)
    # 프론트엔드의 카테고리 탭(PLAN, REPORT, RULE)과 매칭됩니다.
    doc_category: Optional[str] = Field(
        default=None,
        title="문서 카테고리",
        description="특정 카테고리 탭 필터링 (예: PLAN, REPORT, RULE)",
        example="PLAN"
    )

    # 5. 확장자 필터
    file_ext: Optional[str] = Field(
        default=None,
        title="확장자 필터",
        description="특정 확장자만 검색 (예: pdf, hwp, docx)",
        example="pdf"
    )

    # 6. [추가] 시스템 정밀도: 최소 매칭 점수 (1순위 대응)
    # 검색 결과의 질을 제어하기 위해 사용합니다.
    min_score: float = Field(
        default=0.0,
        title="최소 점수",
        description="이 점수 이상의 결과만 반환 (정밀도 조절용)",
        ge=0.0
    )        
    
    # 7. 페이지네이션 (사이즈)
    size: int = Field(
        default=10, 
        title="조회 개수",
        description="한 번에 반환할 검색 결과 문서의 개수",
        ge=1, 
        le=100
    )