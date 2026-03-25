"""
########################################################
# Description
# AI 텍스트 임베딩 모듈
# SentenceTransformer(ko-sroberta-multitask) 모델로
# 한국어 텍스트를 768차원 벡터로 변환
# - 색인 시 문서 본문 → 벡터 임베딩
# - 검색 시 쿼리 → 벡터 임베딩 (KNN 유사도 검색)
# - 서버 시작 시 모델 선로딩 (최초 검색 지연 방지)
#
# Modified History
# 강광묵 / 2026-01-20 / 최초생성
# 강광민 / 2026-03-25 / Lazy Loading 적용 (서버 기동 속도 개선)
# 강광민 / 2026-03-25 / 서버 시작 시 선로딩으로 복귀 (대국민 서비스 초기 응답 안정화)
########################################################
"""
from sentence_transformers import SentenceTransformer

# 한국어 문맥과 의미를 가장 잘 파악하는 검증된 무료 모델 (약 400MB)
MODEL_NAME = 'jhgan/ko-sroberta-multitask'

class AIEmbedder:
    def __init__(self):
        print("🚀 AI 임베딩 모델 로딩 중... (최초 1회 다운로드 발생)")
        self.model = SentenceTransformer(MODEL_NAME)
        print("✅ AI 임베딩 모델 로딩 완료!")

    def get_embedding(self, text: str):
        """텍스트를 입력받아 768차원의 벡터(숫자 리스트)로 변환합니다."""
        if not text:
            return []
        # 텍스트를 벡터로 인코딩 후 파이썬 리스트로 변환
        vector = self.model.encode(text)
        return vector.tolist()

# 서버가 켜질 때 한 번만 생성해서 돌려쓰기 위함 (싱글톤 패턴 메모리 절약)
# 서버 시작 시 즉시 모델을 로드하여 최초 검색 지연을 없앱니다.
embedder = AIEmbedder()