"""수정 후 전체 검색 결과 테스트"""
import requests, urllib3, time
urllib3.disable_warnings()

time.sleep(3)
s = requests.Session()
s.verify = False
BASE = "https://localhost:8443/api/v1/search"

def search(q, **kwargs):
    payload = {"query": q, "page": 1, "size": 10}
    payload.update(kwargs)
    r = s.post(f"{BASE}/query", json=payload, timeout=30)
    return r.json()

print("=== 기본 검색 테스트 (수정 후) ===")
queries = ["연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안"]
for q in queries:
    data = search(q)
    total = data.get("total", "?")
    corr = data.get("corrected_query", q)
    is_c = data.get("is_typo_corrected", False)
    titles = [item["content"].get("Title", "?")[:40] for item in data.get("items", [])]
    msg = f" (교정→{corr})" if is_c else ""
    print(f"  {q}{msg}: {total}건 → {titles}")

print("\n=== 오타 교정 검색 ===")
for q in ["계휙서", "산엽"]:
    data = search(q)
    total = data.get("total", "?")
    corr = data.get("corrected_query", q)
    is_c = data.get("is_typo_corrected", False)
    msg = f" (교정→{corr})" if is_c else ""
    print(f"  {q}{msg}: {total}건")

print("\n=== 이름 검색 정밀도 ===")
for q in ["강광민", "홍길동", "NONAME999"]:
    data = search(q)
    print(f"  {q}: {data.get('total', '?')}건")

print("\n=== 초성 검색 ===")
for q in ["ㅇㄱㄱㅂㄱㅎㅅ", "ㅂㅇ", "ㅌㅎㄱㅅ"]:
    data = search(q)
    total = data.get("total", "?")
    titles = [item["content"].get("Title", "?")[:40] for item in data.get("items", [])]
    print(f"  {q}: {total}건 → {titles}")

print("\n=== 상세검색 (포함/제외/파일형식) ===")
data = search("연구개발계획서", include_keywords=["울산지방청"])
print(f"  연구개발계획서 + 포함=울산지방청: {data.get('total', '?')}건")

data = search("연구개발계획서", exclude_keywords=["작성중"])
print(f"  연구개발계획서 + 제외=작성중: {data.get('total', '?')}건")

data = search("연구개발계획서", file_ext="pdf")
print(f"  연구개발계획서 + pdf필터: {data.get('total', '?')}건")

print("\n=== 자동완성 ===")
for q in ["ㅇㄱ", "연구"]:
    r = s.get(f"{BASE}/autocomplete?q={q}", timeout=10)
    items = r.json()
    print(f"  '{q}': {len(items)}건 → {items[:5]}")

print("\n=== 시나리오10 참고: 통합검색솔루션 삭제 후 ===")
data = search("통합검색솔루션")
curr = data.get("total", 0)
print(f"  현재: {curr}건 → 삭제 후 예상: {max(0, curr - 1)}건")
