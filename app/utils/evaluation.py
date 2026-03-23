"""
########################################################
# Description
# 검색 품질 평가 유틸리티
# 정보 검색(IR) 평가 지표 계산
# - DCG / nDCG@k (Normalized Discounted Cumulative Gain)
# - MRR@k (Mean Reciprocal Rank)
# - Precision@k / Recall@k
#
# Modified History
# 강광민 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from typing import Iterable, Sequence
import math


def dcg(relevances: Sequence[float]) -> float:
    # 랭킹 상단 결과에 더 큰 가중치를 두는 기본 DCG 계산입니다.
    score = 0.0
    for idx, rel in enumerate(relevances, start=1):
        if idx == 1:
            score += rel
        else:
            score += rel / math.log2(idx + 1)
    return score


def ndcg_at_k(predicted: Sequence[str], relevant: Iterable[str], k: int = 10) -> float:
    # 정답셋 대비 현재 검색 결과 순위 품질을 0~1 범위로 환산합니다.
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    gains = [1.0 if title in relevant_set else 0.0 for title in predicted[:k]]
    ideal = [1.0] * min(len(relevant_set), k)

    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return dcg(gains) / ideal_dcg


def mrr_at_k(predicted: Sequence[str], relevant: Iterable[str], k: int = 10) -> float:
    # 첫 정답 문서가 몇 번째에 등장했는지 역수 점수로 계산합니다.
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    for idx, title in enumerate(predicted[:k], start=1):
        if title in relevant_set:
            return 1.0 / idx
    return 0.0


def evaluate_queries(results: list[dict], k: int = 10) -> dict:
    # 여러 질의를 한 번에 평가할 때 평균 NDCG/MRR를 반환합니다.
    if not results:
        return {"queries": 0, "avg_ndcg": 0.0, "avg_mrr": 0.0}

    ndcgs = [ndcg_at_k(r.get("predicted", []), r.get("relevant", []), k=k) for r in results]
    mrrs = [mrr_at_k(r.get("predicted", []), r.get("relevant", []), k=k) for r in results]

    return {
        "queries": len(results),
        "avg_ndcg": round(sum(ndcgs) / len(ndcgs), 4),
        "avg_mrr": round(sum(mrrs) / len(mrrs), 4),
    }
