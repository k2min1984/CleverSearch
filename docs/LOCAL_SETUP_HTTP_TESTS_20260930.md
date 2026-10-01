# CleverSearch 실제 HTTP 시나리오 결과

실행시각: 2026-09-30T00:54:55.458517

| 항목 | 결과 | 상세 |
|---|---|---|
| 관리자 로그인 | 통과 | {"http": 200} |
| viewer 쓰기 거부 | 통과 | 403 |
| 업로드 1. 연구개발계획서 양식_울산지방청.pdf | 통과 | {"http": 200, "result": {"status": "skipped", "message": "DB 중복(동일 파일): 1. 연구개발계획서 양식_울산지방청.pdf", "filename": "1. 연구개발계획서 양식_울산지방청.pdf"}} |
| 업로드 연구개발계획서_작성중.docx | 통과 | {"http": 200, "result": {"status": "skipped", "message": "DB 중복(동일 파일): 연구개발계획서_작성중.docx", "filename": "연구개발계획서_작성중.docx"}} |
| 업로드 AI개발진행-20251201.pptx | 통과 | {"http": 200, "result": {"status": "skipped", "message": "DB 중복(동일 파일): AI개발진행-20251201.pptx", "filename": "AI개발진행-20251201.pptx"}} |
| 업로드 통합검색솔루션_종합문서_20260123_V001.xlsx | 통과 | {"http": 200, "result": {"status": "skipped", "message": "DB 중복(동일 파일): 통합검색솔루션_종합문서_20260123_V001.xlsx", "filename": "통합검색솔루션_종합문서_20260123_V001.xlsx"}} |
| 업로드 2026_운영지침_보안.pdf.jpg | 통과 | {"http": 200, "result": {"status": "skipped", "message": "DB 중복(동일 파일): 2026_운영지침_보안.pdf.jpg", "filename": "2026_운영지침_보안.pdf.jpg"}} |
| 문서 목록 5건 | 통과 | {"total": 5} |
| 5개 다중 업로드 중복 처리 | 통과 | {"http": 200, "summary": {"total": 5, "success": 0, "skipped": 5, "fail": 0}} |
| 중복 연구개발계획서_작성중.docx | 통과 | {"http": 200, "status": "skipped"} |
| 중복 중복이름_변경.docx | 통과 | {"http": 200, "status": "skipped"} |
| 검색 연구개발계획서 | 통과 | {"total": 2, "files": ["연구개발계획서_작성중.docx", "1. 연구개발계획서 양식_울산지방청.pdf"], "ms": 338.7} |
| 검색 AI개발진행 | 통과 | {"total": 2, "files": ["AI개발진행-20251201.pptx", "연구개발계획서_작성중.docx"], "ms": 85.5} |
| 검색 운영지침 | 통과 | {"total": 3, "files": ["2026_운영지침_보안.pdf.jpg", "통합검색솔루션_종합문서_20260123_V001.xlsx", "1. 연구개발계획서 양식_울산지방청.pdf"], "ms": 95.8} |
| 검색 ㅇㄱㄱㅂㄱㅎㅅ | 통과 | {"total": 2, "files": ["연구개발계획서_작성중.docx", "1. 연구개발계획서 양식_울산지방청.pdf"], "ms": 69.0} |
| 시나리오 오타 교정 계휙서 | 통과 | {"total": 2, "corrected": "계획서", "ms": 86.4} |
| 발표 오타 교정 연구개발게획서 | 통과 | {"total": 2, "corrected": "연구개발계획서"} |
| 포함필터 | 통과 | {"total": 1, "files": ["1. 연구개발계획서 양식_울산지방청.pdf"]} |
| 제외필터 | 통과 | {"total": 1, "files": ["1. 연구개발계획서 양식_울산지방청.pdf"]} |
| 확장자필터 | 통과 | {"total": 1, "files": ["1. 연구개발계획서 양식_울산지방청.pdf"]} |
| 24시간 필터 | 통과 | {"total": 2, "files": ["연구개발계획서_작성중.docx", "1. 연구개발계획서 양식_울산지방청.pdf"]} |
| 자동완성 연구 | 통과 | ["연구개발계획서_작성중.docx", "1. 연구개발계획서 양식_울산지방청.pdf"] |
| 자동완성 ㅇㄱ | 통과 | ["연구개발계획서_작성중.docx", "1. 연구개발계획서 양식_울산지방청.pdf"] |
| 없는 검색어 0건 | 통과 | {"total": 0} |
| 관리자 search-logs | 통과 | {"http": 200, "count": 41} |
| 관리자 failed-keywords | 통과 | {"http": 200, "count": 1} |
| 관리자 popular-keywords | 통과 | {"http": 200, "count": 9} |
| 검색 편의 recent | 통과 | {"http": 200, "count": 6} |
| 검색 편의 popular | 통과 | {"http": 200, "count": 4} |
| 검색 편의 recommend | 통과 | {"http": 200, "count": 9} |
| 최근검색 단건 삭제 | 통과 | {"http": 200} |
| 최근검색 전체 삭제 | 통과 | {"http": 200, "result": []} |
| 동시 검색 2건 | 통과 | [200, 200] |
| 화면 HTTP / | 통과 | {"http": 200} |
| 화면 HTTP /admin | 통과 | {"http": 200} |
| 화면 HTTP /static/user/index.html | 통과 | {"http": 200} |
| 화면 HTTP /docs | 통과 | {"http": 200} |