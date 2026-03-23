"""
########################################################
# Description
# 검색 디버그 스크립트
# API에 직접 로그인 후 검색 쿼리를 호출하여 콘솔 출력
#
# Modified History
# 강광민 / 2026-03-19 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
import requests, json, urllib3
urllib3.disable_warnings()
S = requests.Session()
S.verify = False

# login
r = S.post('https://localhost:8000/api/v1/auth/login', json={'username':'admin','password':'admin123!'})
print(f'Login: {r.status_code}')
token = r.json().get('access_token','')
S.headers['Authorization'] = f'Bearer {token}'

# search via main search API
r = S.post('https://localhost:8000/api/v1/search/query', json={'query':'연구개발계획서','page':1,'size':10})
print(f'Search code: {r.status_code}')
d = r.json()
print(f"total: {d.get('total')}")
print(f"error: {d.get('error','none')}")
print(f"corrected: {d.get('corrected_query')}")
print(f"items count: {len(d.get('items',[]))}")
if d.get('items'):
    for item in d['items'][:2]:
        print(f"  hit: {item.get('content',{}).get('origin_file','?')} score={item.get('score')}")

# also try the simpler file/search
print("\n--- file/search ---")
r2 = S.get('https://localhost:8000/api/v1/file/search?keyword=연구개발계획서')
print(f'File search code: {r2.status_code}')
d2 = r2.json()
if isinstance(d2, list):
    print(f'File search hits: {len(d2)}')
    for h in d2[:2]:
        src = h.get('_source', h)
        print(f"  {src.get('origin_file','?')}: score={h.get('_score', h.get('total_score','?'))}")
elif isinstance(d2, dict):
    print(f"File search: {json.dumps(d2, ensure_ascii=False)[:500]}")

# also check index all-data
print("\n--- index/all-data ---")
r3 = S.get('https://localhost:8000/api/v1/index/all-data')
d3 = r3.json()
if isinstance(d3, dict):
    print(f"All data total: {d3.get('total', '?')}")
    for doc in d3.get('data', [])[:3]:
        print(f"  {doc.get('origin_file','?')}")
