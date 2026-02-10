import re
import io
import string
import pandas as pd
import pdfplumber  # 설치 필수: pip install pdfplumber
from docx import Document
from fastapi import Query
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from opensearchpy import helpers
from app.core.opensearch import get_client
from app.core.file import excel, hwp, pdf, office, image

router = APIRouter()
client = get_client()
INDEX_NAME = "cleversearch-docs"

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'hwp', 'hwpx', 'pdf', 'docx', 'doc', 'pptx', 'ppt', 'jpg', 'jpeg', 'png'}

# --- [기존 함수 100% 유지: deep_clean] ---
def deep_clean(text):
    """
    [핵심 수정] 
    1. 바이너리 찌꺼기(\u001F 등)를 글자 단위로 검사하여 물리적으로 제거
    2. JSON 전송이 가능한 문자열만 추출
    """
    if not text: return ""
    if not isinstance(text, str):
        try: 
            text = text.decode('utf-8', 'ignore')
        except: 
            text = str(text)
    
    # 허용할 문자: 한글, 영문, 숫자, 공백, 일반적인 문장부호
    allowed_pattern = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s.,!?;:()\"\'\-\[\]\<\>\t\n\r]')
    
    # 한 글자씩 검사해서 허용된 문자만 리스트에 담아 합침
    clean_chars = [ch for ch in text if allowed_pattern.match(ch)]
    result = "".join(clean_chars)
    
    # 연속된 공백 정리
    return re.sub(r' +', ' ', result).strip()

# --- [기존 함수 100% 유지: create_index_if_not_exists] ---
def create_index_if_not_exists():
    if not client.indices.exists(index=INDEX_NAME):
        index_body = {
            "settings": { "index": { "number_of_shards": 1, "number_of_replicas": 0 } },
            "mappings": {
                "properties": {
                    "origin_file": {"type": "keyword"},
                    "all_text": {
                        "type": "text",
                        "fields": { "keyword": { "type": "keyword", "ignore_above": 1024 } }
                    },
                    "content_hash": {"type": "keyword"},
                    "indexed_at": {"type": "date"}
                }
            }
        }
        client.indices.create(index=INDEX_NAME, body=index_body, ignore=[400, 500])

# --- [기존 함수 100% 유지: ensure_index] ---
def ensure_index():
    if not client.indices.exists(index=INDEX_NAME):
        settings = {
            "mappings": {
                "properties": {
                    "all_text": {
                        "type": "text",
                        "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
                    },
                    "content_hash": { "type": "keyword" },
                    "origin_file": { "type": "keyword" },
                    "Title": { "type": "text" },
                    "indexed_at": { "type": "date" }
                }
            }
        }
        client.indices.create(index=INDEX_NAME, body=settings)

