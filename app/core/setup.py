"""
########################################################
# Description
# OpenSearch 인덱스 초기화 및 매핑(Schema) 설정
# - 한국어 형태소 분석기(Nori) 상세 설정
# - 데이터 필드 타입 및 분석기 적용
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
########################################################
"""

from app.core.opensearch import get_client
from app.core.config import settings

def create_index():
    """
    CleverSearch 전용 인덱스를 생성하고 Nori 분석기를 설정합니다.
    이미 인덱스가 존재하면 생성을 건너뜁니다.
    """
    client = get_client()
    index_name = settings.OPENSEARCH_INDEX  # "cleversearch-docs"

    # [인덱스 설정 정의]
    body = {
        "settings": {
            "index": {
                "analysis": {
                    # 1. 토크나이저 설정 (Nori Custom)
                    "tokenizer": {
                        "nori_token_mixed": {
                            "type": "nori_tokenizer",
                            # decompound_mode: mixed
                            # "가공식품" -> "가공식품", "가공", "식품" 모두 토큰화 (재현율 향상)
                            "decompound_mode": "mixed" 
                        }
                    },
                    # 2. 분석기 설정 (Tokenizer + Filter)
                    "analyzer": {
                        "clever_korean_analyzer": {
                            "type": "custom",
                            "tokenizer": "nori_token_mixed",
                            "filter": [
                                "lowercase",          # 영문 소문자 변환
                                "nori_part_of_speech" # 불용어(조사, 어미 등) 제거 필터
                            ]
                        }
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                # [메타데이터] 정확한 매칭을 위해 keyword 타입 사용
                "origin_file": {"type": "keyword"},
                "origin_sheet": {"type": "keyword"},
                
                # [검색 대상] 형태소 분석기가 적용된 핵심 텍스트 필드
                # file.py에서 'all_text'로 합쳐서 넣기로 한 필드입니다.
                "all_text": {
                    "type": "text", 
                    "analyzer": "clever_korean_analyzer",       # 색인 시 사용
                    "search_analyzer": "clever_korean_analyzer" # 검색 시 사용
                },
                
                # [날짜/숫자] 범위 검색용
                "indexed_at": {"type": "date"},
                
                # [통계/정렬]
                "search_count": {"type": "integer"} 
            }
        }
    }

    try:
        if not client.indices.exists(index=index_name):
            client.indices.create(index=index_name, body=body)
            print(f"✅ 인덱스 생성 완료: '{index_name}' (Nori Analyzer 적용됨)")
        else:
            print(f"ℹ️ 인덱스가 이미 존재합니다: '{index_name}'")
            
    except Exception as e:
        print(f"❌ 인덱스 생성 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    create_index()