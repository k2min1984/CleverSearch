# CleverSearch

CleverSearch는 OpenSearch 기반 문서 검색 서비스입니다.

## 빠른 시작 (Windows)

### 1) 사전 준비

- PowerShell 7 (`pwsh`)
- Python 3.10+
- Docker Desktop (권장)

### 2) 저장소 다운로드

```powershell
git clone https://github.com/k2min1984/CleverSearch.git
cd CleverSearch
```

### 3) 인프라 기동 (권장)

```powershell
docker compose up -d opensearch
```

참고:

- DB는 로컬이 아니라 원격 PostgreSQL 서버를 기본 사용합니다.
- 기본 환경파일 `.env.example`에 원격 DB 접속값이 포함되어 있습니다.

### 4) 앱 기동 (개발)

```powershell
pwsh -File scripts/start_dev.ps1
```

스크립트 동작:

- `.venv`가 없으면 자동 생성
- `requirements.txt` 패키지 자동 설치/업데이트
- 기본 환경파일 `.env.example` 자동 사용 (원격 DB)
- 기존 uvicorn 실행 중이면 자동 종료 후 재기동 (포트 중복 방지)

접속:

- 앱: http://127.0.0.1:8000
- 관리자: http://127.0.0.1:8000/admin
- API 문서: http://127.0.0.1:8000/docs

SSL로 실행하려면:

```powershell
pwsh -File scripts/start_dev.ps1 -UseSsl
```

## 운영 기동

```powershell
pwsh -File scripts/start_prod.ps1 -EnvFile .env.production
```

운영 스크립트 동작:

- `security_preflight.py` 선검증 (실패 시 중단)
- `.venv` 자동 생성/의존성 설치
- `.env.production`이 없으면 `.env.production.example` 사용

## 자주 쓰는 옵션

```powershell
pwsh -File scripts/start_dev.ps1 -CheckOnly
pwsh -File scripts/start_dev.ps1 -BindHost 127.0.0.1 -Port 8000
pwsh -File scripts/start_dev.ps1 -UseSsl
pwsh -File scripts/start_prod.ps1 -CheckOnly
```

## 참고 문서

- 기동 런북: docs/STARTUP_RUNBOOK_20260406.md
- 테스트 체크리스트: docs/test_run_checklist_20260408.md
- 블루/그린 롤아웃: docs/PUBLIC_SERVICE_BLUE_GREEN_ROLLOUT_20260408.md
