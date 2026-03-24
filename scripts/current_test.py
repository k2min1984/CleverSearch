"""현재 상태에서 검색 건수 실측"""
import requests, urllib3
urllib3.disable_warnings()
s = requests.Session()
s.verify = False
BASE = "https://localhost:8443"

r = s.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123!"})
token = r.json()["access_token"]
s.headers.update({"Authorization": f"Bearer {token}"})

# 현재 문서 목록
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
d = r.json()
print(f"=== 현재 문서: {d['total']}건 ===")
for x in d["items"]:
    print(f"  ID={x['id']} | {x['origin_file']} | [{x['doc_category']}]")

# 검색 테스트
print("\n=== 기본 검색 ===")
for kw in ["연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files = [it["content"]["origin_file"] for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files}")

print("\n=== 상세 검색 (연구개발계획서 기준) ===")
r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "include_keywords": ["울산지방청"]})
data = r.json()
print(f"  포함=울산지방청: {data.get('total', 0)}건 → {[it['content']['origin_file'] for it in data.get('items', [])]}")

r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "exclude_keywords": ["작성중"]})
data = r.json()
print(f"  제외=작성중: {data.get('total', 0)}건 → {[it['content']['origin_file'] for it in data.get('items', [])]}")

r = s.post(f"{BASE}/api/v1/search/query", json={"query": "연구개발계획서", "size": 20, "page": 1, "file_ext": "pdf"})
data = r.json()
print(f"  파일형식=pdf: {data.get('total', 0)}건 → {[it['content']['origin_file'] for it in data.get('items', [])]}")

print("\n=== 오타 교정 ===")
for kw in ["계휙서", "산엽"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    corr = data.get("corrected_query", "")
    is_corr = data.get("is_typo_corrected", False)
    total = data.get("total", 0)
    files = [it["content"]["origin_file"] for it in data.get("items", [])]
    print(f"  '{kw}': 교정={is_corr}, 교정어='{corr}', {total}건 → {files}")

print("\n=== 초성 검색 ===")
for kw in ["ㅇㄱㄱㅂㄱㅎㅅ", "ㅂㅇ", "ㅌㅎㄱㅅ"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files = [it["content"]["origin_file"] for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files}")

print("\n=== 이름 검색 ===")
for kw in ["강광민", "홍길동", "NONAME999"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files = [it["content"]["origin_file"] for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files}")

print("\n=== 자동완성 ===")
for q in ["ㅇㄱ", "연구"]:
    r = s.get(f"{BASE}/api/v1/search/autocomplete?q={q}")
    print(f"  '{q}': {r.json()}")
