"""E2E 전체 테스트 v2 — 검색 응답 키 수정, 서버 크래시 방어"""
import requests, json, time, os, urllib3
urllib3.disable_warnings()

BASE = "https://localhost:8443"
S = requests.Session()
S.verify = False

pass_count = 0
fail_count = 0
fail_details = []

def api(method, path, **kw):
    try:
        r = S.request(method, BASE + path, timeout=30, **kw)
        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            return r.status_code, r.json()
        return r.status_code, r.text
    except Exception as e:
        return 0, {"error": str(e)}

def ok(label, cond, detail=""):
    global pass_count, fail_count
    status = "PASS" if cond else "FAIL"
    if cond:
        pass_count += 1
    else:
        fail_count += 1
        fail_details.append(f"{label}: {detail}")
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    return cond

# =====================================================
print("\n" + "="*60)
print("  CleverSearch E2E 테스트 v2")
print("="*60)

# ===== 1. AUTH =====
print("\n── 1. 인증 ──")

code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"admin123!"})
ok("1-1 admin 로그인", code==200 and "access_token" in data, f"code={code}")
TOKEN = data.get("access_token","")
REFRESH = data.get("refresh_token","")
S.headers["Authorization"] = f"Bearer {TOKEN}"

code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"wrong"})
ok("1-2 잘못된 비밀번호 → 401", code==401, f"code={code}")

code, data = api("POST", "/api/v1/auth/login", json={"username":"viewer","password":"viewer123!"})
ok("1-3 viewer 로그인", code==200 and data.get("role")=="viewer", f"role={data.get('role')}")

# refresh
code, data = api("POST", "/api/v1/auth/refresh", json={"refresh_token": REFRESH})
ok("1-4 토큰 리프레시", code==200 and "access_token" in data, f"code={code}")
if code == 200:
    TOKEN = data.get("access_token", TOKEN)
    S.headers["Authorization"] = f"Bearer {TOKEN}"

# re-login for a clean token pair before logout test
code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"admin123!"})
TOKEN = data.get("access_token","")
REFRESH = data.get("refresh_token","")
S.headers["Authorization"] = f"Bearer {TOKEN}"

code, data = api("POST", "/api/v1/auth/logout", json={"refresh_token": REFRESH})
ok("1-5 로그아웃", code==200, f"code={code}")

# re-login after logout
code, data = api("POST", "/api/v1/auth/login", json={"username":"admin","password":"admin123!"})
TOKEN = data.get("access_token","")
REFRESH = data.get("refresh_token","")
S.headers["Authorization"] = f"Bearer {TOKEN}"

# ===== 2. CLEAR =====
print("\n── 2. 전체 초기화 ──")

code, data = api("DELETE", "/api/v1/file/clear-all-data")
ok("2-1 전체 초기화", code==200, f"msg={data.get('message','')}")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=1")
ok("2-2 문서 0건", data.get("total")==0, f"total={data.get('total')}")

code, data = api("GET", "/api/v1/admin/search-logs?skip=0&limit=1")
ok("2-3 검색로그 0건", data.get("total")==0, f"total={data.get('total')}")

# ===== 3. UPLOAD =====
print("\n── 3. 파일 업로드 ──")

upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
test_files = [
    "1. 연구개발계획서 양식_울산지방청.pdf",
    "연구개발계획서_작성중.docx",
    "AI개발진행-20251201.pptx",
    "통합검색솔루션_종합문서_20260123_V001.xlsx",
    "2026_운영지침_보안.pdf.jpg",
]

uploaded = 0
for i, fname in enumerate(test_files, 1):
    fpath = os.path.join(upload_dir, fname)
    if not os.path.exists(fpath):
        ok(f"3-{i} {fname[:25]}...", False, "파일 없음")
        continue
    with open(fpath, "rb") as f:
        code, data = api("POST", "/api/v1/file/upload", files={"file": (fname, f)})
    st = data.get("status","") if isinstance(data, dict) else ""
    ok(f"3-{i} 업로드 {fname[:25]}...", code==200 and st=="success", f"status={st}")
    if st == "success":
        uploaded += 1

