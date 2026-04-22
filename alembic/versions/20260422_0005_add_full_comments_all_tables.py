"""add full table/column comments for all app tables

Revision ID: 20260422_0005
Revises: 20260319_0004
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260422_0005"
down_revision = "20260319_0004"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _table_comments() -> dict[str, str]:
    return {
        "alembic_version": "Alembic 스키마 버전 관리 테이블",
        "search_logs": "검색 실행 원본 이벤트 로그 테이블",
        "recent_searches": "사용자 최근 검색어 상태 테이블",
        "indexed_documents": "업무 DB 문서 메타/본문 동기화 테이블",
        "smb_sources": "SMB 소스 등록/상태 테이블",
        "db_sources": "다중 DB 수집 소스 등록/상태 테이블",
        "dictionary_entries": "동의어/불용어/사용자 사전 테이블",
        "certificate_status": "인증서 상태 모니터링 테이블",
        "auth_roles": "시스템 권한 역할 테이블",
        "auth_users": "인증 사용자 계정 테이블",
        "revoked_access_tokens": "Access token 블랙리스트 테이블",
        "revoked_refresh_tokens": "Refresh token 블랙리스트 테이블",
    }


def _column_comments() -> dict[str, dict[str, str]]:
    return {
        "alembic_version": {
            "version_num": "현재 적용된 Alembic 리비전 식별자",
        },
        "search_logs": {
            "id": "로그 PK",
            "user_id": "사용자 식별자",
            "query": "검색어 원문",
            "total_hits": "검색 결과 문서 수",
            "is_failed": "결과 0건 여부",
            "search_type": "로그 유형(manual_search 등)",
            "created_at": "검색 실행 시각(UTC)",
        },
        "recent_searches": {
            "id": "최근 검색 PK",
            "user_id": "사용자 식별자",
            "query": "최근 검색어",
            "created_at": "최근 검색 시각(UTC)",
        },
        "indexed_documents": {
            "id": "문서 PK",
            "os_doc_id": "OpenSearch 문서 ID",
            "origin_file": "원본 파일명",
            "file_ext": "파일 확장자",
            "doc_category": "자동 분류 카테고리",
            "content_hash": "중복 방지용 콘텐츠 해시",
            "title": "문서 제목",
            "all_text": "추출된 본문 텍스트",
            "indexed_at": "업무 DB 기록 시각(UTC)",
        },
        "smb_sources": {
            "id": "SMB 소스 PK",
            "name": "소스 이름(고유)",
            "share_path": "공유 경로(UNC/마운트 경로)",
            "username": "접속 계정",
            "password": "접속 비밀번호(암호화 저장 권장)",
            "is_active": "활성 여부",
            "last_seen_at": "마지막 감지 시각",
            "last_error": "마지막 오류 메시지",
            "created_at": "생성 시각(UTC)",
            "updated_at": "수정 시각(UTC)",
        },
        "db_sources": {
            "id": "DB 소스 PK",
            "name": "소스 이름(고유)",
            "db_type": "원천 DB 유형(oracle/mysql/postgres 등)",
            "connection_url": "원천 DB 연결 문자열",
            "query_text": "수집 대상 SQL",
            "title_column": "제목 컬럼명",
            "is_active": "활성 여부",
            "chunk_size": "분할 수집 크기",
            "last_synced_at": "마지막 동기화 시각",
            "last_error": "마지막 오류 메시지",
            "created_at": "생성 시각(UTC)",
            "updated_at": "수정 시각(UTC)",
        },
        "dictionary_entries": {
            "id": "사전 항목 PK",
            "dict_type": "사전 유형(synonym/stopword/user)",
            "term": "원본 단어",
            "replacement": "치환 단어(동의어용)",
            "is_active": "활성 여부",
            "created_at": "생성 시각(UTC)",
            "updated_at": "수정 시각(UTC)",
        },
        "certificate_status": {
            "id": "인증서 상태 PK",
            "cert_name": "인증서 이름(고유)",
            "cert_path": "인증서 파일 경로",
            "expires_at": "만료 시각",
            "days_left": "만료까지 남은 일수",
            "health_status": "상태 값(ok/warning/expired/unknown)",
            "last_checked_at": "마지막 점검 시각(UTC)",
            "message": "점검 상세 메시지",
        },
        "auth_roles": {
            "id": "권한 역할 PK",
            "name": "역할명(viewer/operator/admin)",
            "description": "역할 설명",
            "is_active": "활성 여부",
            "created_at": "생성 시각(UTC)",
        },
        "auth_users": {
            "id": "사용자 PK",
            "username": "로그인 아이디(고유)",
            "password_hash": "비밀번호 해시",
            "role_id": "역할 FK(auth_roles.id)",
            "is_active": "활성 여부",
            "created_at": "생성 시각(UTC)",
            "updated_at": "수정 시각(UTC)",
        },
        "revoked_access_tokens": {
            "id": "Access 토큰 블랙리스트 PK",
            "jti": "토큰 고유 식별자(JTI)",
            "subject": "토큰 주체(subject)",
            "expires_at": "토큰 만료 시각",
            "revoked_at": "블랙리스트 등록 시각",
        },
        "revoked_refresh_tokens": {
            "id": "Refresh 토큰 블랙리스트 PK",
            "jti": "토큰 고유 식별자(JTI)",
            "subject": "토큰 주체(subject)",
            "expires_at": "토큰 만료 시각",
            "revoked_at": "블랙리스트 등록 시각",
        },
    }


def upgrade() -> None:
    if not _is_postgresql():
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, table_comment in _table_comments().items():
        if table_name in existing_tables:
            op.execute(f"COMMENT ON TABLE {table_name} IS '{table_comment}'")

    column_map = _column_comments()
    for table_name, comments in column_map.items():
        if table_name not in existing_tables:
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for col_name, col_comment in comments.items():
            if col_name in existing_cols:
                op.execute(f"COMMENT ON COLUMN {table_name}.{col_name} IS '{col_comment}'")


def downgrade() -> None:
    if not _is_postgresql():
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name in _table_comments().keys():
        if table_name in existing_tables:
            op.execute(f"COMMENT ON TABLE {table_name} IS NULL")

    column_map = _column_comments()
    for table_name, comments in column_map.items():
        if table_name not in existing_tables:
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for col_name in comments.keys():
            if col_name in existing_cols:
                op.execute(f"COMMENT ON COLUMN {table_name}.{col_name} IS NULL")
