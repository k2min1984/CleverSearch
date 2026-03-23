"""추가 검증: 오타교정 + 통합검색솔루션 삭제 후 검색"""
import requests, urllib3, time
urllib3.disable_warnings()

s = requests.Session()
s.verify = False
BASE = "https://localhost:8443"

r = s.post(f"{BASE}/api/v1/auth/login", json={"username": "admin", "password": "admin123!"})
s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})

# 현재 문서 확인 (verify_scenarios.py에서 운영지침보안.jpg가 삭제됨 → 재업로드 필요)
print("=== 현재 문서 상태 ===")
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
d = r.json()
print(f"  총 {d['total']}건")
for x in d["items"]:
    print(f"  ID={x['id']} | {x['origin_file']} | [{x['doc_category']}]")

# 전체 초기화 후 5파일 업로드 (깨끗한 상태)
import os
print("\n=== 전체 리셋 + 5파일 업로드 ===")
s.delete(f"{BASE}/api/v1/file/clear-all-data")
time.sleep(2)

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
    if os.path.exists(fpath):
        with open(fpath, "rb") as f:
            r = s.post(f"{BASE}/api/v1/file/upload", files={"file": (fname, f)})
        print(f"  {fname}: {r.json().get('status','?')}")

time.sleep(3)

# 오타 교정 검색
print("\n=== 오타 교정 (5파일) ===")
for kw in ["계휙서", "산엽"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    corr = data.get("corrected_query", "")
    is_corr = data.get("is_typo_corrected", False)
    total = data.get("total", 0)
    files_found = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
    print(f"  '{kw}' → 교정={is_corr}, 교정어='{corr}', {total}건 → {files_found}")

# 통합검색솔루션 삭제
print("\n=== 통합검색솔루션 삭제 ===")
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
docs = r.json()
del_id = None
for doc in docs["items"]:
    if "통합검색솔루션" in doc["origin_file"]:
        del_id = doc["id"]
        print(f"  대상: ID={del_id} ({doc['origin_file']})")
        break

if del_id:
    r = s.delete(f"{BASE}/api/v1/file/document/{del_id}")
    print(f"  삭제: {r.status_code}")
    time.sleep(1)

# 삭제 후 검색 (4파일: pdf, docx, pptx, jpg — xlsx 빠짐)
print("\n=== 삭제 후 검색 (4파일) ===")
for kw in ["연구개발계획서", "AI개발진행", "통합검색솔루션", "운영지침", "보안",
           "ㅇㄱㄱㅂㄱㅎㅅ", "ㅂㅇ", "ㅌㅎㄱㅅ", "NONAME999", "QHDKS"]:
    r = s.post(f"{BASE}/api/v1/search/query", json={"query": kw, "size": 20, "page": 1})
    data = r.json()
    total = data.get("total", 0)
    files_found = [it.get("content", {}).get("origin_file", "?") for it in data.get("items", [])]
    print(f"  '{kw}': {total}건 → {files_found}")

# 카테고리 확인 (운영지침보안 파일)
print("\n=== 카테고리 확인 ===")
r = s.get(f"{BASE}/api/v1/admin/indexed-documents?skip=0&limit=20")
docs = r.json()
for x in docs["items"]:
    print(f"  {x['origin_file']} → [{x['doc_category']}]")
