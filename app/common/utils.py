import re
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
        # 허용 문자: 한글, 영문, 숫자, 공백, 필수 문장부호
        allowed = re.compile(r'[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s.,!?;:()\"\'\-\[\]\<\>\t\n\r]')
        result = "".join([ch for ch in text if allowed.match(ch)])
        return re.sub(r' +', ' ', result).strip()

    @staticmethod
    def generate_content_digest(text: str, filename: str) -> str:
        """[지문] 중복 확인용 고유 데이터 지문 생성"""
        clean = re.sub(r'[^가-힣a-zA-Z0-9]', '', text[:500]).strip()
        # 본문이 비었을 경우 파일명으로 대체하여 'None' 에러 방지
        return clean if clean else re.sub(r'[^가-힣a-zA-Z0-9]', '', filename)

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
        client.indices.refresh(index=index_name)
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