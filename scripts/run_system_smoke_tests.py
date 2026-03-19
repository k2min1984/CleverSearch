from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from app.main import app


def assert_check(name: str, passed: bool, details: dict) -> dict:
    return {"name": name, "passed": passed, "details": details}


def run() -> dict:
    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
    }

    with TestClient(app) as client:
        viewer_headers = {"X-Role": "viewer"}
        operator_headers = {"X-Role": "operator"}
        admin_headers = {"X-Role": "admin"}

        # JWT 로그인/재발급/로그아웃
        login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123!"})
        login_payload = login.json() if login.status_code == 200 else {}
        access_token = login_payload.get("access_token", "")
        refresh_token = login_payload.get("refresh_token", "")

        refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token}) if refresh_token else None
        refresh_payload = refresh.json() if refresh and refresh.status_code == 200 else {}
        refreshed_access = refresh_payload.get("access_token", "")

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {refreshed_access}"} if refreshed_access else {},
            json={"refresh_token": refresh_payload.get("refresh_token")},
        )

        revoked_call = client.post(
            "/api/v1/system/volume/create",
            headers={"Authorization": f"Bearer {refreshed_access}"} if refreshed_access else {},
            json={"index_name": "revoked-smoke-index", "shards": 1, "replicas": 0},
        )

        results["checks"].append(
            assert_check(
                "jwt_lifecycle",
                login.status_code == 200
                and bool(access_token)
                and bool(refresh_token)
                and bool(refresh)
                and refresh.status_code == 200
                and logout.status_code == 200
                and revoked_call.status_code == 401,
                {
                    "login": login.status_code,
                    "refresh": refresh.status_code if refresh else None,
                    "logout": logout.status_code,
                    "revoked_call": revoked_call.status_code,
                },
            )
        )

        # RBAC 기본 동작
        r1 = client.get("/api/v1/admin/popular-keywords", headers=viewer_headers)
        r2 = client.post(
            "/api/v1/system/volume/create",
            headers=viewer_headers,
            json={"index_name": "smoke-volume-viewer", "shards": 1, "replicas": 0},
        )
        results["checks"].append(
            assert_check(
                "rbac_viewer_restriction",
                r1.status_code == 200 and r2.status_code == 403,
                {"admin_read_status": r1.status_code, "volume_create_by_viewer": r2.status_code},
            )
        )

        # 사전 단건 등록/조회
        entry = client.post(
            "/api/v1/system/dictionary/entry",
            params={"dict_type": "synonym", "term": "AI", "replacement": "인공지능"},
            headers=operator_headers,
        )
        entries = client.get("/api/v1/system/dictionary/entries", headers=viewer_headers)
        entries_data = entries.json() if entries.status_code == 200 else []
        has_ai_synonym = any((row.get("term") == "AI" and row.get("dict_type") == "synonym") for row in entries_data)
        results["checks"].append(
            assert_check(
                "dictionary_upsert_and_list",
                entry.status_code == 200 and entries.status_code == 200 and has_ai_synonym,
                {"upsert_status": entry.status_code, "list_status": entries.status_code, "has_ai_synonym": has_ai_synonym},
            )
        )

        # 스케줄러 생명주기
        s_start = client.post("/api/v1/system/scheduler/start", params={"interval_seconds": 30}, headers=operator_headers)
        s_status = client.get("/api/v1/system/scheduler/status", headers=viewer_headers)
        s_stop = client.post("/api/v1/system/scheduler/stop", headers=operator_headers)
        status_payload = s_status.json() if s_status.status_code == 200 else {}
        results["checks"].append(
            assert_check(
                "scheduler_lifecycle",
                s_start.status_code == 200 and s_status.status_code == 200 and s_stop.status_code == 200 and bool(status_payload.get("running")),
                {
                    "start_status": s_start.status_code,
                    "status_status": s_status.status_code,
                    "stop_status": s_stop.status_code,
                    "running": status_payload.get("running"),
                },
            )
        )

        # 대시보드 API
        d1 = client.get("/api/v1/system/dashboard/summary", params={"days": 7}, headers=viewer_headers)
        d2 = client.get("/api/v1/system/dashboard/trend", params={"days": 14}, headers=viewer_headers)
        d3 = client.get("/api/v1/system/health/overview", headers=viewer_headers)
        d4 = client.get("/api/v1/system/dashboard/alerts", headers=viewer_headers)
        results["checks"].append(
            assert_check(
                "dashboard_endpoints",
                d1.status_code == 200 and d2.status_code == 200 and d3.status_code == 200 and d4.status_code == 200,
                {
                    "summary_status": d1.status_code,
                    "trend_status": d2.status_code,
                    "health_status": d3.status_code,
                    "alerts_status": d4.status_code,
                },
            )
        )

        # SMB/DB 소스 등록 및 조회
        smb_create = client.post(
            "/api/v1/system/smb/sources",
            headers=operator_headers,
            json={
                "name": "smoke-smb",
                "share_path": "C:\\",
                "username": None,
                "password": None,
                "is_active": False,
            },
        )
        smb_list = client.get("/api/v1/system/smb/sources", headers=viewer_headers)
        smb_ok = smb_create.status_code == 200 and smb_list.status_code == 200

        db_create = client.post(
            "/api/v1/system/db/sources",
            headers=operator_headers,
            json={
                "name": "smoke-db",
                "db_type": "sqlite",
                "connection_url": "sqlite:///./cleversearch_app.db",
                "query_text": "SELECT 'smoke-title' AS title, 'smoke-content' AS content",
                "title_column": "title",
                "chunk_size": 100,
                "is_active": False,
            },
        )
        db_list = client.get("/api/v1/system/db/sources", headers=viewer_headers)
        db_ok = db_create.status_code == 200 and db_list.status_code == 200

        results["checks"].append(
            assert_check(
                "source_upsert_and_list",
                smb_ok and db_ok,
                {
                    "smb_create": smb_create.status_code,
                    "smb_list": smb_list.status_code,
                    "db_create": db_create.status_code,
                    "db_list": db_list.status_code,
                },
            )
        )

        # SSL 스크립트 생성/상태 조회
        certs = client.get("/api/v1/system/ssl/certificates", params={"cert_dir": "cert", "warn_days": 30}, headers=viewer_headers)
        renew = client.post(
            "/api/v1/system/ssl/renew-script",
            params={"output_path": "scripts/renew_certs.ps1"},
            headers=admin_headers,
        )
        renew_payload = renew.json() if renew.status_code == 200 else {}
        script_path = renew_payload.get("script_path", "scripts/renew_certs.ps1")
        results["checks"].append(
            assert_check(
                "ssl_status_and_script",
                certs.status_code == 200 and renew.status_code == 200 and Path(script_path).exists(),
                {"certs_status": certs.status_code, "renew_status": renew.status_code, "script_path": script_path},
            )
        )

    results["ended_at"] = datetime.now(timezone.utc).isoformat()
    results["passed"] = all(row["passed"] for row in results["checks"])
    return results


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
