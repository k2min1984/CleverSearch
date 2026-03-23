"""
########################################################
# Description
# 사전 서비스 (DictionaryService)
# 동의어/불용어/사용자사전 CRUD 로직
# - 사전 목록 조회 (dict_type별 필터)
# - 단건 등록/수정 (upsert)
# - 엑셀 일괄 업로드
# - 사전 항목 삭제
#
# Modified History
# 강광민 / 2026-03-18 / 최초생성
# 강광민 / 2026-03-23 / 헤더 주석 추가
########################################################
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.database import DictionaryEntry, get_db_session


class DictionaryService:
    @staticmethod
    def list_entries(dict_type: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
        with get_db_session() as db:
            query = db.query(DictionaryEntry)
            if dict_type:
                query = query.filter(DictionaryEntry.dict_type == dict_type)
            if active_only:
                query = query.filter(DictionaryEntry.is_active.is_(True))
            rows = query.order_by(DictionaryEntry.dict_type.asc(), DictionaryEntry.term.asc()).all()
            return [
                {
                    "id": row.id,
                    "dict_type": row.dict_type,
                    "term": row.term,
                    "replacement": row.replacement,
                    "is_active": row.is_active,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in rows
            ]

    @staticmethod
    def upsert_entry(dict_type: str, term: str, replacement: str | None = None, is_active: bool = True) -> dict[str, Any]:
        t = (term or "").strip()
        d = (dict_type or "").strip().lower()
        _aliases = {"user_dict": "user", "userdict": "user"}
        d = _aliases.get(d, d)
        if not t or d not in {"synonym", "stopword", "user"}:
            raise ValueError("dict_type은 synonym/stopword/user/user_dict 중 하나이고 term은 필수")

        with get_db_session() as db:
            row = (
                db.query(DictionaryEntry)
                .filter(DictionaryEntry.dict_type == d, DictionaryEntry.term == t)
                .first()
            )
            now = datetime.now(timezone.utc)
            if row:
                row.replacement = replacement
                row.is_active = is_active
                row.updated_at = now
            else:
                row = DictionaryEntry(
                    dict_type=d,
                    term=t,
                    replacement=(replacement or None),
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.flush()
            return {
                "id": row.id,
                "dict_type": row.dict_type,
                "term": row.term,
                "replacement": row.replacement,
                "is_active": row.is_active,
            }

    @staticmethod
    def ingest_excel(file_path: str) -> dict[str, int]:
        # 시트명 synonym/stopword/user 기준으로 일괄 업서트 수행
        xls = pd.read_excel(file_path, sheet_name=None)
        counts = {"synonym": 0, "stopword": 0, "user": 0}

        for sheet_name, frame in xls.items():
            d_type = str(sheet_name).strip().lower()
            if d_type not in counts:
                continue

            normalized = frame.fillna("")
            for _, row in normalized.iterrows():
                term = str(row.get("term", "")).strip()
                replacement = str(row.get("replacement", "")).strip() or None
                if not term:
                    continue
                DictionaryService.upsert_entry(d_type, term, replacement=replacement, is_active=True)
                counts[d_type] += 1

        return counts

    @staticmethod
    def build_runtime_bundle() -> dict[str, Any]:
        # 검색 시 즉시 사용 가능한 구조로 사전을 변환
        entries = DictionaryService.list_entries(active_only=True)

        synonyms: dict[str, list[str]] = {}
        stopwords: set[str] = set()
        user_corrections: dict[str, str] = {}

        for entry in entries:
            d_type = entry.get("dict_type")
            term = (entry.get("term") or "").strip()
            replacement = (entry.get("replacement") or "").strip()
            if not term:
                continue

            if d_type == "synonym":
                if not replacement:
                    continue
                synonyms.setdefault(term, []).append(replacement)
            elif d_type == "stopword":
                stopwords.add(term)
            elif d_type == "user":
                if replacement:
                    user_corrections[term] = replacement

        return {
            "synonyms": synonyms,
            "stopwords": sorted(stopwords),
            "user_corrections": user_corrections,
        }

    @staticmethod
    def normalize_query(query: str) -> tuple[str, list[str]]:
        q = (query or "").strip()
        if not q:
            return q, []

        bundle = DictionaryService.build_runtime_bundle()
        corrected = q

        for src, dst in bundle["user_corrections"].items():
            corrected = corrected.replace(src, dst)

        tokens = corrected.split()
        filtered_tokens = [tok for tok in tokens if tok not in set(bundle["stopwords"])]
        normalized = " ".join(filtered_tokens) if filtered_tokens else corrected

        expanded: list[str] = []
        for key, values in bundle["synonyms"].items():
            if key in normalized:
                expanded.extend(values)

        return normalized, list(dict.fromkeys(expanded))
