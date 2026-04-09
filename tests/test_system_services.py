"""
########################################################
# Description
# 시스템 서비스 단위 테스트
# 사전/대시보드/스케줄러/SSL 서비스 기능 테스트
#
# Modified History
# 강광민 / 2026-03-19 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import DictionaryEntry, SearchLog, SessionLocal, init_database
from app.services.dictionary_service import DictionaryService
from app.services.system_service import DashboardService, IngestionSchedulerService, VolumeSSLService


class TestSystemServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(DictionaryEntry).delete()
            db.query(SearchLog).delete()
            db.commit()
        finally:
            db.close()

    def test_dictionary_upsert_and_normalize(self):
        DictionaryService.upsert_entry("stopword", "에")
        DictionaryService.upsert_entry("synonym", "AI", "인공지능")
        DictionaryService.upsert_entry("user", "게획", "계획")

        normalized, expanded = DictionaryService.normalize_query("AI 게획 에")
        self.assertIn("인공지능", expanded)
        self.assertIn("계획", normalized)
        self.assertNotIn(" 에 ", f" {normalized} ")

    def test_dashboard_summary(self):
        db = SessionLocal()
        try:
            db.add(SearchLog(user_id="u1", query="검색", total_hits=3, is_failed=False))
            db.add(SearchLog(user_id="u2", query="없는검색", total_hits=0, is_failed=True))
            db.commit()
        finally:
            db.close()

        summary = DashboardService.summary(days=30)
        self.assertEqual(summary["total_logs"], 2)
        self.assertEqual(summary["failed_logs"], 1)

    def test_scheduler_lifecycle(self):
        started = IngestionSchedulerService.start(interval_seconds=10)
        self.assertIn(started["status"], ["started", "already-running"])
        status = IngestionSchedulerService.status()
        self.assertTrue(status["running"])
        stopped = IngestionSchedulerService.stop()
        self.assertIn(stopped["status"], ["stopped", "already-stopped"])

    def test_renew_script_generation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = str(Path(tmp_dir) / "renew.ps1")
            result = VolumeSSLService.generate_renew_script(output_path=script_path)
            self.assertEqual(result["status"], "generated")
            self.assertTrue(Path(script_path).exists())

    def test_admin_smoke_endpoint(self):
        with TestClient(app) as client:
            login_res = client.post(
                "/api/v1/common/auth/login",
                json={"username": "admin", "password": "admin123!"},
            )
            self.assertEqual(login_res.status_code, 200)
            token = login_res.json().get("access_token")
            self.assertTrue(token)

            with patch("app.api.admin.system.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "smoke ok"
                mock_run.return_value.stderr = ""

                res = client.post(
                    "/api/v1/admin/system/ops/run-smoke-test",
                    headers={"Authorization": f"Bearer {token}"},
                )

            self.assertEqual(res.status_code, 200)
            payload = res.json()
            self.assertEqual(payload.get("status"), "success")
            self.assertEqual(payload.get("exit_code"), 0)

    def test_scheduler_stop_endpoint(self):
        with TestClient(app) as client:
            login_res = client.post(
                "/api/v1/common/auth/login",
                json={"username": "admin", "password": "admin123!"},
            )
            self.assertEqual(login_res.status_code, 200)
            token = login_res.json().get("access_token")
            self.assertTrue(token)

            res = client.post(
                "/api/v1/admin/system/scheduler/stop",
                headers={"Authorization": f"Bearer {token}"},
            )

            self.assertEqual(res.status_code, 200)
            payload = res.json()
            self.assertIn(payload.get("status"), ["stopped", "already-stopped"])


if __name__ == "__main__":
    unittest.main()
