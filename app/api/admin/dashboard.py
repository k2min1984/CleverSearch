"""
########################################################
# Description
# 관리자 API 라우터
# 인기 검색어, 문서 목록, 검색 로그 등 관리 기능 제공
# - 인기 검색어 통계 조회
# - 색인 문서 목록 조회
# - viewer 이상 권한 필요
#
# Modified History
# 강광민 / 2026-03-15 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from fastapi import APIRouter, Depends, Query

from app.services.db_service import DBService
from app.core.security import require_role


router = APIRouter(dependencies=[Depends(require_role("viewer"))])


@router.get("/popular-keywords", summary="인기 검색어 카운팅 목록")
async def get_popular_keyword_stats(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(30, ge=1, le=200),
):
    # 인기검색 탭은 search_logs 테이블을 집계한 결과를 보여줍니다.
    return DBService.get_popular_keyword_stats(days=days, limit=limit)


@router.get("/indexed-documents", summary="업무 DB 저장 문서 목록")
async def get_indexed_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    # 문서 탭은 업무 DB에 동기화된 문서 목록을 조회합니다.
    return DBService.list_indexed_documents(skip=skip, limit=limit)


@router.get("/search-logs", summary="검색 로그 목록")
async def get_search_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    # 검색 로그 탭은 원본 로그 레코드를 시간 역순으로 반환합니다.
    return DBService.list_search_logs(skip=skip, limit=limit)


@router.get("/recent-searches", summary="최근 검색어 목록")
async def get_recent_searches(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user_id: str | None = Query(None),
):
    # 최근 검색어 탭은 recent_searches 테이블을 직접 조회합니다.
    return DBService.list_recent_searches(skip=skip, limit=limit, user_id=user_id)


@router.get("/failed-keywords", summary="실패 검색어 카운팅 목록")
async def get_failed_keyword_stats(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(30, ge=1, le=200),
):
    # 실패 검색어 탭은 search_logs 중 결과 0건 로그만 재집계합니다.
    return DBService.get_failed_keywords(days=days, limit=limit)
