"""
########################################################
# Description
# OpenSearch 인덱스 조회 및 데이터 확인용 API
# 전체 데이터 검색(Match All) 로직 포함
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from fastapi import APIRouter, HTTPException
from app.core.config import settings
from app.core.opensearch import get_client
# 설정 파일이 필요하다면 사용하되, 현재 로직에서는 직접 명시하여 직관성을 높였습니다.
# from app.core.config import settings 

router = APIRouter()

# OpenSearch 클라이언트 객체 생성
client = get_client()

INDEX_NAME = settings.OPENSEARCH_INDEX

@router.get("/all-data", summary="색인된 전체 데이터 조회")
async def get_all_indexed_data():
    """
    OpenSearch 인덱스에 저장된 모든 데이터를 조회합니다.
    주로 데이터 적재 확인 및 디버깅 용도로 사용됩니다.
    """
    try:
        # 1. Match All 쿼리 실행
        # 조건 없이 모든 문서를 조회하며, 성능을 위해 최대 100개까지만 가져옵니다.
        response = client.search(
            index=INDEX_NAME,
            body={
                "query": {
                    "match_all": {} # 필터링 없는 전체 검색
                },
                "size": 100 # 프로토타입 UI 부하 방지를 위한 제한
            }
        )
        
        # 2. 검색 결과 파싱
        # OpenSearch 응답 구조에서 실제 데이터(_source)만 추출합니다.
        hits = response.get("hits", {}).get("hits", [])
        results = [hit["_source"] for hit in hits]
        
        return {
            "total": response["hits"]["total"]["value"],
            "data": results
        }
        
    except Exception as e:
        # 3. 예외 처리: 인덱스가 없는 경우 (최초 실행 시)
        # 500 에러 대신 빈 리스트를 반환하여 프론트엔드가 깨지지 않도록 처리
        if "index_not_found_exception" in str(e):
            return {
                "total": 0, 
                "data": [], 
                "message": "인덱스가 존재하지 않습니다. 먼저 엑셀 파일을 업로드하여 데이터를 생성해주세요."
            }
            
        # 그 외의 연결 오류 등은 500 에러로 처리
        raise HTTPException(status_code=500, detail=f"데이터 조회 중 오류 발생: {str(e)}")