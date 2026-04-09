# CleverSearch 수동 테스트 실행 체크리스트 (2026-04-08)

목표

- 최근 반영사항이 기존 기능에 영향 없이 동작하는지 빠르게 검증
- 업로드 중복 차단, 서버 기동 안정성, 검색 파이프라인 무영향 상태를 우선 확인

## 1) 사전 준비

- 가상환경 활성화
- 서버가 떠 있으면 종료 후 시작
- 관리자 계정 준비: admin / admin123!
- 테스트 파일 5종 준비

## 2) 서버 기동 안정성 확인 (Windows)

1. CheckOnly 점검 실행
   - 명령: ./scripts/start_dev.ps1 -CheckOnly -KillExisting
   - 기대: env 로드, 기존 프로세스 정리, 포트 점검, CheckOnly 완료
2. 실제 기동
   - 명령: ./scripts/start_dev.ps1 -KillExisting
   - 기대: 8000 사용 가능 시 8000 기동, 불가 시 fallback 포트 안내
3. 헬스체크
   - 명령: Invoke-WebRequest http://127.0.0.1:8000/
   - 기대: 200 응답

## 3) 업로드/중복 차단 확인

1. 관리자 페이지 접속 후 파일 업로드 탭 진입
2. 5개 파일 일괄 업로드 (클릭 다중선택 또는 드래그)
   - 기대: success 표시
3. 동일 파일 재업로드
   - 기대: skipped
4. 파일명만 바꾼 동일 내용 파일 업로드
   - 기대: skipped (해시 또는 제목+본문 중복)
5. 업로드 도중 버튼 연타
   - 기대: 중복 요청 잠금으로 동시 업로드 재진입 차단

## 4) 검색 기본 동작 회귀 확인

1. 대표 쿼리 검색
   - 연구개발계획서
   - 보안
   - AI개발진행
2. 기대
   - 기존과 동일한 결과 노출
   - 검색 실패/오류 없이 응답

## 5) 검색 파이프라인 무영향 확인

1. 기본값 확인
   - 기대: SEARCH_PIPELINE_VERSION=v1, SEARCH_SHADOW_COMPARE=False
2. 기본값 상태에서 대표 쿼리 재검증
   - 기대: 기존 동작 동일
3. Shadow만 활성화 (선택)
   - SEARCH_SHADOW_COMPARE=true
   - 기대: 사용자 응답은 v1 유지, 비교 로그만 기록

## 6) 초성 검색 확장 모드 확인 (대국민 서비스 대비)

1. 기본 모드 확인
   - 기대: SEARCH_CHOSUNG_QUERY_MODE=wildcard
2. wildcard 모드에서 초성 검색
   - 쿼리: ㅇㄱㄱㅂㄱㅎㅅ, ㅂㅇ
   - 기대: 기존과 동일한 결과
3. hybrid 모드 점검 (선택)
   - SEARCH_CHOSUNG_QUERY_MODE=hybrid 설정 후 재기동
   - 기대: 결과 품질 유지, 에러 없이 응답
4. ngram 모드 점검 (신규 인덱스 환경에서만 선택)
   - SEARCH_CHOSUNG_QUERY_MODE=ngram 설정 후 재기동
   - 기대: 초성 검색/자동완성 정상 동작

## 7) 권한/보안 기본 확인

1. viewer 로그인
   - 기대: 조회 가능, 쓰기 버튼 비활성
2. admin 로그인
   - 기대: 모든 관리 기능 활성

## 8) 빠른 자동 테스트

- 명령:
  - python -m pytest tests/test_search_chosung_mode.py tests/test_config_runtime_safety.py tests/test_db_service.py tests/test_system_services.py tests/test_auth_security.py -q
- 기대:
  - 전체 통과

## 9) 종료

- 테스트 종료 후 python 프로세스 정리
- 필요한 경우 기동 로그 캡처 저장

## 판정 기준

- 서버 기동 실패 없음
- 업로드 중복 차단 정상
- 검색 결과 회귀 없음
- 권한 분리 정상
- 핵심 자동 테스트 통과
