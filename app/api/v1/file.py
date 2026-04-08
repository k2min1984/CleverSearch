"""
########################################################
# Description
# 파일 업로드·색인 API 라우터
# 업로드된 문서 파일을 텍스트 추출 → 임베딩 → OpenSearch 색인
# - 파일 업로드 (PDF, HWP, DOCX, PPTX, XLSX, 이미지)
# - 문서 삭제 (DB + OpenSearch 동시 제거)
# - 전체 초기화 / 인덱스 재생성
# - 중복 파일 자동 감지 (SHA-256 해시)
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / IndexingService 리팩토링 및 통합
########################################################
"""
import re
import hashlib

# FastAPI 관련 항목들을 한 줄로 통합
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Path

# 프로젝트 내부 모듈
from app.core.opensearch import get_client
from app.common.utils import DocumentUtils
from app.common.embedding import embedder  #[추가] AI 벡터 변환기 가져오기
from app.services.indexing_service import IndexingService
from app.services.db_service import DBService

router = APIRouter()
client = get_client()
INDEX_NAME = "cleversearch-docs"

# 허용된 확장자 목록 (doc, ppt는 라이브러리 미지원으로 제외)
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'hwp', 'hwpx', 'pdf', 'docx', 'pptx', 'jpg', 'jpeg', 'png'}

# 업로드 파일 최대 크기 (100MB) - DoS 공격 방지
MAX_UPLOAD_SIZE = 100 * 1024 * 1024
MAX_BATCH_FILES = 50

def ensure_index():
    """인덱스가 없을 경우 초기 설정(Settings/Mappings)과 함께 생성"""
    try:
        IndexingService.ensure_index()
    except Exception as e:
        print(f"❌ 인덱스 생성 실패: {str(e)}")