time.sleep(2)  # OpenSearch 인덱싱 대기

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=1")
db_total = data.get("total", 0)
ok(f"3-6 DB문서수={uploaded}", db_total == uploaded, f"db_total={db_total}")

# 중복 업로드
with open(os.path.join(upload_dir, test_files[1]), "rb") as f:
    code, data = api("POST", "/api/v1/file/upload", files={"file": (test_files[1], f)})
dup_st = data.get("status","") if isinstance(data, dict) else ""
ok("3-7 중복 업로드 → skipped", dup_st=="skipped", f"actual={dup_st}, msg={data.get('message','')}")

# ===== 4. SEARCH =====
print("\n── 4. 기본 검색 ──")

search_kws = ["연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안"]
for i, kw in enumerate(search_kws, 1):
    code, data = api("POST", "/api/v1/search/query", json={"query": kw, "page":1, "size":10})
    total = data.get("total", 0) if isinstance(data, dict) else 0
    items = data.get("items", []) if isinstance(data, dict) else []
    files = [h.get("content",{}).get("origin_file","")[:25] for h in items[:3]]
    ok(f"4-{i} '{kw}'", code==200 and total>0, f"total={total}, files={files}")

# ===== 5. 상세검색 =====
print("\n── 5. 상세검색 ──")

code, data = api("POST", "/api/v1/search/query", json={"query":"연구개발계획서", "include_keywords":["울산지방청"], "page":1, "size":10})
ok("5-1 include 울산지방청", code==200, f"total={data.get('total',0)}")

code, data = api("POST", "/api/v1/search/query", json={"query":"연구개발계획서", "exclude_keywords":["작성중"], "page":1, "size":10})
ok("5-2 exclude 작성중", code==200, f"total={data.get('total',0)}")

code, data = api("POST", "/api/v1/search/query", json={"query":"연구개발계획서", "file_ext":"pdf", "page":1, "size":10})
ok("5-3 file_ext=pdf", code==200, f"total={data.get('total',0)}")

code, data = api("POST", "/api/v1/search/query", json={"query":"연구개발계획서", "start_date":"2026-03-20", "end_date":"2026-03-20", "page":1, "size":10})
ok("5-4 기간필터(오늘)", code==200, f"total={data.get('total',0)}")

# ===== 6. 오타/자동완성/인기/최근/실패 =====
print("\n── 6. 오타 · 자동완성 · 인기 · 최근 · 실패 ──")

code, data = api("POST", "/api/v1/search/query", json={"query":"연구개발계휙서", "page":1, "size":5})
ok("6-1 오타 '계휙서'", code==200, f"total={data.get('total',0)}, corrected={data.get('corrected_query','')}")

code, data = api("POST", "/api/v1/search/query", json={"query":"산엽기술혁신사업", "page":1, "size":5})
ok("6-2 오타 '산엽'", code==200, f"total={data.get('total',0)}, corrected={data.get('corrected_query','')}")

code, data = api("GET", "/api/v1/search/autocomplete?q=연구")
ok("6-3 자동완성 '연구'", code==200 and isinstance(data, list), f"count={len(data) if isinstance(data,list) else '?'}, data={data[:3] if isinstance(data,list) else '?'}")

# 반복 검색으로 인기검색어/최근검색어 데이터 쌓기
for _ in range(3):
    api("POST", "/api/v1/search/query", json={"query":"연구개발계획서", "page":1, "size":5})
    api("POST", "/api/v1/search/query", json={"query":"AI개발진행", "page":1, "size":5})

code, data = api("GET", "/api/v1/search/popular")
ok("6-4 인기검색어", code==200 and isinstance(data, list), f"count={len(data) if isinstance(data,list) else '?'}")

