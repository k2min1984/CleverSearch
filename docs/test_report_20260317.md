# 테스트 리포트 (2026-03-17)

## 1. 단위 테스트

명령어:

```bash
python -m unittest tests/test_db_service.py tests/test_evaluation_metrics.py -v
```

결과:

- Ran 5 tests
- OK

대상:

- 검색 로그/인기검색/실패검색 집계
- 최근 검색어 저장/관리
- 추천/연관 검색어 로직
- NDCG/MRR 평가 로직

## 2. 마이그레이션 테스트

명령어:

```bash
python -m alembic upgrade head
```

결과:

- 초기 스키마 리비전 적용 성공

## 3. 정확도 평가 스크립트 스모크 테스트

명령어:

```bash
python scripts/evaluate_search_quality.py --input tests/search_judgements.example.json --k 10 --size 20
```

결과:

- 스크립트 정상 실행
- 출력 예시: avg_ndcg=0.0, avg_mrr=0.0

참고:

- 예시 정답셋과 실제 색인 문서가 다르면 점수는 0에 수렴할 수 있음
- 실제 운영 평가를 위해서는 현행 색인 문서 제목 기준 정답셋을 구축해야 함

## 4. 캡처 파일 대체

현재 실행 환경에서는 자동 스크린샷 생성 기능이 없어, 테스트 결과를 문서화 방식으로 대체함.
