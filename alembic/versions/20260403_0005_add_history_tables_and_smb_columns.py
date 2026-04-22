"""add history tables and smb columns

Revision ID: 20260403_0005
Revises: 20260319_0004
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260403_0005"
down_revision = "20260319_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── SmbSource 컬럼 추가 (domain, port) ──
    if "smb_sources" in existing_tables:
        columns = {col["name"] for col in inspector.get_columns("smb_sources")}
        if "domain" not in columns:
            op.add_column("smb_sources", sa.Column("domain", sa.String(length=100), nullable=True))
        if "port" not in columns:
            op.add_column("smb_sources", sa.Column("port", sa.Integer(), nullable=False, server_default="445"))

    # ── SMB 동기화 이력 테이블 ──
    if "smb_sync_history" not in existing_tables:
        op.create_table(
            "smb_sync_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_id", sa.Integer(), sa.ForeignKey("smb_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_name", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("indexed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default="manual"),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_smb_sync_history_source_id", "smb_sync_history", ["source_id"])
        op.create_index("ix_smb_sync_history_source_name", "smb_sync_history", ["source_name"])
        op.create_index("ix_smb_sync_history_status", "smb_sync_history", ["status"])
        op.create_index("ix_smb_sync_history_trigger_type", "smb_sync_history", ["trigger_type"])
        op.create_index("ix_smb_sync_history_started_at", "smb_sync_history", ["started_at"])
        op.create_index("ix_smb_sync_history_finished_at", "smb_sync_history", ["finished_at"])

    # ── 색인 이력 테이블 ──
    if "indexing_history" not in existing_tables:
        op.create_table(
            "indexing_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("source_name", sa.String(length=120), nullable=False),
            sa.Column("file_name", sa.String(length=260), nullable=True),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_indexing_history_source_type", "indexing_history", ["source_type"])
        op.create_index("ix_indexing_history_source_name", "indexing_history", ["source_name"])
        op.create_index("ix_indexing_history_action", "indexing_history", ["action"])
        op.create_index("ix_indexing_history_status", "indexing_history", ["status"])
        op.create_index("ix_indexing_history_created_at", "indexing_history", ["created_at"])

    # ── 네트워크 이벤트 로그 테이블 ──
    if "network_event_logs" not in existing_tables:
        op.create_table(
            "network_event_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("source_name", sa.String(length=120), nullable=False),
            sa.Column("event_type", sa.String(length=30), nullable=False),
            sa.Column("detail", sa.String(length=1000), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_network_event_logs_source_type", "network_event_logs", ["source_type"])
        op.create_index("ix_network_event_logs_source_name", "network_event_logs", ["source_name"])
        op.create_index("ix_network_event_logs_event_type", "network_event_logs", ["event_type"])
        op.create_index("ix_network_event_logs_created_at", "network_event_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("network_event_logs")
    op.drop_table("indexing_history")
    op.drop_table("smb_sync_history")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "smb_sources" in set(inspector.get_table_names()):
        columns = {col["name"] for col in inspector.get_columns("smb_sources")}
        if "port" in columns:
            op.drop_column("smb_sources", "port")
        if "domain" in columns:
            op.drop_column("smb_sources", "domain")
