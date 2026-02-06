"""
########################################################
# Description
# 엑셀 파일 업로드 및 데이터 전처리, 
# OpenSearch Bulk API를 활용한 데이터 색인 및 삭제 관리
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from app.core.opensearch import get_client
from opensearchpy import helpers
import pandas as pd
import io
from datetime import datetime

router = APIRouter()
client = get_client()

# 솔루션 명칭 변경에 따른 인덱스 네이밍 업데이트
INDEX_NAME = "cleversearch-docs"


@router.post("/upload-excel", summary="엑셀 모든 시트 업로드 및 색인")
async def upload_excel_to_opensearch(file: UploadFile = File(...)):
    """
    사용자가 업로드한 엑셀 파일(.xlsx, .xls)의 모든 시트를 읽어
    OpenSearch에 벌크(Bulk)로 색인합니다.
    """
    client = get_client()
    
    # 1. 파일 확장자 유효성 검사
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="엑셀 파일만 업로드 가능합니다.")

    try:
        # 파일 바이너리 읽기
        content = await file.read()
        
        # 2. Pandas를 이용해 모든 시트를 딕셔너리 형태로 로드
        # 결과값 구조: { "Sheet1": DataFrame, "Sheet2": DataFrame ... }
        all_sheets_dict = pd.read_excel(io.BytesIO(content), sheet_name=None)
        
        total_actions = []
        file_name = file.filename  # 메타데이터용 파일명
        
        for sheet_name, df in all_sheets_dict.items():
            # 3. 데이터 전처리 (NaN/결측치 처리 및 불필요한 인덱스 컬럼 제거)
            df = df.replace({pd.NA: None, float('nan'): None})
            df = df.where(pd.notnull(df), None)
            
            if 'Unnamed: 0' in df.columns:
                df = df.drop(columns=['Unnamed: 0'])

            # 4. DataFrame을 딕셔너리 리스트로 변환하여 OpenSearch 포맷 구성
            records = df.to_dict(orient='records')
            
            actions = [
                {
                    "_index": INDEX_NAME,
                    "_source": {
                        **record,
                        # [핵심] 전문 검색(Full-Text Search)을 위해 모든 필드값을 하나의 문자열로 결합
                        "all_text": " ".join([str(v) for v in record.values() if v is not None]),
                        # [메타데이터] 출처 파일, 시트 정보 및 색인 시간 기록
                        "origin_file": file_name,
                        "origin_sheet": sheet_name,
                        "indexed_at": datetime.now().isoformat()
                    }
                }
                for record in records
            ]
            total_actions.extend(actions)

        # 5. OpenSearch Helpers를 이용한 대량(Bulk) 색인 실행
        if not total_actions:
            return {"message": "업로드할 유효한 데이터가 없습니다."}

        # success: 성공 횟수, failed: 실패 상세 내역
        success, failed = helpers.bulk(client, total_actions, refresh=True)

        return {
            "message": f"총 {len(all_sheets_dict)}개 시트 데이터 색인 완료",
            "success_count": success,
            "failed_count": len(failed) if isinstance(failed, list) else failed
        }

    except Exception as e:
        # 파일 처리 중 예외 발생 시 500 에러 반환
        raise HTTPException(status_code=500, detail=f"파일 처리 중 오류 발생: {str(e)}")
    
    
@router.delete("/clear-all-data", summary="인덱스의 모든 데이터 삭제")
async def clear_all_data():
    """
    인덱스 구조(Mapping)는 유지한 채 내부의 모든 문서(Document)만 삭제합니다.
    """
    try:
        # 1. 인덱스 존재 여부 사전 확인
        if not client.indices.exists(index=INDEX_NAME):
            raise HTTPException(status_code=404, detail="삭제할 인덱스가 존재하지 않습니다.")

        # 2. delete_by_query API를 사용하여 모든 문서 일괄 삭제
        response = client.delete_by_query(
            index=INDEX_NAME,
            body={"query": {"match_all": {}}},
            refresh=True  # 삭제 작업 후 즉시 검색 결과에 반영
        )
        
        return {
            "message": "모든 데이터가 성공적으로 삭제되었습니다.",
            "deleted_count": response.get("deleted", 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터 삭제 중 오류 발생: {str(e)}")


@router.delete("/delete-index", summary="인덱스 자체를 완전히 삭제")
async def delete_index():
    """
    OpenSearch에서 해당 인덱스를 완전히 제거합니다. (데이터 및 설정 모두 삭제)
    """
    try:
        if client.indices.exists(index=INDEX_NAME):
            client.indices.delete(index=INDEX_NAME)
            return {"message": f"인덱스 '{INDEX_NAME}'가 완전히 삭제되었습니다."}
        else:
            return {"message": "삭제할 대상 인덱스가 존재하지 않습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인덱스 삭제 중 오류 발생: {str(e)}")