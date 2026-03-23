"""전체 시나리오 검색 결과 실측 스크립트 (5파일 기준 + 삭제 후)"""
import requests, urllib3, json, os, time
urllib3.disable_warnings()

s = requests.Session()
s.verify = False
BASE = "https://localhost:8443"

def new_session():
    global s
    s = requests.Session()
    s.verify = False
    return s

def login():
    r = s.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123!"})
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        return True
    return False

login()

# 1. 전체 초기화
print("=== 1. 전체 초기화 ===")
r = s.delete(f"{BASE}/api/v1/file/clear-all-data")
print(f"  초기화: {r.status_code}")
time.sleep(2)

# 2. 5개 파일 업로드
print("\n=== 2. 파일 업로드 (5종) ===")
upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
files = [
    "1. 연구개발계획서 양식_울산지방청.pdf",
    "연구개발계획서_작성중.docx",
    "AI개발진행-20251201.pptx",
    "통합검색솔루션_종합문서_20260123_V001.xlsx",
    "2026_운영지침_보안.pdf.jpg",
]
for fname in files:
    fpath = os.path.join(upload_dir, fname)
    if not os.path.exists(fpath):
        print(f"  ⚠ 파일 없음: {fname}")
        continue
    with open(fpath, "rb") as f:
        r = s.post(f"{BASE}/api/v1/file/upload", files={"file": (fname, f)})
    st = r.json().get("status", "?")
    print(f"  {fname}: {st}")

time.sleep(3)

# 3. 문서 목록 확인
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
d = r.json()
print(f"\n=== 현재 문서: {d['total']}건 ===")
for x in d["items"]:
    print(f"  ID={x['id']} | {x['origin_file']} | [{x['doc_category']}]")

# 4. 시나리오 4 검색 (5파일 기준)
print("\n=== 시나리오 4: 기본 검색 (5파일) ===")
search_tests = ["연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안"]
for kw in search_tests:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    items = data.get("items", [])
    files_found = [it.get("content", {}).get("origin_file", "?") for it in items]
    corr = f" (교정→{data.get('corrected_query','')})" if data.get("is_typo_corrected") else ""
    print(f"  '{kw}'{corr}: {total}건 → {files_found}")

# 5. 시나리오 5 필터 검색
print("\n=== 시나리오 5: 상세검색 필터 ===")
r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "include_keywords": ["울산지방청"]})
data = r.json()
print(f"  포함='울산지방청': {data.get('total',0)}건 → {[it['content']['origin_file'] for it in data.get('items',[])]}")

r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "exclude_keywords": ["작성중"]})
data = r.json()
print(f"  제외='작성중': {data.get('total',0)}건 → {[it['content']['origin_file'] for it in data.get('items',[])]}")

r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "file_ext": "pdf"})
data = r.json()
print(f"  파일형식='pdf': {data.get('total',0)}건 → {[it['content']['origin_file'] for it in data.get('items',[])]}")

# 6. 초성 검색
print("\n=== 시나리오 7: 초성 검색 (5파일) ===")
chosung_tests = ["ㅇㄱㄱㅂㄱㅎㅅ", "ㅂㅇ", "ㅌㅎㄱㅅ"]
for kw in chosung_tests:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files_found = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files_found}")

# 7. 자동완성
print("\n=== 자동완성 ===")
for q in ["ㅇㄱ", "연구"]:
    r = s.get(f"{BASE}/api/v1/search/autocomplete?q={q}")
    print(f"  '{q}': {r.json()}")

# 8. 이름검색 (5파일)
print("\n=== 시나리오 17: 이름 검색 정밀도 (5파일) ===")
for name in ["강광민", "홍길동", "NONAME999"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": name, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files_found = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
    print(f"  '{name}': {total}건 → {files_found}")

# 9. 시나리오 10: 문서 삭제 후 재확인
print("\n=== 시나리오 10: 문서 1건 삭제 ===")
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
docs = r.json()
if docs["items"]:
    del_id = docs["items"][0]["id"]
    del_name = docs["items"][0]["origin_file"]
    r = s.delete(f"{BASE}/api/v1/file/document/{del_id}")
    print(f"  삭제: ID={del_id} ({del_name}) → {r.status_code}")
    time.sleep(1)
    r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
    print(f"  삭제 후 문서: {r.json()['total']}건")

# 10. 삭제 후 검색 결과 (4파일 기준)
print("\n=== 삭제 후 검색 (4파일) ===")
for kw in ["연구개발계획서", "운영지침"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files_found = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files_found}")

# 11. QHDKS 테스트
print("\n=== QHDKS 테스트 ===")
r = s.post(f"{BASE}/api/v1/search/query", json={"query": "QHDKS", "size": 20, "page": 1})
data = r.json()
print(f"  'QHDKS': {data.get('total',0)}건, 교정={data.get('is_typo_corrected',False)}, 교정→{data.get('corrected_query','')}")
print(f"  결과: {[it['content']['origin_file'] for it in data.get('items',[])]}")
