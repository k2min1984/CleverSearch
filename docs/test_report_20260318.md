# 테스트 리포트 (2026-03-18)

## 1. 실행 범위

- 기준 데이터 폴더: C:/Users/CLEVER_KKMIN/Desktop/테스트용 문서 파일
- 단위 테스트: tests.test_db_service, tests.test_evaluation_metrics
- E2E 시나리오: 업로드/중복, 검색 매칭, 상세검색, 이름 정밀도, 자동완성/인기검색/오타, 최근/추천/연관, 실패검색 추적, UI/페이징, 관리자 탭
- 검색 품질 평가: scripts/evaluate_search_quality.py + tests/search_judgements.generated.json

## 2. 실행 결과 요약

- 단위 테스트: 5건 통과
- E2E 시나리오: 9개 중 9개 통과
- 검색 품질 자동평가: avg_ndcg=0.3333, avg_mrr=0.3333

통과:

- A 업로드/중복/색인
- B 검색어 매칭
- C 상세검색/필터/기간
- D 이름 검색 정밀도
- E 자동완성/인기검색/오타
- F 최근검색/추천/연관검색
- G 실패검색 추적
- H UI/페이징 API 확인
- I 관리자 탭 조회

## 3. 이슈 해결 내역

### 3.1 시나리오 A 개선

- 이미지형 PDF OCR 폴백 경로 추가: pdfplumber 추출이 비어 있으면 PyMuPDF 렌더링 후 Tesseract OCR 수행
- 결과: 이미지PDF.pdf 업로드 성공
- 비고: 제조의*심장을*지킬*AI*주치의-5.jpg는 동일 내용으로 skipped 처리되며, 이는 중복 차단 정상 동작

### 3.2 시나리오 C 개선

- include/exclude 상세 필터를 본문(all_text)만 보던 방식에서 제목(Title)+본문 동시 검색으로 변경
- 결과: 울산지방청처럼 파일명에만 있는 키워드도 필터 매칭

### 3.3 시나리오 G 개선

- 실패 검색 판정을 벡터 결과와 분리
- Title/all_text 정확 구문 기준 카운트가 0이면 is_failed=True로 기록
- 결과: ZXCVBNM존재하지않는키워드가 failed-keywords에 정상 집계

## 4. 관찰 사항

- 검색 결과 제목은 업로드 시 sanitize_text 적용으로 특수문자와 일부 구분자가 제거된 형태로 저장됨
- 이름 검색(강광민/홍길동/김영희)은 모두 total=0으로 오탐 방지 로직이 정상 동작함
- 인기검색과 관리자 인기검색 통계는 일관되게 증가함
- 최근검색 삭제/전체삭제 API는 정상 동작함
- UI HTML 응답과 서버측 페이지네이션 응답은 정상 확인됨
- 모바일 레이아웃은 자동화하지 못했고 수동 확인 필요

## 5. 실행 산출물

- E2E 결과 원본: e2e_schedule_test_result.json
- 평가 정답셋: tests/search_judgements.generated.json
- E2E 실행 스크립트: scripts/run_full_schedule_tests.py
