# CleverSearch 운영 투입 마스터 문서 (2026-03-30)

목적: 폐쇄망 + 대국민 서비스 운영 투입 시 필요한 핵심 결정을 한 문서에서 확인하기 위함.

## 1) 현재 상태 요약

- 기능 일정: 완료 상태 (기준: docs/schedule_status.md)
- 보안 하드닝: 코드 반영 완료
- 남은 작업: 운영 환경값 확정/주입, 배포 직전 보안 사전점검 실행

## 2) 코드 기준 보안 반영 항목

- CORS 화이트리스트 적용
- Host 헤더 검증 적용
- 보안 응답 헤더(CSP/HSTS/X-Frame-Options 등) 적용
- 운영 환경 보안 가드(약한 설정 시 기동 차단)
- 로그인 시도 제한(브루트포스 완화)
- API 문서 운영 환경 기본 비노출

## 3) 운영 환경에서 반드시 확정할 값

- APP_ENV=production
- ENABLE_API_DOCS=false
- CORS_ALLOWED_ORIGINS=실제 서비스 도메인만
- ALLOWED_HOSTS=실제 서비스 호스트만
- JWT_SECRET=32자 이상 고강도 랜덤값
- OS_PASSWORD=기본/약한 값 금지
- OPENSEARCH_VERIFY_CERTS=true

## 4) 실행 순서 (운영 배포 전)

1. .env.production.example 기반으로 운영 환경 변수 확정
2. 비밀값(비밀번호/시크릿) 보안 저장소에서 주입
3. 보안 사전점검 실행
4. 실패 항목 0건 확인 후 앱 기동

### 사전점검 커맨드

```powershell
python scripts/security_preflight.py
```

### 앱 기동 예시

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8443
```

## 5) 실패 시 배포 중단 조건

- JWT_SECRET 기본값 또는 32자 미만
- CORS_ALLOWED_ORIGINS/ALLOWED_HOSTS에 와일드카드 사용
- 운영에서 ENABLE_API_DOCS=true
- 운영에서 OPENSEARCH_VERIFY_CERTS=false
- 보안 사전점검 결과 FAIL

## 6) 관련 문서

- docs/security_deployment_checklist_20260330.md
- docs/schedule_status.md
- docs/FULL_TEST_SCENARIO_BY_SCHEDULE_WITH_EVIDENCE_20260330.md
- .env.production.example
- .env.example
- scripts/security_preflight.py
