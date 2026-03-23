"""
########################################################
# Description
# 평가 지표 단위 테스트
# nDCG@k, MRR@k 계산 결과 정확성 검증
#
# Modified History
# 강광민 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import unittest

from app.utils.evaluation import evaluate_queries, mrr_at_k, ndcg_at_k


class TestEvaluationMetrics(unittest.TestCase):
    def test_ndcg_and_mrr_positive(self):
        predicted = ["A", "B", "C"]
        relevant = ["B", "D"]

        ndcg = ndcg_at_k(predicted, relevant, k=3)
        mrr = mrr_at_k(predicted, relevant, k=3)

        self.assertGreater(ndcg, 0)
        self.assertEqual(mrr, 0.5)

    def test_evaluate_queries_summary(self):
        rows = [
            {"predicted": ["A", "B"], "relevant": ["A"]},
            {"predicted": ["X", "Y"], "relevant": ["Z"]},
        ]
        summary = evaluate_queries(rows, k=2)

        self.assertEqual(summary["queries"], 2)
        self.assertIn("avg_ndcg", summary)
        self.assertIn("avg_mrr", summary)


if __name__ == "__main__":
    unittest.main()
