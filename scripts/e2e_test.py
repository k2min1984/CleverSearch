"""E2E 전체 테스트 스크립트"""
import requests, json, sys, time, urllib3
urllib3.disable_warnings()

BASE = "https://localhost:8000"
S = requests.Session()
S.verify = False

def api(method, path, **kw):
    r = S.request(method, BASE + path, **kw)
    return r.status_code, r.json() if r.headers.get("content-type","").startswith("application/json") else r.text

def ok(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond

results = []

# =====================================================
# 1. AUTH
# =====================================================
print("\n========== 1. 인증 (Auth) ==========")

code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"admin123!"})
ok("1-1 admin 로그인", code==200 and "access_token" in data, f"code={code}, role={data.get('role')}")
TOKEN = data.get("access_token","")
REFRESH = data.get("refresh_token","")
S.headers["Authorization"] = f"Bearer {TOKEN}"

code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"wrong"})
ok("1-2 잘못된 비밀번호", code==401, f"code={code}")

code, data = api("POST", "/api/v1/auth/login", json={"username":"viewer","password":"viewer123!"})
ok("1-3 viewer 로그인", code==200, f"role={data.get('role')}")

code, data = api("POST", "/api/v1/auth/login", json={"username":"operator","password":"operator123!"})
ok("1-4 operator 로그인", code==200, f"role={data.get('role')}")

# restore admin token
S.headers["Authorization"] = f"Bearer {TOKEN}"

code, data = api("POST", "/api/v1/auth/refresh", json={"refresh_token": REFRESH})
ok("1-5 토큰 리프레시", code==200 and "access_token" in data, f"code={code}")

code, data = api("POST", "/api/v1/auth/logout", json={"refresh_token": REFRESH})
ok("1-6 로그아웃", code==200, f"code={code}")

# re-login for further tests
code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"admin123!"})
TOKEN = data.get("access_token","")
REFRESH = data.get("refresh_token","")
S.headers["Authorization"] = f"Bearer {TOKEN}"

# =====================================================
# 2. CLEAR (초기화)
# =====================================================
print("\n========== 2. 전체 초기화 ==========")

code, data = api("DELETE", "/api/v1/file/clear-all-data")
ok("2-1 전체 초기화 API", code==200, f"msg={data.get('message')}")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=1")
ok("2-2 문서 0건 확인", code==200 and data.get("total")==0, f"total={data.get('total')}")

code, data = api("GET", "/api/v1/admin/search-logs?skip=0&limit=1")
ok("2-3 검색로그 0건", code==200 and data.get("total")==0, f"total={data.get('total')}")

code, data = api("GET", "/api/v1/admin/recent-searches?skip=0&limit=1")
ok("2-4 최근검색 0건", code==200 and data.get("total")==0, f"total={data.get('total')}")

# =====================================================
# 3. FILE UPLOAD
# =====================================================
print("\n========== 3. 파일 업로드 ==========")

import os
upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
test_files = [
    "1. 연구개발계획서 양식_울산지방청.pdf",
    "연구개발계획서_작성중.docx",
    "AI개발진행-20251201.pptx",
    "통합검색솔루션_종합문서_20260123_V001.xlsx",
    "2026_운영지침_보안.pdf.jpg",
]

uploaded_count = 0
for i, fname in enumerate(test_files, 1):
    fpath = os.path.join(upload_dir, fname)
    if not os.path.exists(fpath):
        ok(f"3-{i} 업로드 {fname}", False, "파일 없음")
        continue
    with open(fpath, "rb") as f:
        code, data = api("POST", "/api/v1/file/upload", files={"file": (fname, f)})
    status = data.get("status","") if isinstance(data, dict) else ""
    ok(f"3-{i} 업로드 {fname[:30]}", code==200 and status=="success", f"status={status}, category={data.get('category','')}")
    if status == "success":
        uploaded_count += 1

# 업로드 후 문서 수 확인
time.sleep(1)
code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=1")
ok(f"3-6 DB 문서 수 = {uploaded_count}", data.get("total")==uploaded_count, f"total={data.get('total')}")

