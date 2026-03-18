from datetime import datetime, timedelta, timezone
from typing import List
import re

from sqlalchemy import desc, func

from app.core.database import IndexedDocument, RecentSearch, SearchLog, get_db_session


class DBService:
    @staticmethod
    def _tokenize(text: str) -> set[str]:
        # 연관 검색어 계산 시 한 글자 노이즈를 줄이기 위해 2글자 이상 토큰만 사용합니다.
        return {tok for tok in re.split(r"\s+", (text or "").strip().lower()) if len(tok) >= 2}

    @staticmethod
    def save_search_log(user_id: str, query: str, total_hits: int, search_type: str = "manual_search") -> None:
        # 인기검색/실패검색/추천검색의 기준이 되는 원본 로그를 적재합니다.
        with get_db_session() as db:
            db.add(
                SearchLog(
                    user_id=user_id or "anonymous",
                    query=query,
                    total_hits=total_hits,
                    is_failed=total_hits == 0,
                    search_type=search_type,
                )
            )

    @staticmethod
    def save_recent_search(user_id: str, query: str, keep_limit: int = 20) -> None:
        # 동일 검색어는 최신 시각만 갱신하고, 사용자별 보관 개수를 제한합니다.
        user = user_id or "anonymous"
        with get_db_session() as db:
            existing = (
                db.query(RecentSearch)
                .filter(RecentSearch.user_id == user, RecentSearch.query == query)
                .first()
            )
            if existing:
                existing.created_at = datetime.now(timezone.utc)
            else:
                db.add(RecentSearch(user_id=user, query=query))

            rows = (
                db.query(RecentSearch)
                .filter(RecentSearch.user_id == user)
                .order_by(desc(RecentSearch.created_at))
                .all()
            )
            for stale in rows[keep_limit:]:
                db.delete(stale)

    @staticmethod
    def get_recent_searches(user_id: str, limit: int = 10) -> List[str]:
        with get_db_session() as db:
            rows = (
                db.query(RecentSearch)
                .filter(RecentSearch.user_id == (user_id or "anonymous"))
                .order_by(desc(RecentSearch.created_at))
                .limit(limit)
                .all()
            )
            return [r.query for r in rows]

    @staticmethod
    def remove_recent_search(user_id: str, query: str) -> int:
        with get_db_session() as db:
            deleted = (
                db.query(RecentSearch)
                .filter(RecentSearch.user_id == (user_id or "anonymous"), RecentSearch.query == query)
                .delete(synchronize_session=False)
            )
            return deleted

    @staticmethod
    def clear_recent_searches(user_id: str) -> int:
        with get_db_session() as db:
            deleted = (
                db.query(RecentSearch)
                .filter(RecentSearch.user_id == (user_id or "anonymous"))
                .delete(synchronize_session=False)
            )
            return deleted

    @staticmethod
    def get_popular_keywords(days: int = 7, limit: int = 10) -> List[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with get_db_session() as db:
            rows = (
                db.query(SearchLog.query, func.count(SearchLog.id).label("cnt"))
                .filter(SearchLog.created_at >= cutoff)
                .group_by(SearchLog.query)
                .order_by(desc("cnt"), SearchLog.query.asc())
                .limit(limit)
                .all()
            )
            return [r[0] for r in rows]

    @staticmethod
    def get_popular_keyword_stats(days: int = 7, limit: int = 20):
        # 관리자 화면에서는 집계 결과와 카운트를 함께 보여주기 위해 별도 메서드를 둡니다.
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with get_db_session() as db:
            rows = (
                db.query(SearchLog.query, func.count(SearchLog.id).label("count"))
                .filter(SearchLog.created_at >= cutoff)
                .group_by(SearchLog.query)
                .order_by(desc("count"), SearchLog.query.asc())
                .limit(limit)
                .all()
            )
            return [{"keyword": query, "count": count} for query, count in rows]

    @staticmethod
    def get_failed_keywords(days: int = 7, limit: int = 10):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with get_db_session() as db:
            rows = (
                db.query(SearchLog.query, func.count(SearchLog.id).label("cnt"))
                .filter(SearchLog.created_at >= cutoff, SearchLog.is_failed.is_(True))
                .group_by(SearchLog.query)
                .order_by(desc("cnt"), SearchLog.query.asc())
                .limit(limit)
                .all()
            )
            return [{"keyword": q, "count": c} for q, c in rows]

    @staticmethod
    def get_related_keywords(query: str, days: int = 30, limit: int = 10) -> List[str]:
        needle = (query or "").strip()
        if not needle:
            return []
        needle_norm = needle.lower()
        needle_tokens = DBService._tokenize(needle_norm)
        if not needle_tokens:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with get_db_session() as db:
            rows = (
                db.query(SearchLog.query, func.count(SearchLog.id).label("cnt"))
                .filter(SearchLog.created_at >= cutoff)
                .group_by(SearchLog.query)
                .order_by(desc("cnt"))
                .all()
            )

        scored = []
        for q, cnt in rows:
            q_norm = q.lower().strip()
            if q_norm == needle_norm:
                continue

            q_tokens = DBService._tokenize(q_norm)
            if not q_tokens:
                continue

            overlap = len(needle_tokens.intersection(q_tokens))
            if overlap == 0:
                continue

            union_size = max(1, len(needle_tokens.union(q_tokens)))
            jaccard = overlap / union_size

            # 텍스트 유사도와 빈도를 함께 반영한 연관도 점수입니다.
            score = jaccard * 100 + min(cnt, 50)
            scored.append((score, q))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [q for _, q in scored[:limit]]

    @staticmethod
    def get_recommended_keywords(user_id: str, limit: int = 10) -> List[str]:
        recent = DBService.get_recent_searches(user_id, limit=limit)
        popular = DBService.get_popular_keywords(days=14, limit=limit)
        merged = []
        for keyword in recent + popular:
            if keyword not in merged:
                merged.append(keyword)
            if len(merged) >= limit:
                break
        return merged

    @staticmethod
    def save_indexed_document(
        os_doc_id: str,
        origin_file: str,
        file_ext: str,
        doc_category: str,
        content_hash: str,
        title: str,
        all_text: str,
    ) -> None:
        # OpenSearch와 업무 DB 간 문서 메타를 맞추기 위한 업서트 로직입니다.
        with get_db_session() as db:
            exists = db.query(IndexedDocument).filter(IndexedDocument.content_hash == content_hash).first()
            if exists:
                exists.os_doc_id = os_doc_id or exists.os_doc_id
                exists.origin_file = origin_file
                exists.file_ext = file_ext
                exists.doc_category = doc_category
                exists.title = title
                exists.all_text = all_text
                exists.indexed_at = datetime.now(timezone.utc)
                return

            db.add(
                IndexedDocument(
                    os_doc_id=os_doc_id,
                    origin_file=origin_file,
                    file_ext=file_ext,
                    doc_category=doc_category,
                    content_hash=content_hash,
                    title=title,
                    all_text=all_text,
                )
            )

    @staticmethod
    def list_indexed_documents(skip: int = 0, limit: int = 20):
        # 관리자 문서 목록 페이지에서 사용하는 페이징 조회입니다.
        with get_db_session() as db:
            total = db.query(func.count(IndexedDocument.id)).scalar() or 0
            rows = (
                db.query(IndexedDocument)
                .order_by(desc(IndexedDocument.indexed_at))
                .offset(skip)
                .limit(limit)
                .all()
            )

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row.id,
                        "os_doc_id": row.os_doc_id,
                        "title": row.title,
                        "origin_file": row.origin_file,
                        "file_ext": row.file_ext,
                        "doc_category": row.doc_category,
                        "content_hash": row.content_hash,
                        "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
                        "text_preview": (row.all_text or "")[:120],
                    }
                )
            return {"total": total, "items": items}

    @staticmethod
    def list_search_logs(skip: int = 0, limit: int = 50):
        # 검색 로그 원본 목록을 그대로 보여주는 관리자 조회입니다.
        with get_db_session() as db:
            total = db.query(func.count(SearchLog.id)).scalar() or 0
            rows = (
                db.query(SearchLog)
                .order_by(desc(SearchLog.created_at))
                .offset(skip)
                .limit(limit)
                .all()
            )

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row.id,
                        "user_id": row.user_id,
                        "query": row.query,
                        "total_hits": row.total_hits,
                        "is_failed": row.is_failed,
                        "search_type": row.search_type,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                )
            return {"total": total, "items": items}

    @staticmethod
    def list_recent_searches(skip: int = 0, limit: int = 50, user_id: str | None = None):
        # 최근 검색어는 사용자 단위 확인이 필요해 선택 필터를 지원합니다.
        with get_db_session() as db:
            query = db.query(RecentSearch)
            if user_id:
                query = query.filter(RecentSearch.user_id == user_id)

            total = query.with_entities(func.count(RecentSearch.id)).scalar() or 0
            rows = (
                query.order_by(desc(RecentSearch.created_at))
                .offset(skip)
                .limit(limit)
                .all()
            )

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row.id,
                        "user_id": row.user_id,
                        "query": row.query,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                )
            return {"total": total, "items": items}
