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

    # [인덱스 설정 정의] — IndexingService.ensure_index()와 동일한 매핑 사용
    body = {
        "settings": {
            "index": {
                "knn": True,
                "analysis": {
                    "analyzer": {
                        "korean_analyzer": {
                            "type": "custom",
                            "tokenizer": "nori_tokenizer",
                            "filter": ["lowercase", "nori_readingform", "my_stop_filter"],
                        }
                    },
                    "filter": {
                        "my_stop_filter": {
                            "type": "stop",
                            "stopwords": ["에", "대해서", "해주세요", "알려주세요", "의", "를", "은", "는"],
                        }
                    },
                },
            }
        },
        "mappings": {
            "properties": {
                "Title": {"type": "text", "analyzer": "korean_analyzer"},
                "all_text": {"type": "text", "analyzer": "korean_analyzer"},
                "doc_category": {"type": "keyword"},
                "chosung_text": {"type": "text", "analyzer": "whitespace"},
                "origin_file": {"type": "keyword"},
                "file_ext": {"type": "keyword"},
                "content_hash": {"type": "keyword"},
                "indexed_at": {"type": "date"},
                "text_vector": {"type": "knn_vector", "dimension": 768},
            }
        },
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