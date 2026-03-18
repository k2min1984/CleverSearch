# 일정 및 산출 요약 (2026-03-17)

## 일정 현황

- 상세 일정 완료 현황: docs/schedule_status.md
- 테스트 결과: docs/test_report_20260317.md

## 1) 라이브러리 목록 및 설명 (요약)

- fastapi: API 서버 프레임워크
- uvicorn[standard]: ASGI 서버 실행
- opensearch-py: OpenSearch 연동
- python-dotenv: 환경변수 로드
- pymupdf: PDF 텍스트 처리
- python-multipart: 업로드 파일 처리
- sqlalchemy: 업무 DB ORM
- psycopg2-binary: PostgreSQL 드라이버
- alembic: DB 마이그레이션

## 2) 설치 프로그램/실행 도구 목록 및 설명 (요약)

- Python venv: 프로젝트 실행 환경
- PostgreSQL(도커 서비스): 업무 데이터 저장소
- OpenSearch(도커 서비스): 검색/벡터 인덱스 저장소
- OpenSearch Dashboards: 검색 데이터 시각화 도구
- Alembic CLI: 스키마 버전 관리 도구

## 3) 추가된 파일 목록 및 설명 (요약)

- app/core/database.py: 업무 DB 모델/세션/초기화
- app/services/db_service.py: DB 저장/집계/리스트 조회 서비스
- app/api/v1/admin.py: 관리자 리스트 API
- static/admin.html: 관리자 리스트 화면
- app/utils/evaluation.py: NDCG/MRR 계산 유틸
- scripts/evaluate_search_quality.py: 검색 품질 자동평가 스크립트
- tests/test_evaluation_metrics.py: 평가 메트릭 테스트
- tests/test_db_service.py: DB 서비스 테스트
- tests/search_judgements.example.json: 평가용 예시 정답셋
- alembic.ini, alembic/env.py, alembic/versions/20260317_0001_init_app_tables.py: 마이그레이션 체계
- docs/migration.md: 마이그레이션 실행 가이드
- .env.example: 환경변수 예시
