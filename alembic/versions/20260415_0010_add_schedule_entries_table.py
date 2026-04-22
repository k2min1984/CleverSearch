"""add schedule_entries table

Revision ID: 20260415_0010
Revises: 20260415_0009
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "20260415_0010"
down_revision = "20260415_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(20), nullable=False, index=True),
        sa.Column("source_id", sa.Integer(), nullable=False, index=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_type", "source_id", name="uq_schedule_source"),
    )


def downgrade() -> None:
    op.drop_table("schedule_entries")
