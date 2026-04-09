# CleverSearch Startup Runbook (2026-04-06)

목표: 개발/운영 기동 경로를 분리하고, startup 로그를 기준으로 원인-조치를 빠르게 판단한다.

## 0. 다운로드 직후(처음 사용자) 빠른 시작

사전 준비:

- Windows + PowerShell 7 (`pwsh`)
- Python 3.10+
- Docker Desktop (OpenSearch/PostgreSQL 컨테이너 사용 시)

인프라 기동(권장):

```powershell
docker compose up -d postgres opensearch
```

앱 기동(개발):

```powershell
pwsh -File scripts/start_dev.ps1
```

설명:

- `start_dev.ps1`는 `.venv`가 없으면 자동 생성합니다.
- `requirements.txt` 기반 패키지 설치/업데이트를 자동 실행합니다.
- 기본 환경파일은 `.env.example`을 사용합니다.

## 1. 실행 스크립트

- 개발 기동: scripts/start_dev.ps1
- 운영 기동: scripts/start_prod.ps1

## 2. 개발 기동 (HTTP + reload)

```powershell
pwsh -File scripts/start_dev.ps1
```

옵션:

```powershell
pwsh -File scripts/start_dev.ps1 -EnvFile .env.example -BindHost 127.0.0.1 -Port 8000
pwsh -File scripts/start_dev.ps1 -CheckOnly
```

설명:

- 개발은 기본적으로 HTTP + reload를 사용한다.
- SSL 테스트는 reload 없이 별도 점검을 권장한다.
- 실행 시 가상환경/의존성 자동 점검을 수행한다.

## 3. 운영 기동 (preflight + non-reload)

```powershell
pwsh -File scripts/start_prod.ps1 -EnvFile .env.production
```

옵션:

```powershell
pwsh -File scripts/start_prod.ps1 -EnvFile .env.production -BindHost 0.0.0.0 -Port 8443
pwsh -File scripts/start_prod.ps1 -EnvFile .env.production -CheckOnly
```

설명:

- 실행 전 scripts/security_preflight.py를 강제 수행한다.
- preflight 실패 시 서버 기동을 중단한다.
- `.env.production`이 없으면 `.env.production.example`을 대체로 사용한다.

## 4. startup 로그 표준

형식:

- [STARTUP][INFO][STEP] 메시지
- [STARTUP][PASS][STEP] 메시지
- [STARTUP][WARN][STEP] 메시지
- [STARTUP][FAIL][STEP] 메시지 | 조치: ...

주요 STEP:

- BOOT
- SECURITY
- DATABASE
- BOOTSTRAP
- OPENSEARCH
- SCHEDULER
- READY
- SHUTDOWN

## 5. 원인-조치 빠른 가이드

- 인증 실패(401): OS_ADMIN/OS_PASSWORD를 OpenSearch 실제 계정과 일치
- 권한 부족(403): 인덱스 조회/생성 권한 부여
- TLS/인증서 실패: 인증서 체인 및 VERIFY_CERTS 설정 점검
- 연결 실패: OpenSearch 서비스 상태/URL/포트/방화벽 점검
- 보안 설정 오류: APP_ENV/JWT_SECRET/CORS/HOST/VERIFY_CERTS 교정

## 6. 운영 전 체크리스트

1. .env.production에 실운영 값 적용
2. preflight PASS 확인
3. startup 로그에서 READY 확인
4. /docs 비노출(ENABLE_API_DOCS=false) 확인