# --- [업로드 로직: 쿼리 세탁 및 중복 차단] ---
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    파일을 업로드하여 텍스트를 추출하고, 내용 기반 중복 확인 후 OpenSearch에 저장합니다.
    """
    # 1. 인덱스 보장
    ensure_index()
    
    # 2. 파일 정보 및 확장자 추출
    # [수정] 파일명도 hwp 모듈의 _clean_text로 검역하여 파일명 내 제어문자 제거
    filename = hwp._clean_text(file.filename)
    ext = filename.split('.')[-1].lower() if '.' in filename else ""
    content = await file.read()
    text_content = ""

    try:
        # 3. 확장자별 텍스트 추출 (hwp 모듈 연동)
        if ext in ['hwp', 'hwpx']:
            text_content = hwp._extract_text(content, ext)
            
        elif ext == 'pdf':
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf_file:
                pages = [p.extract_text() for p in pdf_file.pages if p.extract_text()]
                text_content = "\n".join(pages)
                
        elif ext == 'docx':
            from docx import Document
            doc = Document(io.BytesIO(content))
            text_content = "\n".join([p.text for p in doc.paragraphs])

        elif ext in ['xlsx', 'xls']:
            import pandas as pd
            excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None)
            text_content = "\n".join([df.to_string() for df in excel_data.values()])

        elif ext in ['pptx', 'ppt']:
            text_content = office.parse_pptx(content)

        elif ext in ['jpg', 'jpeg', 'png']:
            text_content = image._extract_text(content)

        # 4. 본문용 텍스트 1차 정화 (사용자님이 만든 hwp._clean_text 활용)
        clean_body_text = hwp._clean_text(text_content)

        if not clean_body_text.strip():
            return {"status": "fail", "message": "텍스트를 추출할 수 없는 파일입니다."}

        # 5. [핵심 수정] 중복 확인용 지문 생성 및 '이중 검역'
        # 1차: 기호 제거 (이 과정에서 정규식이 미세한 제어문자를 '글자'로 오인해 남길 수 있음)
        fingerprint_raw = re.sub(r'[^가-힣a-zA-Z0-9]', '', clean_body_text)[:300] 

        # 2차: [필살기] 생성된 지문을 다시 한번 hwp._clean_text 검역소에 통과시킴
        # 쿼리용 JSON 바디(XContent)가 깨지는 것을 방지하기 위해 safe_fingerprint를 별도로 생성합니다.
        safe_fingerprint = hwp._clean_text(fingerprint_raw).strip()

        if not safe_fingerprint:
            return {"status": "fail", "message": "중복 확인을 위한 유효 텍스트가 부족합니다."}

        # 6. OpenSearch 내용 중복 확인 쿼리 (safe_fingerprint 사용)
        client.indices.refresh(index=INDEX_NAME)
        
        # [ Image of OpenSearch json_parse_exception validation process ]
        # 쿼리 전송 시 safe_fingerprint를 사용하여 json_parse_exception 원천 봉쇄
        content_res = client.search(
            index=INDEX_NAME,
            body={
                "query": {
                    "term": { "content_hash": str(safe_fingerprint) } 
                }
            },
            _source=False
        )

        if content_res['hits']['total']['value'] > 0:
            return {"status": "skipped", "message": "내용 중복: 이미 동일한 문서가 저장되어 있습니다."}

        # 7. 최종 데이터 저장 (모든 필드 str() 강제 적용으로 안정성 확보)
        doc_source = {
            "origin_file": str(filename),
            "all_text": str(clean_body_text),
            "content_hash": str(safe_fingerprint),
            "Title": str(filename),
            "indexed_at": datetime.now().isoformat()
        }

        # 8. Bulk 데이터 전송
        action = {
            "_index": INDEX_NAME,
            "_source": doc_source
        }
        
        from opensearchpy import helpers
        helpers.bulk(client, [action], refresh=True)
        
        return {
            "status": "success", 
            "message": f"{filename} 업로드 완료",
            "hash_preview": safe_fingerprint[:15]
        }

    except Exception as e:
        # 에러 메시지에도 제어문자가 섞여 있을 수 있으므로 세탁해서 반환
        clean_err = hwp._clean_text(str(e))
        raise HTTPException(status_code=500, detail=f"서버 전송 오류: {clean_err}")   

# --- [기타 관리 및 검색 API 100% 보존] ---
@router.delete("/clear-all-data")
async def clear_all_data():
    client.delete_by_query(index=INDEX_NAME, body={"query": {"match_all": {}}}, refresh=True)
    return {"message": "삭제 완료"}

@router.delete("/delete-index")
async def delete_index():
    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)
    return {"message": "인덱스 삭제 완료"}

@router.get("/search")
async def search_documents(keyword: str = Query(...)):
    # 검색 키워드도 세탁해서 쿼리 오류 방지
    safe_kw = re.sub(r'[^가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s]', '', keyword)
    query = {"query": {"match_phrase": {"all_text": safe_kw}}, "highlight": {"fields": {"all_text": {}}}}
    res = client.search(index=INDEX_NAME, body=query)
    return res['hits']['hits']

@router.get("/read/{doc_id}")
async def read_document_full_text(doc_id: str):
    res = client.get(index=INDEX_NAME, id=doc_id)
    return res['_source']