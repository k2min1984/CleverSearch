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

## 8000 재발 방지용 시작/종료

```powershell
# 8000 포트 선정리 후 단일 인스턴스로 시작
pwsh -File scripts/start_8000.ps1

# SSL로 시작
pwsh -File scripts/start_8000.ps1 -UseSsl

# (기본은 no-reload) reload가 필요할 때만 명시적으로 사용
pwsh -File scripts/start_8000.ps1 -UseSsl -UseReload

# 8000 점유/uvicorn 잔여 프로세스 정리
pwsh -File scripts/stop_8000.ps1
```

## 참고 문서

- 기동 런북: docs/STARTUP_RUNBOOK_20260406.md
- 테스트 체크리스트: docs/test_run_checklist_20260408.md
- 블루/그린 롤아웃: docs/PUBLIC_SERVICE_BLUE_GREEN_ROLLOUT_20260408.md

## 검색 방식 비교 (쉬운 설명)

아래 표는 "DB만으로 검색"과 "DB + OpenSearch"의 차이를 일반 사용자 관점에서 쉽게 정리한 것입니다.

| 항목               | DB만 사용              | DB + OpenSearch               |
| ------------------ | ---------------------- | ----------------------------- |
| 검색 속도          | 데이터가 늘수록 느려짐 | 데이터가 늘어도 비교적 안정적 |
| 검색 정확도        | 단순 키워드 중심       | 문맥/유사도까지 반영 가능     |
| 자동완성/추천 품질 | 기본 수준              | 더 정교한 추천 가능           |
| 대량 문서 대응     | 중간 규모부터 부담 큼  | 중대규모에도 유리             |
| 운영 복잡도        | 단순함                 | 검색엔진 운영이 추가됨        |
| 추천 상황          | 소규모/단순 검색       | 운영형/고품질 검색            |

## OpenSearch 설치 시 운영 방안 (옆표)

아래 표는 "OpenSearch를 설치한다"고 가정했을 때, 무엇을 준비하고 어떻게 운영하면 되는지 한눈에 보여줍니다.

| 구분             | 무엇을 하면 되나요?                                | 왜 필요한가요? (쉬운 설명)                     |
| ---------------- | -------------------------------------------------- | ---------------------------------------------- |
| 1. 설치          | `docker compose up -d opensearch` 실행             | 검색 전용 엔진을 먼저 켜야 빠른 검색이 가능함  |
| 2. 앱 연결       | `.env`의 OpenSearch 주소/인덱스 확인               | 앱이 검색엔진 위치를 알아야 연결됨             |
| 3. 데이터 적재   | 문서 업로드 후 색인(Index) 생성                    | 책 목차를 만드는 것처럼, 검색용 색인이 필요함  |
| 4. 검증          | `/docs`에서 검색 API 호출 테스트                   | 실제 검색이 되는지 빠르게 확인 가능            |
| 5. 운영 모니터링 | 검색 응답시간, 실패율, 색인 상태 확인              | 느려지기 전에 미리 이상 징후를 잡기 위함       |
| 6. 장애 대비     | OpenSearch 장애 시 DB 기반 최소 검색 제공          | 완전 중단 대신 "기본 검색"은 유지하기 위함     |
| 7. 확장 전략     | 문서 증가 시 OpenSearch 리소스(메모리/디스크) 증설 | 사용자가 늘어도 검색 체감 속도를 유지하기 위함 |

### 한 줄 권장안

- 소규모 내부 도구면 DB만으로 시작 가능
- 대국민/운영형 서비스면 DB를 기준 데이터로 두고 OpenSearch를 검색 전용으로 함께 운영 권장
