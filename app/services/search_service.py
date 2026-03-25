"""
########################################################
# Description
# OpenSearch 검색 비즈니스 로직 서비스
# - 하이브리드 검색 엔진 (키워드 Bool + 벡터 KNN 결합)
# - 검색어 전처리: 불용어 제거, 오타 자동 교정(hanspell), 초성 변환
# - 상세 필터: 포함/제외 키워드, 파일 형식, 기간/작성자 범위 검색
# - 항목별 가중치 부여: 제목 20배, 본문 5배 등 동적 Scoring
# - 검색 로그 기록 및 실패(0건) 추적 로직 통합
# - 자동완성: 초성+키워드 기반 문서명 후보 제시
# - 추천/연관 검색어, 인기 검색어, 최근 검색어 API 연동
#
# Modified History
# 강광묵 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-18 / 상세 필터(작성자, 최소점수) 기능 강화
# 강광민 / 2026-03-23 / 동적 Scoring 가중치 연동 (ScoringConfigService)
########################################################
"""

import re
from datetime import datetime
from app.core.opensearch import get_client
from app.schemas.search_schema import SearchRequest
from app.core.config import settings
from app.common.utils import DocumentUtils 
from app.common.embedding import embedder
from app.services.db_service import DBService
from app.services.dictionary_service import DictionaryService
from app.services.system_service import ScoringConfigService

# hanspell을 타임아웃 안전하게 import (외부 네트워크 의존 모듈)
try:
    from hanspell import spell_checker
    _HAS_HANSPELL = True
except ImportError:
    _HAS_HANSPELL = False

client = get_client()

# --- 동의어 사전 ---
SYNONYM_DICT = {
    "AI": ["인공지능", "Machine Learning"],
    "한전": ["한국전력공사", "KEPCO"],
    "RAG": ["검색 증강 생성"]
}

# [도우미] 페이지 번호 역추적
def find_page_number(full_text, hit_index):
    if not full_text or hit_index < 0: return "1"
    text_before_hit = full_text[:hit_index]
    matches = list(re.finditer(r'\[\[Page\s+(\d+)\]\]', text_before_hit))
    return matches[-1].group(1) if matches else "1"

# [도우미] 스니펫 생성
def make_snippet(full_text, start_idx, end_idx):
    context_start = max(0, start_idx - 60)
    context_end = min(len(full_text), end_idx + 60)
    prefix = "..." if context_start > 0 else ""
    suffix = "..." if context_end < len(full_text) else ""
    target_word = full_text[start_idx:end_idx]
    return (
        f"{prefix}{full_text[context_start:start_idx]}"
        f"<mark>{target_word}</mark>"
        f"{full_text[end_idx:context_end]}{suffix}"
    )

# [하이라이트] 초성용
def manual_chosung_highlight(full_text, chosung_kw):
    if not full_text or not chosung_kw: return None, "1"
    full_chosung = DocumentUtils.convert_to_chosung(full_text)
    search_kw = chosung_kw.strip().replace(" ", "")
    start_idx = full_chosung.find(search_kw)
    if start_idx == -1: return None, "1"
    return make_snippet(full_text, start_idx, start_idx + len(search_kw)), find_page_number(full_text, start_idx)

# [하이라이트] 일반 텍스트용
def manual_text_highlight(full_text, keyword):
    if not full_text or not keyword: return None, "1"
    lower_text = full_text.lower()
    lower_kw = keyword.lower().strip()
    start_idx = lower_text.find(lower_kw)
    if start_idx == -1: return None, "1"
    return make_snippet(full_text, start_idx, start_idx + len(lower_kw)), find_page_number(full_text, start_idx)


def contains_exact_keyword(source: dict, keyword: str) -> bool:
    """짧은 고유명사 검색에서 오탐 방지를 위한 정확 포함 여부 검사"""
    if not keyword:
        return False
    needle = keyword.strip().lower()
    title = (source.get("Title") or "").lower()
    body = (source.get("all_text") or "").lower()
    return needle in title or needle in body