async def _process_uploaded_file(file: UploadFile) -> dict:
    """단일 파일 업로드 처리 공통 로직."""
    filename = DocumentUtils.sanitize_text(file.filename)
    ext = filename.split('.')[-1].lower() if '.' in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        return {
            "status": "fail",
            "message": f"지원하지 않는 확장자입니다: {ext}",
            "filename": filename,
        }

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return {
            "status": "fail",
            "message": f"파일 크기 초과: 최대 100MB 허용 (현재 {len(content)//1024//1024}MB)",
            "filename": filename,
        }

    # 업로드 API 입구에서 동일 파일(바이트 해시)을 즉시 차단합니다.
    binary_digest = hashlib.sha256(content).hexdigest()
    hash_dup = DBService.find_duplicate_by_content_hash(binary_digest)
    if hash_dup.get("is_duplicate"):
        return {
            "status": "skipped",
            "message": f"DB 중복(동일 파일): {hash_dup.get('origin_file')}",
            "filename": filename,
        }

    try:
        result = IndexingService.index_bytes(filename, content, source_label="upload")
        status = result.get("status", "success")
        if status == "fail":
            return {
                "status": "fail",
                "message": result.get("message", "색인 실패"),
                "filename": filename,
            }
        if status == "skipped":
            return {
                "status": "skipped",
                "message": result.get("message", "중복 문서로 건너뜀"),
                "filename": filename,
            }
        return {
            "status": "success",
            "message": f"[{filename}] 업로드 완료",
            "category": result.get("category", "OTHERS"),
            "doc_id": result.get("doc_id", ""),
            "filename": filename,
        }
    except Exception as e:
        clean_err = DocumentUtils.sanitize_text(str(e))
        return {
            "status": "fail",
            "message": f"서버 내부 오류: {clean_err}",
            "filename": filename,
        }

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    파일 업로드 -> 텍스트 추출 -> 방역 -> 중복체크 -> 카테고리 분류 -> 저장 
    전체 프로세스를 담당하는 엔드포인트
    """
    # 1. 인덱스 존재 여부 확인 및 생성
    ensure_index()

    result = await _process_uploaded_file(file)
    if result.get("status") == "fail":
        message = result.get("message", "업로드 실패")
        if "지원하지 않는 확장자" in message:
            raise HTTPException(status_code=400, detail=message)
        if "파일 크기 초과" in message:
            raise HTTPException(status_code=413, detail=message)
        raise HTTPException(status_code=500, detail=message)
    return result


@router.post("/upload-multiple")
async def upload_multiple_files(files: list[UploadFile] = File(...)):
    """다중 파일 업로드 처리. 파일별 결과를 모두 반환합니다."""
    ensure_index()

    if not files:
        raise HTTPException(status_code=400, detail="업로드할 파일이 없습니다")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"한 번에 최대 {MAX_BATCH_FILES}개 파일까지 업로드할 수 있습니다")

    results = []
    for upload_file in files:
        results.append(await _process_uploaded_file(upload_file))

    success_count = len([r for r in results if r.get("status") == "success"])
    skipped_count = len([r for r in results if r.get("status") == "skipped"])
    fail_count = len([r for r in results if r.get("status") == "fail"])

    overall_status = "success"
    if success_count == 0 and fail_count > 0:
        overall_status = "fail"
    elif fail_count > 0 or skipped_count > 0:
        overall_status = "partial"

    return {
        "status": overall_status,
        "message": f"다중 업로드 처리 완료 (성공 {success_count}, 건너뜀 {skipped_count}, 실패 {fail_count})",
        "summary": {
            "total": len(results),
            "success": success_count,
            "skipped": skipped_count,
            "fail": fail_count,
        },
        "results": results,
    }

# --- 관리용 API ---
@router.delete("/clear-all-data")
async def clear_all_data():
    """OpenSearch 전체 문서 삭제 + 업무 DB(indexed_documents, search_logs, recent_searches) 초기화"""
    os_result = {}
    try:
        if client.indices.exists(index=INDEX_NAME):
            os_result = client.delete_by_query(index=INDEX_NAME, body={"query": {"match_all": {}}}, refresh=True)
    except Exception as e:
        os_result = {"error": str(e)}
    db_result = DBService.clear_all_db_data()
    return {"message": "전체 초기화 완료 (OpenSearch + DB)", "opensearch": os_result, "db": db_result}

@router.delete("/delete-index")
async def delete_index():
    """인덱스 자체를 완전 삭제 + 업무 DB 초기화"""
    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)
    db_result = DBService.clear_all_db_data()
    return {"message": "인덱스 완전 삭제 + DB 초기화 완료", "db": db_result}

@router.delete("/document/{doc_id}")
async def delete_document(doc_id: int = Path(..., ge=1)):
    """개별 문서를 DB와 OpenSearch에서 모두 삭제"""
    os_doc_id = DBService.delete_indexed_document(doc_id)
    if os_doc_id is None:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다")
    # OpenSearch에서도 삭제
    try:
        if os_doc_id and client.indices.exists(index=INDEX_NAME):
            client.delete(index=INDEX_NAME, id=os_doc_id, refresh=True)
    except Exception:
        pass
    return {"message": f"문서 {doc_id} 삭제 완료", "os_doc_id": os_doc_id}

@router.get("/search")
async def search_documents(keyword: str = Query(...)):
    """
    [하이브리드 검색] 키워드 매칭(전통 방식)과 AI 벡터 유사도(문맥 방식)를 동시에 검색합니다.
    """
    # 1. 검색어 방역 (특수문자 제거)
    safe_kw = re.sub(r'[^가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s]', '', keyword)
    if not safe_kw:
        return []

    # 2. 사용자의 검색어도 AI 두뇌를 거쳐 768차원 숫자(벡터)로 변환!
    query_vector = embedder.get_embedding(safe_kw)

    # 3. 궁극의 하이브리드 쿼리 조립 (AND 조건 타파 & AI 가중치 뻥튀기)
    hybrid_query = {
        "size": 10,
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": safe_kw,
                            "fields": ["Title^3", "all_text"],
                            "operator": "or"
                        }
                    },
                    {
                        "knn": {
                            "text_vector": {
                                "vector": query_vector,
                                "k": 10,
                                "boost": 1.0
                            }
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        },
        # 0.5가 아니라 0.75로 세팅해야 유령 단어가 죽습니다!
        "min_score": 0.75, 
        
        "_source": {"excludes": ["text_vector"]},
        "highlight": {"fields": {"all_text": {}}}
    }

    # 4. OpenSearch에 하이브리드 쿼리 발사!
    res = client.search(index=INDEX_NAME, body=hybrid_query)

    # 백엔드에서 실제로 몇 점을 주고 있는지 멱살 잡고 확인하기
    if res['hits']['hits']:
        print(f"👉 [디버그] 검색어: '{keyword}' / 1등 문서 점수: {res['hits']['hits'][0]['_score']}")

    # 검색된 문서 리스트 반환
    return res['hits']['hits']

@router.get("/read/{doc_id}")
async def read_document_full_text(doc_id: str):
    res = client.get(index=INDEX_NAME, id=doc_id)
    return res['_source']