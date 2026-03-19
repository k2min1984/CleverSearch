# CleverSearch 보완 기능 테스트 시나리오 (2026-03-19)

## 1. 사전 관리/실시간 반영 (37, 38)

- 목적: 동의어/불용어/사용자 사전 즉시 반영 확인
- 준비: API 서버 실행, 관리자 권한 헤더 준비 (`X-Role: operator`)
- 절차:
  1. `POST /api/v1/system/dictionary/entry?dict_type=synonym&term=AI&replacement=인공지능`
  2. `POST /api/v1/system/dictionary/entry?dict_type=stopword&term=에`
  3. `POST /api/v1/system/dictionary/entry?dict_type=user&term=게획&replacement=계획`
  4. `POST /api/v1/search/query`로 `AI 게획 에` 검색
- 기대결과:
  - 교정 쿼리 반영
  - 동의어 확장 반영
  - 불용어 제거 반영

## 2. SMB 소스 등록/즉시 동기화 (18, 20)

- 목적: SMB 경로 접근 및 재연결/복구 경로 확인
- 준비: 접근 가능한 SMB 경로
- 절차:
  1. `POST /api/v1/system/smb/sources`로 소스 등록
  2. `POST /api/v1/system/smb/sources/{id}/sync` 실행
- 기대결과:
  - `indexed`, `skipped`, `failed` 카운트 반환
  - 접근 실패 시 `last_error` 기록

## 3. 자동 색인 스케줄러 (19)

- 목적: 주기 실행 확인
- 절차:
  1. `POST /api/v1/system/scheduler/start?interval_seconds=30`
  2. 1분 대기
  3. `GET /api/v1/system/scheduler/status`
  4. `POST /api/v1/system/scheduler/stop`
- 기대결과:
  - `running=true` 상태 확인
  - `last_run_at`, `last_summary` 갱신

## 4. 멀티 DB 소스/배치/분할수집 (21, 22, 23, 51, 52)

- 목적: DB 소스 등록, chunk 단위 수집 동작 확인
- 준비: 테스트 DB 테이블, 접속 URL
- 절차:
  1. `POST /api/v1/system/db/sources` 등록
  2. `POST /api/v1/system/db/sources/{id}/sync?max_rows=2000`
- 기대결과:
  - `chunk_size` 단위 fetchmany 실행
  - `indexed/skipped/failed` 집계
  - `last_synced_at` 갱신

## 5. 검색 정확도 비교 (30)

- 목적: 랭킹 튜닝 전/후 지표 비교
- 절차:
  1. 기준점 측정: `python scripts/evaluate_search_quality.py --input tests/search_judgements.generated.json --k 10 --size 20 > baseline.json`
  2. 튜닝 반영 후 재측정: `python scripts/evaluate_search_quality.py --input tests/search_judgements.generated.json --k 10 --size 20 > candidate.json`
  3. 비교 실행: `python scripts/compare_ranking_runs.py --base baseline.json --candidate candidate.json`
- 기대결과:
  - `delta.avg_ndcg`, `delta.avg_mrr` 확인
  - `improved=true` 목표

## 6. 대시보드 지표 API (40)

- 목적: 통계 시각화용 데이터 제공 확인
- 절차:
  1. `GET /api/v1/system/dashboard/summary?days=7`
  2. `GET /api/v1/system/dashboard/trend?days=14`
  3. `GET /api/v1/system/health/overview`
- 기대결과:
  - 요약 수치/일자별 추이 JSON 반환
  - 운영 상태 요약(JSON) 반환

## 7. 볼륨/SSL 자동화 (42, 43, 44)

