"""init app tables

Revision ID: 20260317_0001
Revises: 
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260317_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "search_logs" not in existing_tables:
        op.create_table(
            "search_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("query", sa.String(length=300), nullable=False),
            sa.Column("total_hits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_failed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("search_type", sa.String(length=50), nullable=False, server_default="manual_search"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_search_logs_user_id", "search_logs", ["user_id"])
        op.create_index("ix_search_logs_query", "search_logs", ["query"])
        op.create_index("ix_search_logs_is_failed", "search_logs", ["is_failed"])
        op.create_index("ix_search_logs_created_at", "search_logs", ["created_at"])

    if "recent_searches" not in existing_tables:
        op.create_table(
            "recent_searches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(length=100), nullable=False),
            sa.Column("query", sa.String(length=300), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_recent_searches_user_id", "recent_searches", ["user_id"])
        op.create_index("ix_recent_searches_created_at", "recent_searches", ["created_at"])

    if "indexed_documents" not in existing_tables:
        op.create_table(
            "indexed_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("os_doc_id", sa.String(length=120), nullable=True),
            sa.Column("origin_file", sa.String(length=260), nullable=False),
            sa.Column("file_ext", sa.String(length=20), nullable=False),
            sa.Column("doc_category", sa.String(length=50), nullable=False),
            sa.Column("content_hash", sa.String(length=600), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("all_text", sa.Text(), nullable=False),
            sa.Column("indexed_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_indexed_documents_os_doc_id", "indexed_documents", ["os_doc_id"], unique=True)
        op.create_index("ix_indexed_documents_origin_file", "indexed_documents", ["origin_file"])
        op.create_index("ix_indexed_documents_file_ext", "indexed_documents", ["file_ext"])
        op.create_index("ix_indexed_documents_doc_category", "indexed_documents", ["doc_category"])
        op.create_index("ix_indexed_documents_content_hash", "indexed_documents", ["content_hash"], unique=True)
        op.create_index("ix_indexed_documents_indexed_at", "indexed_documents", ["indexed_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "indexed_documents" in existing_tables:
        op.drop_index("ix_indexed_documents_indexed_at", table_name="indexed_documents")
        op.drop_index("ix_indexed_documents_content_hash", table_name="indexed_documents")
        op.drop_index("ix_indexed_documents_doc_category", table_name="indexed_documents")
        op.drop_index("ix_indexed_documents_file_ext", table_name="indexed_documents")
        op.drop_index("ix_indexed_documents_origin_file", table_name="indexed_documents")
        op.drop_index("ix_indexed_documents_os_doc_id", table_name="indexed_documents")
        op.drop_table("indexed_documents")

    if "recent_searches" in existing_tables:
        op.drop_index("ix_recent_searches_created_at", table_name="recent_searches")
        op.drop_index("ix_recent_searches_user_id", table_name="recent_searches")
        op.drop_table("recent_searches")

    if "search_logs" in existing_tables:
        op.drop_index("ix_search_logs_created_at", table_name="search_logs")
        op.drop_index("ix_search_logs_is_failed", table_name="search_logs")
        op.drop_index("ix_search_logs_query", table_name="search_logs")
        op.drop_index("ix_search_logs_user_id", table_name="search_logs")
        op.drop_table("search_logs")
