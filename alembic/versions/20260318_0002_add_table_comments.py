"""add table and column comments for postgres

Revision ID: 20260318_0002
Revises: 20260317_0001
Create Date: 2026-03-18
"""

from alembic import op


revision = "20260318_0002"
down_revision = "20260317_0001"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():
        return

    # Table comments
    op.execute("COMMENT ON TABLE search_logs IS '검색 실행 원본 이벤트 로그 테이블'")
    op.execute("COMMENT ON TABLE recent_searches IS '사용자 최근 검색어 상태 테이블'")
    op.execute("COMMENT ON TABLE indexed_documents IS '업무 DB 문서 메타/본문 동기화 테이블'")

    # search_logs column comments
    op.execute("COMMENT ON COLUMN search_logs.id IS '로그 PK'")
    op.execute("COMMENT ON COLUMN search_logs.user_id IS '사용자 식별자'")
    op.execute("COMMENT ON COLUMN search_logs.query IS '검색어 원문'")
    op.execute("COMMENT ON COLUMN search_logs.total_hits IS '검색 결과 문서 수'")
    op.execute("COMMENT ON COLUMN search_logs.is_failed IS '결과 0건 여부'")
    op.execute("COMMENT ON COLUMN search_logs.search_type IS '로그 유형(manual_search 등)'")
    op.execute("COMMENT ON COLUMN search_logs.created_at IS '검색 실행 시각(UTC)'")

    # recent_searches column comments
    op.execute("COMMENT ON COLUMN recent_searches.id IS '최근 검색 PK'")
    op.execute("COMMENT ON COLUMN recent_searches.user_id IS '사용자 식별자'")
    op.execute("COMMENT ON COLUMN recent_searches.query IS '최근 검색어'")
    op.execute("COMMENT ON COLUMN recent_searches.created_at IS '최근 검색 시각(UTC)'")

    # indexed_documents column comments
    op.execute("COMMENT ON COLUMN indexed_documents.id IS '문서 PK'")
    op.execute("COMMENT ON COLUMN indexed_documents.os_doc_id IS 'OpenSearch 문서 ID'")
    op.execute("COMMENT ON COLUMN indexed_documents.origin_file IS '원본 파일명'")
    op.execute("COMMENT ON COLUMN indexed_documents.file_ext IS '파일 확장자'")
    op.execute("COMMENT ON COLUMN indexed_documents.doc_category IS '자동 분류 카테고리'")
    op.execute("COMMENT ON COLUMN indexed_documents.content_hash IS '중복 방지용 콘텐츠 해시'")
    op.execute("COMMENT ON COLUMN indexed_documents.title IS '문서 제목'")
    op.execute("COMMENT ON COLUMN indexed_documents.all_text IS '추출된 본문 텍스트'")
    op.execute("COMMENT ON COLUMN indexed_documents.indexed_at IS '업무 DB 기록 시각(UTC)'")


def downgrade() -> None:
    if not _is_postgresql():
        return

    op.execute("COMMENT ON TABLE search_logs IS NULL")
    op.execute("COMMENT ON TABLE recent_searches IS NULL")
    op.execute("COMMENT ON TABLE indexed_documents IS NULL")

    op.execute("COMMENT ON COLUMN search_logs.id IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.user_id IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.query IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.total_hits IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.is_failed IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.search_type IS NULL")
    op.execute("COMMENT ON COLUMN search_logs.created_at IS NULL")

    op.execute("COMMENT ON COLUMN recent_searches.id IS NULL")
    op.execute("COMMENT ON COLUMN recent_searches.user_id IS NULL")
    op.execute("COMMENT ON COLUMN recent_searches.query IS NULL")
    op.execute("COMMENT ON COLUMN recent_searches.created_at IS NULL")

    op.execute("COMMENT ON COLUMN indexed_documents.id IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.os_doc_id IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.origin_file IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.file_ext IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.doc_category IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.content_hash IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.title IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.all_text IS NULL")
    op.execute("COMMENT ON COLUMN indexed_documents.indexed_at IS NULL")
