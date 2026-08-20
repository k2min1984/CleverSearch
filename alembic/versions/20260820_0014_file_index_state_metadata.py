"""add incremental metadata to file index states

Revision ID: 20260820_0014
Revises: 20260429_0013
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0014"
down_revision = "20260429_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "file_index_states" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("file_index_states")}
    if "mtime" not in columns:
        op.add_column("file_index_states", sa.Column("mtime", sa.DateTime(), nullable=True))
    if "last_seen_at" not in columns:
        op.add_column("file_index_states", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    if "os_doc_id" not in columns:
        op.add_column("file_index_states", sa.Column("os_doc_id", sa.String(length=64), nullable=True))

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("file_index_states")}
    if "ix_file_state_src" not in indexes:
        op.create_index("ix_file_state_src", "file_index_states", ["source_type", "source_name"])
    if "ix_file_state_lookup" not in indexes:
        op.create_index(
            "ix_file_state_lookup",
            "file_index_states",
            ["source_type", "source_name", "file_path"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "file_index_states" not in set(inspector.get_table_names()):
        return

    indexes = {index["name"] for index in inspector.get_indexes("file_index_states")}
    if "ix_file_state_lookup" in indexes:
        op.drop_index("ix_file_state_lookup", table_name="file_index_states")
    if "ix_file_state_src" in indexes:
        op.drop_index("ix_file_state_src", table_name="file_index_states")

    columns = {column["name"] for column in sa.inspect(bind).get_columns("file_index_states")}
    if "last_seen_at" in columns:
        op.drop_column("file_index_states", "last_seen_at")
    if "mtime" in columns:
        op.drop_column("file_index_states", "mtime")
