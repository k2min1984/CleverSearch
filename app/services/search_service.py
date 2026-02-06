"""
########################################################
# Description
# OpenSearch 검색 비즈니스 로직 서비스
# 파일명: Search_Service.py
# - [최종 수정] 에디터 경고(NameError) 해결 및 함수 구조 최적화
# - 단어 단위 가중치 부여 및 정교한 하이라이트 반영
########################################################
"""

from app.core.opensearch import get_client
from app.schemas.search_schema import SearchRequest
from app.core.config import settings
import re

client = get_client()

class SearchService:
    @staticmethod
    async def execute_search(req: SearchRequest):
        index_name = settings.OPENSEARCH_INDEX
        
        # [해결] 에디터 경고를 없애기 위해 호출되는 메서드 내부에 함수 정의
        # 이렇게 하면 'build_weighted_query'를 바로 호출할 수 있습니다.
        def build_weighted_query(keyword):
            clean_kw = keyword.strip()
            if not clean_kw: return None

            return {
                "bool": {
                    "should": [
                        # 1단계: 정확히 단어가 일치하는 경우 (가장 높은 가중치)
                        {
                            "match_phrase": {
                                "all_text": {
                                    "query": clean_kw,
                                    "boost": 10
                                }
                            }
                        },
                        # 2단계: 단어 중심 검색 (조사가 붙어도 핵심어 매칭)
                        {
                            "query_string": {
                                "query": f"\"{clean_kw}\" OR {clean_kw}",
                                "fields": ["all_text^5", "Title^3"],
                                "default_operator": "OR",
                                "boost": 5
                            }
                        },
                        # 3단계: 기존 와일드카드 방식 (부분 일치 보장)
                        {
                            "query_string": {
                                "query": f"*{clean_kw}*",
                                "fields": ["all_text^10", "Content^3", "Title^2", "origin_file"],
                                "analyze_wildcard": True,
                                "default_operator": "OR",
                                "fuzziness": "AUTO",
                                "boost": 1
                            }
                        }
                    ]
                }
            }

        # --- 1. 필수 검색어 쿼리 조립 ---
        must_queries = []
        if req.query and req.query.strip():
            # 이제 노란 물결선 없이 정상 호출됩니다.
            q = build_weighted_query(req.query)
            if q: must_queries.append(q)
            
        for word in req.include_keywords:
            if word.strip():
                q = build_weighted_query(word)
                if q: must_queries.append(q)
            
        # --- 2. 제외 검색어 쿼리 조립 ---
        must_not_queries = []
        for word in req.exclude_keywords:
            if word.strip():
                must_not_queries.append({
                    "query_string": {
                        "query": f"*{word.strip()}*",
                        "fields": ["all_text"]
                    }
                })

        # --- 3. 최종 OpenSearch 쿼리 바디 ---
        query_body = {
            "from": 0,
            "size": req.size,
            "query": {
                "bool": {
                    "must": must_queries if must_queries else [{"match_all": {}}],
                    "must_not": must_not_queries
                }
            },
            "highlight": {
                "require_field_match": False,
                "pre_tags": ["<b style='color: red; font-weight: bold;'>"],
                "post_tags": ["</b>"],
                "fields": {
                    "all_text": {
                        "fragment_size": 400,
                        "number_of_fragments": 1,
                        "type": "unified" 
                    },
                    "Title": {"fragment_size": 200},
                    "Content": {"fragment_size": 400}
                },
                "fragmenter": "span", 
                "no_match_size": 300
            }
        }

        # --- 4. 날짜 필터 적용 및 검색 실행 ---
        if req.start_date:
            date_filter = {"range": {"indexed_at": {"gte": req.start_date}}}
            if req.end_date: date_filter["range"]["indexed_at"]["lte"] = req.end_date
            if "filter" not in query_body["query"]["bool"]:
                query_body["query"]["bool"]["filter"] = []
            query_body["query"]["bool"]["filter"].append(date_filter)
            
        try:
            response = client.search(index=index_name, body=query_body)
        except Exception as e:
            return {"total": 0, "items": [], "message": f"에러 발생: {str(e)}"}

        # --- 5. 결과 가공 및 하이라이트 ---
        processed_results = []
        hits = response.get('hits', {}).get('hits', [])
        
        for hit in hits:
            source = hit['_source']
            highlight_dict = hit.get('highlight', {})
            
            highlighted_summary = ""
            if highlight_dict:
                for field in ["all_text", "Content", "Title"]:
                    if field in highlight_dict and highlight_dict[field]:
                        highlighted_summary = highlight_dict[field][0]
                        break
            
            # 하이라이트 실패 시 수동 강조
            if not highlighted_summary and req.query:
                raw_text = source.get("all_text") or source.get("Content") or ""
                idx = raw_text.lower().find(req.query.lower())
                if idx != -1:
                    start = max(0, idx - 150) 
                    end = start + 450
                    snippet = raw_text[start:end]
                    pattern = re.compile(re.escape(req.query), re.IGNORECASE)
                    highlighted_summary = pattern.sub(
                        f"<b style='color: red; font-weight: bold;'>{req.query}</b>", 
                        snippet
                    )
                    if start > 0: highlighted_summary = "..." + highlighted_summary
                    highlighted_summary += "..."
                else:
                    highlighted_summary = (raw_text[:400] + "...") if raw_text else "내용 없음"

            processed_results.append({
                "id": hit["_id"],
                # 시트 정보가 없는 일반 문서는 깔끔하게 파일명만 나오도록 정돈
                "location": f"[{source.get('origin_file', 'N/A')}] {source.get('origin_sheet', '')}".strip(), 
                "content": source,
                "summary": highlighted_summary,
                "score": hit["_score"]
            })
            
        return {
            "total": response['hits']['total']['value'],
            "items": processed_results
        }
    
    @staticmethod
    async def get_autocomplete(q: str):
        index_name = settings.OPENSEARCH_INDEX
        search_field = "all_text" 
        
        query = {
            "size": 5,
            "query": {
                "match_phrase_prefix": {
                    "all_text": {"query": q, "max_expansions": 10}
                }
            },
            "_source": ["all_text"]
        }
        
        try:
            response = client.search(index=index_name, body=query)
            suggestions = []
            for hit in response['hits']['hits']:
                text = hit['_source'].get('all_text', '')
                if text: suggestions.append(text[:50])
            return list(set(suggestions))
        except Exception:
            return []