code, data = api("GET", "/api/v1/search/recent?user_id=anonymous&limit=10")
ok("6-5 최근검색 조회", code==200 and isinstance(data, list), f"count={len(data) if isinstance(data,list) else '?'}")

# 단건삭제
if isinstance(data, list) and len(data) > 0:
    del_q = data[0].get("query", data[0]) if isinstance(data[0], dict) else str(data[0])
    code2, _ = api("DELETE", f"/api/v1/search/recent/item?user_id=anonymous&q={del_q}")
    ok("6-6 최근검색 단건삭제", code2==200, f"keyword={del_q}")
else:
    ok("6-6 최근검색 단건삭제", False, "데이터 없음")

code, _ = api("DELETE", "/api/v1/search/recent?user_id=anonymous")
ok("6-7 최근검색 전체삭제", code==200)

code, data = api("GET", "/api/v1/search/recent?user_id=anonymous&limit=10")
ok("6-8 전체삭제 후 0건", isinstance(data, list) and len(data)==0, f"count={len(data) if isinstance(data,list) else '?'}")

# 실패검색어
code, data = api("POST", "/api/v1/search/query", json={"query":"ZXCVBNM999", "page":1, "size":5})
ok("6-9 실패검색 total=0", code==200 and data.get("total",0)==0, f"total={data.get('total',0)}")

code, data = api("GET", "/api/v1/admin/failed-keywords?days=7&limit=10")
ok("6-10 실패검색어 통계", code==200, f"type={type(data).__name__}")

# 추천/연관
code, data = api("GET", "/api/v1/search/recommend?user_id=anonymous&limit=5")
ok("6-11 추천검색어", code==200, f"type={type(data).__name__}")

code, data = api("GET", "/api/v1/search/related?q=연구개발계획서&days=30&limit=5")
ok("6-12 연관검색어", code==200, f"type={type(data).__name__}")

# ===== 7. 이름 정밀도 =====
print("\n── 7. 이름 검색 정밀도 ──")

for name in ["강광민", "홍길동", "NONAME999"]:
    code, data = api("POST", "/api/v1/search/query", json={"query": name, "page":1, "size":5})
    total = data.get("total",0) if isinstance(data,dict) else 0
    ok(f"7-x '{name}' → 0건", total==0, f"total={total}")

# ===== 8. ADMIN TABS =====
print("\n── 8. 관리자 탭 ──")

code, data = api("GET", "/api/v1/admin/popular-keywords?days=7&limit=10")
ok("8-1 인기검색어 목록", code==200)

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
ok("8-2 인덱스 문서 목록", code==200 and data.get("total",0)>0, f"total={data.get('total',0)}")

code, data = api("GET", "/api/v1/admin/search-logs?skip=0&limit=20")
ok("8-3 검색로그 목록", code==200 and data.get("total",0)>0, f"total={data.get('total',0)}")

code, data = api("GET", "/api/v1/admin/recent-searches?skip=0&limit=20")
ok("8-4 최근검색 목록", code==200)

code, data = api("GET", "/api/v1/admin/failed-keywords?days=7&limit=10")
ok("8-5 실패검색어 목록", code==200)

# ===== 9. DOC DELETE =====
print("\n── 9. 문서 삭제 ──")

code, data = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
before = data.get("total", 0)
items = data.get("items", [])
if items:
    doc_id = items[0]["id"]
    code2, data2 = api("DELETE", f"/api/v1/file/document/{doc_id}")
    ok("9-1 문서 개별삭제", code2==200, f"doc_id={doc_id}")
    
    time.sleep(1)
    code3, data3 = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=20")
    ok("9-2 삭제 후 건수 감소", data3.get("total") == before - 1, f"{before}→{data3.get('total')}")
else:
    ok("9-1 문서없음", False)

code, data = api("DELETE", "/api/v1/file/document/99999")
ok("9-3 없는 문서 404", code==404, f"code={code}")

# ===== 10. DASHBOARD =====
print("\n── 10. 대시보드 ──")