def is_name_like_query(query: str) -> bool:
    """이름 형태로 볼 수 있는 짧은 한글 쿼리인지 판별"""
    q = (query or "").strip()
    if (not q) or (" " in q) or (not re.match(r'^[가-힣]+$', q)):
        return False

    # 업무 도메인 단어가 포함되면 이름형 쿼리로 보지 않음 (오타교정/일반검색 보존)
    domain_hints = [
        "사업", "계획", "지침", "보안", "검색", "개발", "솔루션", "연구",
        "데이터", "문서", "운영", "공고", "보고", "규정", "가이드",
    ]
    return not any(hint in q for hint in domain_hints)


def normalize_common_typos(query: str) -> str:
    """hanspell 미적용/실패 시 자주 발생하는 오타를 보정하는 폴백"""
    q = (query or "").strip()
    if not q:
        return q

    replacements = [
        ("계확", "계획"),
        ("게확", "계획"),
        ("게획", "계획"),
        ("계휙", "계획"),
        ("게휙", "계획"),
        ("개휙", "계획"),
        ("산엽", "산업"),
        ("산엡", "산업"),
        ("삼엽", "산업"),
    ]
    for src, dst in replacements:
        q = q.replace(src, dst)
    return q


def apply_runtime_dictionary(query: str) -> tuple[str, list[str]]:
    # 시스템 사전(엑셀 업로드 포함)을 검색 전처리에 즉시 반영합니다.
    try:
        return DictionaryService.normalize_query(query)
    except Exception:
        return query, []

