"""인덱스 삭제 -> 재업로드 -> 검색 테스트"""
import requests, json, time, os, urllib3
urllib3.disable_warnings()
S = requests.Session()
S.verify = False

# login
r = S.post('https://localhost:8000/api/v1/auth/login', json={'username':'admin','password':'admin123!'})
print(f'Login: {r.status_code}')
token = r.json()['access_token']
S.headers['Authorization'] = f'Bearer {token}'

# delete index
r = S.delete('https://localhost:8000/api/v1/file/delete-index')
print(f'Delete index: {r.status_code} {r.text}')

# upload one file
fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', '연구개발계획서_작성중.docx')
print(f'\nUpload file exists: {os.path.exists(fpath)}')
with open(fpath, 'rb') as f:
    r = S.post('https://localhost:8000/api/v1/file/upload', files={'file': ('연구개발계획서_작성중.docx', f)})
print(f'Upload: {r.status_code} {r.text}')

time.sleep(2)

# search
r = S.post('https://localhost:8000/api/v1/search/query', json={'query': '연구개발계획서', 'page': 1, 'size': 10})
d = r.json()
print(f'\nSearch: code={r.status_code}')
print(f'  total: {d.get("total")}')
print(f'  error: {d.get("error","none")}')
items = d.get('items', [])
print(f'  items: {len(items)}')
for it in items[:3]:
    print(f'    {it.get("content",{}).get("origin_file","?")} score={it.get("score")}')

# duplicate upload test
print('\n--- Duplicate test ---')
with open(fpath, 'rb') as f:
    r = S.post('https://localhost:8000/api/v1/file/upload', files={'file': ('연구개발계획서_작성중.docx', f)})
print(f'Duplicate upload: {r.status_code} {r.text}')

# dictionary test
print('\n--- Dictionary test ---')
r = S.post('https://localhost:8000/api/v1/system/dictionary/entry?dict_type=user_dict&term=계휙서&replacement=계획서&is_active=true')
print(f'user_dict: {r.status_code} {r.text}')

r = S.post('https://localhost:8000/api/v1/system/dictionary/entry?dict_type=stopword&term=에&is_active=true')
print(f'stopword: {r.status_code} {r.text}')

r = S.post('https://localhost:8000/api/v1/system/dictionary/entry?dict_type=invalid&term=test&is_active=true')
print(f'invalid type: {r.status_code} {r.text}')
