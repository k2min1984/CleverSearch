from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compare_scores(base: dict, candidate: dict) -> dict:
    # evaluate_search_quality.py 출력 형식 기준 비교
    base_ndcg = float(base.get("avg_ndcg", 0))
    base_mrr = float(base.get("avg_mrr", 0))
    cand_ndcg = float(candidate.get("avg_ndcg", 0))
    cand_mrr = float(candidate.get("avg_mrr", 0))

    return {
        "base": {"avg_ndcg": base_ndcg, "avg_mrr": base_mrr},
        "candidate": {"avg_ndcg": cand_ndcg, "avg_mrr": cand_mrr},
        "delta": {
            "avg_ndcg": round(cand_ndcg - base_ndcg, 6),
            "avg_mrr": round(cand_mrr - base_mrr, 6),
        },
        "improved": (cand_ndcg >= base_ndcg) and (cand_mrr >= base_mrr),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare two ranking evaluation summaries")
    parser.add_argument("--base", required=True, help="Baseline summary json path")
    parser.add_argument("--candidate", required=True, help="Candidate summary json path")
    args = parser.parse_args()

    base = load_json(Path(args.base))
    candidate = load_json(Path(args.candidate))
    result = compare_scores(base, candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
