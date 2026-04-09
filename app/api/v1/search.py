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

from fastapi import APIRouter, Query, HTTPException
from app.schemas.search_schema import SearchRequest
from app.services.search_service import SearchService
from app.common.utils import DocumentUtils
from app.core.opensearch import get_client  # 지렁이 줄을 없애줄 녀석입니다!

# OpenSearch 통신용 변수 세팅
client = get_client()
INDEX_NAME = "cleversearch-docs"

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
async def get_popular(limit: int = Query(None, ge=1, le=9)):
    """
    현재 색인된 문서들 중 가장 빈도가 높은 키워드를 반환합니다.
    화면 상단의 인기 검색어 해시태그에 연동됩니다.
    limit이 지정되지 않으면 관리자가 저장한 설정값을 사용합니다.
    """
    if limit is None:
        from app.services.system_service import PopularConfigService
        settings = PopularConfigService.get_settings()
        limit = settings.get("limit") or 9
    return await SearchService.get_popular_keywords(limit=limit)


@router.get("/recent", summary="사용자 최근 검색어 조회")
async def get_recent(user_id: str = Query("anonymous"), limit: int = Query(10, ge=1, le=30)):
    """사용자별 최근 검색어 목록 조회 (최신순, 앱 DB 기준)"""
    return await SearchService.get_recent_keywords(user_id=user_id, limit=limit)


@router.delete("/recent", summary="사용자 최근 검색어 전체 삭제")
async def clear_recent(user_id: str = Query("anonymous")):
    """해당 사용자의 최근 검색어 전체 삭제"""
    return await SearchService.clear_recent_keywords(user_id=user_id)


@router.delete("/recent/item", summary="사용자 최근 검색어 단건 삭제")
async def delete_recent_item(user_id: str = Query("anonymous"), q: str = Query(..., min_length=1)):
    """사용자의 특정 최근 검색어 1건 삭제"""
    return await SearchService.remove_recent_keyword(user_id=user_id, query=q)


@router.get("/recommend", summary="사용자 맞춤 추천 검색어")
async def get_recommend(user_id: str = Query("anonymous"), limit: int = Query(10, ge=1, le=30)):
    """사용자 최근 검색어 + 전체 인기 검색어를 병합한 추천 검색어 제안"""
    return await SearchService.get_recommended_keywords(user_id=user_id, limit=limit)


@router.get("/related", summary="연관 검색어 조회")
async def get_related(
    q: str = Query(..., min_length=1),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=30),
):
    """입력 쿼리와 토큰 유사도+빈도 기반으로 산출된 연관 검색어 반환"""
    return await SearchService.get_related_keywords(query=q, days=days, limit=limit)

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

@router.get("/admin/documents")
async def get_all_documents_for_admin(
    skip: int = Query(0, description="건너뛸 데이터 수 (페이징용)"), 
    limit: int = Query(20, description="한 번에 가져올 데이터 수")
):
    """
    [관리자 전용] OpenSearch에 저장된 전체 문서 목록을 최신순으로 가져옵니다.
    (주의: 무거운 768차원 AI 벡터 데이터는 화면 마비를 막기 위해 빼고 보냅니다.)
    """
    query_body = {
        "from": skip,
        "size": limit,
        "query": {"match_all": {}}, # 조건 없이 다 가져와!
        "_source": {"excludes": ["text_vector"]}, # 🚨 768개 숫자 뭉치는 무조건 제외!
        "sort": [{"indexed_at": {"order": "desc"}}] # 최신 등록순 정렬
    }
    
    try:
        res = client.search(index=INDEX_NAME, body=query_body)
        hits = res['hits']['hits']
        
        items = []
        for hit in hits:
            source = hit['_source']
            items.append({
                "doc_id": hit['_id'], # OpenSearch 고유 ID (나중에 수정/삭제할 때 필수)
                "title": source.get("Title", "제목없음"),
                "category": source.get("doc_category", "-"),
                "file_ext": source.get("file_ext", ""),
                "indexed_at": source.get("indexed_at", "")[:10], # 날짜만 예쁘게 자르기
                "text_preview": source.get("all_text", "")[:100] + "..." # 본문은 100자만 미리보기
            })
            
        return items

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"관리자 데이터 조회 실패: {str(e)}")