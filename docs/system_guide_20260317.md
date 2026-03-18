# CleverSearch 상세 가이드 (2026-03-17)

## 1. 코드 주석 보강 범위

이번 정리에서는 기존 주석은 그대로 두고, 새로 추가한 기능에만 주석을 보강했다.
대상은 다음과 같다.

- app/core/database.py
- app/services/db_service.py
- app/api/v1/admin.py
- app/utils/evaluation.py
- scripts/evaluate_search_quality.py
- app/services/search_service.py 의 신규 정밀도 보정 구간

의도는 다음과 같다.

- 기존 작성자의 설명은 보존
- 새로 만든 DB/관리자/평가 로직만 빠르게 이해 가능
- 추후 유지보수 시 신규 기능의 책임 범위를 즉시 파악 가능

## 2. 현재 생성된 DB는 무엇이고 어디에 있으며 어떻게 생성되는가

### 2.1 현재 기본 DB

현재 기본 업무 DB는 SQLite 파일이다.

- 위치: 프로젝트 루트의 cleversearch_app.db
- 예시 경로: 프로젝트 루트/cleversearch_app.db
- 설정값: app/core/config.py 의 DATABASE_URL 기본값은 sqlite:///./cleversearch_app.db

즉, 지금 로컬 개발에서는 별도 DB 서버 없이 파일 하나로 업무 데이터를 저장한다.

### 2.2 운영용 DB

운영 전환을 위해 PostgreSQL 연결도 이미 준비했다.

- Docker Compose 서비스: docker-compose.yml 의 postgres
- 운영 연결 문자열 예시:
  - postgresql+psycopg2://cleversearch:cleversearch123@cleversearch-postgres:5432/cleversearch

즉, 현재는 로컬 기본값이 SQLite이고, 운영/납품 단계에서는 PostgreSQL로 바꾸는 구조다.

### 2.3 DB 생성 방식

업무 DB는 두 가지 방식으로 생성된다.

1. 앱 시작 시 자동 생성

- app/main.py 에서 lifespan 시작 시 init_database() 호출
- 이 함수는 SQLAlchemy Base.metadata.create_all() 로 최소 테이블을 자동 생성한다.
- 개발 초기 진입 장벽을 낮추기 위한 안전장치다.

2. Alembic 마이그레이션 생성

- alembic.ini, alembic/env.py, alembic/versions/20260317_0001_init_app_tables.py 로 스키마 버전 관리가 가능하다.
- 운영에서는 create_all보다 Alembic을 기준으로 스키마를 관리하는 것이 맞다.

### 2.3.1 "앱 시작 시 자동 생성"이 정확히 무슨 의미인가

핵심은 다음과 같다.

1. 자동 생성 방식(create_all)

- 앱이 켜질 때 파이썬 코드가 현재 모델을 읽고 필요한 테이블이 없으면 만든다.
- 즉, 별도로 SQL 파일을 직접 실행하지 않아도 기본 테이블이 생긴다.
- 장점: 개발 초기 세팅이 빠르고 실수 가능성이 줄어든다.
- 한계: 누가 언제 어떤 스키마를 바꿨는지 이력 관리가 어렵다.

2. 스크립트 실행 방식(Alembic)

- 개발자가 만든 리비전 파일(예: 20260317_0001, 20260318_0002)을 순서대로 실행한다.
- 실행 명령 예시: alembic upgrade head
- 장점: 스키마 변경 이력을 추적할 수 있고 운영 배포에 유리하다.
- 한계: 리비전 파일 관리가 필요하다.

3. 현재 프로젝트는 두 방식이 함께 존재한다.

- 개발 편의: 앱 기동 시 create_all
- 운영 표준: Alembic 리비전 실행

4. 실무 권장

- 로컬 개발: create_all 허용
- 테스트/운영: Alembic 기준으로만 스키마 적용
- 장기적으로는 create_all을 점진적으로 줄이고 Alembic 단일 체계로 통일하는 것이 좋다.

### 2.3.2 질문에 대한 직접 답변

"현재 구조는 앱 시작 시 자동 생성 방식"이라는 말은,
일반적인 SQL 스크립트를 수동 실행하는 방식만 사용한 것이 아니라는 뜻이 맞다.

정확히는 아래 두 가지를 병행 중이다.

- 자동 생성: app/main.py -> init_database() -> create_all
- 스크립트 생성/실행: Alembic 리비전 파일 + alembic upgrade head

