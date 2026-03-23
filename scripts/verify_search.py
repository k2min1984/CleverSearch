"""실제 검색 결과 확인 스크립트"""
import requests, urllib3, os, time
urllib3.disable_warnings()

BASE = "https://localhost:8443"
s = requests.Session()
s.verify = False

# Login
r = s.post(f'{BASE}/api/v1/auth/login', json={'username':'admin','password':'admin123!'})
token = r.json()['access_token']
h = {'Authorization': f'Bearer {token}'}

# Reset
r = s.post(f'{BASE}/api/v1/file/reset-all', headers=h)
print('Reset:', r.json())

# Upload all 5 files
files = [
    'uploads/1. 연구개발계획서 양식_울산지방청.pdf',
    'uploads/연구개발계획서_작성중.docx',
    'uploads/AI개발진행-20251201.pptx',
    'uploads/통합검색솔루션_종합문서_20260123_V001.xlsx',
    'uploads/2026_운영지침_보안.pdf.jpg',
]
for f in files:
    if os.path.exists(f):
        with open(f, 'rb') as fp:
            r = s.post(f'{BASE}/api/v1/file/upload', headers=h, files={'file': (os.path.basename(f), fp)})
            d = r.json()
            print(f'Upload {os.path.basename(f)}: {d.get("status","?")}')
    else:
        print(f'MISSING: {f}')

time.sleep(3)

# Test each search query
queries = ['연구개발계획서', 'AI개발진행', '통합검색솔루션', '운영지침', '보안', '계휙서', '산엽',
           '연구개발계획서 울산지방청']
for q in queries:
    r = s.post(f'{BASE}/api/v1/search/query', headers=h, json={'query': q, 'page': 1, 'size': 10})
    d = r.json()
    total = d.get('total', '?')
    corrected = d.get('corrected_query', '')
    is_typo = d.get('is_typo_corrected', False)
    item_files = [item.get('content',{}).get('origin_file','?') for item in d.get('items',[])]
    print(f'Search "{q}": total={total}, corrected="{corrected}", is_typo={is_typo}, files={item_files}')

# Test exclude
r = s.post(f'{BASE}/api/v1/search/query', headers=h, json={'query': '연구개발계획서', 'exclude_keywords': '작성중', 'page': 1, 'size': 10})
d = r.json()
print(f'Search "연구개발계획서" exclude "작성중": total={d.get("total","?")}, files={[item.get("content",{}).get("origin_file","?") for item in d.get("items",[])]}')

# Test file_ext filter
r = s.post(f'{BASE}/api/v1/search/query', headers=h, json={'query': '연구개발계획서', 'file_ext': 'pdf', 'page': 1, 'size': 10})
d = r.json()
print(f'Search "연구개발계획서" file_ext=pdf: total={d.get("total","?")}, files={[item.get("content",{}).get("origin_file","?") for item in d.get("items",[])]}')

# Test autocomplete
r = s.get(f'{BASE}/api/v1/search/autocomplete?q=연구', headers=h)
print(f'Autocomplete "연구": {r.json()}')

# Test popular
r = s.get(f'{BASE}/api/v1/search/popular', headers=h)
print(f'Popular: {r.json()}')

# Test failed
r = s.get(f'{BASE}/api/v1/admin/failed-keywords', headers=h)
print(f'Failed keywords: {r.json()}')