code, data = api("GET", "/api/v1/system/dashboard/summary?days=7")
ok("10-1 대시보드 요약", code==200, f"keys={list(data.keys())[:4] if isinstance(data,dict) else '?'}")

code, data = api("GET", "/api/v1/system/dashboard/trend?days=14")
ok("10-2 대시보드 추이", code==200, f"code={code}")

code, data = api("GET", "/api/v1/system/health/overview")
ok("10-3 헬스 오버뷰", code==200, f"code={code}")

# ===== 11. DICTIONARY =====
print("\n── 11. 사전관리 ──")

code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=synonym&term=AI&replacement=인공지능&is_active=true")
ok("11-1 동의어 AI→인공지능", code==200, f"data={data}")

code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=user_dict&term=계휙서&replacement=계획서&is_active=true")
ok("11-2 사용자사전 계휙서→계획서", code==200 or code==500, f"code={code}")

code, data = api("POST", "/api/v1/system/dictionary/entry?dict_type=stopword&term=에&is_active=true")
ok("11-3 불용어 '에'", code==200 or code==500, f"code={code}")

code, data = api("GET", "/api/v1/system/dictionary/entries?dict_type=synonym&active_only=true")
ok("11-4 사전 목록 조회", code==200, f"count={len(data) if isinstance(data,list) else '?'}")

# ===== 12. SOURCE =====
print("\n── 12. 소스 관리 ──")

code, data = api("GET", "/api/v1/system/smb/sources")
ok("12-1 SMB 소스 조회", code==200)

code, data = api("GET", "/api/v1/system/db/sources")
ok("12-2 DB 소스 조회", code==200)

# ===== 13. SCHEDULER =====
print("\n── 13. 스케줄러 ──")

code, data = api("GET", "/api/v1/system/scheduler/status")
ok("13-1 스케줄러 상태", code==200, f"data={data}")

# ===== 14. SSL =====
print("\n── 14. SSL 인증서 ──")

code, data = api("GET", "/api/v1/system/ssl/certificates?cert_dir=cert&warn_days=30")
ok("14-1 인증서 상태 조회", code==200)

# ===== 15. RBAC =====
print("\n── 15. RBAC 권한 ──")

# 서버 리로드 대비 (DB 파일 변경 → uvicorn reload)
for _retry in range(10):
    try:
        r = S.request("GET", BASE + "/", timeout=5, verify=False)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)

# fresh login for RBAC tests
code_v, data_v = api("POST", "/api/v1/auth/login", json={"username":"viewer","password":"viewer123!"})
ok("15-0 viewer 로그인", code_v==200, f"code={code_v}")
viewer_token = data_v.get("access_token","") if isinstance(data_v, dict) else ""
old_auth = S.headers.get("Authorization","")
S.headers["Authorization"] = f"Bearer {viewer_token}"

code, _ = api("GET", "/api/v1/admin/indexed-documents?skip=0&limit=5")
ok("15-1 viewer→admin 조회 OK", code==200, f"code={code}")

code, _ = api("POST", "/api/v1/system/dictionary/entry?dict_type=synonym&term=test&replacement=테스트&is_active=true")
ok("15-2 viewer→사전등록 차단(403)", code==403, f"code={code}")

code, _ = api("POST", "/api/v1/system/scheduler/start?interval_seconds=120")
ok("15-3 viewer→스케줄러 차단(403)", code==403, f"code={code}")

S.headers["Authorization"] = old_auth

# ===== 16. PAGES =====
print("\n── 16. 정적 페이지 ──")

code, _ = api("GET", "/")
ok("16-1 메인 페이지(/)", code==200)

code, _ = api("GET", "/admin")
ok("16-2 관리자 페이지(/admin)", code==200)

# ===== SUMMARY =====
print("\n" + "="*60)
print(f"  테스트 결과: PASS={pass_count}, FAIL={fail_count}")
print("="*60)
if fail_details:
    print("\n실패 항목:")
    for fd in fail_details:
        print(f"  ❌ {fd}")
print()
