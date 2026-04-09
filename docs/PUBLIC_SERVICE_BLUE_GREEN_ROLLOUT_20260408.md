# CleverSearch 대국민 서비스 무중단 전환 가이드 (Blue/Green) - 2026-04-08

목적

- 기존 기능 무영향을 최우선으로 유지하면서 초성 검색 성능을 단계적으로 확장
- wildcard 기반 운영에서 ngram/hybrid 기반으로 안전하게 전환

## 1. 기본 원칙

- 기본 운영값은 유지
  - SEARCH_PIPELINE_VERSION=v1
  - SEARCH_SHADOW_COMPARE=false
  - SEARCH_CHOSUNG_QUERY_MODE=wildcard
- 신규 인덱스는 Green으로 별도 생성하고 데이터 검증 후 스위칭
- 스위칭 전/후 동일 쿼리 회귀 검증 필수

## 2. 사전 점검

1. 핵심 테스트 통과 확인
   - python -m pytest tests/test_search_chosung_mode.py tests/test_config_runtime_safety.py tests/test_db_service.py tests/test_system_services.py tests/test_auth_security.py -q
2. 서버 기동 점검
   - ./scripts/start_dev.ps1 -CheckOnly -KillExisting
3. 대표 쿼리 기준선 측정
   - 연구개발계획서, 보안, AI개발진행, ㅇㄱㄱㅂㄱㅎㅅ, ㅂㅇ

## 3. Green 인덱스 준비

1. Green 인덱스명 결정
   - 예: cleversearch-docs-v2
2. 환경변수 OPENSEARCH_INDEX를 Green으로 설정
3. 인덱스 생성
   - 앱 기동 시 ensure_index/create_index 경로에서 chosung_text_ngram 포함 매핑 생성
4. 데이터 재색인
   - 기존 문서 재업로드/배치 색인으로 Green 채우기

## 4. 검증 단계

1. 기능 검증
   - 파일 업로드, 중복 차단, 기본 검색, 상세 검색, 자동완성, 권한 분리
2. 초성 모드 검증
   - wildcard: 기존 품질 확인
   - hybrid: 품질 유지 + 응답 안정성 확인
   - ngram: Green 인덱스에서 응답 시간 비교
3. 성능 검증
   - p95 응답시간, 오류율, 노드 CPU/메모리

## 5. 스위칭 단계

1. 애플리케이션 환경변수 반영
   - OPENSEARCH_INDEX=cleversearch-docs-v2
   - SEARCH_CHOSUNG_QUERY_MODE=hybrid (권장 시작점)
2. 서버 재기동
3. 헬스체크
   - Invoke-WebRequest http://127.0.0.1:8000/
4. 대표 쿼리 회귀 재확인

## 6. 롤백 계획

- 즉시 롤백 기준
  - 검색 실패율 급증
  - p95 응답시간 임계치 초과 지속
  - 업로드/중복 차단 이상
- 롤백 방법
  - OPENSEARCH_INDEX를 이전 Blue 인덱스로 복귀
  - SEARCH_CHOSUNG_QUERY_MODE=wildcard 복귀
  - 서버 재기동 후 헬스체크

## 7. 운영 권장값

- 초기 대국민 오픈
  - SEARCH_CHOSUNG_QUERY_MODE=wildcard 또는 hybrid
- 트래픽 증가 후
  - Green 검증 완료 시 ngram 단계적 전환
- 항상 유지
  - 기본 검색 결과 회귀 테스트 + 업로드 중복 차단 테스트