# 중복 업로드 테스트
with open(os.path.join(upload_dir, test_files[1]), "rb") as f:
    code, data = api("POST", "/api/v1/file/upload", files={"file": (test_files[1], f)})
    dup_status = data.get("status","") if isinstance(data, dict) else ""
ok("3-7 중복 업로드 skipped", dup_status=="skipped", f"actual={dup_status}")

# =====================================================
# 4. SEARCH (기본 검색)
# =====================================================
print("\n========== 4. 기본 검색 ==========")

search_tests = [
    ("연구개발계획서", ["울산지방청", "작성중"]),
    ("AI개발진행", ["pptx"]),
    ("통합검색솔루션", ["xlsx"]),
    ("운영지침", []),
    ("보안", []),
]

for i, (query, expect_files) in enumerate(search_tests, 1):
    code, data = api("POST", "/api/v1/search/query", json={"query": query, "page": 1, "size": 10})
    total = data.get("total", 0) if isinstance(data, dict) else 0
    hits = data.get("results", []) if isinstance(data, dict) else []
    hit_files = [h.get("origin_file","") for h in hits]
    found = all(any(ef in hf for hf in hit_files) for ef in expect_files) if expect_files else total >= 0
    ok(f"4-{i} 검색 '{query}'", code==200 and total>0, f"total={total}, files={[h[:20] for h in hit_files[:3]]}")

# =====================================================
# 5. SEARCH (상세/필터)
# =====================================================
print("\n========== 5. 상세검색 / 필터 ==========")

# include 
code, data = api("POST", "/api/v1/search/query", json={"query": "연구개발계획서", "include_keywords": ["울산지방청"], "page":1, "size":10})
total = data.get("total",0) if isinstance(data, dict) else 0
ok("5-1 include=울산지방청", code==200, f"total={total}")

# exclude
code, data = api("POST", "/api/v1/search/query", json={"query": "연구개발계획서", "exclude_keywords": ["작성중"], "page":1, "size":10})
ok("5-2 exclude=작성중", code==200, f"total={data.get('total',0) if isinstance(data,dict) else 0}")

# file_types
code, data = api("POST", "/api/v1/search/query", json={"query": "연구개발계획서", "file_types": ["pdf"], "page":1, "size":10})
total_pdf = data.get("total",0) if isinstance(data,dict) else 0
ok("5-3 file_types=pdf", code==200, f"total={total_pdf}")

# date range
code, data = api("POST", "/api/v1/search/query", json={"query": "연구개발계획서", "start_date": "2026-03-20", "end_date": "2026-03-20", "page":1, "size":10})
ok("5-4 기간필터 오늘", code==200, f"total={data.get('total',0) if isinstance(data,dict) else 0}")

# =====================================================
# 6. SEARCH (오타/자동완성/인기/최근/실패)
# =====================================================
print("\n========== 6. 오타/자동완성/인기/최근/실패 ==========")

# 오타
code, data = api("POST", "/api/v1/search/query", json={"query": "연구개발계휙서", "page":1, "size":5})
ok("6-1 오타 '계휙서'", code==200, f"total={data.get('total',0) if isinstance(data,dict) else 0}")

code, data = api("POST", "/api/v1/search/query", json={"query": "산엽기술혁신사업", "page":1, "size":5})
ok("6-2 오타 '산엽'", code==200, f"total={data.get('total',0) if isinstance(data,dict) else 0}")

# 자동완성
code, data = api("GET", "/api/v1/search/autocomplete?q=연구")
ok("6-3 자동완성 '연구'", code==200 and isinstance(data, list), f"count={len(data) if isinstance(data,list) else '?'}")