즉, "수동 SQL만으로 만든 구조"는 아니고, "코드 기반 자동 생성 + 버전 스크립트"를 함께 쓰는 구조다.

### 2.4 현재 실제 생성된 테이블

현재 SQLite 기준 확인된 테이블은 4개다.

1. alembic_version
2. indexed_documents
3. recent_searches
4. search_logs

참고:

- alembic_version 은 업무 데이터 테이블이 아니라 마이그레이션 버전 관리용 시스템 테이블이다.

## 3. 각 테이블 상세 설명과 사용 가능한 기능

### 3.1 search_logs

역할:

- 검색 실행 이력 원본 저장소
- 인기검색, 실패검색, 추천검색, 연관검색 계산의 기준 테이블

주요 컬럼:

- id: 로그 PK
- user_id: 사용자 식별자
- query: 사용자가 입력한 검색어
- total_hits: 검색 결과 수
- is_failed: 결과 0건 여부
- search_type: manual_search 등 로그 유형
- created_at: 검색 실행 시각

이 테이블로 가능한 기능:

- 인기 검색어 집계
- 실패 검색어 집계
- 사용자별/전체 검색 이력 조회
- 추천 검색어 계산의 원본 데이터
- 연관 검색어 계산의 원본 데이터
- 검색 트래픽 분석
- 특정 기간 검색 패턴 분석

관리자 페이지에서 연결되는 항목:

- 인기검색 카운트 탭: search_logs 를 group by 한 집계 결과
- 검색로그 탭: search_logs 원본 목록
- 실패검색어 탭: search_logs 중 is_failed = True 만 집계

중요 포인트:

- 인기검색, 검색로그, 실패검색어가 각각 다른 테이블에 저장되는 구조가 아니다.
- 셋 다 search_logs 하나를 기준으로 다른 방식으로 보여주는 파생 뷰다.
- 이 구조가 맞다. 이유는 같은 원본 이벤트를 각각 중복 저장하면 데이터 불일치 가능성이 높아지기 때문이다.

관련 일정:

- 30 검색 정확도 테스트 및 결과 순위 조정
- 32 사용자 맞춤형 추천 검색어 제안 로직
- 34 실시간/일간 인기 검색어 집계 및 노출
- 36 연관 검색어 산출 및 추천 알고리즘 적용
- 41 검색 실패어 추적 및 관리 기능

### 3.2 recent_searches

역할:

- 사용자별 최근 검색어 전용 저장소

주요 컬럼:

- id
- user_id
- query
- created_at

이 테이블로 가능한 기능:

- 사용자 최근 검색어 조회
- 최근 검색어 단건 삭제
- 최근 검색어 전체 삭제
- 사용자 맞춤 추천검색 보조 데이터 제공

별도 테이블로 둔 이유:

- 최근 검색어는 search_logs 에서 매번 group/order 계산으로 만들 수도 있지만, 실제 UI에서는 빠른 조회와 직접 삭제가 필요하다.
- 최근검색은 “이벤트 로그”가 아니라 “현재 사용자 편의 상태”에 가깝다.
- 따라서 search_logs 와 분리하는 것이 맞다.

관련 일정:

- 32 사용자 맞춤형 추천 검색어 제안 로직
- 33 사용자별 최근 검색어 저장 및 관리 API

### 3.3 indexed_documents

역할:

- OpenSearch 에 적재한 문서를 업무 DB에도 동기화 저장하는 테이블
- 관리자 조회, 감사 추적, 클라이언트 요청 대응용 메타/본문 보관소

주요 컬럼:

- id
- os_doc_id: OpenSearch 문서 ID
- origin_file: 원본 파일명
- file_ext: 확장자
- doc_category: 자동 분류 카테고리
- content_hash: 중복 방지용 해시
- title: 제목
- all_text: 추출된 본문
- indexed_at: 색인 시각

이 테이블로 가능한 기능:

- 업로드된 문서 목록 조회
- 본문 미리보기
- OpenSearch 와의 교차 검증
- 향후 관리자 수정/삭제 기능 확장
- 클라이언트 감사 대응용 데이터 보존
- OpenSearch 장애 시 최소 메타 백업 역할

별도 테이블로 둔 이유:

- OpenSearch 는 검색 엔진이지 업무 원본 관리 DB가 아니다.
- 향후 클라이언트가 “무슨 문서가 언제 어떤 해시로 등록되었는지”를 요구할 수 있다.
- 검색엔진만으로는 업무 관리 기능이 약하다.

관련 일정:

