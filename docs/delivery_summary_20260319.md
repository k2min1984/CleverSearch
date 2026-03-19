# 작업 요약 (2026-03-19)

## 1) 구현 완료 범위

- refresh token 서버측 블랙리스트 분리 관리
- 사용자/권한 DB 테이블 이관
- AUTH_USERS_JSON 의존 제거
- 관리자 대시보드 알림 배지 구현
  - 인증서 임박
  - 스케줄러 중지
  - 실패율 급등
- 관리자 화면 JWT 로그인/갱신/로그아웃 흐름 고도화

## 2) 주요 추가 파일

- app/api/v1/auth.py
- alembic/versions/20260319_0004_add_auth_and_token_blacklist_tables.py
- docs/schedule_added_20260319.md

## 3) 주요 수정 파일

- app/core/database.py
- app/core/security.py
- app/core/config.py
- app/api/v1/system.py
- app/services/system_service.py
- static/admin.html
- tests/test_auth_security.py
- scripts/run_system_smoke_tests.py
- docs/test_scenarios_20260319.md
- .env
- .env.example

## 4) 검증 결과

- Alembic 업그레이드: 성공
- 단위 테스트(10건): 전부 통과
- 시스템 스모크 테스트: passed=true

## 5) 운영 확인 포인트

- 실제 SMB 실서버 경로/권한 연결 확인
- Oracle/MySQL 실접속 URL 기반 배치 검증
- 인증서 만료 임계값 정책 확정
