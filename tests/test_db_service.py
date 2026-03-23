"""
########################################################
# Description
# DB 서비스 단위 테스트
# 검색 로그, 최근 검색어, 인기 검색어 집계 등 DB 로직 테스트
#
# Modified History
# 강광민 / 2026-03-17 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import unittest

from app.core.database import RecentSearch, SearchLog, SessionLocal, init_database
from app.services.db_service import DBService


class TestDBService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(RecentSearch).delete()
            db.query(SearchLog).delete()
            db.commit()
        finally:
            db.close()

    def test_recent_search_keeps_latest(self):
        user_id = "tester"
        DBService.save_recent_search(user_id=user_id, query="인공지능")
        DBService.save_recent_search(user_id=user_id, query="검색")
        DBService.save_recent_search(user_id=user_id, query="인공지능")

        recent = DBService.get_recent_searches(user_id=user_id, limit=10)
        self.assertEqual(recent[0], "인공지능")
        self.assertIn("검색", recent)

    def test_popular_and_failed_keywords(self):
        DBService.save_search_log(user_id="u1", query="한전", total_hits=3)
        DBService.save_search_log(user_id="u1", query="한전", total_hits=1)
        DBService.save_search_log(user_id="u2", query="원전", total_hits=0)

        popular = DBService.get_popular_keywords(days=30, limit=5)
        failed = DBService.get_failed_keywords(days=30, limit=5)

        self.assertEqual(popular[0], "한전")
        self.assertTrue(any(item["keyword"] == "원전" for item in failed))

    def test_related_and_recommend(self):
        DBService.save_search_log(user_id="u1", query="원전 계획", total_hits=2)
        DBService.save_search_log(user_id="u1", query="원전 정비", total_hits=1)
        DBService.save_search_log(user_id="u1", query="일반 문서", total_hits=1)
        DBService.save_recent_search(user_id="u1", query="원전 계획")

        related = DBService.get_related_keywords(query="원전", days=30, limit=10)
        recommend = DBService.get_recommended_keywords(user_id="u1", limit=10)

        self.assertIn("원전 계획", related)
        self.assertIn("원전 계획", recommend)


if __name__ == "__main__":
    unittest.main()
