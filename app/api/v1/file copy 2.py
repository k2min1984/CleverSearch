"""
########################################################
# Description
# (레거시) 파일 업로드·색인 API 구버전
# pdfplumber/docx 등 직접 처리하는 이전 코드
# 현재는 file.py + IndexingService로 대체됨
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가 (구버전 보관)
########################################################
"""
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
    def absolute_clean(text):
        """제어 문자 제거 및 한글/영문 완전 보존"""
        if not text: return ""
        text = str(text).encode("utf-8", "ignore").decode("utf-8", "ignore")
        # 한글 전체와 영문, 숫자, 기호만 허용 (code 31 제거)
        allowed_re = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s' + re.escape(string.punctuation) + r']')
        cleaned = "".join(ch for ch in text if allowed_re.match(ch))
        return re.sub(r'\s+', ' ', cleaned).strip()

    def make_fingerprint(text):
        """중복 체크용 지문: 공백/기호 제거 후 순수 글자만 추출"""
        if not text: return ""
        pure = re.sub(r'[^가-힣a-zA-Z0-9]', '', str(text))
        return pure[:300]

    ensure_index()
    filename = absolute_clean(file.filename)
    ext = filename.split('.')[-1].lower() if '.' in filename else ""
    content = await file.read()
    text_content = ""

    try:
        # 1. 확장자별 정밀 추출
        if ext == 'pdf':
            with pdfplumber.open(io.BytesIO(content)) as pdf_file:
                text_content = "\n".join([p.extract_text() for p in pdf_file.pages if p.extract_text()])
        elif ext == 'docx':
            doc = Document(io.BytesIO(content))
            text_content = "\n".join([p.text for p in doc.paragraphs])
        elif ext in ['xlsx', 'xls']:
            excel_data = pd.read_excel(io.BytesIO(content), sheet_name=None)
            text_content = " ".join([df.to_string() for df in excel_data.values()])
        elif ext in ['jpg', 'jpeg', 'png']:
            text_content = image.extract_text(content)
        elif ext in ['hwp', 'hwpx']:
            text_content = hwp._extract_text(content,ext)
        elif ext in ['pptx', 'ppt']:
            text_content = office.parse_pptx(content)

        # 2. 추출 본문 세탁
        text_content = absolute_clean(text_content)

        # 3. 중복 확인용 지문 생성 및 '쿼리 안전 세탁'
        fingerprint = make_fingerprint(text_content)
        
        if not fingerprint:
            return {"status": "fail", "message": "유효한 텍스트를 추출하지 못했습니다."}

        # [핵심 수정] 중복 체크 쿼리를 날릴 때 검색어에 포함된 code 31을 한 번 더 거름
        safe_fingerprint = absolute_clean(fingerprint)
        
        client.indices.refresh(index=INDEX_NAME)
        
        content_res = client.search(
            index=INDEX_NAME,
            body={
                "query": {
                    "term": { "content_hash": safe_fingerprint } # 안전한 지문으로 검색
                }
            },
            _source=False
        )

        if content_res['hits']['total']['value'] > 0:
            return {"status": "skipped", "message": "내용 중복: 이미 등록된 파일입니다."}

        # 4. 저장
        action = {
            "_index": INDEX_NAME,
            "_source": {
                "origin_file": filename,
                "all_text": text_content,
                "content_hash": fingerprint,
                "Title": filename,
                "indexed_at": datetime.now().isoformat()
            }
        }
        helpers.bulk(client, [action], refresh=True)
        return {"status": "success", "message": f"{filename} 완료"}

    except Exception as e:
        # 에러 발생 시 로그에 상세 내용 출력
        print(f"상세 에러 로그: {str(e)}")
        raise HTTPException(status_code=500, detail=f"처리 실패: {str(e)}")

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