- 목적: 인덱스 생성 자동화, 인증서 상태 모니터링, 갱신 스크립트 생성/실행 확인
- 절차:
  1. `POST /api/v1/system/volume/create` (`{"index_name":"cleversearch-volume-test","shards":1,"replicas":1}`)
  2. `GET /api/v1/system/ssl/certificates?cert_dir=cert&warn_days=30`
  3. `POST /api/v1/system/ssl/renew-script?output_path=scripts/renew_certs.ps1`
  4. (선택) `POST /api/v1/system/ssl/renew-run` (`{"script_path":"scripts/renew_certs.ps1"}`)
- 기대결과:
  - 인덱스 생성 성공
  - 인증서 만료일/잔여일/상태 반환
  - 갱신 스크립트 생성 및 실행 로그 반환

## 8. RBAC 메뉴/접근 제어 (39)

- 목적: 최소 권한 제어 확인
- 절차:
  1. `X-Role: viewer`로 `GET /api/v1/admin/popular-keywords` 호출
  2. `X-Role: viewer`로 `POST /api/v1/system/volume/create` 호출
  3. `X-Role: admin`로 `POST /api/v1/system/volume/create` 재호출
- 기대결과:
  - viewer: 조회 허용, 관리자 작업 거부(403)
  - admin: 관리자 작업 허용

## 9. 시스템 스모크 자동화 실행

- 목적: 신규 System 기능을 한 번에 기본 검증
- 절차:
  1. `python scripts/run_system_smoke_tests.py > system_smoke_result.json`
  2. `system_smoke_result.json`에서 `passed` 값 확인
- 기대결과:
  - `passed=true`
  - `checks[]` 전체 `passed=true`

## 10. JWT 인증 전환 검증

- 목적: 헤더 RBAC 하위호환 + JWT 권한 검증
- 절차:
  1. `POST /api/v1/auth/login` (`{"username":"admin","password":"admin123!"}`)
  2. 응답 `access_token` 확인
  3. 응답 `refresh_token` 확인
  4. `POST /api/v1/auth/refresh`로 토큰 재발급
  5. `POST /api/v1/auth/logout` 호출
  6. 로그아웃한 토큰으로 관리자 API 호출 시도
- 기대결과:
  - 로그인 성공
  - 재발급 성공
  - 로그아웃 후 기존 토큰 차단(401)

## 11. 관리자 화면 스모크 원클릭 실행

- 목적: 관리자 UI에서 시스템 스모크 테스트 즉시 실행
- 절차:
  1. `/admin` 접속
  2. JWT 로그인 버튼 클릭
  3. 대시보드 탭 `스모크 실행` 버튼 클릭
- 기대결과:
  - `smokeOutput` 영역에 JSON 결과 표시
  - `passed=true` 확인

## 12. 분리 블랙리스트 검증 (Access/Refresh)

- 목적: access/refresh 토큰이 서버측에서 분리 차단되는지 확인
- 절차:
  1. 로그인 후 `access_token`, `refresh_token` 확보
  2. `POST /api/v1/auth/refresh` 1회 호출
  3. 같은 refresh token 재사용 호출
  4. 재발급 access token으로 `POST /api/v1/auth/logout` 호출
  5. 로그아웃한 access token으로 관리자 API 재호출
- 기대결과:
  - refresh 1회성 사용 성공
  - refresh 재사용 차단(401)
  - 로그아웃 access token 차단(401)

## 13. DB 기반 사용자/권한 검증

- 목적: DB 테이블(auth_users/auth_roles) 기반 인증 동작 확인
- 절차:
  1. `init_database()` 후 기본 계정 생성 확인
  2. `admin/admin123!` 로그인
  3. 권한 필요한 System API 호출
- 기대결과:
  - DB 사용자 인증 성공
  - 권한별 접근 제어 동작

## 14. 운영 알림 배지 검증

- 목적: 인증서 임박/스케줄러 중지/실패율 급등 배지 노출 확인
- 절차:
  1. `GET /api/v1/system/dashboard/alerts`
  2. `/admin` 대시보드에서 배지 렌더링 확인
- 기대결과:
  - 배지 목록 JSON 반환
  - UI 배지 렌더링 정상
