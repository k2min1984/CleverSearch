"""add system feature tables

Revision ID: 20260319_0003
Revises: 20260318_0002
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0003"
down_revision = "20260318_0002"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "smb_sources" not in existing_tables:
        op.create_table(
            "smb_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("share_path", sa.String(length=400), nullable=False),
            sa.Column("username", sa.String(length=200), nullable=True),
            sa.Column("password", sa.String(length=200), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_smb_sources_name", "smb_sources", ["name"], unique=True)
        op.create_index("ix_smb_sources_is_active", "smb_sources", ["is_active"])
        op.create_index("ix_smb_sources_created_at", "smb_sources", ["created_at"])
        op.create_index("ix_smb_sources_updated_at", "smb_sources", ["updated_at"])

    if "db_sources" not in existing_tables:
        op.create_table(
            "db_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("db_type", sa.String(length=40), nullable=False),
            sa.Column("connection_url", sa.String(length=600), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("title_column", sa.String(length=120), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_db_sources_name", "db_sources", ["name"], unique=True)
        op.create_index("ix_db_sources_db_type", "db_sources", ["db_type"])
        op.create_index("ix_db_sources_is_active", "db_sources", ["is_active"])
        op.create_index("ix_db_sources_created_at", "db_sources", ["created_at"])
        op.create_index("ix_db_sources_updated_at", "db_sources", ["updated_at"])

    if "dictionary_entries" not in existing_tables:
        op.create_table(
            "dictionary_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dict_type", sa.String(length=40), nullable=False),
            sa.Column("term", sa.String(length=300), nullable=False),
            sa.Column("replacement", sa.String(length=300), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_dictionary_entries_dict_type", "dictionary_entries", ["dict_type"])
        op.create_index("ix_dictionary_entries_term", "dictionary_entries", ["term"])
        op.create_index("ix_dictionary_entries_is_active", "dictionary_entries", ["is_active"])
        op.create_index("ix_dictionary_entries_created_at", "dictionary_entries", ["created_at"])
        op.create_index("ix_dictionary_entries_updated_at", "dictionary_entries", ["updated_at"])

    if "certificate_status" not in existing_tables:
        op.create_table(
            "certificate_status",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cert_name", sa.String(length=260), nullable=False),
            sa.Column("cert_path", sa.String(length=500), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("days_left", sa.Integer(), nullable=True),
            sa.Column("health_status", sa.String(length=40), nullable=False, server_default="unknown"),
            sa.Column("last_checked_at", sa.DateTime(), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=True),
        )
        op.create_index("ix_certificate_status_cert_name", "certificate_status", ["cert_name"], unique=True)
        op.create_index("ix_certificate_status_expires_at", "certificate_status", ["expires_at"])
        op.create_index("ix_certificate_status_days_left", "certificate_status", ["days_left"])
        op.create_index("ix_certificate_status_health_status", "certificate_status", ["health_status"])
        op.create_index("ix_certificate_status_last_checked_at", "certificate_status", ["last_checked_at"])

    if _is_postgresql():
        op.execute("COMMENT ON TABLE smb_sources IS 'SMB 소스 등록/상태 테이블'")
        op.execute("COMMENT ON TABLE db_sources IS '다중 DB 수집 소스 등록/상태 테이블'")
        op.execute("COMMENT ON TABLE dictionary_entries IS '동의어/불용어/사용자 사전 테이블'")
        op.execute("COMMENT ON TABLE certificate_status IS '인증서 상태 모니터링 테이블'")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "certificate_status" in existing_tables:
        op.drop_index("ix_certificate_status_last_checked_at", table_name="certificate_status")
        op.drop_index("ix_certificate_status_health_status", table_name="certificate_status")
        op.drop_index("ix_certificate_status_days_left", table_name="certificate_status")
        op.drop_index("ix_certificate_status_expires_at", table_name="certificate_status")
        op.drop_index("ix_certificate_status_cert_name", table_name="certificate_status")
        op.drop_table("certificate_status")

    if "dictionary_entries" in existing_tables:
        op.drop_index("ix_dictionary_entries_updated_at", table_name="dictionary_entries")
        op.drop_index("ix_dictionary_entries_created_at", table_name="dictionary_entries")
        op.drop_index("ix_dictionary_entries_is_active", table_name="dictionary_entries")
        op.drop_index("ix_dictionary_entries_term", table_name="dictionary_entries")
        op.drop_index("ix_dictionary_entries_dict_type", table_name="dictionary_entries")
        op.drop_table("dictionary_entries")

    if "db_sources" in existing_tables:
        op.drop_index("ix_db_sources_updated_at", table_name="db_sources")
        op.drop_index("ix_db_sources_created_at", table_name="db_sources")
        op.drop_index("ix_db_sources_is_active", table_name="db_sources")
        op.drop_index("ix_db_sources_db_type", table_name="db_sources")
        op.drop_index("ix_db_sources_name", table_name="db_sources")
        op.drop_table("db_sources")

    if "smb_sources" in existing_tables:
        op.drop_index("ix_smb_sources_updated_at", table_name="smb_sources")
        op.drop_index("ix_smb_sources_created_at", table_name="smb_sources")
        op.drop_index("ix_smb_sources_is_active", table_name="smb_sources")
        op.drop_index("ix_smb_sources_name", table_name="smb_sources")
        op.drop_table("smb_sources")