# 인기검색어
code, data = api("GET", "/api/v1/search/popular")
ok("6-4 인기검색어", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# 최근검색어 조회
code, data = api("GET", "/api/v1/search/recent?user_id=anonymous&limit=10")
ok("6-5 최근검색 조회", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# 최근검색 단건삭제
if isinstance(data, list) and len(data) > 0:
    del_keyword = data[0].get("query","") if isinstance(data[0], dict) else data[0]
    code2, _ = api("DELETE", f"/api/v1/search/recent/item?user_id=anonymous&q={del_keyword}")
    ok("6-6 최근검색 단건삭제", code2==200, f"keyword={del_keyword}")
else:
    ok("6-6 최근검색 단건삭제", False, "최근검색 없음 (테스트 불가)")

# 최근검색 전체삭제
code, _ = api("DELETE", "/api/v1/search/recent?user_id=anonymous")
ok("6-7 최근검색 전체삭제", code==200)

code, data = api("GET", "/api/v1/search/recent?user_id=anonymous&limit=10")
ok("6-8 전체삭제 후 0건", code==200 and (isinstance(data, list) and len(data)==0), f"count={len(data) if isinstance(data,list) else '?'}")

# 실패 검색어 (존재하지 않는 키워드)
code, data = api("POST", "/api/v1/search/query", json={"query": "ZXCVBNM존재하지않는키워드", "page":1, "size":5})
fail_total = data.get("total", 0) if isinstance(data, dict) else 0
ok("6-9 실패검색 total=0", code==200 and fail_total==0, f"total={fail_total}")

# 실패검색어 통계
code, data = api("GET", "/api/v1/search/failed-analysis?days=7")
ok("6-10 실패검색 통계 API", code==200, f"type={type(data).__name__}")

# 추천검색어
code, data = api("GET", "/api/v1/search/recommend?user_id=anonymous&limit=5")
ok("6-11 추천검색어", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# 연관검색어
code, data = api("GET", "/api/v1/search/related?q=연구개발계획서&days=30&limit=5")
ok("6-12 연관검색어", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# =====================================================
# 7. 이름 검색 정밀도
# =====================================================
print("\n========== 7. 이름 검색 정밀도 ==========")

for name in ["강광민", "홍길동", "NONAME999"]:
    code, data = api("POST", "/api/v1/search/query", json={"query": name, "page":1, "size":5})
    total = data.get("total",0) if isinstance(data,dict) else 0
    ok(f"7-x '{name}' 검색", code==200 and total==0, f"total={total} (0이어야 정상)")

# =====================================================
# 8. ADMIN TABS
# =====================================================
print("\n========== 8. 관리자 탭 ==========")

code, data = api("GET", "/api/v1/admin/popular-keywords?days=7&limit=10")
ok("8-1 인기검색어 목록", code==200, f"total={data.get('total','?') if isinstance(data,dict) else type(data).__name__}")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
ok("8-2 인덱스 문서 목록", code==200, f"total={data.get('total','?')}")

code, data = api("GET", "/api/v1/admin/search-logs?skip=0&limit=20")
ok("8-3 검색로그 목록", code==200, f"total={data.get('total','?')}")

code, data = api("GET", "/api/v1/admin/recent-searches?skip=0&limit=20")
ok("8-4 최근검색 목록", code==200, f"total={data.get('total','?')}")

code, data = api("GET", "/api/v1/admin/failed-keywords?days=7&limit=10")
ok("8-5 실패검색어 목록", code==200, f"total={data.get('total','?') if isinstance(data,dict) else type(data).__name__}")

# =====================================================
# 9. DOCUMENT DELETE
# =====================================================
print("\n========== 9. 문서 삭제 ==========")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
before_total = data.get("total", 0)
items = data.get("items", [])
if items:
    doc_id = items[0]["id"]
    code2, data2 = api("DELETE", f"/api/v1/file/document/{doc_id}")
    ok("9-1 문서 개별삭제", code2==200, f"doc_id={doc_id}, msg={data2.get('message','?')}")
    
    code3, data3 = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
    ok("9-2 삭제 후 건수 감소", data3.get("total","?") == before_total - 1, f"before={before_total}, after={data3.get('total','?')}")
else:
    ok("9-1 문서 개별삭제", False, "삭제할 문서 없음")

# 존재하지 않는 ID 삭제
code, data = api("DELETE", "/api/v1/file/document/99999")
ok("9-3 없는 문서 삭제 404", code==404, f"code={code}")

# =====================================================
# 10. SYSTEM - 대시보드
# =====================================================
print("\n========== 10. 시스템 대시보드 ==========")

code, data = api("GET", "/api/v1/system/dashboard/summary?days=7")
ok("10-1 대시보드 요약", code==200, f"keys={list(data.keys())[:5] if isinstance(data,dict) else '?'}")

code, data = api("GET", "/api/v1/system/dashboard/trend?days=14")
ok("10-2 대시보드 추이", code==200, f"type={type(data).__name__}")

code, data = api("GET", "/api/v1/system/health/overview")
ok("10-3 헬스 오버뷰", code==200, f"keys={list(data.keys())[:3] if isinstance(data,dict) else '?'}")

code, data = api("GET", "/api/v1/system/dashboard/alerts?cert_warn_days=7")
ok("10-4 운영 알림", code==200, f"type={type(data).__name__}")

# =====================================================
# 11. SYSTEM - 사전관리
# =====================================================
print("\n========== 11. 사전관리 ==========")

# 동의어 등록
code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=synonym&term=AI&replacement=인공지능&is_active=true")
ok("11-1 동의어 등록 AI→인공지능", code==200, f"msg={data}")

# 사용자사전 등록
code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=user_dict&term=계휙서&replacement=계획서&is_active=true")
ok("11-2 사용자사전 계휙서→계획서", code==200, f"msg={data}")

# 불용어 등록
code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=stopword&term=에&is_active=true")
ok("11-3 불용어 '에' 등록", code==200, f"msg={data}")

# 조회
code, data = api("GET", "/api/v1/system/dictionary/entries?dict_type=synonym&active_only=true")
ok("11-4 동의어 목록 조회", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# =====================================================
# 12. SYSTEM - SMB/DB 소스 (조회만)
# =====================================================
print("\n========== 12. 소스 관리 ==========")

code, data = api("GET", "/api/v1/system/smb/sources")
ok("12-1 SMB 소스 조회", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

code, data = api("GET", "/api/v1/system/db/sources")
ok("12-2 DB 소스 조회", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# =====================================================
# 13. SYSTEM - 스케줄러
# =====================================================
print("\n========== 13. 스케줄러 ==========")

code, data = api("GET", "/api/v1/system/scheduler/status")
ok("13-1 스케줄러 상태", code==200, f"data={data}")

# =====================================================
# 14. SYSTEM - SSL
# =====================================================
print("\n========== 14. SSL 인증서 ==========")

code, data = api("GET", "/api/v1/system/ssl/certificates?cert_dir=cert&warn_days=30")
ok("14-1 인증서 상태 조회", code==200, f"data={str(data)[:100]}")

# =====================================================
# 15. RBAC (권한 차단)
# =====================================================
print("\n========== 15. RBAC 권한 ==========")

# viewer로 admin API 호출
code_v, data_v = api("POST", "/api/v1/auth/login", json={"username":"viewer","password":"viewer123!"})
viewer_token = data_v.get("access_token","")
old_auth = S.headers.get("Authorization","")
S.headers["Authorization"] = f"Bearer {viewer_token}"

# viewer는 admin 탭 조회 가능 (viewer+)
code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=5")
ok("15-1 viewer → admin 조회", code==200, f"code={code}")

# viewer는 operator 기능 차단
code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=synonym&term=test&replacement=테스트&is_active=true")
ok("15-2 viewer → 사전등록 차단(403)", code==403, f"code={code}")

code, data = api("POST", "/api/v1/system/scheduler/start?interval_seconds=120")
ok("15-3 viewer → 스케줄러 시작 차단(403)", code==403, f"code={code}")

# 복원
S.headers["Authorization"] = old_auth

# =====================================================
# 16. INDEX DELETE
# =====================================================
print("\n========== 16. 인덱스 삭제 ==========")

code, data = api("DELETE", "/api/v1/file/delete-index")
ok("16-1 인덱스 완전 삭제", code==200, f"msg={data.get('message','?')}")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=1")
ok("16-2 삭제 후 DB 0건", data.get("total",0)==0, f"total={data.get('total','?')}")

# =====================================================
# 17. PAGES
# =====================================================
print("\n========== 17. 정적 페이지 ==========")

code, _ = api("GET", "/")
ok("17-1 메인 페이지(/)", code==200)

code, _ = api("GET", "/admin")
ok("17-2 관리자 페이지(/admin)", code==200)

# =====================================================
print("\n========== 테스트 완료 ==========")
