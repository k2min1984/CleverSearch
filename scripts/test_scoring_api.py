import requests, urllib3, json
urllib3.disable_warnings()
s = requests.Session()
s.verify = False

r = s.post('https://localhost:8443/api/v1/auth/login', json={'username':'admin','password':'admin123!'})
token = r.json()['access_token']
h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

test_cases = [
    {'query': '연구개발계획서', 'expected_title': '연구개발계획서'},
    {'query': '보안', 'expected_title': '보안'},
    {'query': 'AI개발', 'expected_title': 'AI개발진행'},
    {'query': '통합검색', 'expected_title': '통합검색솔루션'},
    {'query': '운영지침', 'expected_title': '운영지침'}
]
r = s.post('https://localhost:8443/api/v1/system/scoring/evaluate', headers=h, json={'test_cases': test_cases}, timeout=120)
print('Evaluate:', r.status_code)
data = r.json()
print(f"총 {data['total']}건 | 통과 {data['passed']}건 | 실패 {data['failed']}건 | 통과율 {data['pass_rate']}%")
for d in data['details']:
    icon = '✅' if d['found'] else '❌'
    print(f"{icon} \"{d['query']}\" -> {d['result_count']}건, 최고점수: {d['top_score']}, 상위: {d['top_titles']}")