- 8 PDF, Office 문서 텍스트 추출
- 9 한글문서 텍스트 추출
- 10 제어문자 방역 및 정제
- 11 Hash 기반 중복 색인 방지
- 12 파일명/확장자 교차 검증 및 skip
- 13 대용량 Office 파일 파싱 최적화
- 14 더미 데이터 검증
- 운영 보강: OpenSearch + 업무 DB 동시 저장

### 3.4 alembic_version

역할:

- 현재 DB가 어떤 마이그레이션 버전인지 기록하는 시스템 테이블

주요 컬럼:

- version_num

업무 기능과의 관계:

- 사용자 기능과 직접 연결되지 않음
- 운영/배포 시 스키마 정합성 확인에 필수

관련 일정:

- 운영 보강: Alembic 마이그레이션 체계 추가

## 4. 라이브러리 목록 및 자세한 설명

### 4.1 fastapi

- 역할: API 서버 프레임워크
- 사용 위치: 검색, 업로드, 관리자 API 엔드포인트
- 장점:
  - 비동기 지원
  - Swagger 문서 자동 생성
  - Pydantic 기반 검증과 궁합이 좋음
- 이 프로젝트에서 하는 일:
  - /api/v1/search/\*
  - /api/v1/file/\*
  - /api/v1/index/\*
  - /api/v1/admin/\*

### 4.2 uvicorn[standard]

- 역할: FastAPI 실행용 ASGI 서버
- 사용 위치: 로컬 실행, Docker 실행
- 장점:
  - 빠른 개발 서버
  - reload 지원
  - 비동기 앱과 궁합이 좋음

### 4.3 opensearch-py

- 역할: OpenSearch 통신 라이브러리
- 사용 위치: 문서 색인, 검색, 인덱스 설정, 카운트/조회
- 장점:
  - OpenSearch 공식 생태계와 직접 호환
  - 검색/집계/인덱스 관리 모두 가능

### 4.4 python-dotenv

- 역할: .env 환경변수 로드
- 사용 위치: 설정 클래스
- 장점:
  - 로컬과 운영 설정 분리 가능
  - DATABASE_URL, OPENSEARCH_URL 관리에 필요

### 4.5 pymupdf

- 역할: PDF 파싱 보조 라이브러리
- 사용 위치: 파일 서비스 계층
- 장점:
  - PDF 텍스트 추출 속도와 호환성이 좋음

### 4.6 python-multipart

- 역할: 업로드 파일 처리
- 사용 위치: FastAPI UploadFile 엔드포인트
- 장점:
  - multipart/form-data 수신 지원

### 4.7 sqlalchemy

- 역할: 업무 DB ORM
- 사용 위치: search_logs, recent_searches, indexed_documents 모델 정의 및 CRUD
- 장점:
  - SQLite/PostgreSQL 양쪽 지원
  - 서비스 계층 코드 재사용성 좋음
  - 관리자/통계/업무 저장소 구현에 적합

### 4.8 psycopg2-binary

- 역할: PostgreSQL 파이썬 드라이버
- 사용 위치: 운영용 DATABASE_URL 연결
- 장점:
  - PostgreSQL과 직접 연결 가능
  - SQLAlchemy PostgreSQL dialect 에 필요

### 4.9 alembic

- 역할: DB 스키마 마이그레이션 관리
- 사용 위치: 테이블 버전 관리
- 장점:
  - 스키마 변경 이력 관리
  - 운영 배포 시 버전 불일치 방지

## 5. 설치 프로그램 목록 및 자세한 설명

여기서 말하는 설치 프로그램은 실제 운영/개발 실행에 필요한 런타임 또는 서비스다.

### 5.1 Python 가상환경 (venv)

- 역할: 프로젝트 전용 파이썬 실행 환경
- 이유:
  - 시스템 파이썬과 분리
  - 라이브러리 충돌 방지
- 현재 프로젝트는 .venv 기준으로 동작

### 5.2 OpenSearch

- 역할: 검색 및 벡터 저장 엔진
- 저장 대상:
  - cleversearch-docs 인덱스
- 사용 목적:
  - 키워드 검색
  - 하이브리드 검색
  - 벡터 검색
  - 카테고리 집계

### 5.3 OpenSearch Dashboards

- 역할: OpenSearch 관리/시각화 도구
- 사용 목적:
  - 색인 확인
  - 운영 점검
  - 인덱스 내부 상태 확인

### 5.4 PostgreSQL

- 역할: 운영용 업무 DB
- 사용 목적:
  - 문서 메타/본문 관리
  - 검색 로그, 최근 검색어 관리
  - 관리자 기능과 감사 기능의 기준 저장소

