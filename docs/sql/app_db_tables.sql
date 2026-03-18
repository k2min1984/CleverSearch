-- CleverSearch app DB reference DDL
-- Base tables (SQLite/PostgreSQL common logical schema)

CREATE TABLE search_logs (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    query VARCHAR(300) NOT NULL,
    total_hits INTEGER NOT NULL,
    is_failed BOOLEAN NOT NULL,
    search_type VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE INDEX ix_search_logs_user_id ON search_logs(user_id);
CREATE INDEX ix_search_logs_query ON search_logs(query);
CREATE INDEX ix_search_logs_is_failed ON search_logs(is_failed);
CREATE INDEX ix_search_logs_created_at ON search_logs(created_at);

CREATE TABLE recent_searches (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    query VARCHAR(300) NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE INDEX ix_recent_searches_user_id ON recent_searches(user_id);
CREATE INDEX ix_recent_searches_created_at ON recent_searches(created_at);

CREATE TABLE indexed_documents (
    id INTEGER PRIMARY KEY,
    os_doc_id VARCHAR(120),
    origin_file VARCHAR(260) NOT NULL,
    file_ext VARCHAR(20) NOT NULL,
    doc_category VARCHAR(50) NOT NULL,
    content_hash VARCHAR(600) NOT NULL,
    title VARCHAR(300) NOT NULL,
    all_text TEXT NOT NULL,
    indexed_at DATETIME NOT NULL
);

CREATE UNIQUE INDEX ix_indexed_documents_os_doc_id ON indexed_documents(os_doc_id);
CREATE INDEX ix_indexed_documents_origin_file ON indexed_documents(origin_file);
CREATE INDEX ix_indexed_documents_file_ext ON indexed_documents(file_ext);
CREATE INDEX ix_indexed_documents_doc_category ON indexed_documents(doc_category);
CREATE UNIQUE INDEX ix_indexed_documents_content_hash ON indexed_documents(content_hash);
CREATE INDEX ix_indexed_documents_indexed_at ON indexed_documents(indexed_at);

-- PostgreSQL-only comments (managed by Alembic revision 20260318_0002)
-- COMMENT ON TABLE search_logs IS '검색 실행 원본 이벤트 로그 테이블';
-- COMMENT ON TABLE recent_searches IS '사용자 최근 검색어 상태 테이블';
-- COMMENT ON TABLE indexed_documents IS '업무 DB 문서 메타/본문 동기화 테이블';
