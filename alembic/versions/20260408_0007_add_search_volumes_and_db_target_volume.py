"""add search_volumes table and db_sources.target_volume column

Revision ID: 20260408_0007
Revises: 20260403_0006
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260408_0007"
down_revision = "20260403_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "search_volumes" not in existing_tables:
        op.create_table(
            "search_volumes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("index_name", sa.String(length=120), nullable=False),
            sa.Column("shards", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("replicas", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_search_volumes_id", "search_volumes", ["id"])
        op.create_index("ix_search_volumes_index_name", "search_volumes", ["index_name"], unique=True)
        op.create_index("ix_search_volumes_is_active", "search_volumes", ["is_active"])

    db_source_columns = {c["name"] for c in inspector.get_columns("db_sources")} if "db_sources" in existing_tables else set()
    if "target_volume" not in db_source_columns:
        op.add_column("db_sources", sa.Column("target_volume", sa.String(length=120), nullable=True))
        op.create_index("ix_db_sources_target_volume", "db_sources", ["target_volume"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "db_sources" in existing_tables:
        db_source_indexes = {idx["name"] for idx in inspector.get_indexes("db_sources")}
        if "ix_db_sources_target_volume" in db_source_indexes:
            op.drop_index("ix_db_sources_target_volume", table_name="db_sources")
        db_source_columns = {c["name"] for c in inspector.get_columns("db_sources")}
        if "target_volume" in db_source_columns:
            op.drop_column("db_sources", "target_volume")

    if "search_volumes" in existing_tables:
        op.drop_table("search_volumes")