### 5.5 Docker / Docker Compose

- 역할: OpenSearch, Dashboards, PostgreSQL, API를 컨테이너로 실행
- 장점:
  - 재현 가능한 개발/운영 환경
  - 납품 시 설치 표준화 가능

### 5.6 Alembic CLI

- 역할: DB 마이그레이션 실행
- 대표 명령:
  - alembic upgrade head
- 용도:
  - 스키마 버전 적용
  - 운영 배포 전후 DB 상태 정합성 보장

## 6. 추가된 파일 목록 및 자세한 설명

### 백엔드 핵심

- app/core/database.py
  - 업무 DB 엔진, 세션, 모델, 초기화 담당
- app/services/db_service.py
  - 로그 저장, 최근검색 저장, 관리자 목록 조회, 연관검색 계산 담당
- app/api/v1/admin.py
  - 관리자 리스트 API 엔드포인트 집합
- app/utils/evaluation.py
  - 검색 품질 지표 계산 유틸
- scripts/evaluate_search_quality.py
  - 실제 검색 결과를 기준으로 품질 평가 실행

### 데이터/마이그레이션

- alembic.ini
  - Alembic 전역 설정
- alembic/env.py
  - 마이그레이션 실행 환경 설정
- alembic/versions/20260317_0001_init_app_tables.py
  - 초기 테이블 생성 리비전
- .env.example
  - 환경변수 예시

### 테스트/평가

- tests/test_db_service.py
  - DB 저장/집계/추천/연관 로직 테스트
- tests/test_evaluation_metrics.py
  - NDCG/MRR 지표 계산 테스트
- tests/search_judgements.example.json
  - 정답셋 예시

### 문서/UI

- static/admin.html
  - 관리자 리스트 페이지
- docs/migration.md
  - 마이그레이션 가이드
- docs/schedule_status.md
  - 일정 완료 현황
- docs/test_report_20260317.md
  - 테스트 결과 리포트
- docs/delivery_summary_20260317.md
  - 납품 요약

## 7. 관리자 탭 데이터는 각각 다른 테이블인가

정답은 다음과 같다.

### 7.1 search_logs 하나를 여러 방식으로 보여주는 탭

- 인기검색 카운트
- 검색로그
- 실패검색어

이 셋은 모두 search_logs 하나를 기반으로 한다.

차이점:

- 인기검색 카운트: search_logs 를 query 기준 group by count
- 검색로그: search_logs 원본 row 목록
- 실패검색어: search_logs 중 is_failed = True 만 group by count

즉, 한 개 테이블에서 여러 관리자 화면을 파생시키는 구조다.
이 구조가 데이터 정합성 측면에서 가장 맞다.

### 7.2 별도 테이블을 쓰는 탭

- 최근검색어: recent_searches
- 업무DB 문서 목록: indexed_documents

왜 분리했는가:

- recent_searches 는 사용자 편의 상태값이고 삭제/갱신이 잦다.
- indexed_documents 는 문서 관리 데이터라 본질이 다르다.
- search_logs 와 섞어 저장하면 컬럼 대부분이 비어버리고 조회도 비효율적이다.

결론:

- 모든 관리자 탭을 한 테이블에 몰아넣는 방식은 맞지 않다.
- 원본 로그는 search_logs 하나로 통합
- 성격이 다른 최근검색과 문서목록은 별도 테이블 분리
- 현재 구조가 더 정상적이다.

## 8. 테스트 시나리오: 일정 번호 기준으로 어떻게 확인하면 통과인가

### 8.1 색인 계열 (8~14)

시나리오:

1. PDF, DOCX, HWP/HWPX, PPTX, XLSX 파일 업로드
2. 업로드 성공 메시지 확인
3. 관리자 페이지의 문서 목록 탭에서 행이 생성되었는지 확인
4. 같은 내용 파일을 다시 업로드하여 skipped 확인

통과 기준:

- 지원 확장자별 업로드 성공
- 본문 추출 후 검색 가능
- indexed_documents 에 문서 1건 생성
- 동일 본문 중복 업로드 시 중복 스킵

### 8.2 하이브리드 검색 (24)

시나리오:

1. 업로드된 문서에 들어있는 핵심 키워드 검색
2. 키워드와 유사한 문맥 질의 검색

통과 기준:

- 정확 키워드 검색 시 해당 문서가 상단 노출
- 문맥 질의 시 관련 문서가 최소 1건 이상 노출

