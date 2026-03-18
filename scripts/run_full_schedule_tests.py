from __future__ import annotations

import json
import mimetypes
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import IndexedDocument, RecentSearch, SearchLog, get_db_session
from app.core.opensearch import get_client
from app.main import app


DATA_DIR = Path(r"C:\Users\CLEVER_KKMIN\Desktop\테스트용 문서 파일")

ORIGINAL_UPLOADS = [
    "(산업부)_2026년도_산업기술혁신사업_통합_시행계획_공고문.hwp",
    "1. 연구개발계획서 양식_울산지방청.pdf",
    "2026_운영지침_보안.pdf.jpg",
    "대용량_테스트_데이터_7만건.xlsx",
    "연구개발계획서_작성중.docx",
    "이미지PDF.pdf",
    "제조의_심장을_지킬_AI_주치의-5.jpg",
    "통합검색솔루션_종합문서_20260123_V001 - 복사본.xlsx",
    "AI개발진행-20251201.pptx",
]

DUPLICATE_UPLOADS = [
    "test.docx",
    "test.hwp",
    "test.jpg",
    "test.pdf",
    "test.pptx",
    "test.xlsx",
]

SEARCH_EXPECTATIONS = {
    "산업기술혁신사업": ["(산업부)_2026년도_산업기술혁신사업_통합_시행계획_공고문.hwp"],
    "연구개발계획서": ["1. 연구개발계획서 양식_울산지방청.pdf", "연구개발계획서_작성중.docx"],
    "운영지침": ["2026_운영지침_보안.pdf.jpg"],
    "보안": ["2026_운영지침_보안.pdf.jpg"],
    "AI개발진행": ["AI개발진행-20251201.pptx"],
    "통합검색솔루션": ["통합검색솔루션_종합문서_20260123_V001 - 복사본.xlsx"],
    "7만건": ["대용량_테스트_데이터_7만건.xlsx"],
}

NAME_QUERIES = ["강광민", "홍길동", "김영희"]
POPULAR_QUERIES = ["연구개발계획서", "산업기술혁신사업", "보안"]
RECENT_USER_ID = "schedule-test-user"
FAIL_QUERY = "ZXCVBNM존재하지않는키워드"


def reset_state() -> dict:
    client = get_client()
    index_results = {}
    for index_name in [settings.OPENSEARCH_INDEX, "search_logs"]:
        exists = client.indices.exists(index=index_name)
        index_results[index_name] = {"exists_before": bool(exists)}
        if exists:
            client.indices.delete(index=index_name)
            index_results[index_name]["deleted"] = True
        else:
            index_results[index_name]["deleted"] = False

    with get_db_session() as db:
        indexed_deleted = db.query(IndexedDocument).delete(synchronize_session=False)
        recent_deleted = db.query(RecentSearch).delete(synchronize_session=False)
        search_deleted = db.query(SearchLog).delete(synchronize_session=False)

    return {
        "opensearch": index_results,
        "db_deleted": {
            "indexed_documents": indexed_deleted,
            "recent_searches": recent_deleted,
            "search_logs": search_deleted,
        },
    }


def api_json(response):
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def assert_result(name: str, passed: bool, details: dict) -> dict:
    return {"name": name, "passed": passed, "details": details}


def upload_one(client: TestClient, path: Path) -> dict:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as fh:
        response = client.post(
            "/api/v1/file/upload",
            files={"file": (path.name, fh, mime_type)},
        )
    payload = api_json(response)
    return {
        "file": path.name,
        "status_code": response.status_code,
        "payload": payload,
    }


