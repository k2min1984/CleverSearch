"""add connection_type, ssh_host, ssh_key_path to smb_sources

Revision ID: 20260415_0009
Revises: 20260408_0008
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0009"
down_revision = "20260408_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "smb_sources" not in existing_tables:
        return

    columns = {c["name"] for c in inspector.get_columns("smb_sources")}

    if "connection_type" not in columns:
        op.add_column("smb_sources", sa.Column("connection_type", sa.String(length=10), nullable=False, server_default="smb"))

    if "ssh_host" not in columns:
        op.add_column("smb_sources", sa.Column("ssh_host", sa.String(length=200), nullable=True))

    if "ssh_key_path" not in columns:
        op.add_column("smb_sources", sa.Column("ssh_key_path", sa.String(length=400), nullable=True))

    # 기존 데이터는 모두 smb 타입으로 설정
    op.execute("UPDATE smb_sources SET connection_type = 'smb' WHERE connection_type IS NULL")

    indexes = {idx["name"] for idx in inspector.get_indexes("smb_sources")}
    if "ix_smb_sources_connection_type" not in indexes:
        op.create_index("ix_smb_sources_connection_type", "smb_sources", ["connection_type"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "smb_sources" not in existing_tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("smb_sources")}
    if "ix_smb_sources_connection_type" in indexes:
        op.drop_index("ix_smb_sources_connection_type", table_name="smb_sources")

    columns = {c["name"] for c in inspector.get_columns("smb_sources")}
    if "ssh_key_path" in columns:
        op.drop_column("smb_sources", "ssh_key_path")
    if "ssh_host" in columns:
        op.drop_column("smb_sources", "ssh_host")
    if "connection_type" in columns:
        op.drop_column("smb_sources", "connection_type")
