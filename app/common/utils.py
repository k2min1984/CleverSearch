"""
########################################################
# Description
# 공통 유틸리티 (DocumentUtils)
# 문서 처리 전반에 사용되는 공용 함수 모음
# - 텍스트 방역 (sanitize) — 제어문자/특수문자 제거
# - SHA-256 해시 생성 — 중복 파일 감지용
# - 초성 추출 (convert_to_chosung) — 한글 → 초성 변환
# - OpenSearch 벌크 색인 헬퍼
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-02-13 / 초성 추출 및 방역 로직 고도화
########################################################
"""
import re
import hashlib
import math
from datetime import datetime
from opensearchpy import helpers

class DocumentUtils:
    """
    HanSeek 공통 유틸리티 클래스
    어디서든 호출하여 일관된 데이터 정제 및 검증을 수행함.
    """

    @staticmethod
    def sanitize_text(text: str) -> str:
        """[방역] JSON 파싱 에러를 유발하는 제어문자 및 특수문자 제거"""
        if not text: return ""
        # bytes가 혼입된 경우 안전하게 정제
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="ignore")
        text = text.encode("utf-8", errors="ignore").decode("utf-8")
        # JSON 비허용 제어문자 제거 (\t, \n, \r 제외)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', ' ', text)
        # 허용 문자: 한글, 영문, 숫자, 공백, 필수 문장부호
        allowed = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s.,!?;:()\"\'\-\[\]\<\>\t\n\r]')
        result = "".join([ch for ch in text if allowed.match(ch)])
        return re.sub(r' +', ' ', result).strip()

    @staticmethod
    def generate_content_digest(text: str, filename: str) -> str:
        """[지문] 중복 확인용 SHA256 해시 생성"""
        clean = re.sub(r'[^가-힣a-zA-Z0-9]', '', text[:500]).strip()
        payload = clean if clean else re.sub(r'[^가-힣a-zA-Z0-9]', '', filename)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def map_category(filename: str) -> str:
        """[분류] 파일명 키워드 기반 카테고리 매핑"""
        if any(k in filename for k in ["계획", "기획"]): return "PLAN"
        if any(k in filename for k in ["보고", "결과"]): return "REPORT"
        if any(k in filename for k in ["규정", "지침", "가이드", "법규"]): return "RULE"
        return "OTHERS"

    @staticmethod
    def check_duplicate_content(client, index_name: str, digest: str):
        """[검증] OpenSearch 내 중복 데이터 여부 확인"""
        res = client.search(
            index=index_name,
            body={
                "query": {
                    "bool": {
                        "filter": [{"term": {"content_hash": str(digest)}}]
                    }
                }
            },
            _source=["origin_file"]
        )
        is_dup = res['hits']['total']['value'] > 0
        existing_file = res['hits']['hits'][0]['_source']['origin_file'] if is_dup else None
        return is_dup, existing_file

    @staticmethod
    def convert_to_chosung(text: str) -> str:
        """[변환] 한글 초성 추출 (검색 정확도 향상용)"""
        if not text: return ""
        CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
        result = []
        for char in text:
            code = ord(char)
            if 0xAC00 <= code <= 0xD7A3:
                result.append(CHOSUNG_LIST[(code - 0xAC00) // 588])
            else:
                result.append(char)
        return "".join(result)

    @staticmethod
    def sanitize_for_opensearch(value):
        """[정제] OpenSearch JSON body 전송 전 재귀 정제"""
        if value is None:
            return None

        if isinstance(value, (bytes, str)):
            return DocumentUtils.sanitize_text(value)

        if isinstance(value, bool):
            return value

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return value if math.isfinite(value) else 0.0

        if isinstance(value, dict):
            cleaned = {}
            for k, v in value.items():
                clean_key = DocumentUtils.sanitize_text(str(k))
                cleaned[clean_key] = DocumentUtils.sanitize_for_opensearch(v)
            return cleaned

        if isinstance(value, (list, tuple, set)):
            return [DocumentUtils.sanitize_for_opensearch(v) for v in value]

        # numpy array/series 등 tolist 지원 타입 방어
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            return DocumentUtils.sanitize_for_opensearch(tolist())

        return DocumentUtils.sanitize_text(str(value))