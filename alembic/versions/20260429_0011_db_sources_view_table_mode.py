"""switch db_sources to view/table mode

- DROP query_text (no longer storing arbitrary SQL — security)
- ADD source_table (view or table identifier)
- ADD select_columns (comma-separated text columns)

Revision ID: 20260429_0011
Revises: 20260415_0010, 20260422_0005
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260429_0011"
down_revision = ("20260415_0010", "20260422_0005")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "db_sources" not in existing_tables:
        return

    columns = {c["name"] for c in inspector.get_columns("db_sources")}

    if "source_table" not in columns:
        op.add_column("db_sources", sa.Column("source_table", sa.String(length=200), nullable=True))

    if "select_columns" not in columns:
        op.add_column("db_sources", sa.Column("select_columns", sa.String(length=1000), nullable=True))

    if "query_text" in columns:
        # Open development phase — discard arbitrary SQL storage entirely.
        op.drop_column("db_sources", "query_text")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "db_sources" not in existing_tables:
        return

    columns = {c["name"] for c in inspector.get_columns("db_sources")}

    if "query_text" not in columns:
        # 복구 시에는 nullable 로 둔다. 다시 채우려면 운영자가 별도 백필 필요.
        op.add_column("db_sources", sa.Column("query_text", sa.Text(), nullable=True))

    if "select_columns" in columns:
        op.drop_column("db_sources", "select_columns")

    if "source_table" in columns:
        op.drop_column("db_sources", "source_table")