def search(client: TestClient, query: str, **kwargs) -> dict:
    payload = {
        "query": query,
        "include_keywords": kwargs.get("include_keywords", []),
        "exclude_keywords": kwargs.get("exclude_keywords", []),
        "start_date": kwargs.get("start_date"),
        "end_date": kwargs.get("end_date"),
        "doc_category": kwargs.get("doc_category"),
        "file_ext": kwargs.get("file_ext"),
        "min_score": kwargs.get("min_score", 0.0),
        "size": kwargs.get("size", 10),
        "page": kwargs.get("page", 1),
        "user_id": kwargs.get("user_id", "anonymous"),
    }
    response = client.post("/api/v1/search/query", json=payload)
    return {
        "status_code": response.status_code,
        "payload": api_json(response),
    }


def titles_from_search(payload: dict) -> list[str]:
    return [
        ((item.get("content") or {}).get("Title") or "")
        for item in payload.get("items", [])
    ]


def normalize_title(text: str) -> str:
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", text or "").lower()


def run() -> dict:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"테스트 데이터 폴더가 없습니다: {DATA_DIR}")

    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(DATA_DIR),
        "checks": [],
    }

    with TestClient(app) as client:
        results["reset"] = reset_state()

        upload_results = []
        for name in ORIGINAL_UPLOADS + DUPLICATE_UPLOADS:
            upload_results.append(upload_one(client, DATA_DIR / name))

        results["uploads"] = upload_results

        original_success = [
            row for row in upload_results[: len(ORIGINAL_UPLOADS)]
            if row["status_code"] == 200 and row["payload"].get("status") == "success"
        ]
        duplicate_skipped = [
            row for row in upload_results[len(ORIGINAL_UPLOADS):]
            if row["status_code"] == 200 and row["payload"].get("status") == "skipped"
        ]

        admin_docs = client.get("/api/v1/admin/indexed-documents", params={"skip": 0, "limit": 50})
        admin_docs_payload = api_json(admin_docs)
        results["admin_indexed_documents"] = admin_docs_payload

        results["checks"].append(
            assert_result(
                "scenario_a_upload_and_duplicate",
                len(original_success) >= (len(ORIGINAL_UPLOADS) - 1)
                and len(duplicate_skipped) == len(DUPLICATE_UPLOADS)
                and admin_docs_payload.get("total") == len(original_success),
                {
                    "original_success": len(original_success),
                    "duplicate_skipped": len(duplicate_skipped),
                    "indexed_total": admin_docs_payload.get("total"),
                },
            )
        )

        search_results = {}
        scenario_b_pass = True
        for query, expected_titles in SEARCH_EXPECTATIONS.items():
            row = search(client, query, size=5, user_id=RECENT_USER_ID)
            payload = row["payload"]
            titles = titles_from_search(payload)
            normalized_titles = [normalize_title(title) for title in titles[:3]]
            normalized_expected = [normalize_title(title) for title in expected_titles]
            search_results[query] = {
                "total": payload.get("total"),
                "titles": titles,
            }
            if not any(title in normalized_titles for title in normalized_expected):
                scenario_b_pass = False
        results["search_expectations"] = search_results
        results["checks"].append(assert_result("scenario_b_keyword_matching", scenario_b_pass, search_results))

        today = datetime.now().strftime("%Y-%m-%d")
        detailed = search(
            client,
            "연구개발계획서",
            include_keywords=["울산지방청"],
            exclude_keywords=["작성중"],
            file_ext="pdf",
            start_date=f"{today}T00:00:00",
            end_date=f"{today}T23:59:59",
            size=10,
            user_id=RECENT_USER_ID,
        )
        detailed_payload = detailed["payload"]
        detailed_titles = titles_from_search(detailed_payload)
        detailed_pass = (
            detailed["status_code"] == 200
            and detailed_payload.get("total", 0) >= 1
            and all(title.endswith(".pdf") for title in detailed_titles)
            and all("작성중" not in title for title in detailed_titles)
            and any("울산지방청" in title for title in detailed_titles)
        )
        results["detailed_search"] = detailed_payload
        results["checks"].append(
            assert_result(
                "scenario_c_detailed_filters",
                detailed_pass,
                {"titles": detailed_titles, "total": detailed_payload.get("total")},
            )
        )

        precision_rows = {}
        scenario_d_pass = True
        for query in NAME_QUERIES:
            row = search(client, query, size=10, user_id=RECENT_USER_ID)
            payload = row["payload"]
            titles = titles_from_search(payload)
            precision_rows[query] = {"total": payload.get("total"), "titles": titles}
            if payload.get("total") != 0:
                scenario_d_pass = False
        results["name_precision"] = precision_rows
        results["checks"].append(assert_result("scenario_d_name_precision", scenario_d_pass, precision_rows))

        autocomplete = api_json(client.get("/api/v1/search/autocomplete", params={"q": "연구"}))
        for query in POPULAR_QUERIES:
            search(client, query, user_id=RECENT_USER_ID)
            search(client, query, user_id=RECENT_USER_ID)
        typo_rows = {
            "연구개발계휙서": search(client, "연구개발계휙서", user_id=RECENT_USER_ID),
            "산엽기술혁신사업": search(client, "산엽기술혁신사업", user_id=RECENT_USER_ID),
        }
        popular = api_json(client.get("/api/v1/search/popular"))
        admin_popular = api_json(client.get("/api/v1/admin/popular-keywords", params={"days": 7, "limit": 20}))
        scenario_e_pass = (
            isinstance(autocomplete, list)
            and len(autocomplete) > 0
            and all(row["status_code"] == 200 for row in typo_rows.values())
            and all(keyword in popular for keyword in ["연구개발계획서", "산업기술혁신사업", "보안"])
            and all(any(item.get("keyword") == keyword for item in admin_popular) for keyword in ["연구개발계획서", "산업기술혁신사업", "보안"])
        )
        results["autocomplete"] = autocomplete
        results["popular"] = popular
        results["admin_popular"] = admin_popular
        results["typo_rows"] = typo_rows
        results["checks"].append(assert_result("scenario_e_autocomplete_popular_typo", scenario_e_pass, {
            "autocomplete": autocomplete,
            "popular": popular,
            "admin_popular": admin_popular,
        }))

        sequence_queries = [
            "산업기술혁신사업",
            "연구개발계획서",
            "보안",
            "연구개발계획서 양식",
            "연구개발계획서 pdf",
        ]
        for query in sequence_queries:
            search(client, query, user_id=RECENT_USER_ID)

        recent_before_delete = api_json(client.get("/api/v1/search/recent", params={"user_id": RECENT_USER_ID, "limit": 10}))
        recommend = api_json(client.get("/api/v1/search/recommend", params={"user_id": RECENT_USER_ID, "limit": 10}))
        related = api_json(client.get("/api/v1/search/related", params={"q": "연구개발계획서", "days": 30, "limit": 10}))
        delete_one = api_json(client.delete("/api/v1/search/recent/item", params={"user_id": RECENT_USER_ID, "q": "보안"}))
        clear_recent = api_json(client.delete("/api/v1/search/recent", params={"user_id": RECENT_USER_ID}))
        recent_after_clear = api_json(client.get("/api/v1/search/recent", params={"user_id": RECENT_USER_ID, "limit": 10}))
        scenario_f_pass = (
            isinstance(recent_before_delete, list)
            and len(recent_before_delete) >= 5
            and isinstance(recommend, list)
            and len(recommend) >= 1
            and isinstance(related, list)
            and any("연구개발계획서" in item for item in related)
            and delete_one.get("deleted", 0) >= 1
            and clear_recent.get("deleted", 0) >= 1
            and recent_after_clear == []
        )
        results["recent_before_delete"] = recent_before_delete
        results["recommend"] = recommend
        results["related"] = related
        results["recent_delete_one"] = delete_one
        results["recent_clear"] = clear_recent
        results["recent_after_clear"] = recent_after_clear
        results["checks"].append(assert_result("scenario_f_recent_recommend_related", scenario_f_pass, {
            "recent_before_delete": recent_before_delete,
            "recommend": recommend,
            "related": related,
            "delete_one": delete_one,
            "clear_recent": clear_recent,
        }))

        failed_row = search(client, FAIL_QUERY, user_id=RECENT_USER_ID)
        admin_failed = api_json(client.get("/api/v1/admin/failed-keywords", params={"days": 7, "limit": 20}))
        admin_logs = api_json(client.get("/api/v1/admin/search-logs", params={"skip": 0, "limit": 100}))
        failed_logged = any(item.get("query") == FAIL_QUERY and item.get("is_failed") for item in admin_logs.get("items", []))
        failed_counted = any(item.get("keyword") == FAIL_QUERY for item in admin_failed)
        # 실패 검색은 결과 건수(벡터 매칭 가능)와 무관하게 실패 로그/집계 반영 여부로 검증
        scenario_g_pass = failed_logged and failed_counted
        results["failed_query"] = failed_row
        results["admin_failed"] = admin_failed
        results["admin_logs"] = admin_logs
        results["checks"].append(assert_result("scenario_g_failed_tracking", scenario_g_pass, {
            "failed_logged": failed_logged,
            "failed_counted": failed_counted,
        }))

        root_page = client.get("/")
        admin_page = client.get("/admin")
        page1 = search(client, "계획", size=2, page=1, user_id=RECENT_USER_ID)
        page2 = search(client, "계획", size=2, page=2, user_id=RECENT_USER_ID)
        page1_titles = titles_from_search(page1["payload"])
        page2_titles = titles_from_search(page2["payload"])
        scenario_h_pass = (
            root_page.status_code == 200
            and admin_page.status_code == 200
            and page1["payload"].get("page") == 1
            and page2["payload"].get("page") == 2
            and page1_titles != page2_titles
        )
        results["ui_checks"] = {
            "root_status": root_page.status_code,
            "admin_status": admin_page.status_code,
            "page1_titles": page1_titles,
            "page2_titles": page2_titles,
            "mobile_layout": "manual_required",
        }
        results["checks"].append(assert_result("scenario_h_ui_and_paging", scenario_h_pass, results["ui_checks"]))

        admin_recent = api_json(client.get("/api/v1/admin/recent-searches", params={"skip": 0, "limit": 100}))
        scenario_i_pass = (
            isinstance(admin_popular, list)
            and isinstance(admin_failed, list)
            and admin_docs_payload.get("total", 0) >= 1
            and admin_logs.get("total", 0) >= 1
            and admin_recent.get("total", 0) >= 0
        )
        results["admin_recent"] = admin_recent
        results["checks"].append(assert_result("scenario_i_admin_tabs", scenario_i_pass, {
            "popular_count": len(admin_popular),
            "failed_count": len(admin_failed),
            "indexed_total": admin_docs_payload.get("total"),
            "search_logs_total": admin_logs.get("total"),
            "recent_total": admin_recent.get("total"),
        }))

        eval_payload = {
            "queries": [
                {
                    "query": "산업기술혁신사업",
                    "relevant_titles": ["(산업부)_2026년도_산업기술혁신사업_통합_시행계획_공고문.hwp"],
                    "user_id": "eval-user",
                },
                {
                    "query": "연구개발계획서",
                    "relevant_titles": ["1. 연구개발계획서 양식_울산지방청.pdf", "연구개발계획서_작성중.docx"],
                    "user_id": "eval-user",
                },
                {
                    "query": "AI개발진행",
                    "relevant_titles": ["AI개발진행-20251201.pptx"],
                    "user_id": "eval-user",
                },
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(eval_payload, fh, ensure_ascii=False, indent=2)
            temp_eval_path = fh.name
        results["temp_eval_path"] = temp_eval_path

    results["ended_at"] = datetime.now(timezone.utc).isoformat()
    results["passed"] = all(check["passed"] for check in results["checks"])
    return results


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))