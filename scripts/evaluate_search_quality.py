import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
# 단독 스크립트 실행 시에도 app 패키지를 찾을 수 있도록 루트를 추가합니다.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.schemas.search_schema import SearchRequest
from app.services.search_service import SearchService
from app.utils.evaluation import evaluate_queries


async def run_eval(input_path: Path, k: int = 10, size: int = 20):
    # 질의/정답셋 JSON을 읽어 실제 검색 API 로직으로 품질을 측정합니다.
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    queries = payload.get("queries", [])
    eval_rows = []

    for row in queries:
        query = row.get("query", "").strip()
        relevant = row.get("relevant_titles", [])
        user_id = row.get("user_id", "eval-bot")
        if not query:
            continue

        req = SearchRequest(
            query=query,
            include_keywords=[],
            exclude_keywords=[],
            start_date=None,
            end_date=None,
            file_ext=None,
            doc_category=None,
            min_score=0.0,
            size=size,
            page=1,
            user_id=user_id,
        )
        response = await SearchService.execute_search(req)
        # 실제 검색 결과에서 제목 목록만 추출하여 정답셋과 비교합니다.
        predicted = [
            (item.get("content", {}) or {}).get("Title")
            for item in response.get("items", [])
            if (item.get("content", {}) or {}).get("Title")
        ]

        eval_rows.append({"query": query, "predicted": predicted, "relevant": relevant})

    summary = evaluate_queries(eval_rows, k=k)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    # 운영 전 랭킹 변경 전후를 비교할 때 사용하는 CLI 진입점입니다.
    parser = argparse.ArgumentParser(description="Search ranking quality evaluator")
    parser.add_argument("--input", required=True, help="Path to query/relevance json")
    parser.add_argument("--k", type=int, default=10, help="Top-k cutoff")
    parser.add_argument("--size", type=int, default=20, help="Search result size")
    args = parser.parse_args()

    asyncio.run(run_eval(Path(args.input), k=args.k, size=args.size))


if __name__ == "__main__":
    main()