class SearchService:
    
    # --- [3순위] 검색 실패 추적을 위한 로그 기록 함수 ---
    @staticmethod
    async def log_search_event(query: str, total_hits: int, user_id: str = "anonymous", is_failed: bool = None):
        log_index = "search_logs"
        # is_failed를 명시적으로 전달받으면 우선 사용, 없으면 total_hits 기준 판정
        failed_flag = is_failed if is_failed is not None else (total_hits == 0)
        log_doc = {
            "query": query,
            "query_keyword": query.strip(), # 분석용 키워드
            "total_hits": total_hits,
            "is_failed": failed_flag,
            "timestamp": datetime.now().isoformat(),
            "type": "manual_search", # 자동완성과 구분하기 위함
            "user_id": user_id,
        }
        try:
            client.index(index=log_index, body=log_doc)
        except Exception as e:
            print(f"로그 저장 실패: {e}")

        # 운영 리포트/추천용으로는 앱 DB를 기준 데이터로 사용합니다.
        try:
            DBService.save_search_log(user_id=user_id, query=query.strip(), total_hits=total_hits, is_failed=failed_flag)
            DBService.save_recent_search(user_id=user_id, query=query.strip())
        except Exception as e:
            print(f"앱 DB 로그 저장 실패: {e}")

    @staticmethod
    async def execute_search(req: SearchRequest):
        """
        하이브리드 검색 실행 (키워드 Bool + 벡터 KNN 결합)

        처리 흐름:
          1) 검색어 방역(sanitize) 및 오타 자동 교정 (hanspell)
          2) 동의어/사전 기반 잓워드 확장
          3) 초성 여부 판별 → 초성이면 wildcard, 아니면 복합 Bool
          4) 768차원 AI 벡터 변환 → KNN 보조 신호 추가
          5) 상세 필터 적용 (포함/제외 키워드, 파일형식, 기간, 작성자)
          6) ScoringConfigService 동적 가중치 적용
          7) 검색 로그 기록 (OpenSearch + 앱 DB)

        Args:
            req: SearchRequest DTO (쿼리, 페이지, 필터 등)
        Returns:
            dict: total, items, category_stats, page, corrected_query 등
        """
        index_name = settings.OPENSEARCH_INDEX
        
        # 1. 검색어 방역 및 오타 교정
        req.query = DocumentUtils.sanitize_text(req.query)
        original_query = req.query

        # 사전 기반 교정/불용어 제거를 우선 적용
        dict_normalized_query, dict_expanded_keywords = apply_runtime_dictionary(req.query)
        req.query = dict_normalized_query or req.query

        try:
            if _HAS_HANSPELL:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(spell_checker.check, req.query)
                    corrected = future.result(timeout=2)  # 최대 2초 대기
                    clean_query = corrected.checked
            else:
                clean_query = req.query
        except Exception:
            clean_query = req.query
        if clean_query == original_query:
            clean_query = normalize_common_typos(clean_query)
        is_typo_corrected = (clean_query != original_query)

        # 2. 검색어 확장 (동의어)
        target_keywords = [clean_query]
        for key, synonyms in SYNONYM_DICT.items():
            if key.lower() in clean_query.lower():
                target_keywords.extend(synonyms)
        target_keywords.extend(dict_expanded_keywords)
        
        # ---------------------------------------------------------
        # 🚀 [추가됨] 3. 쿼리 빌드 및 AI 벡터 변환 (하이브리드 장착)
        # ---------------------------------------------------------
        is_chosung = bool(re.match(r'^[ㄱ-ㅎ| ]+$', clean_query))
        
        # 프론트엔드에서 넘어온 검색어를 768차원 AI 숫자로 변환
        query_vector = []
        if not is_chosung:
            try:
                query_vector = embedder.get_embedding(clean_query)
            except Exception as e:
                print(f"AI 벡터 변환 실패 (일반 검색으로 진행): {e}")

        def build_weighted_query(keyword):
            """
            키워드 하나에 대한 가중치 적용 Bool 쿼리 생성
            - 초성 검색: wildcard 매칭 (chosung_text 필드)
            - 일반 검색: 제목 phrase(20배) > 제목 AND(10배) > 본문 phrase(5배) > 본문 AND(1배)
            - 가중치는 ScoringConfigService에서 동적으로 로드
            """
            w = ScoringConfigService.get_weights()
            if is_chosung:
                return { "wildcard": { "chosung_text": { "value": f"*{keyword}*", "boost": w["chosung"] } } }
            return {
                "bool": {
                    "should": [
                        { "match_phrase": { "Title": { "query": keyword, "boost": w["title_phrase"] } } }, 
                        { "match": { "Title": { "query": keyword, "boost": w["title_and"], "operator": "and" } } },
                        { "match_phrase": { "all_text": { "query": keyword, "boost": w["content_phrase"] } } },
                        { "match": { "all_text": { "query": keyword, "boost": w["content_and"], "operator": "and" } } }
                    ]
                }
            }

        search_clauses = [build_weighted_query(kw) for kw in target_keywords if kw]
        lexical_query = {
            "bool": {
                "should": search_clauses,
                "minimum_should_match": 1
            }
        }

        # KNN 벡터 쿼리는 BM25와 분리하여 보조 점수(should)로만 사용
        # → 키워드가 실제로 포함된 문서만 반환하되, 벡터 유사도로 순위 보정
        knn_should = []
        if query_vector:
            _w = ScoringConfigService.get_weights()
            knn_should.append({
                "knn": {
                    "text_vector": {
                        "vector": query_vector,
                        "k": req.size if hasattr(req, 'size') and req.size else 10,
                        "boost": _w["vector"]
                    }
                }
            })

        # 4. 전체 검색 바디 구성 (하이브리드 엔진 적용)
        # BM25 키워드 매칭 = must (필수), KNN 벡터 유사도 = should (보조 점수)
        page = req.page if req.page and req.page > 0 else 1
        offset = (page - 1) * req.size
        query_body = {
            "from": offset, "size": req.size,
            "min_score": ScoringConfigService.get_weights()["min_score"],
            "query": {
                "bool": {
                    "must": [lexical_query],
                    "should": knn_should,
                    "filter": []
                }
            },
            # 프론트엔드 보호를 위해 768개 숫자 데이터 숨김
            "_source": {"excludes": ["text_vector"]},
            "sort": [ { "_score": { "order": "desc" } }, { "indexed_at": { "order": "desc" } } ],
            "aggs": {
                "group_by_category": {
                    "terms": { "field": "doc_category" }
                }
            }
        }

        # --- [1순위] 상세 필터 로직 강화 ---
        filters = query_body["query"]["bool"]["filter"]
        if req.start_date:
            filters.append({"range": {"indexed_at": {"gte": req.start_date}}})
        if req.file_ext:
            filters.append({"term": {"file_ext": req.file_ext.lower()}})
        if req.doc_category:
            filters.append({"term": {"doc_category": req.doc_category}})

        if req.end_date:
            filters.append({"range": {"indexed_at": {"lte": req.end_date}}})

        if req.include_keywords:
            for keyword in req.include_keywords:
                safe_kw = DocumentUtils.sanitize_text(keyword)
                if safe_kw:
                    # Title 또는 본문 중 하나라도 포함하면 통과 (제목 검색 누락 방지)
                    filters.append({
                        "bool": {
                            "should": [
                                {"match_phrase": {"all_text": safe_kw}},
                                {"match_phrase": {"Title": safe_kw}},
                            ],
                            "minimum_should_match": 1,
                        }
                    })

        if req.exclude_keywords:
            must_not = query_body["query"]["bool"].setdefault("must_not", [])
            for keyword in req.exclude_keywords:
                safe_kw = DocumentUtils.sanitize_text(keyword)
                if safe_kw:
                    # Title 또는 본문 중 하나라도 포함하면 제외
                    must_not.append({
                        "bool": {
                            "should": [
                                {"match_phrase": {"all_text": safe_kw}},
                                {"match_phrase": {"Title": safe_kw}},
                            ],
                            "minimum_should_match": 1,
                        }
                    })
        
        # 신규 추가: 작성자 필터링
        if hasattr(req, 'author') and req.author:
            filters.append({"term": {"author.keyword": req.author}})
            
        # 신규 추가: 최소 점수 필터링 (품질 제어)
        if hasattr(req, 'min_score') and req.min_score > 0:
            query_body["min_score"] = req.min_score

        # 6. OpenSearch 실행
        try:
            response = client.search(index=index_name, body=query_body)
            total_hits = response['hits']['total']['value']

            # [여기에 딱 2줄 추가!] 터미널 창에 1등 문서 점수 출력하기
            if response['hits']['hits']:
                print(f"👉 [점수 확인] '{req.query}' 검색 ➡️ 최고 점수: {response['hits']['hits'][0]['_score']}")            

            # --- [3순위] 검색 실패 및 통계 추적 로그 남기기 ---
            # 벡터 단독 매칭을 제외하고, 정확 구문(제목/본문) 기준으로 실패 여부를 엄격 판정
            try:
                strict_phrase_query = {
                    "bool": {
                        "should": [
                            {"match_phrase": {"Title": clean_query}},
                            {"match_phrase": {"all_text": clean_query}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
                strict_count_resp = client.count(
                    index=index_name, body={"query": strict_phrase_query}
                )
                strict_hits = strict_count_resp.get("count", 0)
            except Exception:
                strict_hits = 0
            is_failed_flag = (strict_hits == 0)

            await SearchService.log_search_event(clean_query, total_hits, req.user_id or "anonymous", is_failed=is_failed_flag)
            
            # 카테고리 통계 추출
            buckets = response.get('aggregations', {}).get('group_by_category', {}).get('buckets', [])
            category_stats = {b['key']: b['doc_count'] for b in buckets}

            raw_hits = response.get('hits', {}).get('hits', [])

            # 오타 교정이 발생한 경우, 정확히 포함되는 결과가 있으면 벡터 단독 저점수 결과는 제외합니다.
            if is_typo_corrected and clean_query:
                exact_hits = [
                    hit for hit in raw_hits
                    if contains_exact_keyword(hit.get('_source', {}), clean_query)
                ]
                if exact_hits:
                    raw_hits = exact_hits
                    total_hits = len(raw_hits)

                    recalc_stats = {}
                    for hit in raw_hits:
                        cat = (hit.get('_source', {}) or {}).get('doc_category')
                        if cat:
                            recalc_stats[cat] = recalc_stats.get(cat, 0) + 1
                    category_stats = recalc_stats

            # 이름형 쿼리(예: 홍길동, 강광민김영민)는 최종 결과를 정확 포함 기준으로 거릅니다.
            if is_name_like_query(clean_query):
                raw_hits = [
                    hit for hit in raw_hits
                    if contains_exact_keyword(hit.get('_source', {}), clean_query)
                ]
                total_hits = len(raw_hits)

                recalc_stats = {}
                for hit in raw_hits:
                    cat = (hit.get('_source', {}) or {}).get('doc_category')
                    if cat:
                        recalc_stats[cat] = recalc_stats.get(cat, 0) + 1
                category_stats = recalc_stats

            # 결과 가공
            processed_results = []
            for hit in raw_hits:
                # [추가] 모든 문서의 실제 점수를 터미널에 까발려라!
                print(f"📄 문서: {hit['_source'].get('Title')} ➡️ 점수: {hit['_score']}")
                source = hit['_source']
                raw_text = source.get("all_text", "")
                summary, page_num = None, "1"
                if is_chosung:
                    summary, page_num = manual_chosung_highlight(raw_text, clean_query)
                else:
                    for kw in target_keywords:
                        summary, page_num = manual_text_highlight(raw_text, kw)
                        if summary: break
                
                if not summary:
                    summary = (raw_text[:200] + "...") if raw_text else "내용 없음"

                processed_results.append({
                    "id": hit["_id"],
                    "location": f"{page_num}페이지", 
                    "content": source,
                    "summary": summary,
                    "score": hit["_score"],
                    "indexed_at": source.get("indexed_at", "")
                })

            return {
                "total": total_hits,
                "items": processed_results,
                "category_stats": category_stats,
                "page": page,
                "size": req.size,
                "original_query": original_query,
                "corrected_query": clean_query,
                "is_typo_corrected": is_typo_corrected,
            }
        except Exception as e:
            print(f"Search Error: {str(e)}")
            return {
                "total": 0,
                "items": [],
                "category_stats": {},
                "error": str(e),
                "page": page,
                "size": req.size,
                "original_query": original_query,
                "corrected_query": clean_query,
                "is_typo_corrected": is_typo_corrected,
            }

    @staticmethod
    async def get_autocomplete(q: str):
        """
        초성+키워드 자동완성 후보 제시
        - 초성만 입력 시: chosung_text 필드에 wildcard 매칭
        - 일반 텍스트 입력 시: Title 필드에 match_phrase_prefix 매칭
        - 최대 5건의 문서명을 중복 제거 후 반환
        """
        index_name = settings.OPENSEARCH_INDEX
        safe_q = DocumentUtils.sanitize_text(q)
        if not safe_q: return []
        
        is_chosung = bool(re.match(r'^[ㄱ-ㅎ| ]+$', safe_q))
        if is_chosung:
            query = { "query": { "wildcard": { "chosung_text": f"*{safe_q}*" } } }
        else:
            query = { "query": { "match_phrase_prefix": { "Title": safe_q } } }
        
        try:
            res = client.search(index=index_name, body={**query, "size": 5, "_source": ["Title"]})
            return list(set([h['_source']['Title'] for h in res['hits']['hits'] if h['_source'].get('Title')]))
        except:
            return []
        
    # 
    @staticmethod
    async def get_popular_keywords(limit: int = 10):
        """앱 DB에서 최근 검색 로그를 기준으로 인기 검색어를 반환"""
        try:
            from app.services.system_service import PopularConfigService
            settings = PopularConfigService.get_settings()
            days = settings["days"]
            return DBService.get_popular_keywords(days=days, limit=limit)
        except Exception as e:
            print(f"인기 검색어 추출 에러: {e}")
            return []
        
    @staticmethod
    async def get_failed_analysis(days: int = 7):
        """최근 N일간 결과가 0건이었던 검색어들을 집계하여 빈도순으로 반환"""
        try:
            return DBService.get_failed_keywords(days=days, limit=10)
        except Exception as e:
            return {"error": str(e), "message": "앱 DB 실패어 분석 중 오류가 발생했습니다."}

    @staticmethod
    async def get_recent_keywords(user_id: str = "anonymous", limit: int = 10):
        """사용자별 최근 검색어 목록 조회 (앱 DB 기준, 최신순)"""
        try:
            return DBService.get_recent_searches(user_id=user_id, limit=limit)
        except Exception:
            return []

    @staticmethod
    async def remove_recent_keyword(user_id: str = "anonymous", query: str = ""):
        safe_query = DocumentUtils.sanitize_text(query)
        if not safe_query:
            return {"deleted": 0, "message": "삭제할 검색어가 비어있습니다."}
        try:
            deleted = DBService.remove_recent_search(user_id=user_id, query=safe_query)
            return {"deleted": deleted}
        except Exception as e:
            return {"deleted": 0, "error": str(e)}

    @staticmethod
    async def clear_recent_keywords(user_id: str = "anonymous"):
        try:
            deleted = DBService.clear_recent_searches(user_id=user_id)
            return {"deleted": deleted}
        except Exception as e:
            return {"deleted": 0, "error": str(e)}

    @staticmethod
    async def get_recommended_keywords(user_id: str = "anonymous", limit: int = 10):
        """사용자 맞춤형 추천 검색어 제안 (최근 검색어 + 인기 검색어 병합)"""
        try:
            return DBService.get_recommended_keywords(user_id=user_id, limit=limit)
        except Exception:
            return []

    @staticmethod
    async def get_related_keywords(query: str, days: int = 30, limit: int = 10):
        """연관 검색어 추천 (토큰 자카드 유사도 + 빈도 기반 산출)"""
        try:
            return DBService.get_related_keywords(query=query, days=days, limit=limit)
        except Exception:
            return []

    @staticmethod
    async def get_document_detail(doc_id: str):
        """OpenSearch 문서 ID로 전문 조회 (text_vector 제외하지 않은 전체 _source 반환)"""
        index_name = settings.OPENSEARCH_INDEX
        res = client.get(index=index_name, id=doc_id)
        return res.get("_source", {})

    @staticmethod
    async def setup_hybrid_index():
        """기존 인덱스에 AI 벡터(k-NN) 검색용 필드와 세팅을 추가합니다."""
        index_name = settings.OPENSEARCH_INDEX
        try:
            # 1. 인덱스 설정 변경을 위해 잠시 가게 문 닫기 (데이터는 안전하게 유지됨)
            client.indices.close(index=index_name)
            
            # 2. DB에 k-NN(벡터 검색) 엔진 전원 켜기
            client.indices.put_settings(
                index=index_name, 
                body={"index": {"knn": True}}
            )
            
            # 3. 인테리어 끝났으니 가게 문 다시 열기
            client.indices.open(index=index_name)
            
            # 4. 768차원 숫자가 들어갈 'text_vector' 라는 특수 방 만들기
            mapping = {
                "properties": {
                    "text_vector": {
                        "type": "knn_vector",
                        "dimension": 768, # 우리가 깐 모델(sroberta)의 벡터 크기
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "nmslib"
                        }
                    }
                }
            }
            client.indices.put_mapping(index=index_name, body=mapping)
            
            return {"status": "success", "message": f"[{index_name}] 인덱스 하이브리드 벡터 세팅 완료!"}
            
        except Exception as e:
            # 만약 에러가 나더라도 가게 문이 닫혀있으면 안 되므로 강제로 다시 열어줌
            client.indices.open(index=index_name)
            return {"status": "error", "message": str(e)}        