### 8.3 전처리/상세검색/기간검색 (25~29)

시나리오:

1. 포함 키워드 2개 입력
2. 제외 키워드 1개 입력
3. 기간 필터 적용
4. 파일 확장자 필터 적용
5. 카테고리 필터 적용

통과 기준:

- include_keywords 미포함 문서는 제외
- exclude_keywords 포함 문서는 제외
- 기간 외 문서는 제외
- 확장자/카테고리 필터가 UI 카운트와 일치

### 8.4 정확도 테스트 및 순위 조정 (30)

시나리오:

1. tests/search_judgements.example.json 형식으로 정답셋 작성
2. scripts/evaluate_search_quality.py 실행
3. avg_ndcg, avg_mrr 확인
4. 가중치 변경 후 재실행하여 비교

통과 기준:

- 스크립트가 오류 없이 실행
- 지표가 출력됨
- 랭킹 조정 전후 지표 비교 가능

### 8.5 오타 교정/추천/최근검색/인기검색/연관검색 (31~36)

시나리오:

1. 오타 검색어 입력
2. 같은 사용자로 여러 검색 수행
3. 관리자 페이지 확인
4. 최근검색 API 조회/삭제 실행
5. 연관검색 API 호출

통과 기준:

- 오타 질의도 정상 검색 또는 교정 처리
- recent_searches 에 저장됨
- search_logs 에 로그가 저장됨
- 인기검색/실패검색 집계가 반영됨
- 연관검색 결과가 의미상 유사한 질의 위주로 반환됨

### 8.6 실패검색/관리자 페이지/UI/페이징 (41, 45, 46)

시나리오:

1. 존재하지 않는 검색어 입력
2. 관리자 실패검색어 탭 확인
3. 결과가 많은 검색어로 여러 페이지 이동
4. 모바일 뷰에서 화면 확인

통과 기준:

- 실패 검색어가 search_logs 에 is_failed=True 로 저장
- 실패검색어 탭에 카운트 반영
- 페이지 이동 시 결과가 바뀜
- 모바일에서 레이아웃이 깨지지 않음

## 9. 현재 구현의 수정사항/보완 필요사항

### 9.1 가장 중요한 보완점

- create_all 과 Alembic 이 혼용되고 있다.
- 개발 단계에서는 괜찮지만 운영에서는 Alembic 기준으로 단일화하는 것이 맞다.

### 9.2 검색 정밀도 보강 필요

- 짧은 이름 검색은 오탐 방지 패치를 넣었지만, 사람명/부서명/코드명에 대한 별도 질의 규칙이 더 필요하다.
- 예:
  - 2~4글자 무공백 질의는 문자열 포함 강제
  - 파일명 우선 검색 옵션 제공
  - exact mode 토글 추가

### 9.3 관리자 보안 필요

- 현재 /admin 은 공개 상태다.
- 실제 납품 시 인증/권한 관리가 필요하다.
- 최소 요구:
  - 관리자 로그인
  - IP 제한 또는 VPN
  - 감사 로그

### 9.4 문서 저장 전략 결정 필요

- indexed_documents 에 all_text 전체를 저장 중이다.
- 문서 수가 커지면 DB 크기 증가가 빠르다.
- 대안:
  - DB에는 메타 + 본문 일부만 저장
  - 전체 원문은 파일 저장소/NAS에 저장
  - 본문 전문은 OpenSearch 와 오브젝트 스토리지 조합으로 분리

### 9.5 로그 보존 정책 필요

- search_logs 는 계속 쌓인다.
- 운영 단계에서는 보존 기간/압축/아카이브 정책이 필요하다.

### 9.6 테스트 보강 필요

- 현재는 단위 테스트 중심이다.
- 실제 납품 전에는 다음이 추가되어야 한다.
  - API 통합 테스트
  - 업로드-색인-검색 E2E 테스트
  - 성능 테스트
  - 장애 복구 테스트

## 10. 폐쇄망 + 향후 AI 연동 관점에서 우려되는 부분

### 10.1 모델 배포 방식

- 현재 임베딩 모델은 Hugging Face 기반 로딩 흐름이 보인다.
- 폐쇄망에서는 외부 다운로드가 불가능하므로 모델 파일을 사내 저장소에 미리 반입해야 한다.
- 대응 필요:
  - 모델 아티팩트 사전 반입
  - 로컬 모델 경로 고정
  - 버전 관리 문서화

### 10.2 GPU/CPU 자원 계획

