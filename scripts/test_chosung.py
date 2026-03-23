"""초성 검색 기능 테스트 스크립트"""
import requests, urllib3, json
urllib3.disable_warnings()
s = requests.Session()
s.verify = False
BASE = 'https://localhost:8443/api/v1/search'

tests = [
    ("ㅇㄱㄱㅂㄱㅎㅅ", "연구개발계획서"),
    ("ㅂㅇ", "보안"),
    ("ㅇㅈ", "운영지침"),
    ("ㅌㅎㄱㅅ", "통합검색"),
    ("ㄱㅎㅅ", "계획서"),
]

for chosung, meaning in tests:
    r = s.post(f'{BASE}/query', json={'query': chosung, 'page': 1, 'size': 5})
    d = r.json()
    total = d.get('total', 0)
    titles = [item.get('title', '') for item in d.get('results', [])[:3]]
    print(f"[{chosung}] ({meaning}) => total={total}")
    for t in titles:
        print(f"  - {t}")
    print()

# 자동완성 초성 테스트
for q in ["ㅇㄱ", "ㅂㅇ", "ㅌㅎ"]:
    r = s.get(f'{BASE}/autocomplete', params={'q': q})
    d = r.json()
    if isinstance(d, list):
        print(f"자동완성 [{q}] => {len(d)}건: {[x.get('title','') if isinstance(x,dict) else x for x in d[:3]]}")
    else:
        print(f"자동완성 [{q}] => {d}")
