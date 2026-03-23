"""
########################################################
# Description
# 인증/보안 단위 테스트
# 로그인, 토큰 발급, RBAC 권한 검증 등 인증 흐름 테스트
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import unittest

from fastapi.testclient import TestClient

from app.main import app


class TestAuthSecurity(unittest.TestCase):
    def test_login_and_token_access(self):
        with TestClient(app) as client:
            login_res = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin123!"},
            )
            self.assertEqual(login_res.status_code, 200)
            token = login_res.json().get("access_token")
            refresh = login_res.json().get("refresh_token")
            self.assertTrue(token)
            self.assertTrue(refresh)

            viewer_forbidden = client.post(
                "/api/v1/system/volume/create",
                headers={"X-Role": "viewer"},
                json={"index_name": "auth-test-index-xrole", "shards": 1, "replicas": 0},
            )
            self.assertEqual(viewer_forbidden.status_code, 403)

            admin_allowed = client.post(
                "/api/v1/system/volume/create",
                headers={"Authorization": f"Bearer {token}"},
                json={"index_name": "auth-test-index-jwt", "shards": 1, "replicas": 0},
            )
            self.assertIn(admin_allowed.status_code, [200])

            refresh_res = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh},
            )
            self.assertEqual(refresh_res.status_code, 200)
            refreshed_access = refresh_res.json().get("access_token")
            refreshed_refresh = refresh_res.json().get("refresh_token")
            self.assertTrue(refreshed_access)
            self.assertTrue(refreshed_refresh)

            refresh_reuse = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh},
            )
            self.assertEqual(refresh_reuse.status_code, 401)

            logout_res = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {refreshed_access}"},
                json={"refresh_token": refreshed_refresh},
            )
            self.assertEqual(logout_res.status_code, 200)

            revoked_access = client.post(
                "/api/v1/system/volume/create",
                headers={"Authorization": f"Bearer {refreshed_access}"},
                json={"index_name": "auth-test-index-revoked", "shards": 1, "replicas": 0},
            )
            self.assertEqual(revoked_access.status_code, 401)


if __name__ == "__main__":
    unittest.main()