- 검색 + 임베딩 + 향후 생성형 AI까지 붙으면 자원 사용량이 급증한다.
- 특히 AI 응답형 시스템으로 확장 시 다음이 병목이 된다.
  - 임베딩 생성 속도
  - 벡터 검색 응답 시간
  - LLM 추론 시간

### 10.3 폐쇄망 운영 리스크

- 모델 업데이트 지연
- 보안 패치 적용 지연
- 패키지 공급망 검증 필요
- 외부 API 의존 기능 제거 필요

### 10.4 저장소 역할 분리 필요

- OpenSearch: 검색/벡터 엔진
- PostgreSQL: 업무 데이터/감사/관리
- 오브젝트 스토리지/NAS: 원본 파일 보관
- LLM 서버: 추론 전용

이 역할 분리가 무너지면 장애 전파가 커진다.

### 10.5 서버 사양 권장안

개발/검증 최소:

- API 서버: 4 vCPU / 8GB RAM
- OpenSearch: 8 vCPU / 16GB RAM
- PostgreSQL: 2 vCPU / 8GB RAM
- 저장소: SSD 필수

소규모 운영:

- API 서버: 8 vCPU / 16GB RAM
- OpenSearch: 8~16 vCPU / 32GB RAM
- PostgreSQL: 4 vCPU / 16GB RAM
- 문서량 증가 대비 SSD/NVMe 권장

AI 연동 포함 운영:

- API/검색 서버 분리
- OpenSearch 전용 노드 분리
- PostgreSQL 전용 노드 분리
- LLM 추론 서버 별도 구축
- GPU 필요 여부는 모델 크기에 따라 결정

예:

- 임베딩 전용은 CPU 고성능 서버로도 가능
- 생성형 AI 7B 이상 실시간 응답은 GPU 서버 검토 필요

### 10.6 AI 연동 시 꼭 점검할 부분

- 문서 보안 등급별 접근 통제
- 답변 근거 문서/페이지 표시
- 모델 환각 방지 정책
- 프롬프트/응답 로그 저장
- 개인정보/기밀 마스킹
- 재색인 주기와 임베딩 재생성 정책

## 11. 어떤 일정 때문에 어떤 테이블이 생성되었는가

### 11.1 indexed_documents

생성 이유:

- 업로드 문서를 OpenSearch 외에도 업무 DB에 남겨야 하기 때문

연결 일정:

- 8, 9, 10, 11, 12, 13, 14

사용 방식:

- 관리자 문서 목록
- 감사 추적
- 향후 문서 관리 기능 확장

### 11.2 search_logs

생성 이유:

- 검색 활동을 원본 이벤트로 저장하고, 이를 기준으로 인기/실패/추천/연관 검색을 계산하기 위해

연결 일정:

- 30, 32, 34, 36, 41

사용 방식:

- 인기검색 카운트
- 검색로그 목록
- 실패검색어 카운트
- 추천검색어 계산
- 연관검색어 계산

### 11.3 recent_searches

생성 이유:

- 사용자 편의 기능인 최근 검색어 조회/삭제를 빠르게 제공하기 위해

연결 일정:

- 32, 33

사용 방식:

- 최근검색어 목록
- 단건 삭제/전체 삭제
- 사용자 맞춤 추천 보조 데이터

### 11.4 alembic_version

생성 이유:

- DB 스키마 버전을 기록하기 위해

연결 일정:

- 운영 보강 항목 (PostgreSQL/Alembic 도입)

사용 방식:

- 배포 시 스키마 버전 관리
- 운영 DB 정합성 확인

## 12. 결과적으로 몇 개의 테이블이 만들어졌는가

현재 업무 DB 기준 실제 테이블은 4개다.

1. alembic_version
2. indexed_documents
3. recent_searches
4. search_logs

이 중 업무 기능 테이블은 3개다.

1. indexed_documents
2. recent_searches
3. search_logs

정리하면 다음과 같다.

- 문서 관리/감사용: indexed_documents
- 검색 이벤트 원본/집계용: search_logs
- 사용자 편의 상태값: recent_searches
- 스키마 버전 관리용: alembic_version

## 13. 테이블 생성 스크립트 확인 위치

실무에서 바로 볼 수 있는 테이블 스크립트는 아래 두 군데다.

1. Alembic 리비전(실행 스크립트 원본)

- alembic/versions/20260317_0001_init_app_tables.py
- alembic/versions/20260318_0002_add_table_comments.py

2. 참조용 SQL 문서(요약 DDL)

- docs/sql/app_db_tables.sql
