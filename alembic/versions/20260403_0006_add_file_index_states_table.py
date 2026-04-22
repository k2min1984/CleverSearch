"""add file_index_states table

Revision ID: 20260403_0006
Revises: 20260403_0005
Create Date: 2026-04-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260403_0006"
down_revision = "20260403_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "file_index_states" not in existing_tables:
        op.create_table(
            "file_index_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_type", sa.String(length=20), nullable=False),
            sa.Column("source_name", sa.String(length=120), nullable=False),
            sa.Column("file_path", sa.String(length=600), nullable=False),
            sa.Column("file_hash", sa.String(length=64), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_modified", sa.DateTime(), nullable=True),
            sa.Column("indexed_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_file_index_states_source_type", "file_index_states", ["source_type"])
        op.create_index("ix_file_index_states_source_name", "file_index_states", ["source_name"])
        op.create_index("ix_file_index_states_indexed_at", "file_index_states", ["indexed_at"])
        op.create_index(
            "uq_file_index_states_source_file",
            "file_index_states",
            ["source_type", "source_name", "file_path"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_table("file_index_states")
