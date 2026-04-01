# CleverSearch 보안 배포 체크리스트 (2026-03-30)

대상: 폐쇄망/대국민 서비스 운영 배포

관련 마스터 문서: `docs/MASTER_PRODUCTION_READINESS_20260330.md`

## 1. 필수 환경변수 점검

- APP_ENV=production
- ENABLE_API_DOCS=false
- ENABLE_SECURITY_HEADERS=true
- CORS_ALLOWED_ORIGINS: 실제 서비스 도메인만 허용
- ALLOWED_HOSTS: 실제 서비스 호스트만 허용
- JWT_SECRET: 32자 이상 랜덤 고강도 값
- OS_PASSWORD: 기본값 금지 (admin, Admin123! 등)
- OPENSEARCH_VERIFY_CERTS=true

## 2. 인증/인가

- JWT Access 만료: 30분 내외
- JWT Refresh 만료: 24시간 내외
- 로그인 시도 제한 동작 확인(429)
- 관리자 계정 비밀번호 정책 적용(길이/복잡도)

## 3. 네트워크/인프라

- 외부 노출 포트 최소화 (443/필수 포트만)
- 리버스 프록시에서 TLS 종료 시 HSTS 전달 확인
- WAF 정책 적용 (OWASP Top 10 룰셋)
- DDoS 보호 정책 적용

## 4. 데이터 보안

- DB 계정 최소권한 원칙(읽기/쓰기 분리 가능 시 분리)
- 백업 암호화 및 복구 리허설
- 로그 내 민감정보(토큰/비밀번호) 출력 금지

## 5. 운영 점검

- /docs, /redoc, /openapi.json 비노출 확인
- CORS 오리진 차단 테스트(미허용 Origin 요청)
- Host 헤더 검증 테스트(미허용 Host 400/차단)
- CSP, X-Frame-Options, X-Content-Type-Options 응답 헤더 확인

## 6. 배포 전 커맨드 예시

```powershell
# 환경 변수 반영 후 실행
$env:APP_ENV = "production"
$env:ENABLE_API_DOCS = "false"
$env:OPENSEARCH_VERIFY_CERTS = "true"

# 보안 사전 점검 (실패 시 배포 중단)
python scripts/security_preflight.py

# 앱 기동 (운영은 별도 프로세스 매니저 권장)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8443
```

## 7. 위험 신호 (즉시 중단)

- 기본 JWT_SECRET 사용
- CORS_ALLOWED_ORIGINS에 \* 포함
- ENABLE_API_DOCS=true 상태로 운영 배포
- OPENSEARCH_VERIFY_CERTS=false 상태로 운영 배포

운영 환경에서 위 항목 발견 시 배포 중단 후 재검증한다.
