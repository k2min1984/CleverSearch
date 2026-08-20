"""add security columns to auth_users

- must_change_password   : 초기 시드/패스워드 변경 강제 플래그
- last_password_changed_at: 마지막 변경 시각
- failed_login_count     : 로그인 실패 누적 (분산 환경 영속화)
- locked_until           : 잠금 해제 시각

Revision ID: 20260429_0012
Revises: 20260429_0011
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260429_0012"
down_revision = "20260429_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "auth_users" not in set(inspector.get_table_names()):
        return

    cols = {c["name"] for c in inspector.get_columns("auth_users")}
    if "must_change_password" not in cols:
        op.add_column("auth_users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if "last_password_changed_at" not in cols:
        op.add_column("auth_users", sa.Column("last_password_changed_at", sa.DateTime(), nullable=True))
    if "failed_login_count" not in cols:
        op.add_column("auth_users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    if "locked_until" not in cols:
        op.add_column("auth_users", sa.Column("locked_until", sa.DateTime(), nullable=True))

    indexes = {idx["name"] for idx in inspector.get_indexes("auth_users")}
    if "ix_auth_users_must_change_password" not in indexes:
        op.create_index("ix_auth_users_must_change_password", "auth_users", ["must_change_password"])
    if "ix_auth_users_locked_until" not in indexes:
        op.create_index("ix_auth_users_locked_until", "auth_users", ["locked_until"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "auth_users" not in set(inspector.get_table_names()):
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("auth_users")}
    if "ix_auth_users_locked_until" in indexes:
        op.drop_index("ix_auth_users_locked_until", table_name="auth_users")
    if "ix_auth_users_must_change_password" in indexes:
        op.drop_index("ix_auth_users_must_change_password", table_name="auth_users")

    cols = {c["name"] for c in inspector.get_columns("auth_users")}
    for c in ("locked_until", "failed_login_count", "last_password_changed_at", "must_change_password"):
        if c in cols:
            op.drop_column("auth_users", c)
