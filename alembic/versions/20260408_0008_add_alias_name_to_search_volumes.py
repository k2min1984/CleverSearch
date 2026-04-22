"""add alias_name column to search_volumes

Revision ID: 20260408_0008
Revises: 20260408_0007
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260408_0008"
down_revision = "20260408_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "search_volumes" not in existing_tables:
        return

    columns = {c["name"] for c in inspector.get_columns("search_volumes")}
    if "alias_name" not in columns:
        op.add_column("search_volumes", sa.Column("alias_name", sa.String(length=120), nullable=True))

    # 기존 데이터는 alias=index_name으로 초기화
    op.execute("UPDATE search_volumes SET alias_name = index_name WHERE alias_name IS NULL")

    indexes = {idx["name"] for idx in inspector.get_indexes("search_volumes")}
    if "ix_search_volumes_alias_name" not in indexes:
        op.create_index("ix_search_volumes_alias_name", "search_volumes", ["alias_name"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "search_volumes" not in existing_tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("search_volumes")}
    if "ix_search_volumes_alias_name" in indexes:
        op.drop_index("ix_search_volumes_alias_name", table_name="search_volumes")

    columns = {c["name"] for c in inspector.get_columns("search_volumes")}
    if "alias_name" in columns:
        op.drop_column("search_volumes", "alias_name")
