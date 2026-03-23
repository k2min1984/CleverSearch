"""검색 결과 확인 스크립트"""
import requests, urllib3, json
urllib3.disable_warnings()

s = requests.Session()
s.verify = False
BASE = "https://localhost:8443"

r = s.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123!"})
token = r.json().get("access_token", "")
s.headers.update({"Authorization": f"Bearer {token}"})

# 1. 문서 목록
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
d = r.json()
print(f"=== 현재 문서: {d['total']}건 ===")
for x in d["items"]:
    print(f"  ID={x['id']} | {x['origin_file']} | [{x['doc_category']}]")

print()

# 2. 검색 테스트
tests = [
    "연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안",
    "NONAME999", "QHDKS",
    "ㅇㄱㄱㅂㄱㅎㅅ", "ㅂㅇ", "ㅌㅎㄱㅅ",
]
print("=== 검색 결과 ===")
for kw in tests:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    items = data.get("items", [])
    files = [it.get("content", {}).get("origin_file", "?") for it in items[:10]]
    corrected = data.get("corrected_query", "")
    corr_msg = f" (교정→{corrected})" if data.get("is_typo_corrected") else ""
    print(f"  '{kw}'{corr_msg}: {total}건 → {files}")

print()

# 3. 포함 키워드 테스트
r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "include_keywords": ["울산지방청"]})
data = r.json()
files = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
print(f"'연구개발계획서' + 포함='울산지방청': {data.get('total',0)}건 → {files}")

# 4. 제외 키워드 테스트
r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "exclude_keywords": ["작성중"]})
data = r.json()
files = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
print(f"'연구개발계획서' + 제외='작성중': {data.get('total',0)}건 → {files}")

# 5. 자동완성
r = s.get(f"{BASE}/api/v1/search/autocomplete?q=ㅇㄱ")
print(f"\n자동완성 'ㅇㄱ': {r.json()}")

r = s.get(f"{BASE}/api/v1/search/autocomplete?q=연구")
print(f"자동완성 '연구': {r.json()}")
